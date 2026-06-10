"""Domain types for workshop operations — scenario rendering, golden testing, update simulation.

Maps directly to the Allium spec at .scratch/specs/copyroom-workshop.allium.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

# ===========================================================================
# Value types
# ===========================================================================


@dataclass
class GoldenDiffResult:
    """Result of comparing rendered output to a golden snapshot (spec L14-L19).

    ``has_changes`` is derived: true when any of ``added``, ``removed``, or
    ``modified`` is non-empty.
    """

    added: set[str] = field(default_factory=set)
    removed: set[str] = field(default_factory=set)
    modified: set[str] = field(default_factory=set)

    @property
    def has_changes(self) -> bool:
        """``modified.count > 0 or added.count > 0 or removed.count > 0``."""
        return bool(self.modified or self.added or self.removed)


@dataclass
class UpdateSimulationResult:
    """Result of simulating a template update (spec L21-L25)."""

    conflicts: set[str] = field(default_factory=set)
    rejects: set[str] = field(default_factory=set)
    check_passed: bool = True  # checks "pass" until one actually fails

    @property
    def clean(self) -> bool:
        """The update applied with no conflicts, no rejects, and all checks green."""
        return self.check_passed and not self.conflicts and not self.rejects


# ===========================================================================
# Registry value types (read-only / create-only — no lifecycle)
# ===========================================================================


@dataclass
class RegistryEntry:
    """A resolved registry entry for one template id.

    Registry operations (``list``/``show``/``validate``/``add``) are reads or a
    single create — there is no multi-step lifecycle to guard, so these are
    plain value types rather than state-machine entities.
    """

    template_id: str
    source: str | None = None
    checks: list[str] = field(default_factory=list)


@dataclass
class RegistryValidation:
    """Outcome of ``registry validate`` — problems keyed by template id."""

    problems: dict[str, list[str]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """True when no entry reported a problem."""
        return not any(self.problems.values())


# ===========================================================================
# ScenarioRender
# ===========================================================================


class RenderStatus(StrEnum):
    """States in the ScenarioRender lifecycle (copyroom-workshop.allium L29-L41)."""

    initiated = "initiated"
    rendered = "rendered"
    tested = "tested"
    complete = "complete"
    failed = "failed"


# copyroom-workshop.allium L33-L38
VALID_RENDER_TRANSITIONS: dict[RenderStatus, set[RenderStatus]] = {
    RenderStatus.initiated: {RenderStatus.rendered, RenderStatus.failed},
    RenderStatus.rendered: {RenderStatus.tested, RenderStatus.complete, RenderStatus.failed},
    RenderStatus.tested: {RenderStatus.complete, RenderStatus.failed},
    RenderStatus.complete: set(),  # terminal
    RenderStatus.failed: set(),  # terminal
}


@dataclass
class ScenarioRender:
    """Represents a scenario render lifecycle (copyroom-workshop.allium L29-L41).

    Tracks state through the rendering workflow::

        initiated -> rendered -> tested -> complete
        initiated -> rendered -> complete  (short-circuit: no tests)
    """

    template_id: str
    scenario_id: str
    status: RenderStatus = RenderStatus.initiated


# ===========================================================================
# GoldenDiff
# ===========================================================================


class GoldenStatus(StrEnum):
    """States in the GoldenDiff lifecycle (copyroom-workshop.allium L43-L55)."""

    initiated = "initiated"
    rendered = "rendered"
    compared = "compared"
    has_diffs = "has_diffs"
    no_diffs = "no_diffs"
    failed = "failed"


# copyroom-workshop.allium L47-L52
VALID_GOLDEN_TRANSITIONS: dict[GoldenStatus, set[GoldenStatus]] = {
    GoldenStatus.initiated: {GoldenStatus.rendered, GoldenStatus.failed},
    GoldenStatus.rendered: {GoldenStatus.compared, GoldenStatus.failed},
    GoldenStatus.compared: {GoldenStatus.has_diffs, GoldenStatus.no_diffs},
    GoldenStatus.has_diffs: set(),  # terminal
    GoldenStatus.no_diffs: set(),  # terminal
}


@dataclass
class GoldenDiff:
    """Represents a golden diff lifecycle (copyroom-workshop.allium L43-L55).

    Tracks state through golden comparison::

        initiated -> rendered -> compared -> has_diffs | no_diffs
    """

    template_id: str
    scenario_id: str
    result: GoldenDiffResult | None = None
    status: GoldenStatus = GoldenStatus.initiated


# ===========================================================================
# UpdateSimulation
# ===========================================================================


class SimStatus(StrEnum):
    """States in the UpdateSimulation lifecycle (copyroom-workshop.allium L57-L73)."""

    initiated = "initiated"
    old_rendered = "old_rendered"
    user_edited = "user_edited"
    update_applied = "update_applied"
    checks_run = "checks_run"
    complete = "complete"
    failed = "failed"


# copyroom-workshop.allium L65-L72
VALID_SIM_TRANSITIONS: dict[SimStatus, set[SimStatus]] = {
    SimStatus.initiated: {SimStatus.old_rendered, SimStatus.failed},
    SimStatus.old_rendered: {SimStatus.user_edited, SimStatus.failed},
    SimStatus.user_edited: {SimStatus.update_applied, SimStatus.failed},
    SimStatus.update_applied: {SimStatus.checks_run, SimStatus.failed},
    SimStatus.checks_run: {SimStatus.complete, SimStatus.failed},
    SimStatus.complete: set(),  # terminal
    SimStatus.failed: set(),  # terminal
}


@dataclass
class UpdateSimulation:
    """Represents an update simulation lifecycle (copyroom-workshop.allium L57-L73).

    Tracks state through the simulation::

        initiated -> old_rendered -> user_edited -> update_applied -> checks_run -> complete

    If no edits file is found, ``user_edited`` is skipped (pruned).
    """

    template_id: str
    scenario_id: str
    old_version: str
    new_version: str
    result: UpdateSimulationResult | None = None
    status: SimStatus = SimStatus.initiated
