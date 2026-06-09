"""Sanity checks that the integration fixtures themselves work."""

from __future__ import annotations

from pathlib import Path

from copyroom.session.detector import detect_mode, detect_workshop_root
from copyroom.session.model import CLIMode


def test_workshop_is_detected(workshop: Path) -> None:
    assert detect_mode(workshop) == CLIMode.workshop
    assert detect_workshop_root(workshop) == workshop.resolve()


def test_template_repo_has_v1_tag(template_repo: Path) -> None:
    import subprocess

    tags = subprocess.run(
        ["git", "tag"], cwd=template_repo, capture_output=True, text=True
    ).stdout.split()
    assert "v1.0.0" in tags
