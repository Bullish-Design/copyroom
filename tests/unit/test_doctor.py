"""Templateer and jj environment checks."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from copyroom.local.workflow import doctor


def test_doctor_reports_templateer_and_jj() -> None:
    report = doctor()

    assert report["ok"] is True
    assert report["templateer"]
    assert report["jj"].endswith("/jj")


def test_missing_jj_fails_the_environment_check(monkeypatch) -> None:
    real_which = shutil.which
    monkeypatch.setattr(shutil, "which", lambda name: None if name == "jj" else real_which(name))

    report = doctor()

    assert report["ok"] is False
    assert report["templateer"]
    assert report["jj"] is None


def test_doctor_cli_emits_parseable_json(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "copyroom", "doctor", "--json"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["ok"] is True
    assert report["templateer"]
    assert report["jj"]


def test_doctor_reports_the_guard_without_failing_when_it_is_missing(monkeypatch) -> None:
    monkeypatch.setenv("COPYROOM_PYJUTSU", "/nonexistent/pyjutsu")

    report = doctor()

    assert report["ok"] is True
    assert report["guard"] is None
    assert report["guard_version"] is None


def test_doctor_reports_whether_the_guard_publishes_in_a_child_workspace(monkeypatch) -> None:
    from copyroom.local import workflow
    from copyroom.local.guard import Guard

    for guard, expected in (
        (Guard("/opt/pyjutsu", "0.23.0", "0.44.0"), "refused"),
        (Guard("/opt/pyjutsu", "0.24.0", "0.46.0"), "ok"),
        (None, None),
    ):
        monkeypatch.setattr(workflow, "resolve_guard", lambda guard=guard: guard)

        report = doctor()

        assert report["ok"] is True
        assert report["guard_child_workspace"] == expected
        assert report["guard_jj_lib"] == (guard.jj_lib if guard else None)
