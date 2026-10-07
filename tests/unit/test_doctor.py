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
