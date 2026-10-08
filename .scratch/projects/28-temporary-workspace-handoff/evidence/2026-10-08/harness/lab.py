"""Race lab for CopyRoom `update --apply`. Run inside the CopyRoom devenv."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from copyroom.local.workflow import working_digest

ROOT = Path(__file__).resolve().parent
RUNS = ROOT / "runs"
EVID = ROOT / "evidence"
SRC_T = ROOT / "src-template"
DRIVER = ROOT / "barrier_driver.py"
JJ_BIN = shutil.which("jj")
COPYROOM = shutil.which("copyroom")
PY = sys.executable
PREVIEW_SUFFIX = ".copyroom-preview.json"


def sh(argv, cwd, env=None, timeout=120):
    p = subprocess.run([str(a) for a in argv], cwd=cwd, text=True, capture_output=True,
                       env=env, timeout=timeout)
    return {"argv": [str(a) for a in argv], "cwd": str(cwd), "rc": p.returncode,
            "out": p.stdout, "err": p.stderr}


def jjq(project, *args, at_op=None):
    argv = [JJ_BIN, "--ignore-working-copy"]
    if at_op:
        argv.append(f"--at-operation={at_op}")
    argv += list(args)
    p = subprocess.run(argv, cwd=project, text=True, capture_output=True)
    if p.returncode:
        return f"<<rc={p.returncode} {p.stderr.strip()}>>"
    return p.stdout


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def lines(s):
    return [l for l in s.splitlines() if l.strip()]


def op_ids(project):
    return [l.split()[0] for l in lines(jjq(project, "op", "log", "--no-graph", "-T", 'id ++ " " ++ description ++ "\\n"'))]


def capture(project: Path, out: Path, label: str, cdir: Path, preview_state=None) -> dict:
    """Capture all required state. Uses --ignore-working-copy: capture never snapshots."""
    d = {}
    d["op_log"] = jjq(project, "op", "log", "--no-graph", "-T", 'id ++ " " ++ description ++ "\\n"')
    d["log_all"] = jjq(project, "log", "-r", "all()", "--no-graph", "-T",
                       'commit_id ++ " " ++ description.first_line() ++ " | parents=" ++ parents.map(|p| p.commit_id().short(8)).join(",") ++ "\\n"')
    d["heads_all"] = jjq(project, "log", "-r", "heads(all())", "--no-graph", "-T", 'commit_id ++ " " ++ description.first_line() ++ "\\n"')
    d["at"] = jjq(project, "log", "-r", "@", "--no-graph", "-T", "commit_id").strip()
    d["at_parents"] = jjq(project, "log", "-r", "@-", "--no-graph", "-T", 'commit_id ++ " " ++ description.first_line() ++ "\\n"')
    d["workspace_list"] = jjq(project, "workspace", "list")
    d["bookmarks"] = jjq(project, "bookmark", "list")
    try:
        d["tree_digest"] = working_digest(project)
    except Exception as exc:  # pragma: no cover
        d["tree_digest"] = f"<<{exc!r}>>"
    mp = project / ".copyroom-local.json"
    mb = mp.read_bytes() if mp.exists() else b""
    d["marker_sha256"] = sha(mb)
    d["marker_literal"] = mb.decode()
    d["marker_revision"] = json.loads(mb).get("revision") if mb else None
    sidecar = out.with_name(out.name + PREVIEW_SUFFIX)
    d["preview_dir_exists"] = out.exists()
    d["sidecar_exists"] = sidecar.exists()
    d["preview_sidecar"] = json.loads(sidecar.read_text()) if sidecar.exists() else (preview_state or None)
    files = {}
    for p in sorted(project.rglob("*")):
        rel = p.relative_to(project)
        if rel.parts[0] in (".jj", ".git") or p.is_dir():
            continue
        b = p.read_bytes() if not p.is_symlink() else b""
        if rel.parts[0] == ".copyroom-local":
            files[str(rel)] = {"sha256": sha(b)[:12]}
        else:
            files[str(rel)] = {"sha256": sha(b)[:12], "content": b.decode(errors="replace") if len(b) < 4000 else "<big>"}
    d["files"] = files
    pid = json.loads(mb).get("project_id") if mb else None
    if pid:
        d["render_head"] = lines(jjq(project, "log", "-r", f'heads(::@ & subject(glob:"copyroom:render {pid} base *"))', "--no-graph", "-T", 'commit_id ++ "\\n"'))
    cdir.mkdir(parents=True, exist_ok=True)
    txt = [f"== {label} =="]
    for k, v in d.items():
        if k in ("files", "preview_sidecar"):
            txt.append(f"-- {k}\n{json.dumps(v, indent=2, sort_keys=True)}")
        else:
            txt.append(f"-- {k}\n{v}")
    (cdir / f"{label}.txt").write_text("\n".join(txt))
    return d


# ---------------------------------------------------------------- writers
def run_writer(kind: str, project: Path, token: str, ops_before: list[str]) -> dict:
    W = {"kind": kind, "token": token, "procs": [], "bookmarks": [], "path": None}

    def go(argv, **kw):
        p = subprocess.Popen([str(a) for a in argv], cwd=project, text=True,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kw)
        o, e = p.communicate(timeout=60)
        W["procs"].append({"argv": [str(a) for a in argv], "pid": p.pid, "rc": p.returncode, "out": o, "err": e})
        return p.returncode

    if kind == "a":
        W["path"] = "foreign.txt"
        go([JJ_BIN, "new", "-m", "foreign"])
        go(["sh", "-c", f"printf '%s\\n' {token} > foreign.txt"])
        go([JJ_BIN, "commit", "-m", f"foreign-work {token}"])
    elif kind == "b":
        W["path"] = "foreign-b.txt"
        go(["sh", "-c", f"printf '%s\\n' {token} > foreign-b.txt"])
    elif kind == "c":
        W["bookmarks"] = ["foreign"]
        go([JJ_BIN, "bookmark", "set", "foreign", "-r", "@"])
    elif kind in ("d1", "d1x"):
        old = ops_before[1]  # parent of the current head operation
        W["forked_at"] = old
        go([JJ_BIN, f"--at-operation={old}", "new", "-m", f"forked-{token}"])
    elif kind == "d2":
        names = [f"w1-{token}", f"w2-{token}"]
        W["bookmarks"] = names
        gate = project.parent / "d2-gate"
        procs = []
        for n in names:
            procs.append(subprocess.Popen(
                ["sh", "-c", f'while [ ! -e "{gate}" ]; do :; done; exec "{JJ_BIN}" bookmark set "{n}" -r @'],
                cwd=project, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE))
        time.sleep(0.2)
        gate.write_text("go")
        for p, n in zip(procs, names):
            o, e = p.communicate(timeout=60)
            W["procs"].append({"argv": ["jj", "bookmark", "set", n, "-r", "@"], "pid": p.pid, "rc": p.returncode, "out": o, "err": e})
    elif kind == "e_owned":
        W["path"] = "config/project.yml"
        go([PY, "-c", f"open('config/project.yml','a').write('# {token}\\n')"])
    elif kind == "e_unowned":
        W["path"] = "notes.txt"
        go([PY, "-c", f"open('notes.txt','a').write('{token}\\n')"])
    else:
        raise ValueError(kind)
    return W


def locate(project: Path, token: str, bookmarks=()) -> dict:
    """Find the writer token in commits (visible now, or only in older operations), the working copy, bookmarks."""
    vis_all = lines(jjq(project, "log", "-r", "all()", "--no-graph", "-T", 'commit_id ++ " " ++ change_id ++ "\\n"'))
    visible = {l.split()[0]: l.split()[1] for l in vis_all}
    seen_at = {c: None for c in visible}   # commit -> op where it is visible (None = now)
    change_of = dict(visible)
    for op in op_ids(project):
        for l in lines(jjq(project, "log", "-r", "all()", "--no-graph", "-T", 'commit_id ++ " " ++ change_id ++ "\\n"', at_op=op)):
            c, ch = l.split()
            change_of[c] = ch
            seen_at.setdefault(c, op)
    def has_token(c):
        d = jjq(project, "diff", "-r", c, "--git", at_op=seen_at[c])
        m = jjq(project, "log", "-r", c, "--no-graph", "-T", "description", at_op=seen_at[c])
        return token in d or token in m
    carrying = {c for c in change_of if c != "0" * 40 and has_token(c)}
    heads = set(lines(jjq(project, "log", "-r", "heads(all())", "--no-graph", "-T", 'commit_id ++ "\\n"')))
    anc = set(lines(jjq(project, "log", "-r", "::@", "--no-graph", "-T", 'commit_id ++ "\\n"')))
    at = jjq(project, "log", "-r", "@", "--no-graph", "-T", "commit_id").strip()
    hits = []
    vis_hit_changes = set()
    for c in sorted(carrying & set(visible)):
        vis_hit_changes.add(change_of[c])
        desc_heads = lines(jjq(project, "log", "-r", f"heads(all()) & ({c}::)", "--no-graph", "-T", 'commit_id ++ "\\n"'))
        hits.append({"commit": c, "change": change_of[c], "is_head": c in heads, "ancestor_of_at": c in anc, "is_at": c == at,
                     "reachable_from_heads": desc_heads,
                     "desc": jjq(project, "log", "-r", c, "--no-graph", "-T", "description.first_line()").strip()})
    hidden = carrying - set(visible)
    op_only = sorted(c for c in hidden if change_of[c] not in vis_hit_changes)
    old_versions = sorted(c for c in hidden if change_of[c] in vis_hit_changes)
    on_disk = []
    for p in project.rglob("*"):
        rel = p.relative_to(project)
        if rel.parts[0] in (".jj", ".git", ".copyroom-local") or p.is_dir():
            continue
        if token.encode() in p.read_bytes():
            on_disk.append(str(rel))
    bm = jjq(project, "bookmark", "list")
    bm_found = {b: (b in bm) for b in bookmarks}
    return {"in_working_copy_files": on_disk, "visible_commits": hits, "only_in_op_log_commits": op_only,
            "older_versions_of_visible_changes": old_versions, "bookmarks": bm_found}


def classify(loc: dict) -> str:
    parts = []
    if loc["in_working_copy_files"]:
        parts.append("working copy " + ",".join(loc["in_working_copy_files"]))
    for h in loc["visible_commits"]:
        kind = "@ itself" if h["is_at"] else ("ancestor of @" if h["ancestor_of_at"] else ("side head" if h["is_head"] else "NOT an ancestor of @; non-head, reachable only below head(s) " + ",".join(x[:8] for x in h["reachable_from_heads"])))
        parts.append(f"commit {h['commit'][:8]} ({kind})")
    if loc["only_in_op_log_commits"]:
        parts.append("ONLY op log: " + ",".join(c[:8] for c in loc["only_in_op_log_commits"]))
    for b, ok in loc["bookmarks"].items():
        parts.append(f"bookmark {b} {'present' if ok else 'ABSENT'}")
    return "; ".join(parts) or "NOWHERE"


# ---------------------------------------------------------------- barrier driver
def wait_ready(fifo, child, timeout=90):
    res = {}

    def reader():
        with open(fifo) as f:
            res["data"] = f.read()

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    t0 = time.time()
    while t.is_alive():
        t.join(0.1)
        if child.poll() is not None and t.is_alive():
            with open(fifo, "w"):
                pass
            t.join(2)
            return False
        if time.time() - t0 > timeout:
            raise RuntimeError("barrier timeout")
    return "data" in res and res["data"].startswith("ready")


def launch(cdir: Path, project: Path, argv, barrier, tag):
    ready, release = cdir / f"{tag}.ready.fifo", cdir / f"{tag}.release.fifo"
    for f in (ready, release):
        if f.exists():
            f.unlink()
        os.mkfifo(f)
    spec = {"argv": [str(a) for a in argv], "trace": str(cdir / f"{tag}.trace.jsonl"),
            "hit": str(cdir / f"{tag}.hit.json"),
            "barrier": None if barrier is None else {**barrier, "ready": str(ready), "release": str(release)}}
    env = dict(os.environ, LAB_SPEC=json.dumps(spec))
    child = subprocess.Popen([PY, str(DRIVER)], cwd=project, env=env, text=True,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (cdir / f"{tag}.launch.txt").write_text(
        f"launch: {PY} {DRIVER}  (cwd={project})\nequivalent CLI call: copyroom {' '.join(map(str, argv))}\n"
        f"patched: copyroom.local.jj.JJ.run (class attribute) before copyroom.cli.main(argv)\n"
        f"spec: {json.dumps(spec, indent=2)}\ndriver pid: {child.pid}\n")
    return child, ready, release, spec


def release_and_finish(child, release):
    with open(release, "w") as f:
        f.write("go\n")
    out, err = child.communicate(timeout=120)
    return child.returncode, out, err


# ---------------------------------------------------------------- case
def setup(cid: str):
    cdir = EVID / cid
    cdir.mkdir(parents=True, exist_ok=True)
    wdir = RUNS / cid
    wdir.mkdir(parents=True, exist_ok=True)
    src, project, out = wdir / "source", wdir / "project", wdir / "preview"
    shutil.copytree(SRC_T, src)
    r = sh([COPYROOM, "new", src, project, "--answers", src / "answers.json"], wdir)
    assert r["rc"] == 0, r
    (project / "notes.txt").write_text("user notes\n")
    r = sh([JJ_BIN, "commit", "-m", "user-notes"], project)
    assert r["rc"] == 0, r
    st = src / "templates/settings/template.j2"
    st.write_text(st.read_text() + 'revision: "race-v2"\n')
    return cdir, wdir, src, project, out


def make_preview(project, out):
    r = sh([COPYROOM, "update", "--out", out], project)
    assert r["rc"] == 0, r
    return json.loads(r["out"])


def analyse(cid, timing, wkind, project, out, B0, B2, B3, writer, rc, so, se, state):
    ops2, ops3 = op_ids_from(B2["op_log"]), op_ids_from(B3["op_log"])
    new_ops = [l for l in lines(B3["op_log"]) if l.split()[0] not in set(ops2)]
    descs = [l.split(" ", 1)[1] if " " in l else "" for l in new_ops]
    moved = any(d.startswith("new empty commit") for d in descs)
    restore = any("restore" in d for d in descs)
    token = writer["token"] if writer else ""
    loc = locate(project, token, writer["bookmarks"] if writer else ()) if writer else None
    pj = state or {}
    return {
        "case": cid, "timing": timing, "writer": wkind, "exit_code": rc,
        "Q1_success": rc == 0, "stdout": so.strip()[:300], "stderr": se.strip()[:700],
        "Q2_at_moved_before_rejection": moved, "new_ops_after_release": descs,
        "op_restore_ran": restore,
        "at_before_release": B2["at"], "at_after": B3["at"],
        "tree_equals_preview_tree": B3["tree_digest"] == pj.get("preview_tree"),
        "tree_equals_old_active_tree": B3["tree_digest"] == pj.get("active_tree"),
        "marker_unchanged_vs_B0": B3["marker_sha256"] == B0["marker_sha256"],
        "marker_revision_before_after": [B0["marker_revision"], B3["marker_revision"]],
        "render_head_after": B3.get("render_head"), "old_render": pj.get("old_render"), "next_render": pj.get("next_render"),
        "preview_dir_exists_after": B3["preview_dir_exists"], "sidecar_exists_after": B3["sidecar_exists"],
        "Q3_writer_work": classify(loc) if loc else "n/a", "Q3_detail": loc,
        "files_after": sorted(B3["files"]),
    }


def op_ids_from(text):
    return [l.split()[0] for l in lines(text)]


def run_barrier_case(cid, timing, wkind):
    cdir, wdir, src, project, out = setup(cid)
    state = make_preview(project, out)
    B0 = capture(project, out, "B0_after_preview", cdir, state)
    if timing == "T4":   # before `jj new` subprocess launch
        barrier = {"cwd": str(project), "prefix": ["new"], "contains": ["copyroom:update"], "nth": 1, "when": "before"}
    elif timing == "T5":  # after `jj new` returns, before _check_operation_parent
        barrier = {"cwd": str(project), "prefix": ["new"], "contains": ["copyroom:update"], "nth": 1, "when": "after"}
    elif timing == "T5x":  # after jj.conflicts() (resolve --list) returned, before the tree comparison raises/continues
        barrier = {"cwd": str(project), "prefix": ["resolve", "--list"], "contains": [], "nth": 1, "when": "after"}
    elif timing == "T5y":  # after the post-new `jj log -r @` (3rd project-cwd `log -r @` call), before _check_operation_parent's op read
        barrier = {"cwd": str(project), "prefix": ["log", "--no-graph", "-r", "@"], "contains": [], "nth": 3, "when": "after"}
    elif timing == "T6":  # before _discard's workspace forget (project cwd)
        barrier = {"cwd": str(project), "prefix": ["workspace", "forget"], "contains": [], "nth": 1, "when": "before"}
    else:
        raise ValueError(timing)
    child, ready, release, spec = launch(cdir, project, ["update", "--apply", out], barrier, "apply")
    ok = wait_ready(ready, child)
    if not ok:
        o, e = child.communicate()
        (cdir / "apply.stdout").write_text(o); (cdir / "apply.stderr").write_text(e)
        return {"case": cid, "error": "barrier not reached", "rc": child.returncode, "stderr": e[-800:]}
    hit = json.loads((cdir / "apply.hit.json").read_text())
    B1 = capture(project, out, "B1_at_barrier", cdir, state)
    ops_before = op_ids_from(B1["op_log"])
    writer = run_writer(wkind, project, f"FOREIGN{cid.replace('-', '')}", ops_before)
    (cdir / "writer.json").write_text(json.dumps(writer, indent=2))
    if wkind == "d1x":
        # Do NOT load the repo here: any jj command (even --ignore-working-copy) would reconcile the forked op heads itself.
        heads_dir = project / ".jj/repo/op_heads/heads"
        (cdir / "B2_op_heads_listing.txt").write_text("\n".join(sorted(os.listdir(heads_dir))) + "\n")
        B2 = B1
    else:
        B2 = capture(project, out, "B2_after_writer_before_release", cdir, state)
    rc, so, se = release_and_finish(child, release)
    (cdir / "apply.stdout").write_text(so); (cdir / "apply.stderr").write_text(se); (cdir / "apply.exit").write_text(str(rc))
    B3 = capture(project, out, "B3_after", cdir, state)
    res = analyse(cid, timing, wkind, project, out, B0, B2, B3, writer, rc, so, se, state)
    res["barrier_hit"] = hit
    res["writer_pids"] = [p["pid"] for p in writer["procs"]]
    res["writer_rc"] = [p["rc"] for p in writer["procs"]]
    res["writer_err"] = [p["err"].strip()[:200] for p in writer["procs"] if p["err"].strip()]
    (cdir / "summary.json").write_text(json.dumps(res, indent=2))
    return res


def run_t1(cid, wkind):
    cdir, wdir, src, project, out = setup(cid)
    ops = op_ids_from(jjq(project, "op", "log", "--no-graph", "-T", 'id ++ " " ++ description ++ "\\n"'))
    capture(project, out, "B_before_writer", cdir)
    writer = run_writer(wkind, project, f"FOREIGN{cid.replace('-', '')}", ops)
    B0 = capture(project, out, "B0_after_writer_before_update", cdir)
    r = sh([COPYROOM, "update", "--out", out], project)
    (cdir / "update.txt").write_text(json.dumps(r, indent=2))
    state = json.loads(r["out"]) if r["rc"] == 0 else None
    B1 = capture(project, out, "B1_after_update", cdir, state)
    a = sh([COPYROOM, "update", "--apply", out], project) if r["rc"] == 0 else None
    B3 = capture(project, out, "B3_after_apply", cdir, state)
    res = analyse(cid, "T1", wkind, project, out, B1, B1, B3, writer, a["rc"] if a else r["rc"],
                  a["out"] if a else r["out"], a["err"] if a else r["err"], state)
    res["update_rc"] = r["rc"]; res["update_err"] = r["err"].strip()[:300]
    res["preview_head_parent_contains_writer"] = None
    if state:
        res["preview_state_active_head_is_writer_head"] = state["active_head"] == B0["at"]
    (cdir / "summary.json").write_text(json.dumps(res, indent=2))
    return res


def run_t2(cid, wkind):
    cdir, wdir, src, project, out = setup(cid)
    B0 = capture(project, out, "B0_before_update", cdir)
    barrier = {"cwd": str(out), "prefix": ["new"], "contains": ["copyroom:preview"], "nth": 1, "when": "before"}
    child, ready, release, spec = launch(cdir, project, ["update", "--out", out], barrier, "update")
    if not wait_ready(ready, child):
        o, e = child.communicate()
        return {"case": cid, "error": "barrier not reached", "stderr": e[-800:]}
    hit = json.loads((cdir / "update.hit.json").read_text())
    capture(project, out, "B1_at_barrier", cdir)
    ops = op_ids_from(jjq(project, "op", "log", "--no-graph", "-T", 'id ++ " " ++ description ++ "\\n"'))
    writer = run_writer(wkind, project, f"FOREIGN{cid.replace('-', '')}", ops)
    B2 = capture(project, out, "B2_after_writer_before_release", cdir)
    rc, so, se = release_and_finish(child, release)
    (cdir / "update.stdout").write_text(so); (cdir / "update.stderr").write_text(se); (cdir / "update.exit").write_text(str(rc))
    B3 = capture(project, out, "B3_after", cdir)
    res = analyse(cid, "T2", wkind, project, out, B0, B2, B3, writer, rc, so, se, None)
    res["barrier_hit"] = hit
    # retry preview afterwards to see whether recovery is clean
    r2 = sh([COPYROOM, "update", "--out", out.with_name("preview2")], project)
    res["retry_preview_rc"] = r2["rc"]; res["retry_preview_err"] = r2["err"].strip()[:300]
    (cdir / "summary.json").write_text(json.dumps(res, indent=2))
    return res


def run_t3(cid, wkind):
    cdir, wdir, src, project, out = setup(cid)
    state = make_preview(project, out)
    B0 = capture(project, out, "B0_after_preview", cdir, state)
    ops = op_ids_from(B0["op_log"])
    writer = run_writer(wkind, project, f"FOREIGN{cid.replace('-', '')}", ops)
    B2 = capture(project, out, "B2_after_writer_before_apply", cdir, state)
    a = sh([COPYROOM, "update", "--apply", out], project)
    (cdir / "apply.stdout").write_text(a["out"]); (cdir / "apply.stderr").write_text(a["err"]); (cdir / "apply.exit").write_text(str(a["rc"]))
    B3 = capture(project, out, "B3_after", cdir, state)
    res = analyse(cid, "T3", wkind, project, out, B0, B2, B3, writer, a["rc"], a["out"], a["err"], state)
    (cdir / "summary.json").write_text(json.dumps(res, indent=2))
    return res


def main():
    suite = sys.argv[1]
    reps = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    results = []
    plan = []
    if suite == "t1":
        plan = [(f"T1-{k}-r1", run_t1, k) for k in ("a", "b")]
    elif suite == "t2":
        plan = [(f"T2-{k}-r1", run_t2, k) for k in ("a", "b")]
    elif suite == "t3":
        plan = [(f"T3-{k}-r1", run_t3, k) for k in ("a", "b", "c")]
    elif suite[:2] in ("T4","T5","T6"):
        timing = suite.split(":")[0]
        kinds = suite.split(":")[1].split(",")
        for k in kinds:
            for r in range(1, reps + 1):
                plan.append((f"{timing}-{k}-r{r}", lambda c, k_, t=timing: run_barrier_case(c, t, k_), k))
    for cid, fn, k in plan:
        t0 = time.time()
        try:
            res = fn(cid, k)
        except Exception as exc:
            import traceback
            res = {"case": cid, "harness_error": traceback.format_exc()[-1500:]}
        res["seconds"] = round(time.time() - t0, 1)
        print(json.dumps({k_: v for k_, v in res.items() if k_ not in ("Q3_detail", "files_after")}, sort_keys=True), flush=True)
        results.append(res)


if __name__ == "__main__":
    main()
