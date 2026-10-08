"""Unit tests for the atomic JSON writer and the local-state exclude rules."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from copyroom.local.errors import LocalError
from copyroom.local.source import (
    MARKER,
    TEMP_EXCLUDE,
    TEMP_PREFIX,
    exclude_local_state,
    write_json,
)

SAMPLE = {"b": [1, 2], "a": {"z": "é", "y": None}}
SAMPLE_BYTES = (
    b'{\n  "a": {\n    "y": null,\n    "z": "\\u00e9"\n  },\n'
    b'  "b": [\n    1,\n    2\n  ]\n}\n'
)


def test_write_json_bytes_and_mode_are_stable(tmp_path: Path) -> None:
    target = tmp_path / "out.json"
    write_json(target, SAMPLE)
    assert target.read_bytes() == SAMPLE_BYTES
    assert stat.S_IMODE(target.stat().st_mode) == 0o644
    assert [item.name for item in tmp_path.iterdir()] == ["out.json"]


def test_write_json_creates_parent_and_overwrites(tmp_path: Path) -> None:
    target = tmp_path / "deep" / "out.json"
    write_json(target, {"n": 1})
    write_json(target, SAMPLE)
    assert target.read_bytes() == SAMPLE_BYTES


def test_temp_file_uses_documented_prefix(tmp_path: Path) -> None:
    seen: list[Path] = []
    real_replace = os.replace

    def spy(source: str | Path, destination: str | Path) -> None:
        seen.append(Path(source))
        real_replace(source, destination)

    with mock.patch("copyroom.local.source.os.replace", spy):
        write_json(tmp_path / MARKER, SAMPLE)
    assert TEMP_PREFIX == ".copyroom-tmp-"
    assert len(seen) == 1
    assert seen[0].name.startswith(TEMP_PREFIX)
    assert seen[0].parent == tmp_path


def test_failed_replace_leaves_no_temp_file(tmp_path: Path) -> None:
    target = tmp_path / MARKER
    target.write_bytes(b"old\n")
    with mock.patch("copyroom.local.source.os.replace", side_effect=OSError("boom")):
        with pytest.raises(LocalError, match="cannot write"):
            write_json(target, SAMPLE)
    assert [item.name for item in tmp_path.iterdir()] == [MARKER]
    assert target.read_bytes() == b"old\n"


def test_unexpected_error_leaves_no_temp_file(tmp_path: Path) -> None:
    with mock.patch("copyroom.local.source.os.fsync", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError):
            write_json(tmp_path / "out.json", SAMPLE)
    assert list(tmp_path.iterdir()) == []


def test_directory_fsync_failure_does_not_fail_the_write(tmp_path: Path) -> None:
    real_open = os.open

    def refuse_directory(path: str | Path, flags: int, *args: int) -> int:
        if Path(path) == tmp_path:
            raise OSError("no directory handles")
        return real_open(path, flags, *args)

    with mock.patch("copyroom.local.source.os.open", refuse_directory):
        write_json(tmp_path / "out.json", SAMPLE)
    assert (tmp_path / "out.json").read_bytes() == SAMPLE_BYTES


def test_directory_is_fsynced_after_rename(tmp_path: Path) -> None:
    order: list[str] = []
    real_replace, real_fsync = os.replace, os.fsync

    def replace(source: str | Path, destination: str | Path) -> None:
        order.append("replace")
        real_replace(source, destination)

    def fsync(descriptor: int) -> None:
        order.append("fsync")
        real_fsync(descriptor)

    with (
        mock.patch("copyroom.local.source.os.replace", replace),
        mock.patch("copyroom.local.source.os.fsync", fsync),
    ):
        write_json(tmp_path / "out.json", SAMPLE)
    assert order == ["fsync", "replace", "fsync"]


def test_exclude_local_state_is_idempotent(tmp_path: Path) -> None:
    exclude_local_state(tmp_path)
    first = (tmp_path / ".git" / "info" / "exclude").read_text(encoding="utf-8")
    exclude_local_state(tmp_path)
    second = (tmp_path / ".git" / "info" / "exclude").read_text(encoding="utf-8")
    assert first == second
    assert first.splitlines().count(TEMP_EXCLUDE) == 1


def test_exclude_local_state_backfills_older_projects(tmp_path: Path) -> None:
    exclude = tmp_path / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True)
    exclude.write_text("/.copyroom-local/previews/\n/.copyroom-local/write.lock", encoding="utf-8")
    exclude_local_state(tmp_path)
    lines = exclude.read_text(encoding="utf-8").splitlines()
    assert lines == [
        "/.copyroom-local/previews/",
        "/.copyroom-local/write.lock",
        "/.copyroom-local/journal/",
        TEMP_EXCLUDE,
    ]


@pytest.mark.skipif(shutil.which("jj") is None, reason="jj is not installed")
def test_jj_ignores_stray_temp_file(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()

    def jj(*args: str) -> str:
        return subprocess.run(
            ["jj", "--no-pager", "--color=never", *args],
            cwd=project, text=True, capture_output=True, check=True,
            env={**os.environ, "JJ_USER": "t", "JJ_EMAIL": "t@example.com"},
        ).stdout

    jj("git", "init", "--colocate")
    jj("config", "set", "--repo", "snapshot.auto-track", "all()")
    exclude_local_state(project)
    write_json(project / MARKER, {"schema": 2})
    jj("commit", "-m", "base")
    before = jj("log", "-r", "@", "--no-graph", "-T", "commit_id")
    # Simulate a crash between the temp write and os.replace.
    (project / f"{TEMP_PREFIX}d5i8zxwo").write_text("{}\n", encoding="utf-8")
    (project / "sub").mkdir()
    (project / "sub" / f"{TEMP_PREFIX}abcd1234").write_text("{}\n", encoding="utf-8")
    jj("status")
    assert jj("log", "-r", "@", "--no-graph", "-T", "commit_id") == before
    assert jj("file", "list").splitlines() == [MARKER]
    assert TEMP_PREFIX not in jj("status")
