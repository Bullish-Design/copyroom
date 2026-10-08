from common import *
import fcntl
repo = mkrepo("block-d")
ev = Evidence("d-lock-blocks.txt")
exp = cid(repo, "@"); p = cid(repo, 'description(exact:"prepared\n")')
lockpath = str(repo / ".jj/working_copy/working_copy.lock")
ready = Fifo(WORK, "d_ready"); sig_locked = Fifo(WORK, "d_locked"); sig_before = Fifo(WORK, "d_before")
HOLD = 3.0
holder_code = f"""
import fcntl, os, sys, time
fd = os.open({lockpath!r}, os.O_RDWR|os.O_CREAT)
fcntl.flock(fd, fcntl.LOCK_EX)
t_acq = time.time()
open({ready.path!r}, 'wb').write(b'x')
time.sleep({HOLD})
t_rel = time.time()
os.close(fd)
print(t_acq, t_rel, flush=True)
"""
th_r, box_r = ready.reader_thread()
holder = subprocess.Popen([PY, "-c", holder_code], stdout=subprocess.PIPE, text=True)
th_r.join(); t_ready = box_r["t"]          # holder owns the lock
ev.w("holder has the lock (barrier through FIFO)")
time.sleep(0.5)                              # protocol from the earlier agent: start publish_if 0.5 s in
ths_b, box_b = sig_before.reader_thread(); ths_l, box_l = sig_locked.reader_thread()
t_start = time.time()
ops0 = opids(repo)
proc = subprocess.Popen(publish_cmd(repo, exp, p, "publish_if: after-block"),
                        env=env({"PJ_SIGNAL_BEFORE_LOCK": sig_before.path, "PJ_SIGNAL_LOCKED": sig_locked.path}),
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
ths_b.join(); t_before = box_b["t"]
time.sleep(1.0)
ev.w("1.0 s after reaching BEFORE_LOCK: publish_if still running:", proc.poll() is None, "| op log unchanged:", opids(repo) == ops0,
     "| LOCKED signal received yet:", "t" in box_l)
ths_l.join(); t_locked = box_l["t"]
out, err = proc.communicate(); t_end = time.time()
hout = holder.communicate()[0].split(); t_acq, t_rel = float(hout[0]), float(hout[1])
ev.w("exit", proc.returncode, "stdout", out.strip()[:24] + "...", "stderr", err.strip())
ev.w(f"holder: held for {t_rel - t_acq:.2f}s")
ev.w(f"publish_if started at +{t_start - t_acq:.2f}s after lock acquisition; reached BEFORE_LOCK at +{t_before - t_acq:.2f}s")
ev.w(f"LOCKED (publish_if got the lock) at +{t_locked - t_acq:.2f}s; holder released at +{t_rel - t_acq:.2f}s")
ev.w(f"publish_if finished at +{t_end - t_acq:.2f}s; wall time of publish_if = {t_end - t_start:.2f}s (python startup included)")
ev.w(f"block time from BEFORE_LOCK to LOCKED = {t_locked - t_before:.2f}s")
ev.w("got lock only after release:", t_locked >= t_rel)
ev.w("new ops:", [o for o in opids(repo) if o not in ops0])
ev.w("OUTCOME d:", "PASS" if (t_locked >= t_rel and proc.returncode == 0) else "FAIL")
