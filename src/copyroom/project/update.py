"""Template update workflow — ``copyroom update``.

Implements the TemplateUpdate state machine from copyroom-project.allium:

    initiated -> config_loaded -> worktree_verified ->
        [branch_created ->] update_executed -> post_update_run -> complete

Each rule in the spec maps to a function or method in this module.
"""

from __future__ import annotations

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
from .config import load_hook_commands, load_project_config
from .layers import BASE_LAYER, answers_filename, discover_layers
from .model import (
    VALID_UPDATE_TRANSITIONS,
    TemplateUpdate,
    UpdateStatus,
)

__all__ = ["CopyRoomError", "update_all_layers", "update_project"]

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
    layer: str = BASE_LAYER,
) -> TemplateUpdate:
    """Create a TemplateUpdate entity.

    ``target_ref`` may be ``None`` — :func:`resolve_latest_ref` fills it in from
    the template's latest semver tag (InitiateTemplateUpdate + ResolveLatestRef).
    ``template_id``, ``previous_ref``, and ``template_source`` are populated by
    :func:`load_config`, the single reader of the layer's answers file.

    ``layer`` selects **which template** to converge: ``base`` for the project's
    own ``.copier-answers.yml``, or a named overlay (see
    :mod:`copyroom.project.layers`).
    """
    return TemplateUpdate(
        project_root=project_root,
        template_id="unknown",
        previous_ref=None,
        target_ref=target_ref or None,
        use_branch=use_branch,
        layer=layer,
    )


# ===================================================================
# Rule: LoadUpdateConfig               (spec L197-L204)
# ===================================================================


def load_config(update: TemplateUpdate) -> UpdateStatus:
    """Load configuration from the layer's answers file.

    Captures the template source (``_src_path``) and recorded version
    (``_commit``), which feed :func:`resolve_latest_ref` and the no-op check.
    Which file is read is decided by ``update.layer`` — ``.copier-answers.yml``
    for the base layer, ``.copier-answers.<layer>.yml`` for an overlay.

    On success: transitions to ``config_loaded``.
    On failure: transitions to ``failed``.
    """
    answers_file = update.project_root / answers_filename(update.layer)

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
            f"in {answers_filename(update.layer)}. Pass an explicit ref: "
            "copyroom update <ref>",
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

    This is not merely CopyRoom's caution: Copier itself refuses a dirty
    destination, so an ``--all-layers`` run has to commit each layer's output
    before the next layer runs (:func:`update_all_layers`).

    On clean: transitions to ``worktree_verified``.
    On dirty: transitions to ``failed`` with remediation guidance.
    """
    # Unlike release-check (which excludes its own generated/ + .copyroom_sim/
    # scratch output), this intentionally excludes *nothing*: Copier's 3-way
    # update requires a fully clean tree so `git checkout .` is always a way back.
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

    Branch name pattern: ``template-update/<template_id>-<target_ref>``, with
    the layer name inserted for a non-base layer so two layers' updates never
    collide on the same branch.
    Only executed when ``--branch`` was passed.

    On success: transitions to ``branch_created``.
    On failure: transitions to ``failed``.
    """
    scope = "" if update.layer == BASE_LAYER else f"{update.layer}/"
    branch_name = (
        f"template-update/{scope}{update.template_id}-{update.target_ref}"
    )

    result = gitutil.checkout_new_branch(update.project_root, branch_name)
    if result is None:
        # git unavailable (fail-soft helper returns None)
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

    Skills the project declares in ``copyroom.project.yml`` ``agent.overlay``
    are permanently diverged: each is mapped to a Copier ``--exclude`` pattern
    (``<skills_dir>/<name>/**``) so the template stops managing it and the
    project's local version survives the update untouched. The excludes apply to
    **every** layer — an overlay declaration means "no template manages this",
    not "the base template doesn't".

    The update is scoped to ``update.layer``'s answers file, so converging one
    layer never reads or rewrites another's (see :mod:`copyroom.project.layers`).

    On success: transitions to ``update_executed``.
    On failure: transitions to ``failed``.
    """
    from_state = update.status

    excludes = _overlay_excludes(update.project_root)

    try:
        result = copier_update(
            destination=update.project_root,
            vcs_ref=update.target_ref,
            exclude=excludes,
            answers_file=answers_filename(update.layer),
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


def _overlay_excludes(project_root: Path) -> list[str]:
    """Map ``agent.overlay`` from ``copyroom.project.yml`` to exclude patterns.

    Each declared skill becomes ``<skills_dir>/<name>/**`` so Copier's update
    excludes the whole skill directory from both renders — the template stops
    managing it and the repo's local version is left alone (the
    permanently-diverge contract). A missing/unreadable config yields no
    excludes (updates must never be blocked by a config problem).
    """
    try:
        cfg = load_project_config(project_root / "copyroom.project.yml")
    except CopyRoomError:
        return []
    overlay = cfg.agent.overlay
    if not overlay:
        return []
    skills_dir = cfg.agent.skills_dir
    return [f"{skills_dir}/{name}/**" for name in overlay]


# ===================================================================
# High-level workflow
# ===================================================================


def update_project(
    project_root: str | Path | None = None,
    target_ref: str | None = None,
    use_branch: bool = False,
    trust: bool = False,
    layer: str = BASE_LAYER,
) -> TemplateUpdate:
    """Run the full template update workflow for one layer.

    This is the top-level entry point called from the CLI.

    ``trust`` enables execution of the template's post-update hook commands;
    when ``False`` (the default) they are skipped with a warning.

    ``layer`` names which template to converge; it defaults to ``base``, so a
    single-template project behaves exactly as it always has.

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
    update = initiate(project_root, target_ref, use_branch, layer=layer)

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


def update_all_layers(
    project_root: str | Path | None = None,
    use_branch: bool = False,
    trust: bool = False,
) -> list[TemplateUpdate]:
    """Converge **every** recorded layer to its own latest tag, base first.

    Each layer resolves its own latest ref, so no ``target_ref`` is accepted
    here — a single ref is meaningless across different templates.

    **This commits between layers.** Copier refuses a dirty destination
    ("Destination repository is dirty; cannot continue"), and the first layer's
    update necessarily dirties the tree, so converging N layers in one pass is
    only possible if each layer's result is committed before the next runs. That
    is also the history you want: one reviewable commit per layer convergence.
    The run therefore verifies the tree is clean **once, up front**, so
    ``git reset --hard`` back to the starting commit is always the way out.

    It stops rather than commits when a layer leaves conflicts or rejects —
    committing conflict markers unreviewed would be the one genuinely
    destructive outcome here.

    Layers are independent (see :mod:`copyroom.project.layers`), so one layer
    failing does not invalidate the layers already converged; the run stops at
    the first failure and returns the results so far, so the caller can report
    exactly how far it got.
    """
    root = resolve_project_root_for_update(project_root)
    layers = discover_layers(root)
    if not layers:
        raise CopyRoomError(
            f"No template layer here: {root} has no .copier-answers.yml and no "
            ".copier-answers.<name>.yml. Nothing to update."
        )

    dirty = gitutil.worktree_status(root)
    if dirty:
        raise CopyRoomError(
            "Worktree is not clean. Commit or stash changes before updating:\n"
            + "\n".join(f"  {line}" for line in dirty)
        )

    results: list[TemplateUpdate] = []
    for index, layer in enumerate(layers):
        if index > 0 and not _commit_layer_result(root, results[-1]):
            break
        result = update_project(
            project_root=root,
            target_ref=None,
            use_branch=use_branch,
            trust=trust,
            layer=layer.name,
        )
        results.append(result)
        if result.status == UpdateStatus.failed:
            break
    return results


def _commit_layer_result(root: Path, previous: TemplateUpdate) -> bool:
    """Commit the previous layer's output so the next layer can run.

    Returns ``False`` when the run must stop: the previous layer left conflicts
    or rejects (never commit those unreviewed), or git is unavailable. A layer
    that changed nothing leaves a clean tree and needs no commit.
    """
    if previous.conflicts or previous.rejects:
        print(
            f"Layer '{previous.layer}' left conflicts/rejects — stopping before the next layer. "
            "Resolve and commit, then re-run.",
            file=sys.stderr,
        )
        return False
    if not gitutil.worktree_status(root):
        return True  # nothing to commit
    committed = gitutil.commit_all(
        root, f"copyroom: update layer '{previous.layer}' to {previous.target_ref}",
    )
    if not committed:
        print("git is unavailable — cannot commit between layers.", file=sys.stderr)
    return committed


def resolve_project_root_for_update(project_root: str | Path | None) -> Path:
    """Resolve *project_root* the way :func:`update_project` does (cwd default)."""
    if project_root is None:
        return Path.cwd().resolve()
    return Path(project_root).resolve()
