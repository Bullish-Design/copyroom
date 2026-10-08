from common import *
import signal

def scenario(stage, label):
    repo = mkrepo("crash-" + label)
    ev = Evidence(f"crash-{label}.txt")
    exp = cid(repo, "@"); p = cid(repo, 'description(exact:"prepared\n")')
    ev.w(f"== SIGKILL at stage {stage} ==")
    ops0 = opids(repo); sig0 = tree_sig(repo)
    ev.block("jj log BEFORE", log(repo)); 
    d = WORK / f"fifo-{label}"; d.mkdir()
    sig, wait = Fifo(d, "sig"), Fifo(d, "wait")
    th, box = sig.reader_thread()
    proc = subprocess.Popen(publish_cmd(repo, exp, p, "publish_if: crash-test"),
                            env=env({f"PJ_SIGNAL_{stage}": sig.path, f"PJ_WAIT_{stage}": wait.path}),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    th.join()
    ev.w("lock free while publish_if is parked at stage (should be False = held):", tryflock(str(repo/".jj/working_copy/working_copy.lock")))
    proc.send_signal(signal.SIGKILL); proc.wait()
    ev.w("publish_if exit status (negative = signal):", proc.returncode)
    time.sleep(0.05)
    ev.w("working_copy.lock free after SIGKILL:", tryflock(str(repo/".jj/working_copy/working_copy.lock")),
         "| op_heads lock free:", tryflock(str(repo/".jj/repo/op_heads/heads/lock")))
    ev.w("lock files left on disk after SIGKILL:", [str(p.relative_to(repo)) for p in (repo/".jj").rglob("*.lock")] + [str(p.relative_to(repo)) for p in (repo/".jj/repo/op_heads/heads").glob("lock")])
    ev.w("op heads dir (before any jj command):", op_heads(repo))
    ev.w("new ops visible:", [o for o in opids(repo) if o not in ops0])
    ev.w("sig diff of .jj vs before:", {k: v[:6] if isinstance(v, list) else v for k, v in sig_diff(sig0, tree_sig(repo)).items()})
    ev.w("files on disk:", sorted(x.name for x in repo.iterdir() if not x.name.startswith(".")))
    t0 = time.time()
    st = jj(repo, "status", check=False)
    ev.w(f"`jj status` rc={st.returncode} in {time.time()-t0:.2f}s")
    ev.block("jj status stdout", st.stdout); ev.block("jj status stderr", st.stderr)
    ev.block("jj op log (after status)", oplog(repo)); 
    ev.w("is_stale per pyjutsu:", run([PY, "-c", f"import pyjutsu;print(pyjutsu.Workspace.load({str(repo)!r}).is_stale())"]).stdout.strip())
    if st.returncode != 0 or "stale" in (st.stdout + st.stderr).lower():
        us = jj(repo, "workspace", "update-stale", check=False)
        ev.w(f"`jj workspace update-stale` rc={us.returncode}")
        ev.block("update-stale stdout", us.stdout); ev.block("update-stale stderr", us.stderr)
        st2 = jj(repo, "status", check=False)
        ev.block("jj status after update-stale", st2.stdout + st2.stderr)
        ev.block("jj op log after recovery", oplog(repo))
        ev.w("files on disk:", sorted(x.name for x in repo.iterdir() if not x.name.startswith(".")))
        ev.block("jj log after recovery", log(repo))
    # can a fresh publish_if succeed afterwards? (retry from scratch)
    ev.f.close()

scenario("LOCKED", "a-killed-holding-lock-before-publish")
scenario("BEFORE_PUBLISH", "a2-killed-after-op-written-before-cas")
scenario("AFTER_PUBLISH", "b-killed-between-publish-and-checkout")
scenario("AFTER_CHECKOUT", "c-killed-after-checkout-before-finish")
