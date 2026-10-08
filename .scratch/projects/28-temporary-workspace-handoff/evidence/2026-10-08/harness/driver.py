"""Crash driver. Patches copyroom internals, then runs the real CLI.

usage: driver.py POINT MODE LOGFILE -- cli args...
MODE exit: os._exit(137) at the crash point.  MODE hang: write READY then sleep (harness sends SIGKILL).
"""
import os, sys, time, shutil
from pathlib import Path

point, mode, logfile = sys.argv[1:4]
cli_args = sys.argv[sys.argv.index("--") + 1:]

from copyroom.local import jj as jjmod, workflow, source
from copyroom.local.source import MARKER, PREVIEW_DIR

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
orig_write = workflow.write_json
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
    key = "copyroom:project inputs" if point == "A3" else "copyroom:layer marker"
    jj_after(lambda s, a: a[:1] == ("commit",) and any(key in x for x in a) and Path(s.cwd) == PROJECT)
elif point in ("A4", "L4"):
    jj_after(lambda s, a: a[:2] == ("workspace", "forget") and Path(s.cwd) == PROJECT)
elif point in ("A2", "L2"):
    def write_json(path, data):
        orig_write(path, data)
        if Path(path).name == MARKER:
            die(f"write_json path={path}")
    workflow.write_json = write_json
elif point == "A5":
    def rmtree(path, *a, **k):
        orig_rmtree(path, *a, **k)
        if "preview" in str(path) and "/runs/" in str(path):
            die(f"shutil.rmtree path={path}")
    shutil.rmtree = rmtree
elif point == "A6":
    def unlink(self, *a, **k):
        orig_unlink(self, *a, **k)
        if self.parent == PROJECT / PREVIEW_DIR:
            die(f"Path.unlink {self} (state file removed; sidecar not yet)")
    Path.unlink = unlink
elif point == "A2pre":
    # crash after the marker temp file is fully written but before os.replace
    def replace(self, target):
        if Path(target).name == MARKER:
            die(f"Path.replace {self} -> {target} (not yet replaced)")
        return orig_replace(self, target)
    orig_replace = Path.replace
    Path.replace = replace
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
