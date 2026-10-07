"""Repeat real-jj handoff races with barriers and fresh disposable projects.

Run from the CopyRoom devenv with:

    uv run python .scratch/projects/28-temporary-workspace-handoff/harness.py
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from copyroom import __version__ as copyroom_version
from copyroom.local.composer import digest_source
from copyroom.local.jj import JJ
from copyroom.local.source import MARKER, marker, snapshot_path
from copyroom.local.workflow import new, working_digest, working_files

ROOT = Path(__file__).resolve().parents[3]
EXAMPLE = ROOT / ".scratch/projects/26-templateer-jj-slice/example"
DRIVER = Path(__file__).with_name("driver.py")
BARRIER = Path(__file__).with_name("jj_barrier.py")
JJ_BIN = shutil.which("jj")
if JJ_BIN is None:
    raise SystemExit("jj is required; run this harness inside the CopyRoom devenv")


def run_jj(project: Path, *args: str) -> str:
    result = subprocess.run([JJ_BIN, *args], cwd=project, text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(f"jj {' '.join(args)} failed: {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout.strip()


def commit_id(project: Path, revision: str = "@") -> str:
    return run_jj(project, "log", "--ignore-working-copy", "--no-graph", "-r", revision,
                  "-T", "commit_id")


def commit_details(project: Path, revision: str = "@") -> dict[str, str]:
    value = run_jj(
        project,
        "log", "--ignore-working-copy", "--no-graph", "-r", revision, "-T",
        'commit_id ++ " " ++ parents.map(|parent| parent.commit_id()).join(",")',
    )
    commit, parents = value.split()
    return {"head": commit, "parents": parents.split(",") if parents else []}


def operation_id(project: Path) -> str:
    return run_jj(
        project, "op", "log", "--at-op=@", "--ignore-working-copy", "--no-graph", "-n", "1", "-T", "id",
    )


def operation_graph(project: Path) -> str:
    return run_jj(project, "op", "log", "--ignore-working-copy", "--no-graph", "-n", "12")


def file_digest(project: Path) -> str:
    return working_digest(project)


def project_snapshot(project: Path) -> dict[str, Any]:
    marker_path = project / MARKER
    files = {}
    for name, (kind, content, mode) in working_files(project).items():
        files[name] = {
            "kind": kind,
            "mode": mode,
            "sha256": hashlib.sha256(content).hexdigest(),
        }
    marker_data = marker(project) if marker_path.is_file() else None
    render_heads = {}
    source_snapshots = {}
    if marker_data:
        records = marker_data.get("layers", {"base": marker_data})
        if isinstance(records, dict):
            for layer, record in records.items():
                try:
                    expression = (
                        f'heads(::@ & subject(glob:"copyroom:render '
                        f'{marker_data["project_id"]} {layer} *"))'
                    )
                    render_heads[layer] = run_jj(
                        project, "log", "--ignore-working-copy", "--no-graph",
                        "-r", expression, "-T", "commit_id",
                    )
                except Exception as exc:
                    render_heads[layer] = f"unavailable: {exc}"
                digest = record.get("source_digest") if isinstance(record, dict) else None
                if isinstance(digest, str):
                    source_snapshots[layer] = {
                        "digest": digest,
                        "present": snapshot_path(project, digest).is_dir(),
                    }
    return {
        **commit_details(project),
        "operation_id": operation_id(project),
        "tree_digest": file_digest(project),
        "marker_hex": marker_path.read_bytes().hex() if marker_path.exists() else None,
        "marker": marker_data,
        "files": files,
        "render_heads": render_heads,
        "source_snapshots": source_snapshots,
    }


def make_project(root: Path) -> tuple[Path, Path, Path]:
    source = root / "source"
    shutil.copytree(EXAMPLE, source)
    project = root / "project"
    new(source, project, source / "answers.json")
    settings = source / "templates/settings/template.j2"
    settings.write_text(settings.read_text(encoding="utf-8") + '\nrevision: "handoff-v2"\n', encoding="utf-8")
    return source, project, root / "preview"


def make_overlay(source: Path, root: Path) -> Path:
    overlay = root / "overlay"
    shutil.copytree(source, overlay)
    manifest_path = overlay / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["templates"] = ["settings"]
    manifest["executable"] = []
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    metadata = overlay / "templates/settings/metadata.yml"
    metadata.write_text(
        metadata.read_text(encoding="utf-8").replace("config/project.yml", "docs/guide.md"),
        encoding="utf-8",
    )
    return overlay


def add_external_commit(
    project: Path,
    name: str = "external.txt",
    body: str = "independent writer\n",
) -> dict[str, str]:
    (project / name).write_text(body, encoding="utf-8")
    run_jj(project, "commit", "-m", "external writer")
    return {"commit": commit_id(project), "operation_id": operation_id(project)}


def commit_is_visible(project: Path, commit: str) -> bool:
    result = subprocess.run(
        [JJ_BIN, "log", "--ignore-working-copy", "--no-graph", "-r", commit, "-T", "commit_id"],
        cwd=project, text=True, capture_output=True, check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == commit


def make_barrier(root: Path, *, cwd: Path | None, prefix: list[str], when: str) -> tuple[Path, dict[str, str]]:
    bin_dir = root / "barrier-bin"
    bin_dir.mkdir()
    wrapper = bin_dir / "jj"
    shutil.copy2(BARRIER, wrapper)
    wrapper.chmod(0o755)
    ready = root / "barrier-ready"
    release = root / "barrier-release"
    first_hit = root / "barrier-first-hit"
    config = {
        "cwd": str(cwd) if cwd else None,
        "prefix": prefix,
        "when": when,
        "ready": str(ready),
        "release": str(release),
        "first_hit": str(first_hit),
    }
    env = os.environ.copy()
    env["COPYROOM_REAL_JJ"] = JJ_BIN or "jj"
    env["COPYROOM_JJ_BARRIER"] = json.dumps(config)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(ROOT / "src"), env.get("PYTHONPATH", "")]))
    return ready, {"env": env, "release": str(release)}


def wait_ready(path: Path, process: subprocess.Popen[str], timeout: float = 30) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return json.loads(path.with_name("barrier-first-hit").read_text(encoding="utf-8"))
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise RuntimeError(f"child exited before barrier ({process.returncode}): {stdout}\n{stderr}")
        time.sleep(0.01)
    process.kill()
    raise TimeoutError(f"jj barrier did not open: {path}")


def launch_driver(action: str, project: Path, out: Path, env: dict[str, str], *extra: str) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, str(DRIVER), action, str(project), str(out), *extra],
        cwd=ROOT, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )


def run_driver(action: str, project: Path, out: Path, *extra: str) -> tuple[int, dict[str, Any], str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(ROOT / "src"), env.get("PYTHONPATH", "")]))
    result = subprocess.run(
        [sys.executable, str(DRIVER), action, str(project), str(out), *extra],
        cwd=ROOT, env=env, text=True, capture_output=True, check=False,
    )
    try:
        report = json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        report = {"ok": False, "stdout": result.stdout, "stderr": result.stderr}
    return result.returncode, report, result.stderr


def release_barrier(path: str) -> None:
    Path(path).write_text("release\n", encoding="utf-8")


def run_interleaving(kind: str) -> dict[str, Any]:
    """Pause a real CopyRoom child process while a second real jj writes."""

    temporary = tempfile.TemporaryDirectory(prefix=f"copyroom-handoff-{kind}-")
    root = Path(temporary.name)
    source, project, out = make_project(root)
    preview_before = None
    preview_state = None
    if kind == "preview-during-preparation":
        ready, control = make_barrier(root, cwd=out, prefix=["new"], when="after")
        child = launch_driver("preview", project, out, control["env"])
        hit = wait_ready(ready, child)
        temporary_workspace = project_snapshot(out)
        competitor = add_external_commit(project, "during-preview.txt")
    elif kind == "layer-add-during-preparation":
        overlay = make_overlay(source, root)
        ready, control = make_barrier(root, cwd=None, prefix=["new"], when="after")
        child = launch_driver(
            "layer-add", project, root / "unused-preview", control["env"],
            str(overlay), str(overlay / "answers.json"), "docs",
        )
        hit = wait_ready(ready, child)
        temporary_workspace = project_snapshot(Path(hit["cwd"]))
        competitor = add_external_commit(project, "during-layer-add.txt")
    else:
        preview_code, preview_report, preview_stderr = run_driver("preview", project, out)
        if preview_code:
            raise RuntimeError(f"preview failed ({preview_code}): {preview_report}; {preview_stderr}")
        preview_state = preview_report["result"]
        preview_before = project_snapshot(out)
        if kind in {"before-apply", "bookmark-before-apply"}:
            operation_before_writer = operation_id(project)
            if kind == "before-apply":
                competitor = add_external_commit(project, "before-apply.txt")
            else:
                run_jj(project, "bookmark", "create", "before-apply-writer", "-r", "@")
                competitor = {
                    "commit": commit_id(project),
                    "operation_id": operation_id(project),
                    "bookmark": "before-apply-writer",
                }
            before = project_snapshot(project)
            exit_code, result, apply_stderr = run_driver("apply", project, out)
            record = {
                "case": kind, "active_before": before,
                "operation_before_writer": operation_before_writer,
                "preview_head": preview_before["head"],
                "preview_workspace": preview_before, "preview_state": preview_state,
                "competitor": competitor, "result": result, "copyroom_exit_code": exit_code,
                "stderr": apply_stderr.strip(), "active_after": project_snapshot(project),
                "preview_kept": out.exists(),
                "operation_graph_after": operation_graph(project),
                "bookmarks_after": run_jj(project, "bookmark", "list"),
            }
            temporary.cleanup()
            return record
        if kind in {"before-handoff", "uncommitted-at-handoff", "bookmark-at-handoff"}:
            prefix = ["new"]
            side = "before"
        elif kind == "after-new":
            prefix = ["new"]
            side = "after"
        elif kind == "after-marker-commit":
            prefix = ["commit", "-m", "copyroom:project inputs"]
            side = "after"
        elif kind == "before-cleanup":
            prefix = ["workspace", "forget"]
            side = "before"
        else:
            raise ValueError(kind)
        ready, control = make_barrier(root, cwd=project, prefix=prefix, when=side)
        child = launch_driver("apply", project, out, control["env"])
        hit = wait_ready(ready, child)
        temporary_workspace = project_snapshot(Path(hit["cwd"]))
        if kind == "before-handoff":
            competitor = add_external_commit(project, "at-handoff.txt")
        elif kind == "after-new":
            competitor = add_external_commit(project, "during-handoff.txt")
        elif kind == "uncommitted-at-handoff":
            uncommitted_path = project / "uncommitted.txt"
            uncommitted_path.write_text("plain uncommitted writer\n", encoding="utf-8")
            competitor = {"commit": commit_id(project), "operation_id": operation_id(project),
                          "tree_digest": file_digest(project),
                          "file_bytes_hex": uncommitted_path.read_bytes().hex()}
        elif kind == "bookmark-at-handoff":
            run_jj(project, "bookmark", "create", "external-writer", "-r", "@")
            competitor = {"commit": commit_id(project), "operation_id": operation_id(project),
                          "bookmark": "external-writer"}
        else:
            competitor = add_external_commit(project, "after-handoff.txt")
        before_release = project_snapshot(project)
        release_barrier(control["release"])
        stdout, stderr = child.communicate(timeout=30)
        try:
            result = json.loads(stdout.strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError):
            result = {"ok": False, "stdout": stdout, "stderr": stderr, "returncode": child.returncode}
        record = {
            "case": kind, "barrier_command": hit, "competitor": competitor,
            "preview_workspace_before": preview_before,
            "preview_state": preview_state,
            "temporary_workspace_at_barrier": temporary_workspace,
            "competitor_state_before_release": before_release, "result": result,
            "returncode": child.returncode, "stderr": stderr.strip(),
            "active_after": project_snapshot(project), "preview_kept": out.exists(),
            "preview_state_kept": out.with_name(out.name + ".copyroom-preview.json").exists(),
            "bookmarks_after": run_jj(project, "bookmark", "list"),
            "competitor_commit_visible": commit_is_visible(project, competitor["commit"]),
            "operation_graph_after": operation_graph(project),
        }
        if kind == "before-handoff":
            recovery_commit = competitor["commit"]
        elif kind == "uncommitted-at-handoff":
            current_operation = operation_id(project)
            parent_operations = run_jj(
                project, "op", "log", f"--at-op={current_operation}", "--no-graph", "-n", "1",
                "-T", 'parents.map(|parent| parent.id()).join(" ")',
            ).split()
            recovery_operation = parent_operations[0] if parent_operations else None
            recovery_commit = None
            if recovery_operation:
                recovery_commit = run_jj(
                    project, f"--at-operation={recovery_operation}", "log", "--ignore-working-copy",
                    "--no-graph", "-r", "@", "-T", "commit_id",
                )
                record["uncommitted_snapshot"] = {
                    "operation_id": recovery_operation,
                    "workspace_head": recovery_commit,
                }
            record["uncommitted_file_present_after"] = (project / "uncommitted.txt").exists()
        else:
            recovery_commit = None
        if recovery_commit:
            recovery_output = run_jj(project, "edit", recovery_commit)
            record["recovery_command"] = ["jj", "edit", recovery_commit]
            record["recovery_output"] = recovery_output
            record["recovery_active"] = project_snapshot(project)
            record["operation_graph_after_recovery"] = operation_graph(project)
        if kind == "layer-add-during-preparation":
            workspace_text = result.get("error", "").split("workspace kept at ")
            if len(workspace_text) == 2:
                shutil.rmtree(Path(workspace_text[1].split(";")[0]).parent, ignore_errors=True)
        temporary.cleanup()
        return record

    before_release = project_snapshot(project)
    release_barrier(control["release"])
    stdout, stderr = child.communicate(timeout=30)
    try:
        result = json.loads(stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        result = {"ok": False, "stdout": stdout, "stderr": stderr, "returncode": child.returncode}
    record = {
        "case": kind, "barrier_command": hit, "active_before": before_release,
        "temporary_workspace_at_barrier": temporary_workspace,
        "source_digest": digest_source(source),
        "competitor": competitor, "result": result, "returncode": child.returncode,
        "stderr": stderr.strip(), "active_after": project_snapshot(project),
        "preview_exists": out.exists(),
        "preview_state_exists": out.with_name(out.name + ".copyroom-preview.json").exists(),
        "project_source_digest": marker(project)["source_digest"],
    }
    temporary.cleanup()
    return record


def run_clean_apply() -> dict[str, Any]:
    temporary = tempfile.TemporaryDirectory(prefix="copyroom-handoff-clean-")
    root = Path(temporary.name)
    source, project, out = make_project(root)
    before = project_snapshot(project)
    preview_code, preview_report, preview_stderr = run_driver("preview", project, out)
    if preview_code:
        raise RuntimeError(f"preview failed ({preview_code}): {preview_report}; {preview_stderr}")
    preview_state = preview_report["result"]
    prepared = project_snapshot(out)
    prepared_marker = (out / MARKER).read_bytes()
    source_snapshot = snapshot_path(out, preview_state["source_digest"])
    prepared_source = {
        "path": str(source_snapshot),
        "present": source_snapshot.is_dir(),
        "digest": digest_source(source_snapshot),
    }
    active_during_preview = project_snapshot(project)
    apply_code, apply_report, apply_stderr = run_driver("apply", project, out)
    after = project_snapshot(project)
    record = {
        "case": "clean-apply", "active_before": before,
        "jj_version": run_jj(project, "--version"),
        "active_during_preview": active_during_preview,
        "prepared": prepared, "preview_head": preview_state["preview_head"],
        "preview_tree_digest": preview_state["preview_tree"],
        "prepared_marker_hex": prepared_marker.hex(),
        "active_marker_after_hex": (project / MARKER).read_bytes().hex(),
        "source_digest": preview_state["source_digest"],
        "source_snapshot_prepared": prepared_source,
        "render_head": JJ(project).render_head(marker(project)["project_id"]),
        "result": apply_report, "copyroom_exit_code": apply_code,
        "stderr": apply_stderr.strip(), "active_after": after, "operation_graph_after": operation_graph(project),
    }
    temporary.cleanup()
    return record


def run_writer_during_active_update() -> dict[str, Any]:
    """Place an independent filesystem writer inside jj's real checkout window."""

    temporary = tempfile.TemporaryDirectory(prefix="copyroom-handoff-during-update-")
    root = Path(temporary.name)
    source, project, out = make_project(root)
    bulk_source = source / "bulk-source"
    bulk_source.mkdir()
    manifest_path = source / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["static"] = [
        {"path": "bulk-output/000-sentinel.txt", "source": "bulk-source/000-sentinel.txt"},
        {"path": "bulk-output/001-target.txt", "source": "bulk-source/001-target.txt"},
        {"path": "bulk-output/zzz-slow.bin", "source": "bulk-source/zzz-slow.bin"},
    ]
    (bulk_source / "000-sentinel.txt").write_text("prepared sentinel\n", encoding="utf-8")
    (bulk_source / "001-target.txt").write_text("prepared target\n", encoding="utf-8")
    (bulk_source / "zzz-slow.bin").write_bytes(b"p" * (64 * 1024 * 1024))
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    preview_code, preview_report, preview_stderr = run_driver("preview", project, out)
    if preview_code:
        raise RuntimeError(f"preview failed ({preview_code}): {preview_report}; {preview_stderr}")
    preview_state = preview_report["result"]
    active_before_handoff = project_snapshot(project)
    source_snapshot = snapshot_path(out, preview_state["source_digest"])
    temporary_workspace = {
        **commit_details(out),
        "operation_id": operation_id(out),
        "tree_digest": preview_state["preview_tree"],
        "marker_hex": (out / MARKER).read_bytes().hex(),
        "render_head": JJ(out).render_head(preview_state["project_id"]),
        "source_snapshot": {
            "digest": preview_state["source_digest"],
            "present": source_snapshot.is_dir(),
            "actual_digest": digest_source(source_snapshot),
        },
    }
    first_file = project / "bulk-output" / "000-sentinel.txt"
    target_file = project / "bulk-output" / "001-target.txt"
    prepared_bytes = (out / target_file.relative_to(project)).read_bytes()
    writer_bytes = b"independent writer during active jj checkout\n"
    trigger = root / "filesystem-writer-trigger"
    writer_done = root / "filesystem-writer-done"
    writer_script = (
        "from pathlib import Path; import sys,time; "
        "trigger,target,done,payload=sys.argv[1:]; trigger=Path(trigger); "
        "deadline=time.monotonic()+60; "
        "exec('while not trigger.exists() and time.monotonic()<deadline: time.sleep(0.0005)'); "
        "target=Path(target); target.write_bytes(bytes.fromhex(payload)); "
        "Path(done).write_text('written\\n',encoding='utf-8')"
    )
    writer_child = subprocess.Popen(
        [sys.executable, "-c", writer_script, str(trigger), str(target_file),
         str(writer_done), writer_bytes.hex()],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    ready, control = make_barrier(root, cwd=project, prefix=["new"], when="before")
    child = launch_driver("apply", project, out, control["env"])
    hit = wait_ready(ready, child)
    release_barrier(control["release"])

    deadline = time.monotonic() + 60
    writer_during_new = False
    target_had_prepared_bytes_before_writer = False
    while time.monotonic() < deadline and child.poll() is None:
        if first_file.is_file() and target_file.is_file() and target_file.read_bytes() == prepared_bytes:
            target_had_prepared_bytes_before_writer = True
            writer_during_new = child.poll() is None
            trigger.write_text("write\n", encoding="utf-8")
            break
        time.sleep(0.001)
    if not trigger.exists():
        writer_child.terminate()
    writer_stdout, writer_stderr = writer_child.communicate(timeout=10)
    writer_finished_while_new = writer_during_new and child.poll() is None

    try:
        stdout, stderr = child.communicate(timeout=120)
    except subprocess.TimeoutExpired as exc:
        child.kill()
        stdout, stderr = child.communicate()
        raise TimeoutError("CopyRoom apply did not finish after the checkout writer") from exc
    try:
        result = json.loads(stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        result = {"ok": False, "stdout": stdout, "stderr": stderr, "returncode": child.returncode}
    final_bytes = target_file.read_bytes() if target_file.is_file() else None
    record = {
        "case": "writer-during-active-workspace-update",
        "writer_id": f"filesystem-writer-pid-{writer_child.pid}",
        "barrier_command": hit,
        "active_before_handoff": active_before_handoff,
        "temporary_workspace": temporary_workspace,
        "preview_state": preview_state,
        "preview_tree_digest": preview_state["preview_tree"],
        "first_checkout_file_present_before_writer": first_file.is_file(),
        "target_had_prepared_bytes_before_writer": target_had_prepared_bytes_before_writer,
        "writer_process_exit_code": writer_child.returncode,
        "writer_process_stdout": writer_stdout.strip(),
        "writer_process_stderr": writer_stderr.strip(),
        "writer_during_real_jj_new": writer_during_new,
        "writer_finished_while_real_jj_new_running": writer_finished_while_new,
        "target_file": target_file.relative_to(project).as_posix(),
        "prepared_bytes_hex": prepared_bytes.hex(),
        "writer_bytes_hex": writer_bytes.hex(),
        "final_bytes_hex": final_bytes.hex() if final_bytes is not None else None,
        "writer_bytes_survived": final_bytes == writer_bytes,
        "result": result,
        "copyroom_exit_code": child.returncode,
        "stderr": stderr.strip(),
        "active_after": project_snapshot(project),
        "preview_kept": out.exists(),
        "operation_graph_after": operation_graph(project),
    }
    temporary.cleanup()
    return record


def run_source_edit_after_preview() -> dict[str, Any]:
    temporary = tempfile.TemporaryDirectory(prefix="copyroom-handoff-source-edit-")
    root = Path(temporary.name)
    source, project, out = make_project(root)
    preview_code, preview_report, preview_stderr = run_driver("preview", project, out)
    if preview_code:
        raise RuntimeError(f"preview failed ({preview_code}): {preview_report}; {preview_stderr}")
    state = preview_report["result"]
    reviewed_files = {name: value for name, value in working_files(out).items() if name != MARKER}
    source_before = digest_source(source)
    settings = source / "templates/settings/template.j2"
    settings.write_text(settings.read_text(encoding="utf-8") + '\nrevision: "after-preview"\n', encoding="utf-8")
    source_after = digest_source(source)
    apply_code, apply_report, apply_stderr = run_driver("apply", project, out)
    active_files = {name: value for name, value in working_files(project).items() if name != MARKER}
    record = {
        "case": "source-edited-after-preview",
        "preview_state": state,
        "source_digest_before": source_before,
        "source_digest_after": source_after,
        "active_after": project_snapshot(project),
        "reviewed_files_equal_active_files": reviewed_files == active_files,
        "apply_exit_code": apply_code,
        "apply_report": apply_report,
        "apply_stderr": apply_stderr.strip(),
    }
    temporary.cleanup()
    return record


def run_writer_before_preparation() -> dict[str, Any]:
    temporary = tempfile.TemporaryDirectory(prefix="copyroom-handoff-writer-before-")
    root = Path(temporary.name)
    source, project, out = make_project(root)
    competitor = add_external_commit(project, "before-preparation.txt")
    active_before = project_snapshot(project)
    preview_code, preview_report, preview_stderr = run_driver("preview", project, out)
    if preview_code:
        raise RuntimeError(f"preview failed ({preview_code}): {preview_report}; {preview_stderr}")
    state = preview_report["result"]
    preview_workspace = project_snapshot(out)
    active_after = project_snapshot(project)
    record = {
        "case": "writer-before-preparation",
        "competitor": competitor,
        "active_before": active_before,
        "active_after": active_after,
        "preview_state": state,
        "copyroom_exit_code": preview_code,
        "copyroom_report": preview_report,
        "preview_workspace": preview_workspace,
        "operation_graph_after": operation_graph(project),
    }
    temporary.cleanup()
    return record


def main() -> int:
    cases = [
        run_clean_apply(),
        run_writer_during_active_update(),
        run_writer_before_preparation(),
        run_source_edit_after_preview(),
        run_interleaving("preview-during-preparation"),
        run_interleaving("layer-add-during-preparation"),
        run_interleaving("before-apply"),
        run_interleaving("bookmark-before-apply"),
        run_interleaving("before-handoff"),
        run_interleaving("after-new"),
        run_interleaving("uncommitted-at-handoff"),
        run_interleaving("bookmark-at-handoff"),
        run_interleaving("after-marker-commit"),
        run_interleaving("before-cleanup"),
    ]
    encoded = json.dumps(cases, sort_keys=True).encode()
    report = {
        "jj_version": cases[0]["jj_version"],
        "copyroom_version": copyroom_version,
        "root_devenv": os.environ.get("DEVENV_ROOT"),
        "python_executable": sys.executable,
        "jj_executable": JJ_BIN,
        "copyroom_launch": [sys.executable, str(DRIVER), "<action>", "<project>", "<out>"],
        "runs": cases,
        "evidence_sha256": hashlib.sha256(encoded).hexdigest(),
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
