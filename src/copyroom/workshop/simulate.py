"""Update simulation workflow — ``copyroom update-test``.

Implements the UpdateSimulation state machine from copyroom-workshop.allium:

    initiated -> old_rendered -> user_edited -> update_applied -> checks_run -> complete

If no edits file is found, ``user_edited`` is pruned (skipped).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

from .._compat.copier import copier_copy, copier_update
from .._compat.state_machine import StateMachine
from .edits import apply_edits, load_edits
from .model import (
    VALID_SIM_TRANSITIONS,
    SimStatus,
    UpdateSimulation,
    UpdateSimulationResult,
)

# ---------------------------------------------------------------------------
# State machine instance
# ---------------------------------------------------------------------------

_sim_sm = StateMachine(
    VALID_SIM_TRANSITIONS,
    entity_name="UpdateSimulation",
)

_work_dir_name = ".copyroom_sim"


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


# ===================================================================
# Rule: RunUpdateSimulation            (spec L157-L164)
# ===================================================================


def initiate(
    template_id: str,
    scenario_id: str,
    old_version: str,
    new_version: str,
) -> UpdateSimulation:
    """Create an UpdateSimulation entity in ``initiated`` state."""
    if not template_id:
        raise CopyRoomError(
            "Template ID is required.",
            state="not_started",
        )
    if not scenario_id:
        raise CopyRoomError(
            "Scenario ID is required.",
            state="not_started",
        )
    if not old_version:
        raise CopyRoomError(
            "Old version is required. Usage: copyroom update-test <template_id> <scenario_id> <old> <new>",
            state="not_started",
        )
    if not new_version:
        raise CopyRoomError(
            "New version is required. Usage: copyroom update-test <template_id> <scenario_id> <old> <new>",
            state="not_started",
        )

    return UpdateSimulation(
        template_id=template_id,
        scenario_id=scenario_id,
        old_version=old_version,
        new_version=new_version,
    )


# ===================================================================
# Rule: RenderOldVersion               (spec L166-L169)
# ===================================================================


def render_old_version(
    sim: UpdateSimulation,
    workshop_root: Path,
    template_source: str,
) -> SimStatus:
    """Render the template at the old version to produce a base project.

    Output goes to ``.copyroom_sim/<template_id>/<scenario_id>/``.
    """
    work_dir = workshop_root / _work_dir_name / sim.template_id / sim.scenario_id
    scenario_yml = workshop_root / "scenarios" / sim.template_id / f"{sim.scenario_id}.yml"

    if not scenario_yml.is_file():
        sim.status = _sim_sm.transition(
            SimStatus.initiated,
            SimStatus.failed,
        )
        print(
            f"Error: Scenario answers file not found: {scenario_yml}",
            file=sys.stderr,
        )
        return sim.status

    # Clean up previous simulation work
    if work_dir.exists():
        import shutil
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)

    try:
        result = copier_copy(
            source=template_source,
            destination=work_dir,
            answers_file=scenario_yml,
        )
    except Exception as exc:
        sim.status = _sim_sm.transition(
            SimStatus.initiated,
            SimStatus.failed,
        )
        print(f"Error: Copier copy failed: {exc}", file=sys.stderr)
        return sim.status

    if result.returncode != 0:
        sim.status = _sim_sm.transition(
            SimStatus.initiated,
            SimStatus.failed,
        )
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="")
        return sim.status

    sim.status = _sim_sm.transition(
        SimStatus.initiated,
        SimStatus.old_rendered,
    )
    return sim.status


# ===================================================================
# Rule: ApplyUserEdits                 (spec L171-L175)
# ===================================================================


def apply_user_edits(
    sim: UpdateSimulation,
    workshop_root: Path,
) -> SimStatus:
    """Apply deterministic user edits from ``scenarios/<template_id>/<scenario_id>-edits.yml``.

    If no edits file exists, skips straight to ``update_applied`` (prunes
    ``user_edited`` state).
    """
    work_dir = workshop_root / _work_dir_name / sim.template_id / sim.scenario_id
    edits_path = workshop_root / "scenarios" / sim.template_id / f"{sim.scenario_id}-edits.yml"

    if not edits_path.is_file():
        # No edits file — prune user_edited and go directly to update_applied
        sim.status = _sim_sm.transition(
            SimStatus.old_rendered,
            SimStatus.update_applied,
        )
        return sim.status

    try:
        edits = load_edits(edits_path)
        if edits:
            apply_edits(edits, work_dir)
    except Exception as exc:
        sim.status = _sim_sm.transition(
            SimStatus.old_rendered,
            SimStatus.failed,
        )
        print(f"Error: Failed to apply user edits: {exc}", file=sys.stderr)
        return sim.status

    sim.status = _sim_sm.transition(
        SimStatus.old_rendered,
        SimStatus.user_edited,
    )
    return sim.status


# ===================================================================
# Rule: ApplyUpdate                    (spec L177-L182)
# ===================================================================


def apply_update(
    sim: UpdateSimulation,
    workshop_root: Path,
) -> SimStatus:
    """Run ``copier update --defaults`` from old to new version.

    Captures conflicts and rejects from Copier output.
    """
    work_dir = workshop_root / _work_dir_name / sim.template_id / sim.scenario_id
    from_state = sim.status

    try:
        result = copier_update(
            destination=work_dir,
            vcs_ref=sim.new_version,
        )
    except Exception as exc:
        sim.status = _sim_sm.transition(
            from_state,
            SimStatus.failed,
        )
        print(f"Error: Copier update failed: {exc}", file=sys.stderr)
        return sim.status

    if result.returncode != 0:
        sim.status = _sim_sm.transition(
            from_state,
            SimStatus.failed,
        )
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="")
        return sim.status

    sim.status = _sim_sm.transition(
        from_state,
        SimStatus.update_applied,
    )

    # Capture conflicts and rejects from output
    _capture_conflicts(sim, result.stdout or "")
    _capture_rejects(sim, work_dir)

    return sim.status


# ===================================================================
# Rule: RunUpdateChecks                (spec L184-L189)
# ===================================================================


def run_checks(
    sim: UpdateSimulation,
    workshop_root: Path,
) -> SimStatus:
    """Run generated project checks against the updated output."""
    work_dir = workshop_root / _work_dir_name / sim.template_id / sim.scenario_id

    # Load checks from registry
    checks = _load_checks(workshop_root, sim.template_id)

    if not checks:
        # No checks configured — transition to checks_run anyway
        sim.status = _sim_sm.transition(
            SimStatus.update_applied,
            SimStatus.checks_run,
        )
        # Complete immediately
        return _complete(sim, workshop_root)

    sim.status = _sim_sm.transition(
        SimStatus.update_applied,
        SimStatus.checks_run,
    )

    sim.result = UpdateSimulationResult(
        conflicts=sim.result.conflicts if sim.result else set(),
        rejects=sim.result.rejects if sim.result else set(),
        check_passed=True,
    )

    for cmd in checks:
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                cwd=str(work_dir),
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                sim.result.check_passed = False
                print(
                    f"Check failed (exit {result.returncode}): {cmd}",
                    file=sys.stderr,
                )
                if result.stderr:
                    print(result.stderr, file=sys.stderr, end="")
        except subprocess.TimeoutExpired:
            sim.result.check_passed = False
            print(f"Check timed out (120s): {cmd}", file=sys.stderr)
        except Exception as exc:
            sim.result.check_passed = False
            print(f"Check raised: {cmd}: {exc}", file=sys.stderr)

    return _complete(sim, workshop_root)


# ===================================================================
# Rule: UpdateSimulationComplete       (spec L191-L201)
# ===================================================================


def _complete(sim: UpdateSimulation, workshop_root: Path) -> SimStatus:
    """Complete the simulation, producing the final result.

    Sets ``sim.result`` with conflicts, rejects, and check_passed.
    """
    work_dir = workshop_root / _work_dir_name / sim.template_id / sim.scenario_id

    # Re-scan for rejects (may have been created during checks)
    _capture_rejects(sim, work_dir)

    # Build final result
    sim.result = UpdateSimulationResult(
        conflicts=sim.result.conflicts if sim.result else set(),
        rejects=sim.result.rejects if sim.result else set(),
        check_passed=sim.result.check_passed if sim.result else True,
    )

    sim.status = _sim_sm.transition(
        SimStatus.checks_run,
        SimStatus.complete,
    )
    return sim.status


# ===================================================================
# High-level workflow
# ===================================================================


def run_update_simulation(
    template_id: str,
    scenario_id: str,
    old_version: str,
    new_version: str,
    workshop_root: Path | None = None,
    template_source: str | None = None,
) -> UpdateSimulation:
    """Run the full update simulation workflow.

    This is the top-level entry point called from the CLI for
    ``copyroom update-test <template_id> <scenario_id> <old> <new>``.

    Returns the ``UpdateSimulation`` entity in its final state
    (``complete`` or ``failed``).
    """
    if workshop_root is None:
        workshop_root = Path.cwd()

    # 1. RunUpdateSimulation — create entity
    sim = initiate(template_id, scenario_id, old_version, new_version)

    # Resolve template source from registry if not provided
    if template_source is None:
        template_source = _resolve_template_source(workshop_root, template_id)
        if template_source is None:
            sim.status = _sim_sm.transition(
                SimStatus.initiated,
                SimStatus.failed,
            )
            print(
                f"Error: Template '{template_id}' not found in workshop registry.",
                file=sys.stderr,
            )
            return sim

    # 2. RenderOldVersion
    status = render_old_version(sim, workshop_root, template_source)
    if status == SimStatus.failed:
        return sim

    # 3. ApplyUserEdits (may prune to update_applied)
    status = apply_user_edits(sim, workshop_root)
    if status == SimStatus.failed:
        return sim

    # If edits pruned (no edits file), we're already at update_applied
    if status == SimStatus.user_edited:
        # 4. ApplyUpdate
        status = apply_update(sim, workshop_root)
        if status == SimStatus.failed:
            return sim

    # 5. RunUpdateChecks → UpdateSimulationComplete
    status = run_checks(sim, workshop_root)
    return sim


# ===================================================================
# Internal helpers
# ===================================================================


def _resolve_template_source(workshop_root: Path, template_id: str) -> str | None:
    """Resolve a template ID to its source path/URL from the workshop registry."""
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
                        return source.get("source", source.get("url", str(source)))
        except yaml.YAMLError:
            pass

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


def _load_checks(workshop_root: Path, template_id: str) -> list[str]:
    """Load checks for a template from the workshop registry."""
    checks: list[str] = []
    config_path = workshop_root / "copyroom.yml"

    if config_path.is_file():
        try:
            with open(config_path) as f:
                config = yaml.safe_load(f)
            if isinstance(config, dict):
                templates = config.get("templates", {})
                if isinstance(templates, dict):
                    template = templates.get(template_id)
                    if isinstance(template, dict):
                        raw = template.get("checks", [])
                        if isinstance(raw, list):
                            checks = [str(c) for c in raw]
        except yaml.YAMLError:
            pass

    if not checks:
        registry_dir = workshop_root / "registry"
        template_yml = registry_dir / f"{template_id}.yml"
        if template_yml.is_file():
            try:
                with open(template_yml) as f:
                    template = yaml.safe_load(f)
                if isinstance(template, dict):
                    raw = template.get("checks", [])
                    if isinstance(raw, list):
                        checks = [str(c) for c in raw]
            except yaml.YAMLError:
                pass

    return checks


def _capture_conflicts(sim: UpdateSimulation, output: str) -> None:
    """Parse Copier output for conflict markers."""
    if not output:
        return
    if sim.result is None:
        sim.result = UpdateSimulationResult()
    for line in output.splitlines():
        if "conflict" in line.lower():
            sim.result.conflicts.add(line.strip())


def _capture_rejects(sim: UpdateSimulation, work_dir: Path) -> None:
    """Scan for .rej files in the work directory."""
    if sim.result is None:
        sim.result = UpdateSimulationResult()
    for rej_file in work_dir.rglob("*.rej"):
        sim.result.rejects.add(str(rej_file.relative_to(work_dir)))
