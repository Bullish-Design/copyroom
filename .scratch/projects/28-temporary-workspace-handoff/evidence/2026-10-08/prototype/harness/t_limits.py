from common import *
import signal, sys

def parked_run(repo, stage, exp, p, extra_env=None, msg="publish_if: limits"):
    d = Path(tempfile.mkdtemp(dir=WORK)); sig, wait = Fifo(d, "sig"), Fifo(d, "wait")
    th, box = sig.reader_thread()
    proc = subprocess.Popen(publish_cmd(repo, exp, p, msg),
                            env=env({f"PJ_SIGNAL_{stage}": sig.path, f"PJ_WAIT_{stage}": wait.path, **(extra_env or {})}),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    th.join()
    return proc, wait

def summarize(repo, ev, ops0):
    ev.w("op heads dir right after (before any reload):", op_heads(repo))
    ev.block("jj log", log(repo))
    ev.block("jj op log (first 8)", "\n".join(oplog(repo, 8).splitlines()))
    st = jj(repo, "status", check=False)
    ev.block("jj status", st.stdout + st.stderr)
    ev.w("op heads after a normal jj command:", op_heads(repo))

# ---------- g1: lock-free writer publishes while publish_if is parked between write and CAS
for cas in (True, False):
    tag = "with-cas" if cas else "NO-cas"
    repo = mkrepo(f"g1-{tag}")
    ev = Evidence(f"g1-lockfree-writer-before-publish-{tag}.txt")
    exp = cid(repo, "@"); p = cid(repo, 'description(exact:"prepared\n")'); ops0 = opids(repo)
    proc, wait = parked_run(repo, "BEFORE_PUBLISH", exp, p, {} if cas else {"PJ_NO_CAS": "1"})
    t0 = time.time()
    w = jj(repo, "--ignore-working-copy", "describe", "-r", p, "-m", "lock-free writer edited P", check=False)
    ev.w(f"lock-free writer (`jj --ignore-working-copy describe`) rc={w.returncode} in {time.time()-t0:.2f}s while publish_if holds the WC lock")
    wait.write(); out, err = proc.communicate()
    ev.w("publish_if rc", proc.returncode, "out", out.strip()[:140], "err", err.strip())
    summarize(repo, ev, ops0)
    ev.w("our op in log:", [l for l in oplog(repo, 20).splitlines() if "limits" in l])

# ---------- g2: a lock-free writer that loaded BEFORE our publish publishes AFTER it
for variant in ("describe-other-commit", "moves-@"):
    repo = mkrepo(f"g2-{variant}")
    ev = Evidence(f"g2-stale-base-writer-after-publish-{variant}.txt")
    exp = cid(repo, "@"); p = cid(repo, 'description(exact:"prepared\n")'); base_op = opids(repo)[0]
    r = run(publish_cmd(repo, exp, p, "publish_if: g2"), check=False)
    ev.w("publish_if rc", r.returncode, "heads now", op_heads(repo))
    if variant == "describe-other-commit":
        w = jj(repo, "--ignore-working-copy", "--at-op", base_op, "describe", "-r", p, "-m", "stale-base writer edited P", check=False)
    else:
        w = jj(repo, "--ignore-working-copy", "--at-op", base_op, "new", "-m", "stale-base writer new", check=False)
    ev.w("stale-base lock-free writer rc", w.returncode, w.stderr.strip()[:200])
    ev.w("op heads dir after both:", op_heads(repo))
    summarize(repo, ev, None)
    ev.w("files on disk:", sorted(x.name for x in repo.iterdir() if not x.name.startswith(".")))

# ---------- h: direct file writes while publish_if holds the WC lock, after publish, before checkout
variants = {
 "h1-new-untracked-file": (False, "open('w_new.txt','w').write('writer bytes\\n')"),
 "h2-edit-file-checkout-does-not-touch": (False, "open('a.txt','w').write('WRITER EDIT of a.txt\\n')"),
 "h3-create-file-checkout-will-add": (False, "open('p.txt','w').write('WRITER p.txt\\n')"),
 "h4-edit-file-checkout-rewrites": (True, "open('a.txt','w').write('WRITER EDIT of a.txt\\n')"),
}
for name, (p_edit_a, code) in variants.items():
    repo = mkrepo(name, p_edit_a=p_edit_a)
    ev = Evidence(f"{name}.txt")
    exp = cid(repo, "@"); p = cid(repo, 'description(exact:"prepared\n")')
    proc, wait = parked_run(repo, "AFTER_PUBLISH", exp, p)
    ev.w("publish_if parked after publish, before checkout, WC lock held. Writer runs:", code)
    run([PY, "-c", code], cwd=repo)
    wait.write(); out, err = proc.communicate()
    ev.w("publish_if rc", proc.returncode, "out", out.strip()[:20], "err", err.strip()[:300])
    ev.w("files on disk:", {x.name: x.read_text() for x in repo.iterdir() if x.is_file()})
    st = jj(repo, "status", check=False)
    ev.block("jj status after (first normal command snapshots any surviving write)", st.stdout + st.stderr)
    ev.block("jj op log (first 4)", "\n".join(oplog(repo, 4).splitlines()))
    ev.block("jj log", log(repo))
    for fn in ("a.txt", "p.txt", "w_new.txt"):
        r = jj(repo, "file", "show", "-r", "@", fn, observe=True, check=False)
        ev.w(f"@ contains {fn}:", repr(r.stdout) if r.returncode == 0 else "no")
    if proc.returncode != 0:
        ev.w("is_stale:", run([PY, "-c", f"import pyjutsu;print(pyjutsu.Workspace.load({str(repo)!r}).is_stale())"]).stdout.strip())
