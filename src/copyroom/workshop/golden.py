"""Golden testing workflow — ``copyroom golden`` and ``copyroom golden --refresh``.

Implements the GoldenDiff state machine from copyroom-workshop.allium:

    initiated -> rendered -> compared -> has_diffs | no_diffs

The snapshot is the full rendered tree, compared file-by-file, excluding
Copier's machine-specific ``.copier-answers.yml``.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from .._compat.errors import CopyRoomError
from .._compat.state_machine import StateMachine
from .._compat.treediff import collect_files, tree_diff
from .model import (
    VALID_GOLDEN_TRANSITIONS,
    GoldenDiff,
    GoldenDiffResult,
    GoldenStatus,
)
from .registry import require_workshop_root, resolve_template_source
from .render import execute_render
from .render import initiate as render_initiate

__all__ = ["CopyRoomError", "golden_diff", "refresh_golden"]

# ---------------------------------------------------------------------------
# State machine instance
# ---------------------------------------------------------------------------

_golden_sm = StateMachine(
    VALID_GOLDEN_TRANSITIONS,
    entity_name="GoldenDiff",
)


# ===================================================================
# Rule: DiffGolden                     (spec L110-L116)
# ===================================================================


def initiate(template_id: str, scenario_id: str) -> GoldenDiff:
    """Create a GoldenDiff entity in ``initiated`` state."""
    if not template_id:
        raise CopyRoomError(
            "Template ID is required. Usage: copyroom golden <template_id> <scenario_id>",
            state="not_started",
        )
    if not scenario_id:
        raise CopyRoomError(
            "Scenario ID is required. Usage: copyroom golden <template_id> <scenario_id>",
            state="not_started",
        )

    return GoldenDiff(template_id=template_id, scenario_id=scenario_id)


# ===================================================================
# Rule: RenderForGoldenDiff            (spec L118-L124)
# ===================================================================


def render_for_golden(
    diff: GoldenDiff,
    workshop_root: Path,
    template_source: str,
) -> GoldenStatus:
    """Render the template with the scenario to get current output.

    Reuses the same rendering logic as ``copyroom render`` but stores
    state in the GoldenDiff entity.
    """
    # Reuse ScenarioRender for the rendering step
    render = render_initiate(diff.template_id, diff.scenario_id)
    status = execute_render(render, workshop_root, template_source)

    if status.value == "failed":
        diff.status = _golden_sm.transition(
            GoldenStatus.initiated,
            GoldenStatus.failed,
        )
        return diff.status

    diff.status = _golden_sm.transition(
        GoldenStatus.initiated,
        GoldenStatus.rendered,
    )
    return diff.status


# ===================================================================
# Rule: CompareToGolden                (spec L126-L132)
# Rule: GoldenHasDiffs                 (spec L134-L139)
# Rule: GoldenNoDiffs                  (spec L141-L146)
# ===================================================================


def compare_to_golden(
    diff: GoldenDiff,
    workshop_root: Path,
) -> GoldenStatus:
    """Compare generated output to golden snapshot.

    Compares every file in the rendered tree against the golden snapshot,
    excluding Copier's ``.copier-answers.yml`` (see ``_is_copier_answers_file``),
    and produces lists of added, removed, and modified files in ``diff.result``.
    """
    generated_dir = workshop_root / "generated" / diff.template_id / diff.scenario_id
    golden_dir = workshop_root / "golden" / diff.template_id / diff.scenario_id

    if not generated_dir.is_dir():
        diff.status = _golden_sm.transition(
            GoldenStatus.rendered,
            GoldenStatus.failed,
        )
        print(
            f"Error: Generated directory not found: {generated_dir}",
            file=sys.stderr,
        )
        return diff.status

    if not golden_dir.is_dir():
        # No golden snapshot exists — everything is "added"
        all_files = collect_files(generated_dir)
        diff.result = GoldenDiffResult(added=all_files)
    else:
        # Baseline = golden, target = generated, so "added" means present in the
        # new render but not the snapshot (matching the prior semantics).
        added, modified, removed = tree_diff(golden_dir, generated_dir)
        diff.result = GoldenDiffResult(
            added=added, removed=removed, modified=modified,
        )

    # Transition to compared
    diff.status = _golden_sm.transition(
        GoldenStatus.rendered,
        GoldenStatus.compared,
    )

    # Branch on has_changes
    if diff.result.has_changes:
        diff.status = _golden_sm.transition(
            GoldenStatus.compared,
            GoldenStatus.has_diffs,
        )
    else:
        diff.status = _golden_sm.transition(
            GoldenStatus.compared,
            GoldenStatus.no_diffs,
        )

    return diff.status


# ===================================================================
# Rule: RefreshGolden                  (spec L148-L152)
# ===================================================================


def refresh_golden(
    template_id: str,
    scenario_id: str,
    workshop_root: Path | None = None,
) -> None:
    """Overwrite the golden snapshot with the current generated output.

    Copies ``generated/<template_id>/<scenario_id>/`` to
    ``golden/<template_id>/<scenario_id>/``.
    """
    workshop_root = require_workshop_root(workshop_root)
    generated_dir = workshop_root / "generated" / template_id / scenario_id
    golden_dir = workshop_root / "golden" / template_id / scenario_id

    if not generated_dir.is_dir():
        raise CopyRoomError(
            f"Generated directory not found: {generated_dir}\n"
            f"Run 'copyroom render {template_id} {scenario_id}' first.",
            state="refresh_failed",
        )

    # Remove old golden if it exists
    if golden_dir.exists():
        shutil.rmtree(golden_dir)

    # Copy generated output to golden
    shutil.copytree(generated_dir, golden_dir)


# ===================================================================
# High-level workflow
# ===================================================================


def golden_diff(
    template_id: str,
    scenario_id: str,
    workshop_root: Path | None = None,
    template_source: str | None = None,
    reuse_generated: bool = False,
) -> GoldenDiff:
    """Run the full golden diff workflow.

    This is the top-level entry point called from the CLI for
    ``copyroom golden <template_id> <scenario_id>``.

    When *reuse_generated* is ``True`` the existing
    ``generated/<template_id>/<scenario_id>/`` output is compared as-is and the
    render step is skipped. ``release-check`` uses this to avoid re-rendering a
    scenario it has already rendered in the matrix pass (one Copier invocation
    per scenario instead of two).

    Returns the ``GoldenDiff`` entity in its final state
    (``has_diffs``, ``no_diffs``, or ``failed``).
    """
    workshop_root = require_workshop_root(workshop_root)

    # Resolve template source from registry if not provided. Not needed when
    # reusing already-generated output, since no render happens.
    if template_source is None and not reuse_generated:
        template_source = resolve_template_source(workshop_root, template_id)
        if template_source is None:
            diff = initiate(template_id, scenario_id)
            diff.status = _golden_sm.transition(
                GoldenStatus.initiated,
                GoldenStatus.failed,
            )
            print(
                f"Error: Template '{template_id}' not found in workshop registry.",
                file=sys.stderr,
            )
            return diff

    # 1. DiffGolden — create entity
    diff = initiate(template_id, scenario_id)

    # 2. RenderForGoldenDiff (or reuse the output a prior render produced)
    if reuse_generated:
        diff.status = _golden_sm.transition(
            GoldenStatus.initiated,
            GoldenStatus.rendered,
        )
    else:
        status = render_for_golden(diff, workshop_root, template_source)
        if status == GoldenStatus.failed:
            return diff

    # 3. CompareToGolden → GoldenHasDiffs | GoldenNoDiffs
    status = compare_to_golden(diff, workshop_root)
    return diff
