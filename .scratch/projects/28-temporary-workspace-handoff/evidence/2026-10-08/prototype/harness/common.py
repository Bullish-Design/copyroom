"""Shared helpers for the publish_if prototype tests. Disposable repos only, under /tmp."""
from __future__ import annotations
import hashlib, json, os, shutil, signal, subprocess, sys, tempfile, threading, time
from pathlib import Path

ROOT = Path(open("/tmp/pj-proto-dir.txt").read().strip())
PYJ = ROOT / "pyjutsu"
EVID = ROOT / "evidence"
PY = str(PYJ / ".devenv/state/venv/bin/python")
JJ44 = "/nix/store/jhgh5xvl0s92021dqpnsh5llj9wlv26s-jujutsu-0.44.0/bin/jj"
JJ43 = "/nix/store/w10748j1nsa40j6yjxvissjm8ljq4wlf-jujutsu-0.43.0/bin/jj"
WORK = Path(tempfile.mkdtemp(prefix="pj-run-", dir=str(ROOT)))
HOME = WORK / "home"
(HOME / ".config/jj").mkdir(parents=True, exist_ok=True)
(HOME / ".config/jj/config.toml").write_text('[user]\nname = "Test"\nemail = "t@example.com"\n')

def env(extra=None):
    e = {k: v for k, v in os.environ.items() if not k.startswith("PJ_")}
    e.update(HOME=str(HOME), XDG_CONFIG_HOME=str(HOME / ".config"), JJ_USER="Test", JJ_EMAIL="t@example.com",
             PYTHONPATH=str(PYJ / "python"), PAGER="cat", NO_COLOR="1")
    e.pop("JJ_CONFIG", None)
    if extra: e.update(extra)
    return e

def run(cmd, cwd=None, extra=None, check=True, input=None):
    r = subprocess.run(cmd, cwd=cwd, env=env(extra), capture_output=True, text=True, input=input)
    if check and r.returncode != 0:
        raise RuntimeError(f"{cmd} failed rc={r.returncode}\n{r.stdout}\n{r.stderr}")
    return r

def jj(repo, *args, jjbin=JJ44, check=True, observe=False):
    a = [jjbin, *args]
    if observe: a.insert(1, "--ignore-working-copy")
    return run(a, cwd=repo, check=check)

def mkrepo(name, jjbin=JJ44, nfiles=0, colocate=False, p_edit_a=False):
    repo = WORK / name
    repo.mkdir(parents=True)
    run([jjbin, "git", "init", *(["--no-colocate"] if not colocate else []), str(repo)])
    (repo / "a.txt").write_text("base\n")
    jj(repo, "describe", "-m", "base", jjbin=jjbin)
    jj(repo, "new", "-m", "prepared", jjbin=jjbin)
    (repo / "p.txt").write_text("prepared\n")
    if p_edit_a: (repo / "a.txt").write_text("a edited in P\n")
    for i in range(nfiles):
        d = repo / "bulk" / f"d{i % 50}"; d.mkdir(parents=True, exist_ok=True)
        (d / f"f{i}.txt").write_text(f"bulk {i}\n")
    jj(repo, "new", 'description(exact:"base\\n")', jjbin=jjbin)      # @ = empty child of base, P = prepared (sibling)
    return repo

def cid(repo, rev, jjbin=JJ44):
    return jj(repo, "log", "-r", rev, "--no-graph", "-T", "commit_id", jjbin=jjbin, observe=True).stdout.strip()

def oplog(repo, n=50, jjbin=JJ44):
    return jj(repo, "op", "log", "--no-graph", "-n", str(n), "-T",
              'self.id().short(12) ++ " " ++ description.first_line() ++ "\\n"', jjbin=jjbin, observe=True).stdout
def opids(repo, jjbin=JJ44):
    return [l.split()[0] for l in oplog(repo, 500, jjbin).splitlines()]
def log(repo, jjbin=JJ44):
    return jj(repo, "log", "-r", "all()", "-T",
              'commit_id.short(12) ++ " " ++ if(current_working_copy, "@ ", "  ") ++ "[" ++ description.first_line() ++ "] empty=" ++ empty ++ "\\n"',
              jjbin=jjbin, observe=True).stdout
def op_heads(repo):
    d = Path(repo) / ".jj/repo/op_heads/heads"
    return sorted(p.name[:12] for p in d.iterdir())
def tree_sig(repo):
    """sha256 of every file under .jj (excluding lock files' content), for before/after diffs."""
    out = {}
    base = Path(repo) / ".jj"
    for p in sorted(base.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(base))] = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    return out
def sig_diff(a, b):
    added = sorted(set(b) - set(a)); removed = sorted(set(a) - set(b))
    changed = sorted(k for k in a if k in b and a[k] != b[k])
    return {"added": added, "removed": removed, "changed": changed}

def publish_cmd(repo, expected, onto, msg="published-by-publish_if"):
    return [PY, "-m", "pyjutsu", "publish-if", "--repo", str(repo), "--expected", expected, "--onto", onto, "-m", msg]

class Fifo:
    def __init__(self, d, name):
        self.path = str(Path(d) / name)
        os.mkfifo(self.path)
    def read(self, timeout=60):
        """block until the child writes; returns time. Runs in caller thread."""
        with open(self.path, "rb") as f: f.read(1)
        return time.time()
    def write(self):
        with open(self.path, "wb") as f: f.write(b"x")
        return time.time()
    def reader_thread(self):
        box = {}
        def t(): box["t"] = self.read()
        th = threading.Thread(target=t, daemon=True); th.start()
        return th, box

def tryflock(path):
    import fcntl
    if not os.path.exists(path): return True      # jj removes the lock file on clean release
    fd = os.open(path, os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB); return True
    except BlockingIOError:
        return False
    finally:
        os.close(fd)

class Evidence:
    def __init__(self, name):
        self.f = open(EVID / name, "w"); self.name = name
    def w(self, *a):
        s = " ".join(str(x) for x in a); self.f.write(s + "\n"); self.f.flush(); print(s)
    def block(self, title, text):
        self.w(f"--- {title} ---"); self.w(text.rstrip()); 
