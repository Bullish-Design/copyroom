"""Update simulation workflow — ``copyroom update-test``.

Implements the UpdateSimulation state machine from copyroom-workshop.allium:

    initiated -> old_rendered -> user_edited -> update_applied -> checks_run -> complete

If no edits file is found, ``user_edited`` is pruned (skipped).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from .._compat.copier import copier_copy, copier_update
from .._compat.errors import CopyRoomError
from .._compat.state_machine import StateMachine
from .edits import apply_edits, load_edits
from .model import (
    VALID_SIM_TRANSITIONS,
    SimStatus,
    UpdateSimulation,
    UpdateSimulationResult,
)
from .registry import load_checks, require_workshop_root, resolve_template_source

__all__ = ["CopyRoomError", "run_update_simulation"]

# ---------------------------------------------------------------------------
# State machine instance
# ---------------------------------------------------------------------------

_sim_sm = StateMachine(
    VALID_SIM_TRANSITIONS,
    entity_name="UpdateSimulation",
)

_work_dir_name = ".copyroom_sim"


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

    # ``copier update`` only works on git-tracked projects, so snapshot the
    # freshly-rendered baseline. Failure here is fatal — the update can't run.
    if not _git_snapshot(work_dir, "copyroom: render old version"):
        sim.status = _sim_sm.transition(
            SimStatus.initiated,
            SimStatus.failed,
        )
        print(
            "Error: Failed to initialise git in the simulation work dir.",
            file=sys.stderr,
        )
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
        # No edits file: the user made zero edits, but the edit step still ran.
        # Spec (copyroom-workshop.allium L82-L84) only allows
        # old_rendered -> user_edited; never old_rendered -> update_applied.
        sim.status = _sim_sm.transition(
            SimStatus.old_rendered,
            SimStatus.user_edited,
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

    # Commit the edits so the worktree is clean for ``copier update``.
    _git_snapshot(work_dir, "copyroom: apply user edits")

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
    checks = load_checks(workshop_root, sim.template_id)

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
    workshop_root = require_workshop_root(workshop_root)

    # 1. RunUpdateSimulation — create entity
    sim = initiate(template_id, scenario_id, old_version, new_version)

    # Resolve template source from registry if not provided
    if template_source is None:
        template_source = resolve_template_source(workshop_root, template_id)
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

    # 3. ApplyUserEdits (always advances to user_edited, even with zero edits)
    status = apply_user_edits(sim, workshop_root)
    if status == SimStatus.failed:
        return sim

    # 4. ApplyUpdate (always runs — this is the update being simulated)
    status = apply_update(sim, workshop_root)
    if status == SimStatus.failed:
        return sim

    # 5. RunUpdateChecks → UpdateSimulationComplete
    status = run_checks(sim, workshop_root)
    return sim


# ===================================================================
# Internal helpers
# ===================================================================


def _git_snapshot(work_dir: Path, message: str) -> bool:
    """Init (if needed) and commit everything in *work_dir*.

    ``copier update`` only operates on git-tracked projects with a clean
    worktree, so the simulation commits its baseline (and any user edits)
    here. A repo-local identity is configured so this works even when the
    user has no global git identity. Returns ``False`` if git is unavailable.
    """
    def git(*args: str) -> subprocess.CompletedProcess[str] | None:
        try:
            return subprocess.run(
                ["git", *args],
                cwd=str(work_dir),
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None

    if not (work_dir / ".git").is_dir():
        if git("init") is None:
            return False
        git("config", "user.email", "copyroom@localhost")
        git("config", "user.name", "CopyRoom Simulation")
        git("config", "commit.gpgsign", "false")

    git("add", "-A")
    # Allow empty commits so a no-op edit step still produces a clean HEAD.
    git("commit", "--allow-empty", "-m", message)
    return True


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
