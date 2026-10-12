"""Check how the publication mode treats a colocated child workspace."""

from __future__ import annotations

from pathlib import Path

import pytest

from copyroom.local import workflow
from copyroom.local.errors import LocalError
from copyroom.local.guard import UNGUARDED_ENV, Guard


@pytest.fixture
def child(tmp_path: Path) -> Path:
    (tmp_path / "repo/.git/worktrees/child").mkdir(parents=True)
    path = tmp_path / "child"
    path.mkdir()
    (path / ".git").write_text("gitdir: ../repo/.git/worktrees/child\n", encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def guarded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(UNGUARDED_ENV, raising=False)


def use_guard(monkeypatch: pytest.MonkeyPatch, version: str, jj_lib: str | None) -> Guard:
    guard = Guard("/opt/pyjutsu", version, jj_lib)
    monkeypatch.setattr(workflow, "resolve_guard", lambda: guard)
    return guard


def test_an_old_jj_lib_refuses_with_exit_code_2_in_a_child_workspace(
    child: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_guard(monkeypatch, "0.23.0", "0.44.0")

    with pytest.raises(LocalError) as raised:
        workflow._publication_mode(child, False)

    assert raised.value.code == 2
    message = str(raised.value)
    assert "pyjutsu 0.23.0 (jj-lib 0.44.0)" in message
    assert "default workspace" in message
    assert "--publish-unguarded" in message


def test_an_old_jj_lib_still_publishes_outside_a_child_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    guard = use_guard(monkeypatch, "0.23.0", "0.44.0")
    (tmp_path / ".git").mkdir()

    assert workflow._publication_mode(tmp_path, False) == guard.describe()


def test_a_fixed_jj_lib_publishes_in_a_child_workspace(
    child: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    guard = use_guard(monkeypatch, "0.24.0", "0.46.0")

    assert workflow._publication_mode(child, False) == guard.describe()


def test_the_unguarded_choice_skips_the_child_workspace_refusal(
    child: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_guard(monkeypatch, "0.23.0", "0.44.0")

    assert workflow._publication_mode(child, True) == {"guard": False}
