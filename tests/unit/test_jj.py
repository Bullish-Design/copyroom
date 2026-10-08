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
