"""Unit tests for `copyroom doctor` environment checks."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from copyroom import doctor


def test_run_doctor_all_ok_in_healthy_env() -> None:
    """In the devenv (Copier present, git on PATH, writable cache) all checks pass.

    The ``agent-files`` check is warn-level; it is non-conformant only in a
    bare directory, which still leaves ``report.ok`` True (warn-only).
    """
    report = doctor.run_doctor()
    assert report.ok is True
    names = {c.name for c in report.checks}
    assert names == {"copier", "git", "cache", "agent-files"}


def test_agent_files_check_is_warn_only(tmp_path: Path) -> None:
    """A non-conformant agent-files check warns but never fails the report."""
    bare = tmp_path / "bare"
    bare.mkdir()
    check = doctor._check_agent_files(target=bare)
    assert check.ok is False
    assert check.warn_only is True
    # Warn-only semantics: the aggregate report stays ok even when the check fails.
    report = doctor.DoctorReport(checks=[check])
    assert report.ok is True


def test_agent_files_check_conformant_after_export(tmp_path: Path) -> None:
    """After exporting into a target, the doctor agent-files check passes."""
    from copyroom.agent.files import export_agent_files

    export_agent_files(tmp_path)
    check = doctor._check_agent_files(target=tmp_path)
    assert check.ok is True


def test_agent_files_check_warns_when_skill_deleted(tmp_path: Path) -> None:
    """Deleting a canonical skill makes the doctor agent-files check warn."""
    from copyroom.agent.files import export_agent_files

    export_agent_files(tmp_path)
    (tmp_path / ".agents" / "skills" / "copyroom" / "SKILL.md").unlink()
    check = doctor._check_agent_files(target=tmp_path)
    assert check.ok is False
    assert check.warn_only is True


def test_missing_git_fails_report(monkeypatch) -> None:
    monkeypatch.setattr(doctor.shutil, "which", lambda _: None)
    report = doctor.run_doctor()
    assert report.ok is False
    git = next(c for c in report.checks if c.name == "git")
    assert git.ok is False
    assert "not found on PATH" in git.detail


def test_unwritable_cache_fails_report(monkeypatch, tmp_path: Path) -> None:
    """An unwritable cache root makes the cache check (and the report) fail."""
    # Point the cache at a path under a regular file, so mkdir cannot succeed.
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("")
    monkeypatch.setattr(doctor, "_cache_root", lambda: blocker / "templates")
    report = doctor.run_doctor()
    assert report.ok is False
    cache = next(c for c in report.checks if c.name == "cache")
    assert cache.ok is False


def test_format_report_marks_ok_and_failure() -> None:
    report = doctor.DoctorReport(
        checks=[
            doctor.DoctorCheck(name="copier", ok=True, detail="9.15.1"),
            doctor.DoctorCheck(name="git", ok=False, detail="not found on PATH"),
        ]
    )
    text = doctor.format_doctor_report(report)
    assert "OK" in text
    assert "✗" in text
    assert "copier" in text and "git" in text


def test_doctor_cli_exits_zero_and_json_parses(tmp_path: Path) -> None:
    """Integration: `python -m copyroom doctor` runs anywhere and `--json` parses."""
    plain = subprocess.run(
        [sys.executable, "-m", "copyroom", "doctor"],
        cwd=str(tmp_path), capture_output=True, text=True,
    )
    assert plain.returncode == 0, plain.stderr
    assert "copier" in plain.stdout

    js = subprocess.run(
        [sys.executable, "-m", "copyroom", "doctor", "--json"],
        cwd=str(tmp_path), capture_output=True, text=True,
    )
    assert js.returncode == 0, js.stderr
    payload = json.loads(js.stdout)
    assert {c["name"] for c in payload["checks"]} == {"copier", "git", "cache", "agent-files"}
    assert all("ok" in c for c in payload["checks"])
    af = next(c for c in payload["checks"] if c["name"] == "agent-files")
    assert af["warn_only"] is True
