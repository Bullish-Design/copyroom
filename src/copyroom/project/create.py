"""Project creation workflow — ``copyroom new``.

Implements the ProjectCreation state machine from copyroom-project.allium:

    initiated -> target_verified -> prompts_collected -> copy_executed ->
        [post_create_run ->] complete

Each rule in the spec maps to a function or method in this module.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

from .._compat.copier import copier_copy
from .._compat.errors import CopyRoomError
from .._compat.shellcmd import run_hook_commands
from .._compat.state_machine import StateMachine
from .config import load_hook_commands
from .model import (
    VALID_CREATION_TRANSITIONS,
    CreationStatus,
    ProjectCreation,
)

__all__ = ["CopyRoomError", "create_project"]

# ---------------------------------------------------------------------------
# State machine instance
# ---------------------------------------------------------------------------

_creation_sm = StateMachine(
    VALID_CREATION_TRANSITIONS,
    entity_name="ProjectCreation",
)


# ===================================================================
# Rule: InitiateProjectCreation       (spec L76-L85)
# ===================================================================


def initiate(
    source: str,
    target_dir: str = ".",
    answer_file: str | None = None,
) -> ProjectCreation:
    """Create a ProjectCreation entity.

    Validates ``source != ""`` (InitiateProjectCreation requires clause).
    """
    if not source:
        raise CopyRoomError(
            "Template source is required. Usage: copyroom new <source> [target]",
            state="not_started",
        )

    creation = ProjectCreation(
        template_source=source,
        target_dir=target_dir or ".",
        uses_answer_file=answer_file is not None,
    )
    return creation


# ===================================================================
# Rule: VerifyTargetDirectory          (spec L87-L94)
# Rule: RejectNonEmptyTarget           (spec L96-L100)
# ===================================================================


def verify_target(creation: ProjectCreation) -> CreationStatus:
    """Check that the target directory is empty or non-existent.

    On success: transitions to ``target_verified``.
    On failure: transitions to ``failed`` with a suggestion.
    """
    target = Path(creation.target_dir).resolve()

    if target.exists():
        entries = list(target.iterdir())
        if entries:
            creation.status = _creation_sm.transition(
                CreationStatus.initiated,
                CreationStatus.failed,
            )
            creation.result_suggestions = [
                "Target directory is not empty. Choose an empty or non-existent directory.",
            ]
            return creation.status

    creation.status = _creation_sm.transition(
        CreationStatus.initiated,
        CreationStatus.target_verified,
    )
    return creation.status


# ===================================================================
# Rule: CollectPrompts                 (spec L102-L107)
# ===================================================================


def collect_prompts(
    creation: ProjectCreation,
    answers_file: str | None = None,
) -> CreationStatus:
    """Load answers from a YAML file or prepare for interactive prompts.

    On success: transitions to ``prompts_collected``.
    On failure: transitions to ``failed``.
    """
    if answers_file is not None:
        answers_path = Path(answers_file)
        if not answers_path.is_file():
            creation.status = _creation_sm.transition(
                CreationStatus.target_verified,
                CreationStatus.failed,
            )
            creation.result_suggestions = [
                f"Answers file not found: {answers_file}",
            ]
            return creation.status

        try:
            with open(answers_path) as f:
                yaml.safe_load(f)
        except (yaml.YAMLError, OSError) as exc:
            creation.status = _creation_sm.transition(
                CreationStatus.target_verified,
                CreationStatus.failed,
            )
            creation.result_suggestions = [
                f"Failed to parse answers file: {exc}",
            ]
            return creation.status

    creation.status = _creation_sm.transition(
        CreationStatus.target_verified,
        CreationStatus.prompts_collected,
    )
    return creation.status


# ===================================================================
# Rule: ExecuteCopierCopy              (spec L109-L116)
# Rule: CopierCopyFailed               (spec L118-L125)
# ===================================================================


def execute_copy(
    creation: ProjectCreation,
    answers_file: str | None = None,
) -> CreationStatus:
    """Run ``copier copy`` to generate the project.

    On success: transitions to ``copy_executed``.
    On failure: transitions to ``failed`` with suggestions.
    """
    target = Path(creation.target_dir).resolve()
    answer_path = Path(answers_file) if answers_file else None

    try:
        result = copier_copy(creation.template_source, target, answer_path)
    except Exception as exc:
        creation.status = _creation_sm.transition(
            CreationStatus.prompts_collected,
            CreationStatus.failed,
        )
        creation.result_suggestions = [
            f"Copier copy failed: {exc}",
            "The target directory may be in an inconsistent state.",
        ]
        return creation.status

    if result.returncode != 0:
        creation.status = _creation_sm.transition(
            CreationStatus.prompts_collected,
            CreationStatus.failed,
        )
        creation.result_suggestions = [
            "Copier copy failed. Check the error output above.",
            "The target directory may be in an inconsistent state.",
        ]
        # Forward Copier's stderr so the user sees what went wrong
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="")
        if result.stdout:
            print(result.stdout, file=sys.stderr, end="")
        return creation.status

    creation.status = _creation_sm.transition(
        CreationStatus.prompts_collected,
        CreationStatus.copy_executed,
    )
    return creation.status


# ===================================================================
# Rule: DetectPostCreateCommands       (spec L127-L133)
# ===================================================================


def detect_post_create_commands(creation: ProjectCreation) -> CreationStatus:
    """Check for post-create commands in ``copyroom.project.yml``.

    If commands are found, transitions to ``post_create_run``.
    If no commands are configured, short-circuits to ``complete``.
    On failure: transitions to ``failed``.
    """
    project_yml = Path(creation.target_dir).resolve() / "copyroom.project.yml"

    try:
        # Resilient read: a schema-divergent but readable config (e.g. a newer
        # template's project.kind) must not block generation — only truly
        # unusable YAML raises here.
        commands = load_hook_commands(project_yml, "post_project_create")
    except CopyRoomError:
        creation.status = _creation_sm.transition(
            CreationStatus.copy_executed,
            CreationStatus.failed,
        )
        creation.result_suggestions = [
            "Failed to parse copyroom.project.yml for post-create commands.",
        ]
        return creation.status

    if not commands:
        # No post-create commands configured — short-circuit to complete
        creation.status = _creation_sm.transition(
            CreationStatus.copy_executed,
            CreationStatus.complete,
        )
        _populate_completion_suggestions(creation)
        return creation.status

    creation.status = _creation_sm.transition(
        CreationStatus.copy_executed,
        CreationStatus.post_create_run,
    )
    return creation.status


# ===================================================================
# Rule: RunPostCreateCommands          (spec L135-L139)
# ===================================================================


def run_post_create_commands(
    creation: ProjectCreation,
    trust: bool = False,
) -> CreationStatus:
    """Execute post-create commands from ``copyroom.project.yml``.

    Commands come from a fetched template and only run when ``trust`` is set;
    otherwise they are skipped with a warning. Failures do not block completion.
    """
    project_yml = Path(creation.target_dir).resolve() / "copyroom.project.yml"

    try:
        commands = load_hook_commands(project_yml, "post_project_create")
    except CopyRoomError:
        creation.status = _creation_sm.transition(
            CreationStatus.post_create_run,
            CreationStatus.failed,
        )
        creation.result_suggestions = [
            "Failed to parse copyroom.project.yml for post-create commands.",
        ]
        return creation.status

    target = Path(creation.target_dir).resolve()
    run_hook_commands(commands, target, trust=trust, label="post-create")

    creation.status = _creation_sm.transition(
        CreationStatus.post_create_run,
        CreationStatus.complete,
    )
    _populate_completion_suggestions(creation)
    return creation.status


# ===================================================================
# Rule: CompleteProjectCreation        (spec L141-L149)
# ===================================================================


def _populate_completion_suggestions(creation: ProjectCreation) -> None:
    """Populate result_suggestions with next-steps on completion."""
    creation.result_suggestions = [
        f"cd {creation.target_dir}",
        "git init && git add . && git commit -m \"Initial generation\"",
        "copyroom inspect",
    ]


# ===================================================================
# High-level workflow
# ===================================================================


def create_project(
    source: str,
    target_dir: str = ".",
    answers_file: str | None = None,
    trust: bool = False,
) -> ProjectCreation:
    """Run the full project creation workflow.

    This is the top-level entry point called from the CLI.

    ``trust`` enables execution of the template's post-create hook commands;
    when ``False`` (the default) they are skipped with a warning.

    Returns the ``ProjectCreation`` entity in its final state (``complete``
    or ``failed``).
    """
    # 1. InitiateProjectCreation
    creation = initiate(source, target_dir, answers_file)

    # 2. VerifyTargetDirectory / RejectNonEmptyTarget
    status = verify_target(creation)
    if status == CreationStatus.failed:
        return creation

    # 3. CollectPrompts
    status = collect_prompts(creation, answers_file)
    if status == CreationStatus.failed:
        return creation

    # 4. ExecuteCopierCopy / CopierCopyFailed
    status = execute_copy(creation, answers_file)
    if status == CreationStatus.failed:
        return creation

    # 5. DetectPostCreateCommands (may short-circuit to complete)
    status = detect_post_create_commands(creation)
    if status == CreationStatus.failed:
        return creation
    if status == CreationStatus.complete:
        return creation

    # 6. RunPostCreateCommands
    status = run_post_create_commands(creation, trust=trust)
    return creation
