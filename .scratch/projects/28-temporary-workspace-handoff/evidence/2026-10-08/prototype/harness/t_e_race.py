from common import *
import json, random, sys
jjbin = JJ43 if sys.argv[1] == "jj043" else JJ44
nocas = len(sys.argv) > 3 and sys.argv[3] == "nocas"
tag = sys.argv[1] + ("-NOCAS" if nocas else ""); N = int(sys.argv[2])
ev = Evidence(f"e-race-{tag}.txt")
results = []
deltas = [0, 3, -3, 6, -6, 10, -10, 15, -15, 20, -20, 30, -30, 45, -45, 60, -60, 90, -90, 130, -130, -170, -220, -300]
def busy(sec):
    t = time.perf_counter() + sec
    while time.perf_counter() < t: pass

def one(i):
    delta_ms = deltas[(i // 2) % len(deltas)]
    kind = "newcommit" if i % 2 == 0 else "new1"
    repo = mkrepo(f"race-{tag}-{i}", jjbin=jjbin)
    exp = cid(repo, "@", jjbin); p = cid(repo, 'description(exact:"prepared\n")', jjbin)
    d = WORK / f"fifos-{tag}-{i}"; d.mkdir()
    sigBL, goBL, goC = Fifo(d, "sigBL"), Fifo(d, "goBL"), Fifo(d, "goC")
    comp = subprocess.Popen([PY, str(Path(__file__).parent / "competitor.py"), jjbin, str(repo), goC.path, kind],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env())
    th, box = sigBL.reader_thread()
    pub = subprocess.Popen(publish_cmd(repo, exp, p, "publish_if: race"),
                           env=env({"PJ_SIGNAL_BEFORE_LOCK": sigBL.path, "PJ_WAIT_BEFORE_LOCK": goBL.path, **({"PJ_NO_CAS": "1"} if nocas else {})}),
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    th.join()                       # publish_if is now about to take the working-copy lock
    time.sleep(0.05)                # let the competitor finish python startup and block on its FIFO
    # release both at the barrier, offset by delta_ms (positive: publish first)
    if delta_ms >= 0:
        goBL.write(); busy(delta_ms / 1000); goC.write()
    else:
        goC.write(); busy(-delta_ms / 1000); goBL.write()
    pout, perr = pub.communicate(timeout=120); cout, cerr = comp.communicate(timeout=120)
    # ---- classify, read-only, BEFORE any reconcile
    heads_dir = op_heads(repo)
    ops = oplog(repo, 500, jjbin)
    ours = [l for l in ops.splitlines() if "publish_if: race" in l]
    lg = log(repo, jjbin)
    kids_of_P = jj(repo, "log", "-r", f"children({p}) ~ description(exact:\"prepared\\n\")", "--no-graph", "-T", 'commit_id.short(12) ++ " empty=" ++ empty ++ " desc=[" ++ description.first_line() ++ "] parents=" ++ parents.len() ++ "\\n"', jjbin=jjbin, observe=True).stdout
    comp_commits = jj(repo, "log", "-r", 'description(substring:"competitor")', "--no-graph", "-T", 'commit_id.short(12) ++ "\\n"', jjbin=jjbin, observe=True).stdout.split()
    comp_after_ours = None
    ours_commit = jj(repo, "log", "-r", f"children({p}) & empty() & description(exact:\"\")", "--no-graph", "-T", 'commit_id.short(12) ++ "\\n"', jjbin=jjbin, observe=True).stdout.split()
    if ours_commit and comp_commits:
        comp_after_ours = bool(jj(repo, "log", "-r", f"{ours_commit[0]}:: & description(substring:\"competitor\")", "--no-graph", "-T", "commit_id", jjbin=jjbin, observe=True).stdout.strip())
    comp_work_intact = True
    if kind == "newcommit":
        cw = jj(repo, "log", "-r", 'description(substring:"competitor work")', "--no-graph", "-T", "commit_id", jjbin=jjbin, observe=True).stdout.strip()
        comp_work_intact = bool(cw) and jj(repo, "file", "show", "-r", cw, "comp.txt", jjbin=jjbin, observe=True).stdout == "competitor bytes\n" \
                           and (repo / "comp.txt").read_text() == "competitor bytes\n"
    else:
        comp_work_intact = bool(comp_commits)
    # a normal (snapshotting) jj command afterwards: is the WC consistent?
    st = jj(repo, "status", jjbin=jjbin, check=False)
    stale = "stale" in (st.stdout + st.stderr).lower()
    reasons = pout.strip()
    rec = dict(i=i, kind=kind, delta_ms=delta_ms, pub_rc=pub.returncode, pub_out=pout.strip()[:200], pub_err=perr.strip()[:200],
               comp_out=cout.strip()[:120], comp_err=cerr.strip()[:200], heads=heads_dir, ours_ops=len(ours),
               ours_commit=ours_commit, comp_after_ours=comp_after_ours, comp_intact=comp_work_intact, kids_of_P=kids_of_P.strip(), stale=stale)
    p_on_disk = (repo / "p.txt").exists()
    rec["p_on_disk"] = p_on_disk
    ok_common = len(heads_dir) == 1 and not stale and comp_work_intact
    if pub.returncode == 0 and len(ours) == 1 and ours_commit and comp_after_ours and ok_common and p_on_disk:
        rec["outcome"] = "A_published_then_competitor_after"
    elif pub.returncode == 1 and len(ours) == 0 and not ours_commit and ok_common and not p_on_disk:
        rec["outcome"] = "B_rejected_nothing_published"
    else:
        rec["outcome"] = "C_THIRD_OUTCOME"
        rec["log"] = lg; rec["oplog"] = ops; rec["status"] = (st.stdout + st.stderr)[:400]
    ev.w(json.dumps({k: v for k, v in rec.items() if k not in ("log", "oplog")}))
    if rec["outcome"].startswith("C"):
        ev.block(f"run {i} log", lg); ev.block(f"run {i} oplog", ops); ev.block(f"run {i} status", rec["status"])
    return rec

for i in range(N):
    results.append(one(i))
from collections import Counter
c = Counter(r["outcome"] for r in results)
ev.w("SUMMARY", tag, dict(c))
by_kind = Counter((r["kind"], r["outcome"]) for r in results)
ev.w("BY KIND", {f"{k[0]}:{k[1]}": v for k, v in by_kind.items()})
ev.w("pub reject reasons:", dict(Counter(r["pub_out"].split("reason=")[-1] for r in results if r["pub_rc"] == 1)))
json.dump(results, open(EVID / f"e-race-{tag}.json", "w"), indent=1)
