"""Domain types for the template-edit workflow.

This is the "drive a change back into the template, from a project" feature:
resolve the project's template into an isolated editable worktree, render-test
it, then preview the update the project would receive — all without touching the
real project working tree.

Two guarded lifecycles (``TemplateCheckout`` and ``TemplatePreview``) mirror the
state-machine style used across CopyRoom; render-testing is a single step and
returns a plain ``ValidateResult``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

# ===========================================================================
# Value types
# ===========================================================================


@dataclass
class PreviewResult:
    """What a project would receive when updated to the edited template.

    ``has_changes`` is derived: true when any file set is non-empty.
    """

    added: set[str] = field(default_factory=set)
    modified: set[str] = field(default_factory=set)
    removed: set[str] = field(default_factory=set)
    conflicts: set[str] = field(default_factory=set)
    rejects: set[str] = field(default_factory=set)
    patch_path: str | None = None

    @property
    def has_changes(self) -> bool:
        """True when the update would add, modify, or remove any file."""
        return bool(self.added or self.modified or self.removed)


@dataclass
class ValidateResult:
    """Outcome of render-testing an edited template with the project's answers."""

    ok: bool = False
    output_dir: str | None = None
    messages: list[str] = field(default_factory=list)


# ===========================================================================
# TemplateCheckout
# ===========================================================================


class CheckoutStatus(StrEnum):
    """States in the TemplateCheckout lifecycle."""

    initiated = "initiated"
    source_resolved = "source_resolved"
    worktree_ready = "worktree_ready"
    failed = "failed"


VALID_CHECKOUT_TRANSITIONS: dict[CheckoutStatus, set[CheckoutStatus]] = {
    CheckoutStatus.initiated: {CheckoutStatus.source_resolved, CheckoutStatus.failed},
    CheckoutStatus.source_resolved: {CheckoutStatus.worktree_ready, CheckoutStatus.failed},
    CheckoutStatus.worktree_ready: set(),  # terminal
    CheckoutStatus.failed: set(),  # terminal
}


@dataclass
class TemplateCheckout:
    """An isolated, editable checkout of the project's template.

    Tracks resolution of the template source from ``.copier-answers.yml`` and
    creation of a scratch worktree/branch the agent edits on::

        initiated -> source_resolved -> worktree_ready
    """

    project_root: Path
    template_source: str = ""
    previous_ref: str | None = None
    base_ref: str | None = None
    repo_dir: Path | None = None
    worktree_dir: Path | None = None
    branch: str | None = None
    # Number of commits already on a *reused* edit branch beyond its base — a
    # leftover from an abandoned prior edit session. 0 on a fresh worktree.
    reused_commits: int = 0
    status: CheckoutStatus = CheckoutStatus.initiated


# ===========================================================================
# TemplatePreview
# ===========================================================================


class PreviewStatus(StrEnum):
    """States in the TemplatePreview lifecycle."""

    initiated = "initiated"
    sandbox_prepared = "sandbox_prepared"
    update_simulated = "update_simulated"
    diffed = "diffed"
    complete = "complete"
    failed = "failed"


VALID_PREVIEW_TRANSITIONS: dict[PreviewStatus, set[PreviewStatus]] = {
    PreviewStatus.initiated: {PreviewStatus.sandbox_prepared, PreviewStatus.failed},
    PreviewStatus.sandbox_prepared: {PreviewStatus.update_simulated, PreviewStatus.failed},
    PreviewStatus.update_simulated: {PreviewStatus.diffed, PreviewStatus.failed},
    PreviewStatus.diffed: {PreviewStatus.complete, PreviewStatus.failed},
    PreviewStatus.complete: set(),  # terminal
    PreviewStatus.failed: set(),  # terminal
}


@dataclass
class TemplatePreview:
    """A sandboxed preview of updating the project to the edited template::

        initiated -> sandbox_prepared -> update_simulated -> diffed -> complete
    """

    project_root: Path
    worktree_dir: Path
    branch: str
    result: PreviewResult | None = None
    status: PreviewStatus = PreviewStatus.initiated
