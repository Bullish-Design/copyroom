"""Tests for plain jj command handling."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from copyroom.local.jj import JJ


def test_jj_surfaces_refused_snapshot_warning(tmp_path: Path, capsys) -> None:
    completed = subprocess.CompletedProcess(
        ["jj", "new"], 0, "commit-id\n", "Warning: Refused to snapshot some files:\nlarge.bin\n",
    )
    with (
        patch("copyroom.local.jj.shutil.which", return_value="/usr/bin/jj"),
        patch("copyroom.local.jj.subprocess.run", return_value=completed),
    ):
        output = JJ(tmp_path).run("new", "preview")

    assert output == "commit-id\n"
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Warning: Refused to snapshot some files: large.bin\n"


def test_jj_spawns_the_resolved_absolute_path(tmp_path: Path, monkeypatch) -> None:
    fake = tmp_path / "jj-fake"
    fake.write_text("#!/bin/sh\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("COPYROOM_JJ", str(fake))
    completed = subprocess.CompletedProcess([str(fake), "log"], 0, "ok\n", "")
    with patch("copyroom.local.jj.subprocess.run", return_value=completed) as run:
        JJ(tmp_path).run("log")

    assert run.call_args.args[0] == [str(fake), "log"]


def test_jj_refuses_a_named_executable_that_does_not_exist(tmp_path: Path, monkeypatch) -> None:
    import pytest

    from copyroom.local.errors import LocalError

    monkeypatch.setenv("COPYROOM_JJ", str(tmp_path / "missing"))
    with pytest.raises(LocalError) as raised:
        JJ(tmp_path).run("log")

    assert raised.value.code == 2
