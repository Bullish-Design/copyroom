"""Domain types for the repo-adoption / templatization workflow.

This is the "turn a non-CopyRoom repo into a managed one" feature. Two guarded
lifecycles mirror the state-machine style used across CopyRoom:

- ``Adoption`` — render a named/extracted template with inferred answers and
  report how the repo drifts from it (writing only ``.copier-answers.yml``).
- ``Templatization`` — scaffold a self-contained template repo (Home A) whose
  golden snapshot is the repo, so the agent can parameterize it to ``no_diffs``.

Both end by feeding the same ``adopt`` primitive a template that already
reproduces the repo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

# Directory names never copied into a template/golden snapshot nor counted as
# drift: VCS metadata, CopyRoom's own scratch, and common tool/build caches.
# Shared by ``templatize`` (snapshot/copy) and ``adopt`` (drift comparison).
EXCLUDE_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".copyroom",
        ".copyroom_sim",
        "generated",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".venv",
        "node_modules",
    }
)

# ===========================================================================
# Value types
# ===========================================================================


@dataclass
class DriftResult:
    """How a repo differs from the template rendered with its inferred answers.

    Framed as the change needed to make the repo match the template:

    - ``added`` — files the template produces that the repo lacks;
    - ``modified`` — files in both whose content differs;
    - ``removed`` — files in the repo the template does not produce (the repo's
      legitimately-extra content).

    ``patch_path`` points at a reviewable unified diff. ``has_drift`` is derived.
    """

    added: set[str] = field(default_factory=set)
    modified: set[str] = field(default_factory=set)
    removed: set[str] = field(default_factory=set)
    patch_path: str | None = None

    @property
    def has_drift(self) -> bool:
        """True when the repo diverges from the rendered template in any file."""
        return bool(self.added or self.modified or self.removed)


# ===========================================================================
# Adoption
# ===========================================================================


class AdoptionStatus(StrEnum):
    """States in the Adoption lifecycle."""

    initiated = "initiated"
    template_resolved = "template_resolved"
    rendered = "rendered"
    drifted = "drifted"
    complete = "complete"
    failed = "failed"


VALID_ADOPTION_TRANSITIONS: dict[AdoptionStatus, set[AdoptionStatus]] = {
    AdoptionStatus.initiated: {AdoptionStatus.template_resolved, AdoptionStatus.failed},
    AdoptionStatus.template_resolved: {AdoptionStatus.rendered, AdoptionStatus.failed},
    AdoptionStatus.rendered: {AdoptionStatus.drifted, AdoptionStatus.failed},
    AdoptionStatus.drifted: {AdoptionStatus.complete, AdoptionStatus.failed},
    AdoptionStatus.complete: set(),  # terminal
    AdoptionStatus.failed: set(),  # terminal
}


@dataclass
class Adoption:
    """Adopting a repo into management by a named/extracted template::

        initiated -> template_resolved -> rendered -> drifted -> complete

    ``wrote_answers`` records whether ``.copier-answers.yml`` was written into
    the repo (only under ``--write``); no other repo file is ever touched.
    """

    repo_root: Path
    template_source: str = ""
    template_ref: str | None = None
    repo_dir: Path | None = None
    result: DriftResult | None = None
    wrote_answers: bool = False
    status: AdoptionStatus = AdoptionStatus.initiated


# ===========================================================================
# Templatization
# ===========================================================================


class TemplatizationStatus(StrEnum):
    """States in the Templatization lifecycle."""

    initiated = "initiated"
    scaffolded = "scaffolded"
    golden_captured = "golden_captured"
    complete = "complete"
    failed = "failed"


VALID_TEMPLATIZATION_TRANSITIONS: dict[
    TemplatizationStatus, set[TemplatizationStatus]
] = {
    TemplatizationStatus.initiated: {
        TemplatizationStatus.scaffolded,
        TemplatizationStatus.failed,
    },
    TemplatizationStatus.scaffolded: {
        TemplatizationStatus.golden_captured,
        TemplatizationStatus.failed,
    },
    TemplatizationStatus.golden_captured: {
        TemplatizationStatus.complete,
        TemplatizationStatus.failed,
    },
    TemplatizationStatus.complete: set(),  # terminal
    TemplatizationStatus.failed: set(),  # terminal
}


@dataclass
class Templatization:
    """Scaffolding a self-contained template repo (Home A) from a repo::

        initiated -> scaffolded -> golden_captured -> complete

    ``home_dir`` is the new sibling template repo; ``template_id`` is the id the
    workshop registry / scenarios / golden use to refer to it.
    """

    repo_root: Path
    home_dir: Path
    template_id: str
    project_name: str = ""
    status: TemplatizationStatus = TemplatizationStatus.initiated
