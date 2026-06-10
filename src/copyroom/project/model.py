"""Domain types for project operations — creation and template update.

Maps directly to the Allium spec at .scratch/specs/copyroom-project.allium.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

# ---------------------------------------------------------------------------
# ProjectCreation
# ---------------------------------------------------------------------------


class CreationStatus(StrEnum):
    """States in the ProjectCreation lifecycle (copyroom-project.allium L12-L39)."""

    initiated = "initiated"
    target_verified = "target_verified"
    prompts_collected = "prompts_collected"
    copy_executed = "copy_executed"
    post_create_run = "post_create_run"
    complete = "complete"
    failed = "failed"


# copyroom-project.allium L26-L39
VALID_CREATION_TRANSITIONS: dict[CreationStatus, set[CreationStatus]] = {
    CreationStatus.initiated: {CreationStatus.target_verified, CreationStatus.failed},
    CreationStatus.target_verified: {CreationStatus.prompts_collected, CreationStatus.failed},
    CreationStatus.prompts_collected: {CreationStatus.copy_executed, CreationStatus.failed},
    CreationStatus.copy_executed: {
        CreationStatus.post_create_run,
        CreationStatus.complete,
        CreationStatus.failed,
    },
    CreationStatus.post_create_run: {CreationStatus.complete, CreationStatus.failed},
    CreationStatus.complete: set(),  # terminal
    CreationStatus.failed: set(),  # terminal
}


@dataclass
class ProjectCreation:
    """Represents a project creation lifecycle (copyroom-project.allium L12-L24).

    Tracks state through the creation workflow:

        initiated -> target_verified -> prompts_collected -> copy_executed ->
            [post_create_run ->] complete

    Failure can occur at any non-terminal state.
    """

    template_source: str
    target_dir: str = "."
    uses_answer_file: bool = False
    status: CreationStatus = CreationStatus.initiated
    result_suggestions: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# TemplateUpdate
# ---------------------------------------------------------------------------


class UpdateStatus(StrEnum):
    """States in the TemplateUpdate lifecycle (copyroom-project.allium L41-L72)."""

    initiated = "initiated"
    config_loaded = "config_loaded"
    worktree_verified = "worktree_verified"
    branch_created = "branch_created"
    update_executed = "update_executed"
    post_update_run = "post_update_run"
    complete = "complete"
    failed = "failed"


# copyroom-project.allium L58-L72
VALID_UPDATE_TRANSITIONS: dict[UpdateStatus, set[UpdateStatus]] = {
    UpdateStatus.initiated: {UpdateStatus.config_loaded, UpdateStatus.failed},
    UpdateStatus.config_loaded: {UpdateStatus.worktree_verified, UpdateStatus.failed},
    UpdateStatus.worktree_verified: {
        UpdateStatus.branch_created,
        UpdateStatus.update_executed,
        UpdateStatus.failed,
    },
    UpdateStatus.branch_created: {UpdateStatus.update_executed, UpdateStatus.failed},
    UpdateStatus.update_executed: {
        UpdateStatus.post_update_run,
        UpdateStatus.complete,
        UpdateStatus.failed,
    },
    UpdateStatus.post_update_run: {UpdateStatus.complete, UpdateStatus.failed},
    UpdateStatus.complete: set(),  # terminal
    UpdateStatus.failed: set(),  # terminal
}


@dataclass
class TemplateUpdate:
    """Represents a template update lifecycle (copyroom-project.allium L41-L56).

    Tracks state through the update workflow:

        initiated -> config_loaded -> worktree_verified ->
            [branch_created ->] update_executed -> post_update_run -> complete

    Failure can occur at any non-terminal state.
    """

    project_root: Path
    template_id: str
    previous_ref: str | None = None
    target_ref: str | None = None
    use_branch: bool = False
    status: UpdateStatus = UpdateStatus.initiated
    update_branch: str | None = None
    conflicts: set[str] = field(default_factory=set)
    rejects: set[str] = field(default_factory=set)
    # The template source (``_src_path`` from .copier-answers.yml), captured by
    # load_config and used to resolve the latest semver tag for a no-arg update.
    template_source: str | None = None
    # True when target_ref was auto-resolved (the no-arg "update to latest" path)
    # rather than passed explicitly — drives the "already at latest" message.
    resolved_latest: bool = False
