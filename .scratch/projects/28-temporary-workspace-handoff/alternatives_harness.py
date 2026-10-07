"""Probe advisory locks and generation activation in disposable jj projects.

Run inside the root devenv with ``uv run python alternatives_harness.py``.
This file does not change CopyRoom runtime behavior.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from harness import (
    JJ_BIN,
    commit_details,
    launch_driver,
    make_barrier,
    make_overlay,
    make_project,
    operation_graph,
    operation_id,
    project_snapshot,
    release_barrier,
    run_driver,
    run_jj,
    wait_ready,
)

from copyroom import __version__ as copyroom_version
from copyroom.local.composer import digest_source
from copyroom.local.jj import JJ
from copyroom.local.source import MARKER, marker, snapshot_path, write_json
from copyroom.local.workflow import working_digest


def child_result(child: subprocess.Popen[str]) -> dict[str, object]:
    stdout, stderr = child.communicate(timeout=45)
    return {"exit": child.returncode, "stdout": stdout.strip(), "stderr": stderr.strip()}


def lock_probe(raw_writer: bool) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="copyroom-alternative-lock-") as temp:
        root = Path(temp)
        source, project, preview = make_project(root)
        code, report, stderr = run_driver("preview", project, preview)
        if code:
            raise RuntimeError(f"preview: {code}: {report}: {stderr}")
        prepared = project_snapshot(preview)
        active_before = project_snapshot(project)
        ready, control = make_barrier(root, cwd=project, prefix=["new"], when="before")
        first = launch_driver("apply", project, preview, control["env"])
        hit = wait_ready(ready, first)
        second = launch_driver("apply", project, preview, os.environ.copy())
        time.sleep(0.4)
        second_waiting = second.poll() is None
        # This independent jj process does not acquire CopyRoom's flock.
        raw = None
        raw_op = None
        if raw_writer:
            raw = subprocess.run(
                [JJ_BIN, "bookmark", "create", "raw-writer", "-r", "@"],
                cwd=project, text=True, capture_output=True, check=False, timeout=10,
            )
            raw_op = operation_id(project)
        release_barrier(control["release"])
        first_result = child_result(first)
        second_result = child_result(second)
        return {
            "case": "copyroom-lock-and-plain-jj" if raw_writer else "copyroom-lock-two-processes",
            "jj_binary": JJ_BIN,
            "python": sys.version.split()[0],
            "copyroom_launch": [sys.executable, "driver.py", "apply"],
            "barrier": hit,
            "active_before": active_before,
            "prepared": prepared,
            "preview_exit": code,
            "preview_report": report,
            "second_copyroom_waited": second_waiting,
            "plain_jj_exit": raw.returncode if raw else None,
            "plain_jj_stderr": raw.stderr.strip() if raw else None,
            "plain_jj_operation": raw_op,
            "first": first_result,
            "second": second_result,
            "active_after": project_snapshot(project),
            "preview_exists": preview.exists(),
            "operation_graph": operation_graph(project),
        }


def save_json(path: Path, value: dict[str, object]) -> None:
    staged = path.with_suffix(".tmp")
    with staged.open("wb") as stream:
        stream.write(json.dumps(value, sort_keys=True).encode() + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(staged, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def switch_pointer(active: Path, target: Path) -> None:
    staged = active.with_name("active.next")
    staged.symlink_to(target)
    os.replace(staged, active)
    directory = os.open(active.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def complete_marker(project: Path, prepared: Path, state: dict[str, object]) -> None:
    data = marker(project)
    old = data.get("layers", {"base": data})["base"]
    keys = (
        "source", "source_digest", "manifest_digest", "templateer_version",
        "templateer_digest", "composer_digest", "answers", "owners", "revision",
        "render_digest",
    )
    new_record = {**old, **{key: state[key] for key in keys}}
    next_data = {**data, **new_record, "layers": {**data.get("layers", {"base": data}), "base": new_record}}
    write_json(prepared / MARKER, next_data)
    JJ(prepared).run("commit", "-m", "prototype:complete reviewed generation")


def recovery(active: Path, journal: Path, prepared: Path) -> dict[str, object]:
    state = json.loads(journal.read_text())
    target = active.resolve()
    if target == Path(state["old"]):
        action = "old generation active; prepared result retained for retry"
    elif target == prepared:
        valid = (
            working_digest(prepared) == state["prepared_tree"]
            and (prepared / MARKER).read_bytes().hex() == state["prepared_marker_hex"]
            and commit_details(prepared)["head"] == state["prepared_head"]
        )
        action = "new generation active; finalize journal" if valid else "new generation differs; stop"
        if valid and state["phase"] != "complete":
            state["phase"] = "complete"
            save_json(journal, state)
    else:
        action = "unknown pointer target; stop"
    return {"action": action, "target": str(target), "journal": json.loads(journal.read_text())}


def generation_probe(stop_after: str, writer: str = "none") -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix=f"copyroom-generation-{stop_after}-") as temp:
        root = Path(temp)
        source, old, prepared = make_project(root)
        active = root / "active"
        active.symlink_to(old)
        before = project_snapshot(old)
        code, report, stderr = run_driver("preview", old, prepared)
        if code:
            raise RuntimeError(f"preview: {code}: {report}: {stderr}")
        state = report["result"]
        complete_marker(old, prepared, state)
        prepared_state = project_snapshot(prepared)
        source_snapshot = snapshot_path(prepared, state["source_digest"])
        journal = root / "generation-journal.json"
        journal_data: dict[str, object] = {
            "phase": "prepared", "old": str(old), "prepared": str(prepared),
            "expected_old_head": before["head"],
            "expected_old_tree": before["tree_digest"],
            "expected_old_marker_hex": before["marker_hex"],
            "prepared_head": prepared_state["head"],
            "prepared_tree": prepared_state["tree_digest"],
            "prepared_marker_hex": prepared_state["marker_hex"],
            "render_head": state["next_render"],
            "source_digest": state["source_digest"],
        }
        save_json(journal, journal_data)
        if writer == "before-pointer":
            (old / "direct-writer.txt").write_text("direct writer before switch\n")
        open_file = (old / MARKER).open("rb")
        if stop_after != "prepared":
            switch_pointer(active, prepared)
        if writer == "after-pointer":
            (old / "direct-writer.txt").write_text("direct writer after switch\n")
        pointer_state = {
            "target": str(active.resolve()),
            "active_head": commit_details(active),
            "active_marker_sha256": hashlib.sha256((active / MARKER).read_bytes()).hexdigest(),
            "old_open_handle_marker_sha256": hashlib.sha256(open_file.read()).hexdigest(),
            "direct_writer_in_old": (old / "direct-writer.txt").exists(),
            "direct_writer_in_active": (active / "direct-writer.txt").exists(),
        }
        open_file.close()
        if stop_after == "journal-complete":
            journal_data["phase"] = "complete"
            save_json(journal, journal_data)
        recovered = recovery(active, journal, prepared)
        return {
            "case": f"generation-{stop_after}-{writer}",
            "jj_binary": JJ_BIN,
            "preview_exit": code,
            "preview_report": report,
            "before": before,
            "prepared": prepared_state,
            "source_snapshot_digest": digest_source(source_snapshot),
            "state_source_digest": state["source_digest"],
            "reviewed_render_head": state["next_render"],
            "pointer_state": pointer_state,
            "recovery": recovered,
            "operation_graph": operation_graph(old),
            "workspaces": run_jj(old, "workspace", "list"),
        }


def generation_layer_probe() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="copyroom-generation-layer-") as temp:
        root = Path(temp)
        source, old, _ = make_project(root)
        overlay = make_overlay(source, root)
        staged = root / "staged-layer"
        active = root / "active"
        active.symlink_to(old)
        before = project_snapshot(old)
        JJ(old).run("workspace", "add", "--name", "staged-layer", "-r", "@", str(staged))
        code, report, stderr = run_driver(
            "layer-add", staged, root / "unused", str(overlay), str(overlay / "answers.json"), "docs",
        )
        if code:
            raise RuntimeError(f"layer add failed: {code}: {report}: {stderr}")
        reviewed = project_snapshot(staged)
        record = marker(staged)["layers"]["docs"]
        snapshot = snapshot_path(staged, record["source_digest"])
        old_after_prepare = project_snapshot(old)
        switch_pointer(active, staged)
        return {
            "case": "generation-layer-add",
            "layer_add_exit": code,
            "layer_add_report": report,
            "layer_add_stderr": stderr,
            "old_before": before,
            "old_after_prepare": old_after_prepare,
            "reviewed": reviewed,
            "active_head": commit_details(active),
            "active_tree": working_digest(active),
            "active_marker_hex": (active / MARKER).read_bytes().hex(),
            "source_snapshot_digest": digest_source(snapshot),
            "source_digest": record["source_digest"],
            "render_head": JJ(active).render_head(marker(active)["project_id"], "docs"),
            "operation_graph": operation_graph(old),
            "workspaces": run_jj(old, "workspace", "list"),
        }


def main() -> None:
    runs = [lock_probe(False), lock_probe(True)]
    for step in ("prepared", "pointer", "journal-complete"):
        runs.append(generation_probe(step))
    runs.append(generation_probe("pointer", "before-pointer"))
    runs.append(generation_probe("pointer", "after-pointer"))
    runs.append(generation_layer_probe())
    version = subprocess.run([JJ_BIN, "--version"], capture_output=True, text=True, check=True).stdout.strip()
    print(json.dumps({
        "jj_version": version,
        "copyroom_version": copyroom_version,
        "root_devenv": os.environ.get("DEVENV_ROOT"),
        "python_executable": sys.executable,
        "jj_executable": JJ_BIN,
        "copyroom_launch": [sys.executable, "driver.py", "<action>", "<project>", "<out>"],
        "runs": runs,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
