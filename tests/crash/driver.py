"""Run one real CLI action and stop at a selected transaction boundary."""

from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

point, mode, logfile, ready_fifo, release_fifo = sys.argv[1:6]
cli_args = sys.argv[sys.argv.index("--") + 1 :]
project = Path.cwd().resolve()
preview_path = Path(cli_args[2]).resolve() if cli_args[:1] == ["apply"] else None
state = {"crashed": False}


def log(message: str) -> None:
    with Path(logfile).open("a", encoding="utf-8") as stream:
        stream.write(message + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def wait_at_barrier() -> None:
    if not ready_fifo or not release_fifo:
        return
    with Path(ready_fifo).open("w", encoding="utf-8") as stream:
        stream.write("ready\n")
    with Path(release_fifo).open("r", encoding="utf-8") as stream:
        stream.read()


def crash(description: str) -> None:
    state["crashed"] = True
    log(f"CRASH point={point} mode={mode} pid={os.getpid()} matched={description}")
    wait_at_barrier()
    if mode == "sigkill":
        time.sleep(3600)
    os._exit(137)


from copyroom.local import jj as jj_module  # noqa: E402
from copyroom.local import workflow  # noqa: E402
from copyroom.local.source import PREVIEW_DIR  # noqa: E402

original_run = jj_module.JJ.run
original_phase = workflow._set_journal_phase
original_rmtree = shutil.rmtree
original_unlink = Path.unlink


def patch_jj(match) -> None:
    def run(self, *args, **kwargs):
        result = original_run(self, *args, **kwargs)
        if match(self, args):
            crash(f"JJ.run cwd={self.cwd} args={args}")
        return result

    jj_module.JJ.run = run


if point in {"A1", "L1"}:
    subject = "copyroom:update" if point == "A1" else "copyroom:layer add docs"
    patch_jj(
        lambda jj, args: Path(jj.cwd).resolve() == project
        and args[:1] == ("new",)
        and subject in args,
    )
elif point in {"L0"}:
    patch_jj(
        lambda jj, args: Path(jj.cwd).resolve() == project
        and args[:2] == ("workspace", "add"),
    )
elif point in {"A3", "L3"}:
    patch_jj(
        lambda jj, args: Path(jj.cwd).resolve() == project
        and args[:2] == ("workspace", "forget"),
    )
elif point in {"A2", "L2", "X0", "X1"}:
    def set_phase(project_arg, journal, phase, *args, **kwargs):
        result = original_phase(project_arg, journal, phase, *args, **kwargs)
        if Path(project_arg).resolve() != project:
            return result
        if point in {"A2", "L2"} and phase == "published":
            crash(f"published journal workspace={journal.get('workspace')}")
        if point == "X0" and phase == "prepared" and journal.get("prepared_head"):
            crash(f"prepared journal workspace={journal.get('workspace')}")
        if point == "X1" and phase == "publishing" and journal.get("prepared_head"):
            crash(f"publishing journal workspace={journal.get('workspace')}")
        return result

    workflow._set_journal_phase = set_phase
elif point in {"A4", "L4"}:
    def rmtree(path, *args, **kwargs):
        original_rmtree(path, *args, **kwargs)
        path = Path(path)
        matches = point == "A4" and path == preview_path
        matches = matches or point == "L4" and path.name.startswith("copyroom-layer-")
        if matches:
            crash(f"rmtree path={path}")

    shutil.rmtree = rmtree
elif point in {"A5", "A6"}:
    def unlink(path, *args, **kwargs):
        result = original_unlink(path, *args, **kwargs)
        if point == "A5" and path.parent == project / PREVIEW_DIR:
            crash(f"preview state removed path={path}")
        if point == "A6" and path.name.endswith(".copyroom-preview.json"):
            crash(f"preview sidecar removed path={path}")
        return result

    Path.unlink = unlink
elif point == "X1j":
    pass
else:
    raise SystemExit(f"unknown crash point {point}")

log(f"DRIVER start point={point} cwd={project} args={cli_args}")
from copyroom.cli import main  # noqa: E402

main(cli_args)
