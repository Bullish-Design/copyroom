"""Fixtures for end-to-end workflow tests.

These build a real (tiny) Copier template in a tmp git repo and a workshop
layout whose registry points at it, so the high-level workflow functions
(render_scenario, golden_diff, refresh_golden, run_update_simulation,
run_release_check) can be exercised against genuine Copier invocations.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", "-c", "user.email=test@test", "-c", "user.name=test", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def template_repo(tmp_path: Path) -> Path:
    """A git repo holding the fixture template, tagged ``v1.0.0``."""
    dst = tmp_path / "template"
    shutil.copytree(FIXTURES / "template", dst)
    _git("init", cwd=dst)
    _git("add", "-A", cwd=dst)
    _git("commit", "-qm", "v1", cwd=dst)
    _git("tag", "v1.0.0", cwd=dst)
    return dst


def tag_v2(template_repo: Path) -> None:
    """Add a v2-only file to *template_repo* and tag it ``v2.0.0``."""
    (template_repo / "CHANGELOG.md.jinja").write_text(
        "# Changelog for {{ project_name }}\n\n- v2: added changelog\n"
    )
    _git("add", "-A", cwd=template_repo)
    _git("commit", "-qm", "v2", cwd=template_repo)
    _git("tag", "v2.0.0", cwd=template_repo)


@pytest.fixture
def workshop(tmp_path: Path, template_repo: Path) -> Path:
    """A workshop dir whose ``copyroom.yml`` points template ``demo`` at the repo."""
    ws = tmp_path / "workshop"
    shutil.copytree(FIXTURES / "workshop", ws)
    (ws / "copyroom.yml").write_text(
        "templates:\n"
        "  demo:\n"
        f"    source: {template_repo}\n"
        "    checks:\n"
        '      - "test -f README.md"\n'
    )
    return ws


@pytest.fixture
def git_workshop(workshop: Path) -> Path:
    """A *workshop* committed to git with generated output gitignored."""
    (workshop / ".gitignore").write_text("generated/\n.copyroom_sim/\n")
    _git("init", cwd=workshop)
    _git("add", "-A", cwd=workshop)
    _git("commit", "-qm", "workshop", cwd=workshop)
    return workshop
