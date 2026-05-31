"""Unit tests for mode detection logic.

Covers the ``detect_mode`` function and its helper predicates.
"""

from __future__ import annotations

import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from copyroom.session.detector import detect_mode, is_project, is_workshop
from copyroom.session.model import CLIMode

# ---------------------------------------------------------------------------
# Helper: create a temporary directory tree with markers
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_path() -> Iterator[Path]:
    """Yield a clean tmp dir that is removed afterward."""
    d = Path(tempfile.mkdtemp(prefix="copyroom_ut_"))
    yield d
    import shutil
    shutil.rmtree(d, ignore_errors=True)


def make_workshop(base: Path) -> Path:
    """Add workshop markers to *base* (creates parent dirs)."""
    base.mkdir(parents=True, exist_ok=True)
    (base / "copyroom.yml").touch()
    (base / "registry").mkdir()
    (base / "scenarios").mkdir()
    return base


def make_project(base: Path) -> Path:
    """Add project markers to *base* (creates parent dirs)."""
    base.mkdir(parents=True, exist_ok=True)
    (base / ".copier-answers.yml").touch()
    return base


# ===========================================================================
# Helper predicate tests
# ===========================================================================


class TestIsWorkshop:
    def test_all_markers_present(self, tmp_path: Path) -> None:
        make_workshop(tmp_path)
        assert is_workshop(tmp_path)

    def test_missing_copyroom_yml(self, tmp_path: Path) -> None:
        (tmp_path / "registry").mkdir()
        (tmp_path / "scenarios").mkdir()
        assert not is_workshop(tmp_path)

    def test_missing_registry(self, tmp_path: Path) -> None:
        (tmp_path / "copyroom.yml").touch()
        (tmp_path / "scenarios").mkdir()
        assert not is_workshop(tmp_path)

    def test_missing_scenarios(self, tmp_path: Path) -> None:
        (tmp_path / "copyroom.yml").touch()
        (tmp_path / "registry").mkdir()
        assert not is_workshop(tmp_path)

    def test_empty_dir(self, tmp_path: Path) -> None:
        assert not is_workshop(tmp_path)


class TestIsProject:
    def test_copier_answers_yml(self, tmp_path: Path) -> None:
        (tmp_path / ".copier-answers.yml").touch()
        assert is_project(tmp_path)

    def test_copyroom_project_yml(self, tmp_path: Path) -> None:
        (tmp_path / "copyroom.project.yml").touch()
        assert is_project(tmp_path)

    def test_both_markers(self, tmp_path: Path) -> None:
        (tmp_path / ".copier-answers.yml").touch()
        (tmp_path / "copyroom.project.yml").touch()
        assert is_project(tmp_path)

    def test_empty_dir(self, tmp_path: Path) -> None:
        assert not is_project(tmp_path)


# ===========================================================================
# detect_mode tests
# ===========================================================================


class TestDetectMode:
    def test_workshop_mode(self, tmp_path: Path) -> None:
        make_workshop(tmp_path)
        assert detect_mode(tmp_path) == CLIMode.workshop

    def test_project_mode_via_copier_answers(self, tmp_path: Path) -> None:
        make_project(tmp_path)
        assert detect_mode(tmp_path) == CLIMode.project

    def test_project_mode_via_project_yml(self, tmp_path: Path) -> None:
        (tmp_path / "copyroom.project.yml").touch()
        assert detect_mode(tmp_path) == CLIMode.project

    def test_no_markers_returns_none(self, tmp_path: Path) -> None:
        assert detect_mode(tmp_path) is None

    def test_workshop_wins_over_project_at_same_level(self, tmp_path: Path) -> None:
        """At the same ancestor level, workshop markers are checked first."""
        make_workshop(tmp_path)
        make_project(tmp_path)
        assert detect_mode(tmp_path) == CLIMode.workshop

    def test_project_nested_in_workshop(self, tmp_path: Path) -> None:
        """Closest ancestor with markers wins (proximity over mode type)."""
        workshop_root = tmp_path / "repo"
        make_workshop(workshop_root)
        sub_project = workshop_root / "sub-project"
        sub_project.mkdir()
        make_project(sub_project)
        assert detect_mode(sub_project) == CLIMode.project

    def test_workshop_at_grandparent_not_parent(self, tmp_path: Path) -> None:
        """Should find workshop markers at grandparent level."""
        workshop_root = tmp_path / "repo"
        make_workshop(workshop_root)
        nested = workshop_root / "a" / "b"
        nested.mkdir(parents=True)
        assert detect_mode(nested) == CLIMode.workshop

    def test_defaults_to_cwd_when_no_arg(self) -> None:
        """Calling detect_mode() without arguments should use cwd (no crash)."""
        # We can't assert the result since it depends on the test environment,
        # but it should not raise.
        result = detect_mode()
        assert result is None or isinstance(result, CLIMode)

    def test_project_at_root_no_markers_at_cwd(self, tmp_path: Path) -> None:
        """Should walk up to parent and find project markers there."""
        make_project(tmp_path)
        child = tmp_path / "inner"
        child.mkdir()
        assert detect_mode(child) == CLIMode.project
