#!/usr/bin/env python3
"""Pause a real jj subprocess at one selected command boundary."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    args = sys.argv[1:]
    real_jj = os.environ["COPYROOM_REAL_JJ"]
    match = json.loads(os.environ["COPYROOM_JJ_BARRIER"])
    cwd = Path.cwd().resolve()
    selected_cwd = match.get("cwd")
    prefix = match["prefix"]
    matches = args[: len(prefix)] == prefix and (
        selected_cwd is None or cwd == Path(selected_cwd).resolve()
    )
    ready = Path(match["ready"])
    release = Path(match["release"])
    first_hit = Path(match["first_hit"])
    pause_before = matches and not first_hit.exists() and match["when"] == "before"

    def pause() -> None:
        first_hit.write_text(
            json.dumps({"cwd": str(cwd), "args": args, "pid": os.getpid()}),
            encoding="utf-8",
        )
        ready.write_text("ready\n", encoding="utf-8")
        deadline = time.monotonic() + 60
        while not release.exists():
            if time.monotonic() > deadline:
                raise SystemExit("barrier timed out")
            time.sleep(0.01)

    if pause_before:
        pause()
    result = subprocess.run([real_jj, *args], text=True, capture_output=True, check=False)
    if matches and not first_hit.exists() and match["when"] == "after":
        pause()
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
