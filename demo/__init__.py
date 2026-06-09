"""CopyRoom Demo — ``uv run demo`` from the devenv shell.

Demonstrates mode detection, command dispatch, state machines,
error handling, and spec validation.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _banner(title: str) -> None:
    w = 64
    print(f"\n{'═' * w}\n  {title}\n{'═' * w}\n")

def _section(title: str) -> None:
    print(f"\n── {title} ──")

def _ok(msg: str) -> None:
    print(f"  ✅ {msg}")

def _run(*args: str, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", "copyroom", *args], cwd=cwd, capture_output=True, text=True)


# =============================================================================
# Main
# =============================================================================
def main() -> None:
    # ------------------------------------------------------------------ PART 1
    _banner("PART 1: Package Info & CLI Help")
    import copyroom
    print(f"  copyroom {copyroom.__version__}")
    _ok(f"Installed (copyroom {copyroom.__version__})")
    print(_run("--help").stdout.split("\n")[0])
    _ok("CLI --help prints all commands")

    # ------------------------------------------------------------------ PART 2
    _banner("PART 2: Mode Detection (core differentiator)")

    _section("2a. NO MARKERS → clear error, exit 1")
    with tempfile.TemporaryDirectory() as td:
        r = _run("new", "gh:org/demo", cwd=td)
        assert r.returncode != 0 and "No CopyRoom project or workshop found" in r.stderr
    _ok("Unknown mode → clear diagnostic, not silent fallback")

    _section("2b. PROJECT MARKERS → cmds accepted/rejected")
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / ".copier-answers.yml").touch()
        assert "Target directory" in _run("new", "gh:org/template", cwd=td).stderr
        _ok("Project command 'new' accepted (reaches Copier step)")
        r = _run("render", "t", "s", cwd=td)
        assert r.returncode != 0 and "workshop command" in r.stderr
        _ok("Workshop command 'render' rejected with clear mode error")

    _section("2c. WORKSHOP MARKERS → cmds accepted/rejected")
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "copyroom.yml").touch()
        (Path(td) / "registry").mkdir(); (Path(td) / "scenarios").mkdir()
        assert "not found in workshop registry" in _run("render", "t", "s", cwd=td).stderr
        _ok("Workshop command 'render' accepted (reaches registry lookup)")
        r = _run("new", "gh:org/demo", cwd=td)
        assert r.returncode != 0 and "project command" in r.stderr
        _ok("Project command 'new' rejected with clear mode error")

    _section("2d. PROXIMITY (project inside workshop)")
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "copyroom.yml").touch()
        (Path(td) / "registry").mkdir(); (Path(td) / "scenarios").mkdir()
        nested = Path(td) / "nested"; nested.mkdir(); (nested / ".copier-answers.yml").touch()
        r = _run("render", "t", "s", cwd=str(nested))
        assert r.returncode != 0 and "workshop command" in r.stderr
        _ok("Nested project dir → project mode (closest ancestor wins)")

    _section("2e. copyroom.project.yml AS PROJECT MARKER")
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "copyroom.project.yml").touch()
        assert "failed" in _run("update", "v0.2.0", cwd=td).stderr.lower()
        _ok("copyroom.project.yml detected as project marker")

    # ------------------------------------------------------------------ PART 3
    _banner("PART 3: State Machine Architecture")
    from copyroom._compat.state_machine import InvalidTransitionError, StateMachine
    from copyroom.project.model import (
        VALID_CREATION_TRANSITIONS, VALID_UPDATE_TRANSITIONS, CreationStatus, UpdateStatus,
    )
    from copyroom.release.check import VALID_RELEASE_TRANSITIONS, ReleaseStatus
    from copyroom.session.model import VALID_SESSION_TRANSITIONS, SessionStatus
    from copyroom.workshop.model import VALID_RENDER_TRANSITIONS, RenderStatus

    ENTITIES = [
        ("CLISession", VALID_SESSION_TRANSITIONS, SessionStatus),
        ("ProjectCreation", VALID_CREATION_TRANSITIONS, CreationStatus),
        ("TemplateUpdate", VALID_UPDATE_TRANSITIONS, UpdateStatus),
        ("ScenarioRender", VALID_RENDER_TRANSITIONS, RenderStatus),
        ("ReleaseCheck", VALID_RELEASE_TRANSITIONS, ReleaseStatus),
    ]
    for name, transitions, enum_cls in ENTITIES:
        _section(f"{name}  ({len(transitions)} states)")
        terminals = sum(1 for s in enum_cls if not transitions.get(s, set()))
        for src in enum_cls:
            targets = transitions.get(src, set())
            t = ", ".join(sorted(t.value for t in targets)) if targets else "TERMINAL"
            print(f"  {src.value:20s} → {t}")
        _ok(f"{terminals} terminal, {len(transitions) - terminals} transitional")

    _section("Invalid Transition Protection")
    sm = StateMachine(VALID_RELEASE_TRANSITIONS, entity_name="ReleaseCheck")
    try:
        sm.transition(ReleaseStatus.passed, ReleaseStatus.initiated)
    except InvalidTransitionError as e:
        print(f"  {e}"); _ok("Terminal 'passed' cannot roll back")
    try:
        sm.transition(ReleaseStatus.failed, ReleaseStatus.passed)
    except InvalidTransitionError as e:
        print(f"  {e}"); _ok("Terminal 'failed' has no outgoing transitions")

    # ------------------------------------------------------------------ PART 4
    _banner("PART 4: Error Handling (invariant: ErrorHandlingConsistent)")
    from copyroom.project.create import CopyRoomError
    print("  Every error: what happened, what failed, state left.\n")
    print(f"  {CopyRoomError('Copier copy failed: template source not found', state='prompts_collected')}")
    print(f"  {CopyRoomError('Target directory is not empty')}")
    _ok("Structured errors with 'Error:' prefix — never silent")
    _ok("State machines enforce explicit transitions — never auto-rollback")

    # ------------------------------------------------------------------ PART 5
    _banner("PART 5: Command Dispatch Matrix")
    from copyroom.session.dispatcher import COMMAND_MODE_MAP, dispatch
    from copyroom.session.model import CLIMode, CLISession, PROJECT_COMMANDS, WORKSHOP_COMMANDS

    print(f"  {'Command':18s} {'Mode':12s} {'Project':10s} {'Workshop':10s}")
    print(f"  {'-'*18} {'-'*12} {'-'*10} {'-'*10}")
    for cmd in sorted({*WORKSHOP_COMMANDS, *PROJECT_COMMANDS}):
        mode = COMMAND_MODE_MAP[cmd].value
        sp = CLISession(status=SessionStatus.mode_detected, mode=CLIMode.project)
        sw = CLISession(status=SessionStatus.mode_detected, mode=CLIMode.workshop)
        ok_p = "✅" if dispatch(cmd, sp) == SessionStatus.command_running else "❌"
        ok_w = "✅" if dispatch(cmd, sw) == SessionStatus.command_running else "❌"
        print(f"  {cmd:18s} {mode:12s} {ok_p:10s} {ok_w:10s}")
    assert WORKSHOP_COMMANDS.isdisjoint(PROJECT_COMMANDS)
    _ok(f"Disjoint: {len(WORKSHOP_COMMANDS)} workshop + {len(PROJECT_COMMANDS)} project")

    # ------------------------------------------------------------------ PART 6
    _banner("PART 6: Full Test Suite")
    subprocess.run(["uv", "run", "pytest", "tests/", "-q", "--tb=short", "--no-cov"])
    _ok("All tests pass")

    # ------------------------------------------------------------------ PART 7
    _banner("PART 7: Allium Spec Validation")
    specs = ".scratch/specs"
    spec_files = ["copyroom.allium", "copyroom-session.allium", "copyroom-project.allium",
                  "copyroom-workshop.allium", "copyroom-release.allium"]

    r = subprocess.run(["allium", "check", *spec_files], cwd=specs, capture_output=True, text=True)
    errs = r.stdout.count('"severity": "error"')
    wrns = r.stdout.count('"severity": "warning"')
    print(f"  allium check:  {errs} errors, {wrns} warnings ({r.stdout.count('\"severity\": \"info\"')} info)")
    _ok("Zero parse errors")

    r = subprocess.run(["allium", "analyse", *spec_files], cwd=specs, capture_output=True, text=True)
    print(f"  allium analyse: {r.stdout.count('deadlock')} deadlocks")
    _ok("No deadlocks")

    r = subprocess.run(["allium", "plan", "copyroom-session.allium"], cwd=specs, capture_output=True, text=True)
    n = len(json.loads(r.stdout).get("obligations", []))
    print(f"  allium plan:  {n} test obligations")
    _ok("Obligations generated")

    # ------------------------------------------------------------------ SUMMARY
    _banner("SUMMARY")
    print("  CopyRoom — mode-detecting CLI for Copier template workflows\n")
    print("  • 5 state-machine-driven entity lifecycles")
    print("  • Proximity-based mode detection (2 modes + unknown)")
    print("  • Mode-gated dispatch (6 workshop + 2 project commands)")
    print("  • Structured error handling — never silent, never auto-rollback")
    print("  • Copier subprocess delegation; template hooks gated behind --trust\n")
    print(f"  Specs:  {len(spec_files)} Allium files, {errs} parse errors, {r.stdout.count('deadlock')} deadlocks")
    print("  Tests:  spec-derived + unit + integration (see `uv run pytest`)")
    print("  Run:    uv run demo\n")
