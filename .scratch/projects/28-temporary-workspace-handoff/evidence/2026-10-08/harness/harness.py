"""Crash-state harness. Run inside the devenv: python harness.py RUNNAME [RUNNAME...]"""
import hashlib, json, os, shutil, signal, subprocess, sys, time
from pathlib import Path

ROOT = Path("/tmp/cr-crash-2578910")
EV = ROOT / "evidence"
PY = sys.executable
OPLOG_T = 'id ++ " " ++ description.first_line() ++ "\\n"'
LOG_T = 'commit_id ++ " " ++ description.first_line() ++ if(empty, " [empty]", "") ++ "\\n"'

# name -> (kind, point, mode, writer)
RUNS = {
    "A1": ("A", "A1", "exit", False), "A2": ("A", "A2", "exit", False),
    "A3": ("A", "A3", "exit", False), "A4": ("A", "A4", "exit", False),
    "A5": ("A", "A5", "exit", False), "A6": ("A", "A6", "exit", False),
    "L1": ("L", "L1", "exit", False), "L2": ("L", "L2", "exit", False),
    "L3": ("L", "L3", "exit", False), "L4": ("L", "L4", "exit", False),
    "A1w": ("A", "A1", "exit", True), "A2w": ("A", "A2", "exit", True),
    "A3w": ("A", "A3", "exit", True),
    "L1w": ("L", "L1", "exit", True), "L2w": ("L", "L2", "exit", True),
    "L3w": ("L", "L3", "exit", True),
    "A2pre": ("A", "A2pre", "exit", False), "L0": ("L", "L0", "exit", False),
    "A1k": ("A", "A1", "hang", False), "A3k": ("A", "A3", "hang", False),
    "L1k": ("L", "L1", "hang", False),
}


class Run:
    def __init__(self, name):
        self.name = name
        self.kind, self.point, self.mode, self.writer = RUNS[name]
        self.dir = ROOT / "runs" / name
        shutil.rmtree(self.dir, ignore_errors=True)
        (self.dir / "tmp").mkdir(parents=True)
        self.project = self.dir / "project"
        self.source = self.dir / "source"
        self.overlay = self.dir / "overlay"
        self.preview = self.dir / "preview"
        self.ev = EV / f"{name}.txt"
        self.ev.write_text("")
        self.env = {**os.environ, "TMPDIR": str(self.dir / "tmp")}
        self.rcs = {}

    def w(self, text):
        with self.ev.open("a") as f:
            f.write(text + "\n")

    def h(self, title):
        self.w(f"\n===== {title} =====")

    def sh(self, cmd, cwd=None, key=None, quiet=False, env=None):
        cwd = cwd or self.project
        p = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, env=env or self.env, timeout=120)
        if not quiet:
            self.w(f"$ (cd {cwd}) {' '.join(str(c) for c in cmd)}")
            if p.stdout: self.w("--- stdout\n" + p.stdout.rstrip("\n"))
            if p.stderr: self.w("--- stderr\n" + p.stderr.rstrip("\n"))
            self.w(f"--- exit: {p.returncode}")
        if key:
            first = (p.stderr.strip() or p.stdout.strip()).splitlines()
            self.rcs[key] = {"rc": p.returncode, "msg": (first[0][:300] if first else "")}
        return p

    def cli(self, args, key=None, cwd=None):
        return self.sh([PY, "-m", "copyroom", *args], cwd=cwd, key=key)

    def jj(self, args, cwd=None, key=None, quiet=False):
        return self.sh(["jj", *args], cwd=cwd, key=key, quiet=quiet)

    # ---------- setup ----------
    def setup(self):
        shutil.copytree(ROOT / "tpl/base", self.source)
        shutil.copytree(ROOT / "tpl/overlay", self.overlay)
        self.h("SETUP: copyroom new")
        p = self.cli(["new", str(self.source), str(self.project), "--answers", str(self.source / "answers.json")], key="new", cwd=self.dir)
        assert p.returncode == 0, p.stderr
        self.w("marker sha256 (pre): " + sha(self.project / ".copyroom-local.json"))
        self.jj(["--ignore-working-copy", "op", "log", "--no-graph", "-T", OPLOG_T])
        if self.kind == "A":
            t = self.source / "templates/settings/template.j2"
            t.write_text(t.read_text() + 'revision: "v2"\n')
            self.h("SETUP: copyroom update (make preview)")
            p = self.cli(["update", "--out", str(self.preview)], key="update-preview")
            assert p.returncode == 0, p.stderr
            self.w("preview sidecar exists: " + str(sidecar(self.preview).exists()))

    # ---------- crash ----------
    def crash(self):
        self.h(f"CRASH point={self.point} mode={self.mode}")
        if self.kind == "A":
            cli = ["update", "--apply", str(self.preview)]
        else:
            cli = ["layer", "add", "--source", str(self.overlay), "--answers", str(self.overlay / "answers.json"), "--as", "docs"]
        log = EV / f"{self.name}.crashlog"
        log.unlink(missing_ok=True)
        ready = Path(str(log) + ".ready"); ready.unlink(missing_ok=True)
        cmd = [PY, str(ROOT / "driver.py"), self.point, self.mode, str(log), "--", *cli]
        self.w("$ " + " ".join(cmd))
        proc = subprocess.Popen(cmd, cwd=self.project, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env)
        if self.mode == "hang":
            for _ in range(600):
                if ready.exists(): break
                time.sleep(0.1)
            else:
                proc.kill(); raise SystemExit("never reached crash point")
            os.kill(proc.pid, signal.SIGKILL)
            self.w(f"harness sent SIGKILL to pid {proc.pid}")
        out, err = proc.communicate(timeout=120)
        self.w(f"--- driver exit: {proc.returncode} (137 = os._exit; -9 = SIGKILL)")
        self.w("--- driver stdout\n" + out); self.w("--- driver stderr\n" + err)
        self.w("--- crashlog\n" + (log.read_text() if log.exists() else "(none)"))
        self.rcs["crash"] = {"rc": proc.returncode, "msg": (log.read_text().splitlines()[-1] if log.exists() else "")[:300]}
        # does a lock still hold? try flock
        import fcntl
        lock = self.project / ".copyroom-local/write.lock"
        if lock.exists():
            with lock.open("a+b") as s:
                try:
                    fcntl.flock(s.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB); self.w("write.lock: free after crash (OS dropped flock)")
                except OSError:
                    self.w("write.lock: STILL HELD")

    # ---------- writer ----------
    def second_writer(self):
        self.h("SECOND WRITER: edit README.md + new file, jj commit, then uncommitted wip file")
        readme = self.project / "README.md"
        readme.write_text(readme.read_text() + "\nwriter edit\n")
        (self.project / "writer-notes.txt").write_text("writer notes\n")
        self.jj(["commit", "-m", "writer: notes and readme"], key="writer-commit")
        (self.project / "writer-wip.txt").write_text("writer uncommitted wip\n")
        self.jj(["log", "-r", "all()", "--no-graph", "-T", LOG_T])

    def writer_check(self, label):
        self.h(f"WRITER-WORK CHECK ({label})")
        r = {}
        readme = self.project / "README.md"
        r["README has writer edit"] = readme.exists() and "writer edit" in readme.read_text()
        r["writer-notes.txt on disk"] = (self.project / "writer-notes.txt").exists()
        r["writer-wip.txt on disk (uncommitted)"] = (self.project / "writer-wip.txt").exists()
        q = self.jj(["log", "-r", 'description(substring:"writer:")', "--no-graph", "-T", "commit_id ++ \"\\n\""], quiet=True)
        r["writer commit visible in jj (all())"] = bool(q.stdout.strip())
        q = self.jj(["log", "-r", 'description(substring:"writer:") & ::@', "--no-graph", "-T", "commit_id ++ \"\\n\""], quiet=True)
        r["writer commit is ancestor of @"] = bool(q.stdout.strip())
        for k, v in r.items(): self.w(f"{k}: {v}")
        self.rcs[f"writer-check-{label}"] = r
        return r

    # ---------- capture ----------
    def capture(self, label):
        self.h(f"CAPTURE: {label}")
        P = self.project
        self.w("-- raw jj state (--ignore-working-copy: no snapshot)")
        self.jj(["--ignore-working-copy", "op", "log", "--no-graph", "-T", OPLOG_T])
        self.jj(["--ignore-working-copy", "log", "-r", "all()", "--no-graph", "-T", LOG_T])
        self.jj(["--ignore-working-copy", "log", "-r", "all()"])
        self.w("-- marker on disk")
        m = P / ".copyroom-local.json"
        self.w("sha256: " + sha(m)); self.w("bytes:\n" + m.read_text())
        self.w("(no .copyroom-label file exists in CopyRoom; MARKER = .copyroom-local.json)")
        for rev in ("@", "@-"):
            q = subprocess.run(["jj", "--ignore-working-copy", "file", "show", "-r", rev, ".copyroom-local.json"], cwd=P, capture_output=True, env=self.env)
            self.w(f"marker sha256 committed at {rev} (pre-snapshot, rc={q.returncode}): " + hashlib.sha256(q.stdout).hexdigest())
        self.w("-- file set: project (excl .jj .git)")
        self.w(listing(P))
        self.w("-- file set: run dir")
        self.w(listing(self.dir, skip=("project", "source", "overlay", "tmp")) )
        self.w("-- tmp dir (layer add tempdirs)")
        self.w(listing(self.dir / "tmp", maxdepth=3))
        self.w("-- preview dir listing")
        self.w(listing(P / ".copyroom-local/previews"))
        for f in sorted((P / ".copyroom-local/previews").glob("*.json")) + sorted(self.dir.glob("*.copyroom-preview.json")):
            self.w(f"-- state file {f} sha256 {sha(f)}"); self.w(f.read_text())
        self.w("-- jj workspace list / status")
        self.jj(["workspace", "list"], key=f"{label}:workspace-list")
        self.jj(["status"], key=f"{label}:jj-status")
        self.jj(["op", "log", "--no-graph", "-T", OPLOG_T])
        for sub in self.workspace_dirs():
            self.w(f"-- jj status inside secondary workspace dir {sub}")
            self.jj(["status"], cwd=sub, key=f"{label}:jj-status:{sub.name}")
        self.w("-- copyroom commands")
        for key, args in (("status", ["status"]), ("inspect", ["inspect"]), ("list-previews", ["preview", "list", "--project", str(P)]), ("doctor", ["doctor"]), ("layer-list", ["layer", "list"])):
            self.cli(args, key=f"{label}:{key}")

    def workspace_dirs(self):
        out = []
        if self.preview.is_dir(): out.append(self.preview)
        for d in sorted((self.dir / "tmp").glob("copyroom-layer-*/workspace")): out.append(d)
        return [d for d in out if d.is_dir()]

    # ---------- recovery ----------
    def recover(self):
        if self.kind == "A":
            self.h("RECOVERY 1: copyroom update --apply (retry)")
            self.cli(["update", "--apply", str(self.preview)], key="retry-apply")
            self.h("RECOVERY 2: copyroom discard --preview")
            self.cli(["discard", "--preview", str(self.preview)], key="discard")
            self.capture("after-recovery-1-2")
            self.h("RECOVERY 3: fresh copyroom update (new preview)")
            p = self.cli(["update", "--out", str(self.dir / "preview2")], key="fresh-update")
            if p.returncode == 0 and "no-change" not in p.stdout:
                self.h("RECOVERY 4: apply fresh preview")
                self.cli(["update", "--apply", str(self.dir / "preview2")], key="fresh-apply")
            self.capture("after-recovery-3-4")
        else:
            self.h("RECOVERY 1: copyroom layer add (retry, same args)")
            self.cli(["layer", "add", "--source", str(self.overlay), "--answers", str(self.overlay / "answers.json"), "--as", "docs"], key="retry-layer-add")
            self.h("RECOVERY 2: copyroom discard --preview <leftover temp workspace>")
            for d in self.workspace_dirs():
                self.cli(["discard", "--preview", str(d)], key="discard-tmp")
            self.h("RECOVERY 3: layer add with a different name")
            self.cli(["layer", "add", "--source", str(self.overlay), "--answers", str(self.overlay / "answers.json"), "--as", "docs2"], key="layer-add-other-name")
            self.capture("after-recovery")


def jjq(r, args, cwd=None):
    return subprocess.run(["jj", *args], cwd=cwd or r.project, text=True, capture_output=True, env=r.env).stdout


def manual(r):
    """Manual recovery experiments, run on the finished run dir."""
    r.h("MANUAL RECOVERY EXPERIMENT")
    P = r.project
    if r.name == "L1w":
        wid = jjq(r, ["--ignore-working-copy", "workspace", "list"]).splitlines()
        ws = [l.split(":")[0] for l in wid if l.startswith("copyroom-")][0]
        w = jjq(r, ["log", "-r", 'description(substring:"writer:")', "--no-graph", "-T", "commit_id"]).strip()
        parent = jjq(r, ["log", "-r", w + "-", "--no-graph", "-T", "commit_id"]).strip()
        ah = jjq(r, ["log", "-r", f"parents(parents({parent})) ~ subject(glob:'copyroom:render*')", "--no-graph", "-T", "commit_id"]).strip()
        r.w("writer commit " + w + "; merge head " + parent + "; active head to rebase onto: " + ah)
        r.jj(["rebase", "-s", w, "-d", ah], key="manual-rebase")
        r.jj(["abandon", f"{parent} | parents({parent})"], key="manual-abandon-merge")
        r.jj(["workspace", "forget", ws], key="manual-forget-ws")
        shutil.rmtree(r.dir / "tmp", ignore_errors=True); (r.dir / "tmp").mkdir()
        r.jj(["log", "-r", "all()"])
        r.jj(["status"])
        r.cli(["layer", "add", "--source", str(r.overlay), "--answers", str(r.overlay / "answers.json"), "--as", "docs"], key="manual-layer-add")
        r.cli(["layer", "list"], key="manual-layer-list")
        r.cli(["status"], key="manual-status")
        r.writer_check("after-manual")
        r.jj(["log", "-r", "all()"])
    elif r.name == "A5":
        for f in list((P / ".copyroom-local/previews").glob("*.json")) + list(r.dir.glob("*.copyroom-preview.json")):
            r.w("rm " + str(f)); f.unlink()
        r.cli(["preview", "list", "--project", str(P)], key="manual-list")
        r.cli(["status"], key="manual-status")
    elif r.name == "A6":
        for f in list(r.dir.glob("*.copyroom-preview.json")):
            r.w("rm " + str(f)); f.unlink()
        r.cli(["status"], key="manual-status")
    elif r.name in ("L2", "L3", "L4"):
        ws = [l.split(":")[0] for l in jjq(r, ["--ignore-working-copy", "workspace", "list"]).splitlines() if l.startswith("copyroom-")]
        for x in ws: r.jj(["workspace", "forget", x], key="manual-forget-ws")
        shutil.rmtree(r.dir / "tmp", ignore_errors=True); (r.dir / "tmp").mkdir()
        r.cli(["layer", "list"], key="manual-layer-list")
        r.jj(["workspace", "list"], key="manual-ws-list")


MANUAL = {"L1w", "A5", "A6", "L2", "L3", "L4"}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def sidecar(out):
    return out.with_name(out.name + ".copyroom-preview.json")


def listing(root, skip=(), maxdepth=8):
    root = Path(root)
    if not root.exists(): return f"(missing: {root})"
    lines = []
    for dp, dn, fn in os.walk(root):
        rel = Path(dp).relative_to(root)
        dn[:] = sorted(d for d in dn if d not in (".jj", ".git") and not (rel == Path(".") and d in skip) and len(rel.parts) < maxdepth)
        if rel.as_posix().endswith(".copyroom-local/sources"):
            for d in dn:
                n = sum(len(x[2]) for x in os.walk(Path(dp) / d))
                lines.append(f"{(rel / d).as_posix()[:60]}.../ ({n} files)")
            dn[:] = []
            continue
        for f in sorted(fn):
            p = Path(dp) / f
            if rel == Path(".") and f in skip: continue
            lines.append(f"{(rel / f).as_posix():60s} {p.stat().st_size:6d} {oct(p.stat().st_mode & 0o777)}")
        for d in dn:
            lines.append(f"{(rel / d).as_posix() + '/':60s}")
    return "\n".join(lines) if lines else "(empty)"


def main():
    names = sys.argv[1:] or list(RUNS)
    summary = {}
    for n in names:
        r = Run(n)
        try:
            r.setup(); r.crash()
            r.capture("post-crash")
            if r.writer:
                r.second_writer(); r.writer_check("before-recovery")
            r.recover()
            if r.writer: r.writer_check("after-recovery")
            if n in MANUAL: manual(r)
        except Exception as e:
            r.w(f"HARNESS ERROR: {e!r}"); r.rcs["harness-error"] = repr(e)
        summary[n] = r.rcs
        print("done", n, flush=True)
    out = EV / "summary.json"
    old = json.loads(out.read_text()) if out.exists() else {}
    old.update(summary)
    out.write_text(json.dumps(old, indent=1))


main()
