"""Run the real copyroom CLI (copyroom.cli.main) with one FIFO barrier on JJ.run.

Spec comes from env LAB_SPEC (json):
  argv      CLI argv, e.g. ["update", "--apply", "/path/preview"]
  trace     path of the per-call trace file
  hit       path where the barrier hit record is written
  barrier   null or {cwd, prefix, contains, nth, when, ready, release}
Barrier: when the nth JJ.run call whose cwd, leading args and extra args match
is reached, write the ready FIFO (blocks until the lab reads it), then block
reading the release FIFO until the lab writes to it.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

spec = json.loads(os.environ["LAB_SPEC"])

from copyroom.local.jj import JJ  # noqa: E402

_orig = JJ.run
_state = {"n": 0, "matches": 0}
_trace = open(spec["trace"], "a", buffering=1, encoding="utf-8")
_trace.write(json.dumps({
    "start": True, "pid": os.getpid(), "python": sys.executable,
    "jj_which": shutil.which("jj"), "argv": spec["argv"],
}) + "\n")


def _hit(point: str, record: dict) -> None:
    b = spec["barrier"]
    Path(spec["hit"]).write_text(json.dumps({**record, "point": point, "pid": os.getpid()}, indent=2))
    with open(b["ready"], "w") as f:  # blocks until the lab opens the read end
        f.write("ready\n")
    with open(b["release"], "r") as f:  # blocks until the lab writes release
        f.read()


def _run(self, *args, **kw):
    _state["n"] += 1
    n = _state["n"]
    cwd = str(Path(self.cwd).resolve())
    rec = {"ordinal": n, "cwd": cwd, "args": list(args)}
    b = spec.get("barrier")
    is_hit = False
    if b and cwd == b["cwd"] and list(args[: len(b["prefix"])]) == b["prefix"] \
            and all(s in args for s in b.get("contains", [])):
        _state["matches"] += 1
        rec["match_ordinal"] = _state["matches"]
        is_hit = _state["matches"] == b.get("nth", 1)
    if is_hit and b["when"] == "before":
        _hit("before", rec)
    try:
        out = _orig(self, *args, **kw)
    except BaseException as exc:
        rec["raised"] = repr(exc)[:300]
        _trace.write(json.dumps(rec) + "\n")
        raise
    rec["ok"] = True
    _trace.write(json.dumps(rec) + "\n")
    if is_hit and b["when"] == "after":
        _hit("after", rec)
    return out


JJ.run = _run

from copyroom.cli import main  # noqa: E402

main(spec["argv"])
