"""Template update workflow — ``copyroom update``.

Implements the TemplateUpdate state machine from copyroom-project.allium:

    initiated -> config_loaded -> worktree_verified ->
        [branch_created ->] update_executed -> post_update_run -> complete

Each rule in the spec maps to a function or method in this module.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import yaml

from .._compat.copier import copier_update
from .._compat.state_machine import StateMachine
from .model import (
    VALID_UPDATE_TRANSITIONS,
    TemplateUpdate,
    UpdateStatus,
)

# ---------------------------------------------------------------------------
# State machine instance
# ---------------------------------------------------------------------------

_update_sm = StateMachine(
    VALID_UPDATE_TRANSITIONS,
    entity_name="TemplateUpdate",
)

# ---------------------------------------------------------------------------
# Error
# ---------------------------------------------------------------------------


class CopyRoomError(Exception):
    """Base error with structured message (§10.3 of the implementation plan)."""

    def __init__(self, message: str, state: str | None = None) -> None:
        self.message = message
        self.state = state
        super().__init__(self._format())

    def _format(self) -> str:
        parts = [f"Error: {self.message}"]
        if self.state:
            parts.append(f"State left: {self.state}")
        return "\n".join(parts)


# ===================================================================
# Rule: InitiateTemplateUpdate         (spec L154-L164)
# ===================================================================


def initiate(
    project_root: Path,
    target_ref: str,
    use_branch: bool = False,
) -> TemplateUpdate:
    """Create a TemplateUpdate entity.

    Requires ``target_ref != null`` (InitiateTemplateUpdate requires clause).
    Infers ``template_id`` and ``previous_ref`` from ``.copier-answers.yml``.
    """
    if not target_ref:
        raise CopyRoomError(
            "Target ref is required. Usage: copyroom update <target_ref>",
            state="not_started",
        )

    answers_file = project_root / ".copier-answers.yml"
    template_id = "unknown"
    previous_ref = None

    if answers_file.is_file():
        try:
            with open(answers_file) as f:
                answers = yaml.safe_load(f)
            if isinstance(answers, dict):
                template_id = str(answers.get("_template", template_id))
                previous_ref = answers.get("_commit")
                if previous_ref is not None:
                    previous_ref = str(previous_ref)
        except (yaml.YAMLError, OSError):
            # Non-fatal: we can still proceed with defaults
            pass

    update = TemplateUpdate(
        project_root=project_root,
        template_id=template_id,
        previous_ref=previous_ref,
        target_ref=target_ref,
        use_branch=use_branch,
    )
    return update


# ===================================================================
# Rule: ResolveLatestRef               (spec L166-L170)
# ===================================================================


def resolve_latest_ref(update: TemplateUpdate) -> UpdateStatus:
    """Resolve ``target_ref`` to the latest semver tag when it is ``None``.

    This is a stub: in v0.x, if target_ref is None, the rule
    short-circuits to ``failed`` with a message. Full semver resolution
    from a remote is deferred (needs network + git ls-remote).
    """
    if update.target_ref is None:
        # Deferred: needs network access to resolve latest semver tag
        update.status = _update_sm.transition(
            UpdateStatus.initiated,
            UpdateStatus.failed,
        )
        # The entity keeps meaningful ref info per NoSilentErrors invariant
        return update.status

    # target_ref is already set; nothing to resolve
    return update.status


# ===================================================================
# Rule: LoadUpdateConfig               (spec L172-L177)
# ===================================================================


def load_config(update: TemplateUpdate) -> UpdateStatus:
    """Load configuration from ``.copier-answers.yml`` and ``copyroom.project.yml``.

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

    update.status = _update_sm.transition(
        UpdateStatus.initiated,
        UpdateStatus.config_loaded,
    )
    return update.status


# ===================================================================
# Rule: NoUpdateAvailable              (spec L179-L183)
# ===================================================================


def no_update_available(update: TemplateUpdate) -> UpdateStatus:
    """Check if the update is a no-op.

    When ``previous_ref == target_ref``, the update is already at the
    target — transition to ``failed`` with a clear message.
    """
    if update.previous_ref == update.target_ref:
        update.status = _update_sm.transition(
            UpdateStatus.config_loaded,
            UpdateStatus.failed,
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

    Runs ``git status --porcelain`` in the project root.
    On clean: transitions to ``worktree_verified``.
    On dirty: transitions to ``failed`` with remediation guidance.
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(update.project_root),
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        # Not a git repository or git not installed — treat as clean
        update.status = _update_sm.transition(
            UpdateStatus.config_loaded,
            UpdateStatus.worktree_verified,
        )
        return update.status

    if result.returncode != 0:
        # Not a git repository — treat as clean
        update.status = _update_sm.transition(
            UpdateStatus.config_loaded,
            UpdateStatus.worktree_verified,
        )
        return update.status

    if result.stdout.strip():
        # Worktree is dirty
        update.status = _update_sm.transition(
            UpdateStatus.config_loaded,
            UpdateStatus.failed,
        )
        print(
            "Worktree is not clean. Commit or stash changes before updating.",
            file=sys.stderr,
        )
        print("Dirty files:", file=sys.stderr)
        for line in result.stdout.strip().splitlines():
            print(f"  {line}", file=sys.stderr)
        return update.status

    # Worktree is clean
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

    # Capture any conflict or .rej artifacts from the output
    _capture_conflicts_from_output(update, result.stdout)
    return update.status


# ===================================================================
# Rule: CaptureUpdateConflicts         (spec L228-L234)
# ===================================================================


def capture_conflicts(update: TemplateUpdate) -> UpdateStatus:
    """Capture conflicts and rejects from the Copier output.

    If no post-update commands are configured, short-circuits to ``complete``.
    Otherwise transitions to ``post_update_run``.

    On success: transitions to ``post_update_run`` or ``complete``.
    On failure: transitions to ``failed``.
    """
    # Scan for .rej files in the project tree
    rej_files = list(update.project_root.rglob("*.rej"))
    if rej_files:
        update.rejects.update(str(f.relative_to(update.project_root)) for f in rej_files)

    # Check for post-update commands
    project_yml = update.project_root / "copyroom.project.yml"
    has_post_commands = False

    if project_yml.is_file():
        try:
            with open(project_yml) as f:
                config = yaml.safe_load(f)
            commands = _extract_post_update_commands(config)
            has_post_commands = bool(commands)
        except (yaml.YAMLError, OSError):
            pass

    if not has_post_commands:
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


def run_post_update_commands(update: TemplateUpdate) -> UpdateStatus:
    """Execute post-update commands from ``copyroom.project.yml``.

    Failures are reported but do not block completion.
    """
    project_yml = update.project_root / "copyroom.project.yml"

    try:
        with open(project_yml) as f:
            config = yaml.safe_load(f)
    except (yaml.YAMLError, OSError):
        update.status = _update_sm.transition(
            UpdateStatus.post_update_run,
            UpdateStatus.failed,
        )
        return update.status

    commands = _extract_post_update_commands(config)

    for cmd in commands:
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                cwd=str(update.project_root),
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                print(
                    f"Warning: post-update command '{cmd}' failed (exit {result.returncode}):",
                    file=sys.stderr,
                )
                if result.stderr:
                    print(result.stderr, file=sys.stderr, end="")
        except subprocess.TimeoutExpired:
            print(
                f"Warning: post-update command '{cmd}' timed out after 120s",
                file=sys.stderr,
            )
        except Exception as exc:
            print(
                f"Warning: post-update command '{cmd}' raised {exc}",
                file=sys.stderr,
            )

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
) -> TemplateUpdate:
    """Run the full template update workflow.

    This is the top-level entry point called from the CLI.

    Returns the ``TemplateUpdate`` entity in its final state (``complete``
    or ``failed``).
    """
    if project_root is None:
        project_root = Path.cwd()
    elif isinstance(project_root, str):
        project_root = Path(project_root).resolve()
    else:
        project_root = project_root.resolve()

    # 1. InitiateTemplateUpdate
    # If target_ref is not given, set to None — ResolveLatestRef will handle it
    update = initiate(project_root, target_ref or "", use_branch)

    # 2. ResolveLatestRef (if target_ref is null)
    if update.target_ref is None or not update.target_ref:
        status = resolve_latest_ref(update)
        if status == UpdateStatus.failed:
            return update

    # 3. LoadUpdateConfig
    status = load_config(update)
    if status == UpdateStatus.failed:
        return update

    # 4. NoUpdateAvailable — check if already at target
    if update.previous_ref is not None:
        status = no_update_available(update)
        if status == UpdateStatus.failed:
            return update

    # 5. VerifyCleanWorktree / RejectDirtyWorktree
    status = verify_worktree(update)
    if status == UpdateStatus.failed:
        return update

    # 6. CreateUpdateBranch (only if --branch)
    if use_branch:
        status = create_branch(update)
        if status == UpdateStatus.failed:
            return update

    # 7. ExecuteCopierUpdate / ExecuteCopierUpdateFromBranch
    status = execute_update(update)
    if status == UpdateStatus.failed:
        return update

    # 8. CaptureUpdateConflicts (may short-circuit to complete)
    status = capture_conflicts(update)
    if status == UpdateStatus.failed:
        return update
    if status == UpdateStatus.complete:
        return update

    # 9. RunPostUpdateCommands
    status = run_post_update_commands(update)
    return update


# ===================================================================
# Internal helpers
# ===================================================================


def _capture_conflicts_from_output(
    update: TemplateUpdate,
    output: str,
) -> None:
    """Parse Copier output for conflict markers and .rej references."""
    if not output:
        return

    # Look for lines mentioning conflicts
    for line in output.splitlines():
        if "conflict" in line.lower() or ".rej" in line:
            update.conflicts.add(line.strip())

    # Also capture any .rej files referenced in the output
    for match in re.finditer(r"[\w./-]+\.rej", output):
        update.rejects.add(match.group(0))


def _extract_post_update_commands(config: object) -> list[str]:
    """Extract post-update commands from a copyroom.project.yml dict.

    Expected structure::

        commands:
          post_template_update:
            - "pytest"
            - "ruff check"
    """
    if not isinstance(config, dict):
        return []
    commands = config.get("commands", {})
    if not isinstance(commands, dict):
        return []
    post = commands.get("post_template_update", [])
    if isinstance(post, list):
        return [str(c) for c in post]
    if isinstance(post, str):
        return [post]
    return []
