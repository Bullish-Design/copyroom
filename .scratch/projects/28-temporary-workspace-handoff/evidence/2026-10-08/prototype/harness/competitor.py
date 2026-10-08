# usage: competitor.py <jjbin> <repo> <fifo> <kind>
import subprocess, sys, os, time
jjbin, repo, fifo, kind = sys.argv[1:5]
open(fifo, "rb").read(1)           # barrier: block until the harness writes
def jj(*a): return subprocess.run([jjbin, *a], cwd=repo, capture_output=True, text=True)
t0 = time.time()
if kind == "newcommit":
    r1 = jj("new", "-m", "competitor")
    open(os.path.join(repo, "comp.txt"), "w").write("competitor bytes\n")
    r2 = jj("commit", "-m", "competitor work")
    rc = (r1.returncode, r2.returncode, r1.stderr + r2.stderr)
elif kind == "new1":
    r1 = jj("new", "-m", "competitor")
    rc = (r1.returncode, 0, r1.stderr)
print(rc, time.time() - t0)
