"""Un-barriered copyroom.cli.main with a timestamped JJ.run trace (no blocking)."""
import json, os, sys, time
from pathlib import Path
spec = json.loads(os.environ["LAB_SPEC"])
from copyroom.local.jj import JJ
_orig = JJ.run
_n = {"n": 0}
_t = open(spec["trace"], "a", buffering=1)
def _run(self, *args, **kw):
    _n["n"] += 1
    rec = {"ordinal": _n["n"], "cwd": str(Path(self.cwd).resolve()), "args": list(args), "t0": time.time()}
    try:
        return _orig(self, *args, **kw)
    finally:
        rec["t1"] = time.time()
        _t.write(json.dumps(rec) + "\n")
JJ.run = _run
from copyroom.cli import main
main(spec["argv"])
