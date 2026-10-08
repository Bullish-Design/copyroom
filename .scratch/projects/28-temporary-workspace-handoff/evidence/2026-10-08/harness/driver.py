"""Crash driver. Patches copyroom internals, then runs the real CLI.

usage: driver.py POINT MODE LOGFILE -- cli args...
MODE exit: os._exit(137) at the crash point.  MODE hang: write READY then sleep (harness sends SIGKILL).
"""
import os, sys, time, shutil
from pathlib import Path

point, mode, logfile = sys.argv[1:4]
cli_args = sys.argv[sys.argv.index("--") + 1:]

from copyroom.local import jj as jjmod, workflow, source
from copyroom.local.source import PREVIEW_DIR

PROJECT = Path.cwd()
# find project root (cwd is project for all runs)
state = {"n": 0}


def log(msg):
    with open(logfile, "a") as f:
        f.write(msg + "\n")
        f.flush()
        os.fsync(f.fileno())


def die(desc):
    state["n"] += 1
    log(f"CRASH point={point} mode={mode} pid={os.getpid()} matched={desc}")
    if mode == "exit":
        os._exit(137)
    ready = logfile + ".ready"
    open(ready, "w").write("READY\n")
    time.sleep(10_000)


orig_run = jjmod.JJ.run
orig_set_phase = workflow._set_journal_phase
orig_rmtree = shutil.rmtree
orig_unlink = Path.unlink


def jj_after(match):
    def run(self, *args, **kw):
        out = orig_run(self, *args, **kw)
        if match(self, args):
            die(f"JJ.run cwd={self.cwd} args={args}")
        return out
    jjmod.JJ.run = run


if point in ("A1", "L1"):
    key = "copyroom:update" if point == "A1" else "copyroom:layer add"
    jj_after(lambda s, a: a[:1] == ("new",) and any(key in x for x in a) and Path(s.cwd) == PROJECT)
elif point in ("A3", "L3"):
    jj_after(lambda s, a: a[:2] == ("workspace", "forget") and Path(s.cwd) == PROJECT)
elif point in ("A2", "L2"):
    def set_phase(project, journal, phase, *args, **kwargs):
        result = orig_set_phase(project, journal, phase, *args, **kwargs)
        if Path(project) == PROJECT and phase == "published":
            die(f"published journal workspace={journal.get('workspace')}")
        return result
    workflow._set_journal_phase = set_phase
elif point in ("A4", "L4"):
    def rmtree(path, *a, **k):
        orig_rmtree(path, *a, **k)
        path = Path(path)
        if point == "A4" and path == Path(cli_args[2]):
            die(f"preview removed path={path}")
        if point == "L4" and path.name.startswith("copyroom-layer-"):
            die(f"layer directory removed path={path}")
    shutil.rmtree = rmtree
elif point in ("A5", "A6"):
    def unlink(self, *a, **k):
        orig_unlink(self, *a, **k)
        if point == "A5" and self.parent == PROJECT / PREVIEW_DIR:
            die(f"preview state removed path={self}")
        if point == "A6" and self.name.endswith(".copyroom-preview.json"):
            die(f"preview sidecar removed path={self}")
    Path.unlink = unlink
elif point == "L0":
    jj_after(lambda s, a: a[:2] == ("workspace", "add") and Path(s.cwd) == PROJECT)
elif point == "NONE":
    pass
else:
    raise SystemExit(f"unknown point {point}")

log(f"DRIVER start point={point} mode={mode} cwd={PROJECT} args={cli_args}")
from copyroom.cli import main
try:
    main(cli_args)
except SystemExit as e:
    log(f"DRIVER exit code={e.code} crashed={state['n'] > 0}")
    raise
