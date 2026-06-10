"""Template update workflow — ``copyroom update``.

Implements the TemplateUpdate state machine from copyroom-project.allium:

    initiated -> config_loaded -> worktree_verified ->
        [branch_created ->] update_executed -> post_update_run -> complete

Each rule in the spec maps to a function or method in this module.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

from .._compat import gitutil
from .._compat.conflicts import scan_conflict_markers, scan_rejects
from .._compat.copier import copier_update
from .._compat.errors import CopyRoomError
from .._compat.refs import same_version
from .._compat.shellcmd import run_hook_commands
from .._compat.state_machine import StateMachine
from .config import load_hook_commands
from .model import (
    VALID_UPDATE_TRANSITIONS,
    TemplateUpdate,
    UpdateStatus,
)

__all__ = ["CopyRoomError", "update_project"]

# ---------------------------------------------------------------------------
# State machine instance
# ---------------------------------------------------------------------------

_update_sm = StateMachine(
    VALID_UPDATE_TRANSITIONS,
    entity_name="TemplateUpdate",
)


# ===================================================================
# Rule: InitiateTemplateUpdate         (spec L181-L195)
# ===================================================================


def initiate(
    project_root: Path,
    target_ref: str | None,
    use_branch: bool = False,
) -> TemplateUpdate:
    """Create a TemplateUpdate entity.

    ``target_ref`` may be ``None`` — :func:`resolve_latest_ref` fills it in from
    the template's latest semver tag (InitiateTemplateUpdate + ResolveLatestRef).
    ``template_id``, ``previous_ref``, and ``template_source`` are populated by
    :func:`load_config`, the single reader of ``.copier-answers.yml``.
    """
    return TemplateUpdate(
        project_root=project_root,
        template_id="unknown",
        previous_ref=None,
        target_ref=target_ref or None,
        use_branch=use_branch,
    )


# ===================================================================
# Rule: LoadUpdateConfig               (spec L197-L204)
# ===================================================================


def load_config(update: TemplateUpdate) -> UpdateStatus:
    """Load configuration from ``.copier-answers.yml``.

    Captures the template source (``_src_path``) and recorded version
    (``_commit``), which feed :func:`resolve_latest_ref` and the no-op check.

    On success: transitions to ``config_loaded``.
    On failure: transitions to ``failed``.
    """
    answers_file = update.project_root / ".copier-answers.yml"

    if not answers_file.is_file():
        update.status = _update_sm.transition(
            UpdateStatus.initiated,
            UpdateStatus.failed,
        )
        return update.status

    try:
        with open(answers_file) as f:
            answers = yaml.safe_load(f)
    except (yaml.YAMLError, OSError):
        update.status = _update_sm.transition(
            UpdateStatus.initiated,
            UpdateStatus.failed,
        )
        return update.status

    if isinstance(answers, dict):
        template_id = answers.get("_template")
        if template_id is not None:
            update.template_id = str(template_id)
        commit = answers.get("_commit")
        if commit is not None:
            update.previous_ref = str(commit)
        src_path = answers.get("_src_path")
        if src_path is not None:
            update.template_source = str(src_path)

    update.status = _update_sm.transition(
        UpdateStatus.initiated,
        UpdateStatus.config_loaded,
    )
    return update.status


# ===================================================================
# Rule: ResolveLatestRef               (spec L206-L217)
# ===================================================================


def resolve_latest_ref(update: TemplateUpdate) -> None:
    """Resolve a missing ``target_ref`` to the template's latest semver tag.

    Only runs on the no-arg ``copyroom update`` path (``target_ref is None``);
    an explicit ref is left untouched and stays fully offline. Resolution lists
    the template's tags (locally via ``git tag``, or remotely via
    ``git ls-remote`` — fetch-class, may need the network) and picks the highest
    ``vX.Y.Z``. A source we can't read or that has no semver tags is a clear
    ``CopyRoomError`` rather than a silent fallback to Copier's implicit latest.
    """
    if update.target_ref is not None:
        return

    if not update.template_source:
        update.status = _update_sm.transition(
            UpdateStatus.config_loaded,
            UpdateStatus.failed,
        )
        raise CopyRoomError(
            "Cannot resolve the latest template version: no _src_path recorded "
            "in .copier-answers.yml. Pass an explicit ref: copyroom update <ref>",
            state="config_loaded",
        )

    latest = gitutil.resolve_latest_ref(update.template_source)
    if latest is None:
        update.status = _update_sm.transition(
            UpdateStatus.config_loaded,
            UpdateStatus.failed,
        )
        raise CopyRoomError(
            f"Could not resolve the latest version of template "
            f"'{update.template_source}'. The source may be unreachable or have "
            "no semver (vX.Y.Z) tags. Pass an explicit ref: copyroom update <ref>",
            state="config_loaded",
        )

    update.target_ref = latest
    update.resolved_latest = True


# ===================================================================
# Rule: NoUpdateAvailable              (spec L179-L183)
# ===================================================================


def no_update_available(update: TemplateUpdate) -> UpdateStatus:
    """Check if the update is a no-op.

    The recorded ``previous_ref`` (Copier's ``_commit``) may be a bare tag, a
    ``git describe`` string (``vX.Y.Z-N-gsha``), or a SHA, so this compares
    *versions* via :func:`same_version` rather than raw strings — a project
    generated at a post-tag commit of the target version is still a no-op.

    A no-op transitions to ``up_to_date`` (a *success* terminal): "already at
    the target version, nothing to do" is not a failure (P1-2).
    """
    if same_version(update.previous_ref, update.target_ref):
        update.status = _update_sm.transition(
            UpdateStatus.config_loaded,
            UpdateStatus.up_to_date,
        )
        return update.status

    # Refs differ; continue to worktree verification
    return update.status


# ===================================================================
# Rule: VerifyCleanWorktree            (spec L185-L192)
# Rule: RejectDirtyWorktree            (spec L194-L199)
# ===================================================================


def verify_worktree(update: TemplateUpdate) -> UpdateStatus:
    """Verify that the git worktree is clean.

    Reads ``git status --porcelain`` via :func:`gitutil.worktree_status` (so it
    inherits the shared 120s git timeout and fail-soft behavior). A non-repo or
    missing git (``None``) is treated as clean.

    On clean: transitions to ``worktree_verified``.
    On dirty: transitions to ``failed`` with remediation guidance.
    """
    dirty = gitutil.worktree_status(update.project_root)

    if dirty:
        update.status = _update_sm.transition(
            UpdateStatus.config_loaded,
            UpdateStatus.failed,
        )
        print(
            "Worktree is not clean. Commit or stash changes before updating.",
            file=sys.stderr,
        )
        print("Dirty files:", file=sys.stderr)
        for line in dirty:
            print(f"  {line}", file=sys.stderr)
        return update.status

    # Clean, not a git repo, or git unavailable — all treated as clean.
    update.status = _update_sm.transition(
        UpdateStatus.config_loaded,
        UpdateStatus.worktree_verified,
    )
    return update.status


# ===================================================================
# Rule: CreateUpdateBranch            (spec L201-L209)
# ===================================================================


def create_branch(update: TemplateUpdate) -> UpdateStatus:
    """Create an isolation branch for the update.

    Branch name pattern: ``template-update/<template_id>-<target_ref>``.
    Only executed when ``--branch`` was passed.

    On success: transitions to ``branch_created``.
    On failure: transitions to ``failed``.
    """
    branch_name = (
        f"template-update/{update.template_id}-{update.target_ref}"
    )

    try:
        result = subprocess.run(
            ["git", "checkout", "-b", branch_name],
            cwd=str(update.project_root),
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        update.status = _update_sm.transition(
            UpdateStatus.worktree_verified,
            UpdateStatus.failed,
        )
        return update.status

    if result.returncode != 0:
        update.status = _update_sm.transition(
            UpdateStatus.worktree_verified,
            UpdateStatus.failed,
        )
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="")
        return update.status

    update.update_branch = branch_name
    update.status = _update_sm.transition(
        UpdateStatus.worktree_verified,
        UpdateStatus.branch_created,
    )
    return update.status


# ===================================================================
# Rule: ExecuteCopierUpdate            (spec L211-L216)
# Rule: ExecuteCopierUpdateFromBranch  (spec L218-L226)
# ===================================================================


def execute_update(update: TemplateUpdate) -> UpdateStatus:
    """Run ``copier update`` on the project.

    Called after either ``worktree_verified`` (no branch) or
    ``branch_created`` (with isolation branch).

    On success: transitions to ``update_executed``.
    On failure: transitions to ``failed``.
    """
    from_state = update.status

    try:
        result = copier_update(
            destination=update.project_root,
            vcs_ref=update.target_ref,
        )
    except Exception as exc:
        update.status = _update_sm.transition(
            from_state,
            UpdateStatus.failed,
        )
        print(f"Copier update failed: {exc}", file=sys.stderr)
        return update.status

    if result.returncode != 0:
        update.status = _update_sm.transition(
            from_state,
            UpdateStatus.failed,
        )
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="")
        if result.stdout:
            print(result.stdout, file=sys.stderr, end="")
        return update.status

    update.status = _update_sm.transition(
        from_state,
        UpdateStatus.update_executed,
    )
    return update.status


# ===================================================================
# Rule: CaptureUpdateConflicts         (spec L228-L234)
# ===================================================================


def capture_conflicts(update: TemplateUpdate) -> UpdateStatus:
    """Capture conflicts and rejects left by ``copier update``.

    The worktree was verified clean before the update (:func:`verify_worktree`),
    so its now-dirty files *are* the update's output. ``.rej`` siblings and inline
    ``<<<<<<<`` / ``>>>>>>>`` markers in those changed files are both captured via
    the shared :mod:`_compat.conflicts` scanners — the same logic ``preview`` and
    ``simulate`` use (was: a fragile stdout grep — P2-1).

    If no post-update commands are configured, short-circuits to ``complete``.
    Otherwise transitions to ``post_update_run``.

    On success: transitions to ``post_update_run`` or ``complete``.
    On failure: transitions to ``failed``.
    """
    update.rejects.update(scan_rejects(update.project_root))
    changed = gitutil.changed_paths(update.project_root)
    update.conflicts.update(scan_conflict_markers(update.project_root, changed))

    # Check for post-update commands. Read through the resilient accessor so a
    # schema-divergent (but readable) config never silently drops configured
    # hooks — both this reader and run_post_update_commands now agree.
    project_yml = update.project_root / "copyroom.project.yml"
    try:
        commands = load_hook_commands(project_yml, "post_template_update")
    except CopyRoomError:
        update.status = _update_sm.transition(
            UpdateStatus.update_executed,
            UpdateStatus.failed,
        )
        print(
            "Failed to parse copyroom.project.yml for post-update commands.",
            file=sys.stderr,
        )
        return update.status

    if not commands:
        # Short-circuit to complete
        update.status = _update_sm.transition(
            UpdateStatus.update_executed,
            UpdateStatus.complete,
        )
        return update.status

    update.status = _update_sm.transition(
        UpdateStatus.update_executed,
        UpdateStatus.post_update_run,
    )
    return update.status


# ===================================================================
# Rule: RunPostUpdateCommands          (spec L236-L241)
# ===================================================================


def run_post_update_commands(
    update: TemplateUpdate,
    trust: bool = False,
) -> UpdateStatus:
    """Execute post-update commands from ``copyroom.project.yml``.

    Commands come from the template and only run when ``trust`` is set;
    otherwise they are skipped with a warning. Failures do not block completion.
    """
    project_yml = update.project_root / "copyroom.project.yml"

    try:
        commands = load_hook_commands(project_yml, "post_template_update")
    except CopyRoomError:
        update.status = _update_sm.transition(
            UpdateStatus.post_update_run,
            UpdateStatus.failed,
        )
        return update.status

    run_hook_commands(commands, update.project_root, trust=trust, label="post-update")

    update.status = _update_sm.transition(
        UpdateStatus.post_update_run,
        UpdateStatus.complete,
    )
    return update.status


# ===================================================================
# High-level workflow
# ===================================================================


def update_project(
    project_root: str | Path | None = None,
    target_ref: str | None = None,
    use_branch: bool = False,
    trust: bool = False,
) -> TemplateUpdate:
    """Run the full template update workflow.

    This is the top-level entry point called from the CLI.

    ``trust`` enables execution of the template's post-update hook commands;
    when ``False`` (the default) they are skipped with a warning.

    Returns the ``TemplateUpdate`` entity in its final state (``complete``
    or ``failed``).
    """
    if project_root is None:
        project_root = Path.cwd()
    elif isinstance(project_root, str):
        project_root = Path(project_root).resolve()
    else:
        project_root = project_root.resolve()

    # 1. InitiateTemplateUpdate (target_ref may be None — resolved below)
    update = initiate(project_root, target_ref, use_branch)

    # 2. LoadUpdateConfig — reads _src_path / _commit
    status = load_config(update)
    if status == UpdateStatus.failed:
        return update

    # 2b. ResolveLatestRef — only when no explicit ref was given. Raises a clear
    # CopyRoomError (caught by the CLI) when the latest tag can't be resolved.
    resolve_latest_ref(update)

    # 3. NoUpdateAvailable — check if already at target. A no-op is a success
    # terminal (up_to_date), not a failure.
    if update.previous_ref is not None:
        status = no_update_available(update)
        if status in (UpdateStatus.up_to_date, UpdateStatus.failed):
            return update

    # 4. VerifyCleanWorktree / RejectDirtyWorktree
    status = verify_worktree(update)
    if status == UpdateStatus.failed:
        return update

    # 5. CreateUpdateBranch (only if --branch)
    if use_branch:
        status = create_branch(update)
        if status == UpdateStatus.failed:
            return update

    # 6. ExecuteCopierUpdate / ExecuteCopierUpdateFromBranch
    status = execute_update(update)
    if status == UpdateStatus.failed:
        return update

    # 7. CaptureUpdateConflicts (may short-circuit to complete)
    status = capture_conflicts(update)
    if status == UpdateStatus.failed:
        return update
    if status == UpdateStatus.complete:
        return update

    # 8. RunPostUpdateCommands
    status = run_post_update_commands(update, trust=trust)
    return update
