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
