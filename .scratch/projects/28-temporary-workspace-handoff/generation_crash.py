"""Kill a generation publisher after each durable step, then recover."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from alternatives_harness import complete_marker, recovery, save_json, switch_pointer
from harness import JJ_BIN, commit_details, make_project, operation_graph, operation_id, run_driver, run_jj

from copyroom import __version__ as copyroom_version
from copyroom.local.source import MARKER
from copyroom.local.workflow import working_digest


def worker(root: Path, stop: str) -> None:
    prepared = root / "preview"
    active = root / "active"
    journal = root / "generation-journal.json"
    saved = json.loads((root / "payload.json").read_text())
    save_json(journal, saved)
    if stop != "journal":
        switch_pointer(active, prepared)
    if stop in {"complete", "cleanup"}:
        saved["phase"] = "complete"
        save_json(journal, saved)
    if stop == "cleanup":
        (root / "preview.copyroom-preview.json").unlink(missing_ok=True)
    (root / "ready").write_text(stop + "\n")
    time.sleep(60)


def probe(stop: str, writer: str = "none") -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix=f"copyroom-crash-{stop}-") as temp:
        root = Path(temp)
        source, old, prepared = make_project(root)
        active = root / "active"
        active.symlink_to(old)
        before_head = commit_details(old)
        before_tree = working_digest(old)
        before_marker = (old / MARKER).read_bytes().hex()
        code, report, stderr = run_driver("preview", old, prepared)
        if code:
            raise RuntimeError(f"preview failed: {code}: {report}: {stderr}")
        state = report["result"]
        complete_marker(old, prepared, state)
        prepared_head = commit_details(prepared)
        payload = {
            "phase": "prepared", "old": str(old), "prepared": str(prepared),
            "expected_old_head": before_head["head"],
            "expected_old_tree": before_tree,
            "expected_old_marker_hex": before_marker,
            "prepared_head": prepared_head["head"],
            "prepared_tree": working_digest(prepared),
            "prepared_marker_hex": (prepared / MARKER).read_bytes().hex(),
            "render_head": state["next_render"],
            "source_digest": state["source_digest"],
        }
        (root / "payload.json").write_text(json.dumps(payload))
        child = subprocess.Popen([sys.executable, __file__, "worker", str(root), stop])
        deadline = time.monotonic() + 30
        while not (root / "ready").exists():
            if child.poll() is not None:
                raise RuntimeError(f"worker exited early: {child.returncode}")
            if time.monotonic() > deadline:
                child.kill()
                raise TimeoutError("publisher did not reach crash barrier")
            time.sleep(0.01)
        barrier = (root / "ready").read_text().strip()
        publisher_pid = child.pid
        child.send_signal(signal.SIGKILL)
        child.wait(timeout=10)
        writer_commit = None
        if writer == "direct-file":
            (active / "competing.txt").write_text("writer after activation\n")
        elif writer == "jj-commit":
            (active / "competing.txt").write_text("writer after activation\n")
            run_jj(active, "commit", "-m", "competing writer")
            writer_commit = commit_details(active)["parents"][0]
        recovered = recovery(active, root / "generation-journal.json", prepared)
        jj_version = subprocess.run(
            [JJ_BIN, "--version"], capture_output=True, text=True, check=True,
        ).stdout.strip()
        return {
            "case": f"crash-{stop}-{writer}",
            "jj_version": jj_version,
            "preview_exit": code,
            "preview_report": report,
            "publisher_pid": publisher_pid,
            "barrier": barrier,
            "worker_exit": child.returncode,
            "writer": writer,
            "writer_commit": writer_commit,
            "active_target": str(active.resolve()),
            "old_head": before_head,
            "old_tree": before_tree,
            "prepared_head": prepared_head,
            "prepared_tree": payload["prepared_tree"],
            "prepared_marker_hex": payload["prepared_marker_hex"],
            "active_head_after": commit_details(active),
            "active_tree_after": working_digest(active),
            "active_marker_hex_after": (active / MARKER).read_bytes().hex(),
            "competing_file_in_active": (active / "competing.txt").exists(),
            "recovery": recovered,
            "preview_sidecar_exists": (root / "preview.copyroom-preview.json").exists(),
            "operation_id": operation_id(old),
            "operation_graph": operation_graph(old),
            "workspaces": run_jj(old, "workspace", "list"),
        }


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "worker":
        worker(Path(sys.argv[2]), sys.argv[3])
        return
    runs = [probe(step) for step in ("journal", "pointer", "complete", "cleanup")]
    runs.append(probe("pointer", "direct-file"))
    runs.append(probe("pointer", "jj-commit"))
    print(json.dumps({
        "copyroom_version": copyroom_version,
        "root_devenv": os.environ.get("DEVENV_ROOT"),
        "python_executable": sys.executable,
        "jj_executable": JJ_BIN,
        "copyroom_launch": [sys.executable, "driver.py", "preview", "<project>", "<out>"],
        "runs": runs,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
