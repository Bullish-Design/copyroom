import sys, glob
from common import *
ev = Evidence("h5-recovery-after-failed-checkout.txt")
base = sorted(glob.glob(str(ROOT / "pj-run-*/h5-7")))
repo = Path(base[-1]); ev.w("repo", repo)
ev.w("bulk files present:", len(list((repo/"bulk").rglob("*.txt"))), "of 25000; a.txt:", repr((repo/"a.txt").read_text()))
st = jj(repo, "status", check=False); ev.block(f"jj status rc={st.returncode}", st.stdout + st.stderr)
us = jj(repo, "workspace", "update-stale", check=False); ev.block(f"jj workspace update-stale rc={us.returncode}", us.stdout + us.stderr)
ev.w("bulk files present:", len(list((repo/"bulk").rglob("*.txt"))), "a.txt:", repr((repo/"a.txt").read_text()))
st = jj(repo, "status", check=False); ev.block(f"jj status rc={st.returncode}", st.stdout + st.stderr)
ev.block("op log", "\n".join(oplog(repo, 6).splitlines()))
