from __future__ import annotations

import tomllib
from pathlib import Path


def test_only_copyroom_is_a_public_console_script() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert project["scripts"] == {"copyroom": "copyroom.cli:main"}
