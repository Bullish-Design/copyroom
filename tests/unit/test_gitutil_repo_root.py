"""``resolve_repo_root`` — where a repo-scoped command operates.

Moved here from the retired agent-files tests: the resolver is a general
repo-root helper, not an agent-files concern.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from copyroom._compat.gitutil import resolve_repo_root


def _git_ancestor_of(path: Path) -> Path | None:
    """Nearest ancestor of *path* that is a git repo root, or None."""
    resolved = path.resolve()
    for parent in (resolved, *resolved.parents):
        if (parent / ".git").exists():
            return parent
    return None


def test_explicit_target_wins(tmp_path: Path) -> None:
    assert resolve_repo_root(tmp_path) == tmp_path.resolve()


def test_git_root(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    (repo / "sub").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    monkeypatch.chdir(repo / "sub")
    assert resolve_repo_root(None) == repo.resolve()


def test_devenv_root(tmp_path: Path, monkeypatch) -> None:
    bare = tmp_path / "bare"
    bare.mkdir()
    if _git_ancestor_of(bare) is not None:
        pytest.skip(
            "tmp dir sits inside a git repo root — the git-root scan wins over "
            "DEVENV_ROOT by design, so this fallback cannot be exercised here"
        )
    monkeypatch.chdir(bare)
    monkeypatch.setenv("DEVENV_ROOT", str(tmp_path / "devenv-root"))
    assert resolve_repo_root(None) == (tmp_path / "devenv-root").resolve()


def test_falls_back_to_cwd(tmp_path: Path, monkeypatch) -> None:
    bare = tmp_path / "bare"
    bare.mkdir()
    if _git_ancestor_of(bare) is not None:
        pytest.skip(
            "tmp dir sits inside a git repo root — the git-root scan wins over "
            "cwd by design, so this fallback cannot be exercised here"
        )
    monkeypatch.chdir(bare)
    monkeypatch.delenv("DEVENV_ROOT", raising=False)
    assert resolve_repo_root(None) == bare.resolve()
