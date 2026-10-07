"""Kill a real CopyRoom process at jj handoff barriers in disposable projects."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

from harness import (
    JJ_BIN,
    launch_driver,
    make_barrier,
    make_project,
    operation_graph,
    project_snapshot,
    run_driver,
    run_jj,
    wait_ready,
)

from copyroom import __version__ as copyroom_version
from copyroom.local.workflow import list_previews


def snapshot_if_ready(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"exists": False}
    try:
        return project_snapshot(path)
    except Exception as exc:
        return {"exists": True, "snapshot_error": str(exc)}


def probe(step: str) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix=f"copyroom-lock-crash-{step}-") as temp:
        root = Path(temp)
        source, project, preview = make_project(root)
        before = project_snapshot(project)
        if step == "preview-workspace-added":
            ready, control = make_barrier(root, cwd=project, prefix=["workspace", "add"], when="after")
            child = launch_driver("preview", project, preview, control["env"])
            preview_result = None
        else:
            code, report, stderr = run_driver("preview", project, preview)
            if code:
                raise RuntimeError(f"preview failed: {code}: {report}: {stderr}")
            preview_result = {"exit": code, "report": report, "stderr": stderr}
            prefix, when = {
                "before-new": (["new"], "before"),
                "after-new": (["new"], "after"),
                "after-marker-commit": (["commit", "-m", "copyroom:project inputs"], "after"),
                "before-cleanup": (["workspace", "forget"], "before"),
                "after-forget": (["workspace", "forget"], "after"),
            }[step]
            ready, control = make_barrier(root, cwd=project, prefix=prefix, when=when)
            child = launch_driver("apply", project, preview, control["env"])
        barrier = wait_ready(ready, child)
        at_barrier = project_snapshot(project)
        preview_at_barrier = snapshot_if_ready(preview)
        child.send_signal(signal.SIGKILL)
        child.wait(timeout=10)
        os.kill(barrier["pid"], signal.SIGKILL)
        after = project_snapshot(project)
        try:
            listed = list_previews(project)
        except Exception as exc:
            listed = {"error": str(exc)}
        workspaces_at_crash = run_jj(project, "workspace", "list")
        graph_at_crash = operation_graph(project)
        recovery = None
        if step in {"before-new", "after-new"}:
            action = None
            if step == "after-new":
                action = run_jj(project, "edit", before["head"])
            code, report, stderr = run_driver("apply", project, preview)
            recovery = {
                "action": "edit old head, then apply" if action is not None else "retry apply",
                "edit_output": action,
                "apply_exit": code,
                "apply_report": report,
                "apply_stderr": stderr,
                "active_after": project_snapshot(project),
            }
        jj_version = subprocess.run(
            [JJ_BIN, "--version"], capture_output=True, text=True, check=True,
        ).stdout.strip()
        return {
            "case": step,
            "copyroom_version": copyroom_version,
            "jj_version": jj_version,
            "python_executable": sys.executable,
            "jj_executable": JJ_BIN,
            "root_devenv": os.environ.get("DEVENV_ROOT"),
            "copyroom_launch": [sys.executable, "driver.py", "preview" if preview_result is None else "apply"],
            "publisher_pid": child.pid,
            "publisher_exit": child.returncode,
            "barrier": barrier,
            "preview_result": preview_result,
            "active_before": before,
            "active_at_barrier": at_barrier,
            "temporary_at_barrier": preview_at_barrier,
            "active_after_crash": after,
            "preview_exists": preview.exists(),
            "sidecar_exists": preview.with_name(preview.name + ".copyroom-preview.json").exists(),
            "listed_previews": listed,
            "workspaces": workspaces_at_crash,
            "operation_graph": graph_at_crash,
            "recovery": recovery,
        }


def main() -> None:
    steps = (
        "preview-workspace-added", "before-new", "after-new",
        "after-marker-commit", "before-cleanup", "after-forget",
    )
    print(json.dumps({"runs": [probe(step) for step in steps]}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
