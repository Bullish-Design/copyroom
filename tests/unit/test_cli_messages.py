"""Unit tests for CLI message gating that don't need a real workflow run."""

from __future__ import annotations

import argparse
import contextlib
import io

from copyroom import cli
from copyroom.workshop.model import (
    SimStatus,
    UpdateSimulation,
    UpdateSimulationResult,
)


def _run_update_test(monkeypatch, result: UpdateSimulationResult) -> str:
    sim = UpdateSimulation(
        template_id="t", scenario_id="s", old_version="v1", new_version="v2",
        status=SimStatus.complete, result=result,
    )
    monkeypatch.setattr(cli, "run_update_simulation", lambda **kwargs: sim)
    buf = io.StringIO()
    args = argparse.Namespace(
        template_id="t", scenario_id="s", old_version="v1", new_version="v2",
    )
    with contextlib.redirect_stdout(buf):
        cli._cmd_update_test(args)
    return buf.getvalue()


def test_update_test_conflict_not_reported_clean(monkeypatch) -> None:
    """#P2-3: a conflicted update with passing checks is NOT 'applied cleanly'."""
    out = _run_update_test(
        monkeypatch,
        UpdateSimulationResult(conflicts={"README.md"}, check_passed=True),
    )
    assert "applied cleanly" not in out
    assert "had issues" in out
    assert "README.md" in out


def test_update_test_clean_run_reported_clean(monkeypatch) -> None:
    out = _run_update_test(monkeypatch, UpdateSimulationResult())
    assert "applied cleanly" in out
