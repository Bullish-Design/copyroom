from common import *
import collections
ev = Evidence("h5-writer-during-checkout-many-files.txt")
res = collections.Counter()
writer_code = r'''
import sys, os, time
fifo, = sys.argv[1:2]
n = 0
open(fifo, "rb").read(1)           # barrier: released when publish_if reaches AFTER_PUBLISH (lock held, checkout about to start)
stop = sys.argv[2]
while not os.path.exists(stop):
    n += 1
    with open("a.txt", "w") as f: f.write("WRITER %d\n" % n)
    with open("w_new.txt", "w") as f: f.write("WRITER NEW %d\n" % n)
print(n)
'''
for i in range(14):
    repo = mkrepo(f"h5-{i}", nfiles=25000, p_edit_a=True)
    exp = cid(repo, "@"); p = cid(repo, 'description(exact:"prepared\n")')
    d = Path(tempfile.mkdtemp(dir=WORK)); sig, wait, go = Fifo(d, "sig"), Fifo(d, "wait"), Fifo(d, "go"); stop = d / "stop"
    th, box = sig.reader_thread()
    pub = subprocess.Popen(publish_cmd(repo, exp, p, "publish_if: h5"),
                           env=env({"PJ_SIGNAL_AFTER_PUBLISH": sig.path, "PJ_WAIT_AFTER_PUBLISH": wait.path}),
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    wr = subprocess.Popen([PY, "-c", writer_code, go.path, str(stop)], cwd=repo, stdout=subprocess.PIPE, text=True)
    th.join()
    t0 = time.time()
    go.write(); wait.write()          # release the writer and publish_if (checkout) together
    out, err = pub.communicate(); t1 = time.time(); stop.write_text("x")
    n = wr.communicate()[0].strip()
    a = (repo / "a.txt").read_text(); w = (repo / "w_new.txt").read_text() if (repo / "w_new.txt").exists() else None
    st = jj(repo, "status", check=False)
    clean = "no changes" in st.stdout
    a_in_commit = jj(repo, "file", "show", "-r", "@", "a.txt", observe=True).stdout
    lines = [l for l in st.stdout.splitlines() if l.startswith(("M ", "A ", "D "))]
    intact = len(list((repo / "bulk").rglob("*.txt"))) == 25000
    key = ("pub_rc=%d" % pub.returncode, "a.txt=" + ("P-version" if a == "a edited in P\n" else "WRITER-" + ("whole" if a.startswith("WRITER ") and a.endswith("\n") else "PARTIAL/EMPTY:" + repr(a))), "bulk_all_25000=%s" % intact, "status=" + ("clean" if clean else "dirty:" + ",".join(lines)))
    res[key] += 1
    ev.w(f"run {i}: checkout wall {t1-t0:.2f}s, writer iterations {n}, a.txt={a!r}, w_new={w!r}, rc={pub.returncode} err={err.strip()[:900]!r}, status lines={lines}")
for k, v in res.items(): ev.w(v, "x", k)
