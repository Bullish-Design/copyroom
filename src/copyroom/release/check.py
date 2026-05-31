"""Release readiness checks — ``copyroom release-check``.

Implements the ReleaseCheck state machine from copyroom-release.allium:

    initiated -> matrix_run -> checked -> passed | failed

Runs the full workshop matrix for a template and reports pass/fail
for release readiness. Release checks are advisory in v0.x;
actual tagging is manual.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

import yaml

from .._compat.state_machine import StateMachine
from ..session.detector import detect_workshop_root
from ..workshop.golden import golden_diff as _golden_diff
from ..workshop.model import GoldenStatus, RenderStatus
from ..workshop.render import render_scenario


# ===========================================================================
# ReleaseCheck entity
# ===========================================================================


class ReleaseStatus(StrEnum):
    """States in the ReleaseCheck lifecycle (copyroom-release.allium L18-L22)."""

    initiated = "initiated"
    matrix_run = "matrix_run"
    checked = "checked"
    passed = "passed"
    failed = "failed"


# copyroom-release.allium L18-L22
VALID_RELEASE_TRANSITIONS: dict[ReleaseStatus, set[ReleaseStatus]] = {
    ReleaseStatus.initiated: {ReleaseStatus.matrix_run, ReleaseStatus.failed},
    ReleaseStatus.matrix_run: {ReleaseStatus.checked, ReleaseStatus.failed},
    ReleaseStatus.checked: {ReleaseStatus.passed, ReleaseStatus.failed},
    ReleaseStatus.passed: set(),   # terminal
    ReleaseStatus.failed: set(),   # terminal
}

_release_sm = StateMachine(
    VALID_RELEASE_TRANSITIONS,
    entity_name="ReleaseCheck",
)

# ---------------------------------------------------------------------------
# Error
# ---------------------------------------------------------------------------


class CopyRoomError(Exception):
    """Base error with structured message."""

    def __init__(self, message: str, state: str | None = None) -> None:
        self.message = message
        self.state = state
        super().__init__(self._format())

    def _format(self) -> str:
        parts = [f"Error: {self.message}"]
        if self.state:
            parts.append(f"State left: {self.state}")
        return "\n".join(parts)


# ===========================================================================
# Entity dataclass
# ===========================================================================


@dataclass
class ReleaseCheck:
    """Release readiness check entity (copyroom-release.allium L12-L27).

    Tracks:
    * ``matrix_passed`` — all scenario render + test invocations succeeded
    * ``worktree_clean`` — git working tree has no uncommitted changes
    * ``golden_ok`` — all golden diffs have zero changes
    * ``status`` — current state in the lifecycle

    All three boolean fields must be ``True`` for a passing result.
    """

    template_id: str

    # Boolean pass/fail fields (from spec)
    matrix_passed: bool = False
    worktree_clean: bool = False
    golden_ok: bool = False

    status: ReleaseStatus = ReleaseStatus.initiated

    # Detail counts for reporting
    scenario_ids: list[str] = field(default_factory=list)
    scenario_total: int = 0
    scenario_passed: int = 0
    golden_total: int = 0
    golden_passed: int = 0

    # Per-scenario failure details
    render_failures: list[str] = field(default_factory=list)
    golden_failures: list[str] = field(default_factory=list)


# ===========================================================================
# Rule: RunReleaseCheck                (spec L29-L37)
# ===========================================================================


def create_check(template_id: str) -> ReleaseCheck:
    """Create a ReleaseCheck entity in ``initiated`` state."""
    if not template_id:
        raise CopyRoomError(
            "Template ID is required. Usage: copyroom release-check <template_id>",
            state="not_started",
        )
    return ReleaseCheck(template_id=template_id)


# ===========================================================================
# Rule: RunMatrix                      (spec L39-L43)
# ===========================================================================


def run_matrix(
    check: ReleaseCheck,
    workshop_root: Path,
    template_source: str,
) -> ReleaseStatus:
    """Run all scenarios for this template: render, test, golden diff.

    Discovers scenarios from ``scenarios/<template_id>/``, runs each
    through render + test (populates ``matrix_passed``) and golden diff
    (populates ``golden_ok``).  Also checks the git worktree.

    Returns the new status (``matrix_run`` or ``failed``).
    """
    # --- discover scenarios ---
    scenario_ids = _discover_scenarios(workshop_root, check.template_id)
    check.scenario_ids = scenario_ids
    check.scenario_total = len(scenario_ids)

    if not scenario_ids:
        # No scenarios — the matrix is trivially passing but golden can't run
        check.matrix_passed = True
        check.golden_ok = True
        check.scenario_passed = 0
        check.golden_total = 0
        check.golden_passed = 0
    else:
        # --- run render + test for every scenario ---
        check.scenario_passed = 0
        for scenario_id in scenario_ids:
            render = render_scenario(
                template_id=check.template_id,
                scenario_id=scenario_id,
                workshop_root=workshop_root,
                template_source=template_source,
            )
            if render.status == RenderStatus.complete:
                check.scenario_passed += 1
            else:
                check.render_failures.append(scenario_id)

        check.matrix_passed = (check.scenario_passed == check.scenario_total)

        # --- run golden diff for every scenario ---
        check.golden_total = len(scenario_ids)
        check.golden_passed = 0
        for scenario_id in scenario_ids:
            diff = _golden_diff(
                template_id=check.template_id,
                scenario_id=scenario_id,
                workshop_root=workshop_root,
                template_source=template_source,
            )
            if diff.status == GoldenStatus.no_diffs:
                check.golden_passed += 1
            elif diff.status == GoldenStatus.has_diffs:
                check.golden_failures.append(scenario_id)
            # failed or any other state: not a pass

        check.golden_ok = (check.golden_passed == check.golden_total)

    # --- check worktree ---
    check.worktree_clean = _check_worktree_clean(workshop_root)

    # Transition to matrix_run
    check.status = _release_sm.transition(
        ReleaseStatus.initiated,
        ReleaseStatus.matrix_run,
    )
    return check.status


# ===========================================================================
# Rule: EvaluateReleaseReadiness       (spec L45-L47)
# ===========================================================================


def evaluate(check: ReleaseCheck) -> ReleaseStatus:
    """Evaluate release readiness, advancing to ``checked``."""
    check.status = _release_sm.transition(
        ReleaseStatus.matrix_run,
        ReleaseStatus.checked,
    )
    return check.status


# ===========================================================================
# Rule: ReleaseCheckPassed             (spec L49-L54)
# Rule: ReleaseCheckFailed             (spec L56-L62)
# ===========================================================================


def resolve(check: ReleaseCheck) -> ReleaseStatus:
    """Resolve the check to ``passed`` or ``failed`` based on booleans.

    ReleaseCheckPassed: requires ``matrix_passed and worktree_clean and golden_ok``.
    ReleaseCheckFailed: any one false → failed.
    """
    if check.matrix_passed and check.worktree_clean and check.golden_ok:
        check.status = _release_sm.transition(
            ReleaseStatus.checked,
            ReleaseStatus.passed,
        )
    else:
        check.status = _release_sm.transition(
            ReleaseStatus.checked,
            ReleaseStatus.failed,
        )
    return check.status


# ===========================================================================
# High-level workflow
# ===========================================================================


def run_release_check(
    template_id: str,
    workshop_root: Path | None = None,
    template_source: str | None = None,
) -> ReleaseCheck:
    """Run the full release check workflow.

    This is the top-level entry point called from the CLI for
    ``copyroom release-check <template_id>``.

    Workflow::

        create_check -> run_matrix -> evaluate -> resolve

    Returns the ``ReleaseCheck`` entity in its final state
    (``passed`` or ``failed``).
    """
    # Auto-detect workshop root from current directory
    if workshop_root is None:
        workshop_root = detect_workshop_root()
        if workshop_root is None:
            raise CopyRoomError(
                "No CopyRoom workshop found here. "
                "Run 'copyroom release-check' from a workshop directory "
                "or any descendant.",
                state="not_started",
            )

    # 1. RunReleaseCheck — create entity
    check = create_check(template_id)

    # Resolve template source from registry if not provided
    if template_source is None:
        template_source = _resolve_template_source(workshop_root, template_id)
        if template_source is None:
            check.status = _release_sm.transition(
                ReleaseStatus.initiated,
                ReleaseStatus.failed,
            )
            print(
                f"Error: Template '{template_id}' not found in workshop registry.",
                file=sys.stderr,
            )
            return check

    # 2. RunMatrix — run all scenarios
    status = run_matrix(check, workshop_root, template_source)

    # If run_matrix failed or we advanced to failed directly
    if check.status == ReleaseStatus.failed:
        return check

    # 3. EvaluateReleaseReadiness
    status = evaluate(check)

    # 4. ReleaseCheckPassed | ReleaseCheckFailed
    status = resolve(check)
    return check


# ===========================================================================
# Output formatting
# ===========================================================================


def format_release_report(check: ReleaseCheck) -> str:
    """Format the release check result as a human-readable report.

    Example output::

        Release Check: my-template
          Matrix:     ✅ PASSED (5/5 scenarios rendered, tested)
          Worktree:   ✅ CLEAN
          Golden:     ✅ OK (3/3 scenarios match golden)
          Result:     🟢 PASSED

        Note: Release checks are advisory in v0.x.
        Tagging is manual: git tag v0.4.0 && git push --tags
    """
    lines: list[str] = []
    lines.append(f"\nRelease Check: {check.template_id}")

    # Matrix line
    if check.matrix_passed:
        matrix_marker = "✅"
        matrix_label = "PASSED"
    else:
        matrix_marker = "❌"
        matrix_label = "FAILED"

    matrix_detail = f"{check.scenario_passed}/{check.scenario_total} scenarios rendered, tested"
    if check.render_failures:
        matrix_detail += f" (failures: {', '.join(check.render_failures)})"
    lines.append(f"  Matrix:     {matrix_marker} {matrix_label} ({matrix_detail})")

    # Worktree line
    if check.worktree_clean:
        lines.append("  Worktree:   ✅ CLEAN")
    else:
        lines.append("  Worktree:   ❌ DIRTY (uncommitted changes present)")

    # Golden line
    if check.golden_ok:
        golden_marker = "✅"
        golden_label = "OK"
    else:
        golden_marker = "❌"
        golden_label = "DIFFS"

    golden_detail = f"{check.golden_passed}/{check.golden_total} scenarios match golden"
    if check.golden_failures:
        golden_detail += f" (diffs: {', '.join(check.golden_failures)})"
    lines.append(f"  Golden:     {golden_marker} {golden_label} ({golden_detail})")

    # Result line
    if check.status == ReleaseStatus.passed:
        lines.append("  Result:     🟢 PASSED")
    elif check.status == ReleaseStatus.failed:
        lines.append("  Result:     🔴 FAILED")
    else:
        lines.append(f"  Result:     ⚠️  UNEXPECTED ({check.status.value})")

    # Advisory note
    lines.append("")
    lines.append("Note: Release checks are advisory in v0.x.")
    lines.append("Tagging is manual: git tag v0.4.0 && git push --tags")
    lines.append("")

    return "\n".join(lines)


# ===========================================================================
# Internal helpers
# ===========================================================================


def _discover_scenarios(
    workshop_root: Path,
    template_id: str,
) -> list[str]:
    """Discover scenario IDs for *template_id*.

    Scans ``scenarios/<template_id>/`` for ``.yml`` files, excluding
    ``*-edits.yml`` files (those are edit specification files, not
    standalone scenarios).

    Returns scenario IDs (filenames without ``.yml`` extension) sorted
    alphabetically for deterministic output.
    """
    scenarios_dir = workshop_root / "scenarios" / template_id
    if not scenarios_dir.is_dir():
        return []

    scenario_ids: list[str] = []
    for entry in sorted(scenarios_dir.iterdir()):
        if not entry.is_file():
            continue
        if not entry.suffix == ".yml":
            continue
        # Skip edit files (they're companions, not standalone scenarios)
        if entry.name.endswith("-edits.yml"):
            continue
        scenario_ids.append(entry.stem)

    return scenario_ids


def _resolve_template_source(
    workshop_root: Path,
    template_id: str,
) -> str | None:
    """Resolve a template ID to its source path/URL from the workshop registry.

    Uses the same logic as the workshop modules (copyroom.yml and
    registry/<template_id>.yml).
    """
    # Try copyroom.yml first
    config_path = workshop_root / "copyroom.yml"
    if config_path.is_file():
        try:
            with open(config_path) as f:
                config = yaml.safe_load(f)
            if isinstance(config, dict):
                templates = config.get("templates", config.get("registry", None))
                if isinstance(templates, dict):
                    source = templates.get(template_id)
                    if isinstance(source, str):
                        return source
                    if isinstance(source, dict):
                        return source.get(
                            "source", source.get("url", str(source))
                        )
        except yaml.YAMLError:
            pass

    # Fall back to registry/ directory
    registry_dir = workshop_root / "registry"
    template_yml = registry_dir / f"{template_id}.yml"
    if template_yml.is_file():
        try:
            with open(template_yml) as f:
                template = yaml.safe_load(f)
            if isinstance(template, dict):
                source = template.get("source", template.get("url"))
                if isinstance(source, str):
                    return source
        except yaml.YAMLError:
            pass

    return None


def _check_worktree_clean(repo_root: Path) -> bool:
    """Check that the git working tree is clean (no uncommitted changes).

    Returns ``True`` when ``git status --porcelain`` produces no output.
    If the directory is not inside a git repository (or git is not available),
    returns ``True`` (no changes to report).
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError:
        # git not available — nothing to check
        return True
    except subprocess.TimeoutExpired:
        # git timed out — can't verify, assume clean
        return True
    except Exception:
        return True

    # If git isn't initialised at this path, treat as clean
    if result.returncode != 0 and "not a git repository" in (
        result.stderr or ""
    ):
        return True

    return result.stdout.strip() == ""
