"""Integration tests for the read-only `inspect` and `status` commands."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from copyroom._compat.copier import copier_copy
from copyroom.project.inspect import inspect_project, project_status

from .conftest import _git, tag_v2


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "copyroom", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def _generate_project(template_repo: Path, dest: Path) -> Path:
    assert copier_copy(str(template_repo), dest).returncode == 0
    _git("init", cwd=dest)
    _git("add", "-A", cwd=dest)
    _git("commit", "-qm", "generated", cwd=dest)
    return dest


# ---------------------------------------------------------------------------
# inspect
# ---------------------------------------------------------------------------


def test_inspect_reports_template_link(template_repo: Path, tmp_path: Path) -> None:
    proj = _generate_project(template_repo, tmp_path / "proj")
    report = inspect_project(project_root=proj)

    assert report.project_root == proj.resolve()
    assert report.template_source == str(template_repo)
    assert report.commit == "v1.0.0"
    assert report.answers_file == str(proj / ".copier-answers.yml")
    assert report.has_project_config is False
    assert report.hooks == {}


def test_inspect_json_is_parseable(template_repo: Path, tmp_path: Path) -> None:
    _generate_project(template_repo, tmp_path / "proj")
    r = _run("inspect", "--json", cwd=tmp_path / "proj")
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["command"] == "inspect"
    assert data["template_source"] == str(template_repo)
    assert data["commit"] == "v1.0.0"
    assert data["has_project_config"] is False


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def test_status_no_update_when_at_latest(template_repo: Path, tmp_path: Path) -> None:
    proj = _generate_project(template_repo, tmp_path / "proj")
    report = project_status(project_root=proj)

    assert report.mode == "project"
    assert report.current_ref == "v1.0.0"
    assert report.latest_ref == "v1.0.0"
    assert report.update_available is False
    assert report.worktree_clean is True


def test_status_reports_update_available(template_repo: Path, tmp_path: Path) -> None:
    proj = _generate_project(template_repo, tmp_path / "proj")
    tag_v2(template_repo)  # publish v2.0.0

    report = project_status(project_root=proj)
    assert report.current_ref == "v1.0.0"
    assert report.latest_ref == "v2.0.0"
    assert report.update_available is True


def test_status_detects_dirty_worktree(template_repo: Path, tmp_path: Path) -> None:
    proj = _generate_project(template_repo, tmp_path / "proj")
    (proj / "README.md").write_text("locally edited\n")
    report = project_status(project_root=proj)
    assert report.worktree_clean is False


def test_status_json_is_parseable(template_repo: Path, tmp_path: Path) -> None:
    proj = _generate_project(template_repo, tmp_path / "proj")
    tag_v2(template_repo)
    r = _run("status", "--json", cwd=proj)
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["command"] == "status"
    assert data["mode"] == "project"
    assert data["update_available"] is True
    assert data["latest_ref"] == "v2.0.0"


# ---------------------------------------------------------------------------
# mode gating
# ---------------------------------------------------------------------------


def test_inspect_rejected_in_workshop_mode(workshop: Path) -> None:
    r = _run("inspect", cwd=workshop)
    assert r.returncode != 0
    assert "project command" in r.stderr


def test_status_rejected_in_workshop_mode(workshop: Path) -> None:
    r = _run("status", cwd=workshop)
    assert r.returncode != 0
    assert "project command" in r.stderr
