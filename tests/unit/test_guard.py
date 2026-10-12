"""Tests for the pyjutsu guard probe."""

from __future__ import annotations

from pathlib import Path

import pytest

from copyroom.local.guard import GUARD_ENV, UNGUARDED_ENV, resolve_guard, unguarded_requested


def script(path: Path, body: str) -> Path:
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(0o755)
    return path


def test_probe_accepts_an_executable_that_fails_the_known_way(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = script(
        tmp_path / "pyjutsu-good",
        'if [ "$1" = "--help" ]; then echo "publish-if recover"; exit 0; fi\n'
        'printf "result=error\\nreason=repo-not-found\\nmessage=absent\\n"; exit 2\n',
    )
    monkeypatch.setenv(GUARD_ENV, str(fake))

    guard = resolve_guard()

    assert guard is not None
    assert guard.path == str(fake)
    assert guard.describe()["guard"] is True


@pytest.mark.parametrize(
    "body",
    [
        'echo "no such command"; exit 0\n',
        'if [ "$1" = "--help" ]; then echo "publish-if"; exit 0; fi\n'
        'printf "result=published\\n"; exit 0\n',
        'if [ "$1" = "--help" ]; then echo "publish-if"; exit 0; fi\n'
        'printf "result=error\\nreason=other\\n"; exit 2\n',
    ],
)
def test_probe_rejects_an_executable_that_does_not_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str
) -> None:
    monkeypatch.setenv(GUARD_ENV, str(script(tmp_path / "pyjutsu-bad", body)))

    assert resolve_guard() is None


def test_missing_or_non_executable_guard_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plain = tmp_path / "plain"
    plain.write_text("x", encoding="utf-8")
    monkeypatch.setenv(GUARD_ENV, str(plain))
    assert resolve_guard() is None
    monkeypatch.setenv(GUARD_ENV, str(tmp_path / "absent"))
    assert resolve_guard() is None


def test_unguarded_request_comes_from_the_flag_or_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(UNGUARDED_ENV, raising=False)
    assert unguarded_requested(False) is False
    assert unguarded_requested(True) is True
    monkeypatch.setenv(UNGUARDED_ENV, "1")
    assert unguarded_requested(False) is True


def test_version_comes_from_the_interpreter_in_the_shebang(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    python = tmp_path / "py"
    python.write_text('#!/bin/sh\necho 9.9.9\n', encoding="utf-8")
    python.chmod(0o755)
    fake = tmp_path / "pyjutsu-shebang"
    fake.write_text(
        f"#!{python}\n"
        "# the shebang stands in for the real interpreter\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    from copyroom.local.guard import _interpreter, _versions

    assert _interpreter(str(fake)) == str(python)
    assert _versions(str(fake)) == ("9.9.9", None)


def test_a_colocated_child_workspace_has_a_git_file_that_points_into_worktrees(
    tmp_path: Path,
) -> None:
    from copyroom.local.guard import is_colocated_child_workspace

    repo = tmp_path / "repo"
    (repo / ".git" / "worktrees" / "child").mkdir(parents=True)
    child = tmp_path / "child"
    child.mkdir()
    (child / ".git").write_text("gitdir: ../repo/.git/worktrees/child\n", encoding="utf-8")
    absolute = tmp_path / "absolute"
    absolute.mkdir()
    (absolute / ".git").write_text(
        f"gitdir: {repo}/.git/worktrees/child\n", encoding="utf-8",
    )

    assert is_colocated_child_workspace(child) is True
    assert is_colocated_child_workspace(absolute) is True


def test_other_checkouts_are_not_colocated_child_workspaces(tmp_path: Path) -> None:
    from copyroom.local.guard import is_colocated_child_workspace

    bare = tmp_path / "none"
    bare.mkdir()
    main = tmp_path / "main"
    (main / ".git").mkdir(parents=True)
    submodule = tmp_path / "submodule"
    submodule.mkdir()
    (submodule / ".git").write_text("gitdir: ../main/.git/modules/lib\n", encoding="utf-8")
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / ".git").write_bytes(b"\xff\xfe not text")
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / ".git").write_text("", encoding="utf-8")

    for path in (bare, main, submodule, broken, empty, tmp_path / "absent"):
        assert is_colocated_child_workspace(path) is False


@pytest.mark.parametrize(
    ("version", "jj_lib", "keeps"),
    [
        ("0.23.0", "0.44.0", False),
        ("0.23.0", "0.45.0", True),
        ("0.24.0", "0.45.1", True),
        ("0.24.0", "1.0.0", True),
        # The jj-lib version wins over the pyjutsu version.
        ("0.30.0", "0.44.0", False),
        ("0.20.0", "0.46.0", True),
        # Without a jj-lib version, 0.24.0 is the first fixed pyjutsu.
        ("0.23.9", None, False),
        ("0.24.0", None, True),
        ("0.100.0", None, True),
        ("1.0.0", "", True),
        # Without either version, CopyRoom cannot prove the build is safe.
        (None, None, False),
        ("unknown", "unknown", False),
    ],
)
def test_the_version_gate_lifts_with_the_fixed_jj_lib_or_pyjutsu(
    version: str | None, jj_lib: str | None, keeps: bool
) -> None:
    from copyroom.local.guard import Guard

    assert Guard("/opt/pyjutsu", version, jj_lib).keeps_child_git_head() is keeps


def test_versions_come_from_the_interpreter_in_the_shebang_with_the_jj_lib(
    tmp_path: Path,
) -> None:
    from copyroom.local.guard import _versions

    python = tmp_path / "py"
    python.write_text("#!/bin/sh\necho 0.24.0\necho 0.45.0\n", encoding="utf-8")
    python.chmod(0o755)
    fake = tmp_path / "pyjutsu-shebang"
    fake.write_text(f"#!{python}\n", encoding="utf-8")
    fake.chmod(0o755)

    assert _versions(str(fake)) == ("0.24.0", "0.45.0")
