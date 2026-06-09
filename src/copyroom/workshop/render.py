"""Scenario rendering workflow — ``copyroom render``.

Implements the ScenarioRender state machine from copyroom-workshop.allium:

    initiated -> rendered -> tested -> complete
    initiated -> rendered -> complete  (short-circuit: no tests)
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

from .._compat.copier import copier_copy
from .._compat.errors import CopyRoomError
from .._compat.state_machine import StateMachine
from .model import (
    VALID_RENDER_TRANSITIONS,
    RenderStatus,
    ScenarioRender,
)
from .registry import load_checks, require_workshop_root, resolve_template_source

__all__ = ["CopyRoomError", "render_scenario"]

# ---------------------------------------------------------------------------
# State machine instance
# ---------------------------------------------------------------------------

_render_sm = StateMachine(
    VALID_RENDER_TRANSITIONS,
    entity_name="ScenarioRender",
)


# ===================================================================
# Rule: RenderScenario                 (spec L77-L83)
# ===================================================================


def initiate(template_id: str, scenario_id: str) -> ScenarioRender:
    """Create a ScenarioRender entity in ``initiated`` state.

    Validates that both *template_id* and *scenario_id* are non-empty.
    """
    if not template_id:
        raise CopyRoomError(
            "Template ID is required. Usage: copyroom render <template_id> <scenario_id>",
            state="not_started",
        )
    if not scenario_id:
        raise CopyRoomError(
            "Scenario ID is required. Usage: copyroom render <template_id> <scenario_id>",
            state="not_started",
        )

    return ScenarioRender(template_id=template_id, scenario_id=scenario_id)


# ===================================================================
# Rule: ExecuteRender                  (spec L85-L89)
# ===================================================================


def execute_render(
    render: ScenarioRender,
    workshop_root: Path,
    template_source: str,
) -> RenderStatus:
    """Run ``copier copy`` with scenario answers into ``generated/<template_id>/<scenario_id>/``.

    Scenario answers are loaded from ``scenarios/<template_id>/<scenario_id>.yml``.
    """
    # Determine paths
    generated_dir = workshop_root / "generated" / render.template_id / render.scenario_id
    scenario_yml = workshop_root / "scenarios" / render.template_id / f"{render.scenario_id}.yml"

    # Load scenario answers
    if not scenario_yml.is_file():
        render.status = _render_sm.transition(
            RenderStatus.initiated,
            RenderStatus.failed,
        )
        print(
            f"Error: Scenario answers file not found: {scenario_yml}",
            file=sys.stderr,
        )
        return render.status

    try:
        with open(scenario_yml) as f:
            _ = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        render.status = _render_sm.transition(
            RenderStatus.initiated,
            RenderStatus.failed,
        )
        print(f"Error: Failed to parse scenario answers: {exc}", file=sys.stderr)
        return render.status

    # Clean previous generated output
    if generated_dir.exists():
        import shutil
        shutil.rmtree(generated_dir)

    generated_dir.mkdir(parents=True)

    try:
        result = copier_copy(
            source=template_source,
            destination=generated_dir,
            answers_file=scenario_yml,
        )
    except Exception as exc:
        render.status = _render_sm.transition(
            RenderStatus.initiated,
            RenderStatus.failed,
        )
        print(f"Error: Copier copy failed: {exc}", file=sys.stderr)
        return render.status

    if result.returncode != 0:
        render.status = _render_sm.transition(
            RenderStatus.initiated,
            RenderStatus.failed,
        )
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="")
        if result.stdout:
            print(result.stdout, file=sys.stderr, end="")
        return render.status

    render.status = _render_sm.transition(
        RenderStatus.initiated,
        RenderStatus.rendered,
    )
    return render.status


# ===================================================================
# Rule: TestRenderedOutput             (spec L91-L95)
# Rule: RenderTestsPassed              (spec L97-L99)
# Rule: RenderTestsFailed              (spec L101-L103)
# ===================================================================


def test_rendered_output(
    render: ScenarioRender,
    workshop_root: Path,
    checks: list[str] | None = None,
) -> RenderStatus:
    """Run checks against the rendered output.

    If no checks are configured, short-circuits to ``complete``.
    If checks are configured and all pass, transitions to ``tested`` then ``complete``.
    If any check fails, transitions to ``failed``.

    Parameters
    ----------
    render:
        The ScenarioRender entity (must be in ``rendered`` state).
    workshop_root:
        Root of the workshop directory.
    checks:
        List of shell commands to run. Loaded from the registry if not provided.
    """
    generated_dir = workshop_root / "generated" / render.template_id / render.scenario_id

    # If checks are not provided, try to load from registry
    if checks is None:
        checks = load_checks(workshop_root, render.template_id)

    if not checks:
        # Short-circuit: no tests configured -> complete directly
        render.status = _render_sm.transition(
            RenderStatus.rendered,
            RenderStatus.complete,
        )
        return render.status

    # Transition to tested
    render.status = _render_sm.transition(
        RenderStatus.rendered,
        RenderStatus.tested,
    )

    # Run each check
    all_passed = True
    for cmd in checks:
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                cwd=str(generated_dir),
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                all_passed = False
                print(
                    f"Check failed (exit {result.returncode}): {cmd}",
                    file=sys.stderr,
                )
                if result.stderr:
                    print(result.stderr, file=sys.stderr, end="")
                if result.stdout:
                    print(result.stdout, end="")
        except subprocess.TimeoutExpired:
            all_passed = False
            print(
                f"Check timed out (120s): {cmd}",
                file=sys.stderr,
            )
        except Exception as exc:
            all_passed = False
            print(
                f"Check raised exception: {cmd}: {exc}",
                file=sys.stderr,
            )

    if all_passed:
        render.status = _render_sm.transition(
            RenderStatus.tested,
            RenderStatus.complete,
        )
    else:
        render.status = _render_sm.transition(
            RenderStatus.tested,
            RenderStatus.failed,
        )

    return render.status


# ===================================================================
# High-level workflow
# ===================================================================


def render_scenario(
    template_id: str,
    scenario_id: str,
    workshop_root: Path | None = None,
    template_source: str | None = None,
) -> ScenarioRender:
    """Run the full scenario rendering workflow.

    This is the top-level entry point called from the CLI.

    Parameters
    ----------
    template_id:
        Template identifier.
    scenario_id:
        Scenario identifier.
    workshop_root:
        Root of the workshop directory (defaults to CWD).
    template_source:
        Template source (local path or git URL). If not provided,
        loaded from the workshop registry (``copyroom.yml``).

    Returns
    -------
    ScenarioRender
        The entity in its final state (``complete`` or ``failed``).
    """
    workshop_root = require_workshop_root(workshop_root)

    # 1. RenderScenario — create entity
    render = initiate(template_id, scenario_id)

    # Resolve template source from registry if not provided
    if template_source is None:
        template_source = resolve_template_source(workshop_root, template_id)
        if template_source is None:
            render.status = _render_sm.transition(
                RenderStatus.initiated,
                RenderStatus.failed,
            )
            print(
                f"Error: Template '{template_id}' not found in workshop registry.",
                file=sys.stderr,
            )
            return render

    # 2. ExecuteRender
    status = execute_render(render, workshop_root, template_source)
    if status == RenderStatus.failed:
        return render

    # 3. TestRenderedOutput (may short-circuit to complete)
    status = test_rendered_output(render, workshop_root)
    return render
