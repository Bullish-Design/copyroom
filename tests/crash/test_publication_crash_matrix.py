"""Test process crashes at publication boundaries.

These tests kill a process. They do not simulate power loss, so they do not
prove that write_json's fsync calls make data durable.

For X0, X1, and X1j writer cases, publication has not happened. The writer
commit and prepared head are separate branches, so only the writer commit is
expected to be an ancestor of the active head.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from copyroom.local.jj import JJ
from copyroom.local.workflow import _is_ancestor, tracked_tree_digest

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / ".scratch" / "projects" / "26-templateer-jj-slice" / "example"
DRIVER = Path(__file__).with_name("driver.py")
PREVIEW_SUFFIX = ".copyroom-preview.json"

# case, crash point, operation, mode, competing writer
CASES = [
    ("A1", "A1", "update", "exit", False),
    ("A2", "A2", "update", "exit", False),
    ("A3", "A3", "update", "exit", False),
    ("A4", "A4", "update", "exit", False),
    ("A5", "A5", "update", "exit", False),
    ("A6", "A6", "update", "exit", False),
    ("L0", "L0", "layer", "exit", False),
    ("L1", "L1", "layer", "exit", False),
    ("L2", "L2", "layer", "exit", False),
    ("L3", "L3", "layer", "exit", False),
    ("L4", "L4", "layer", "exit", False),
    ("A1w", "A1", "update", "barrier", True),
    ("A2w", "A2", "update", "barrier", True),
    ("A3w", "A3", "update", "barrier", True),
    ("L1w", "L1", "layer", "barrier", True),
    ("L2w", "L2", "layer", "barrier", True),
    ("L3w", "L3", "layer", "barrier", True),
    ("A1k", "A1", "update", "sigkill", False),
    ("A3k", "A3", "update", "sigkill", False),
    ("L1k", "L1", "layer", "sigkill", False),
    ("X0", "X0", "update", "exit", False),
    ("X0w", "X0", "update", "barrier", True),
    ("X1", "X1", "update", "exit", False),
    ("X1w", "X1", "update", "barrier", True),
    ("X1j", "X1j", "update", "jj", False),
    ("X1jw", "X1j", "update", "jj", True),
]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _run_cli(
    args: list[str], cwd: Path, env: dict[str, str], timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "copyroom", *args],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def _check_cli(args: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    result = _run_cli(args, cwd, env)
    assert result.returncode == 0, result.stderr or result.stdout
    return result


def _sidecar(preview: Path) -> Path:
    return preview.with_name(preview.name + PREVIEW_SUFFIX)


def _make_overlay(source: Path, overlay: Path) -> None:
    shutil.copytree(source, overlay)
    manifest_path = overlay / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["templates"] = ["settings"]
    manifest["executable"] = []
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    metadata = overlay / "templates/settings/metadata.yml"
    metadata.write_text(
        metadata.read_text(encoding="utf-8").replace(
            "config/project.yml", "docs/guide.md",
        ),
        encoding="utf-8",
    )


def _wait_ready(ready: Path, process: subprocess.Popen[str], timeout: float = 30) -> None:
    received: dict[str, str] = {}

    def read_ready() -> None:
        with ready.open("r", encoding="utf-8") as stream:
            received["value"] = stream.readline()

    reader = threading.Thread(target=read_ready, daemon=True)
    reader.start()
    end = time.monotonic() + timeout
    while reader.is_alive() and time.monotonic() < end:
        reader.join(0.05)
        if process.poll() is not None and reader.is_alive():
            with ready.open("w", encoding="utf-8"):
                pass
            reader.join(1)
            break
    assert not reader.is_alive(), f"driver did not reach the crash barrier; rc={process.poll()}"
    assert received.get("value", "").startswith("ready"), "crash barrier did not report ready"


def _release(release: Path) -> None:
    with release.open("w", encoding="utf-8") as stream:
        stream.write("go\n")


def _writer_edit(project: Path) -> tuple[bytes, str, dict[str, tuple[str, bytes, int]]]:
    readme = project / "README.md"
    expected_readme = readme.read_bytes() + b"\nwriter edit\n"
    readme.write_bytes(expected_readme)
    (project / "writer-notes.txt").write_bytes(b"writer notes\n")
    JJ(project).run("commit", "-m", "writer: notes and readme")
    writer_head = JJ(project).commit_id("@-")
    (project / "writer-wip.txt").write_bytes(b"writer uncommitted wip\n")
    JJ(project).commit_id("@")  # Snapshot the uncommitted writer file.
    writer_files = {
        name: (
            "file",
            (project / name).read_bytes(),
            stat.S_IMODE((project / name).stat().st_mode),
        )
        for name in ("README.md", "writer-notes.txt", "writer-wip.txt")
    }
    return expected_readme, writer_head, writer_files


def _tracked_snapshot(
    root: Path, jj: JJ, rev: str = "@",
) -> dict[str, tuple[str, bytes, int]]:
    snapshot: dict[str, tuple[str, bytes, int]] = {}
    for name in sorted(jj.tracked_paths(rev)):
        path = root / name
        if path.is_symlink():
            snapshot[name] = ("symlink", os.readlink(path).encode(), 0)
        elif path.is_file():
            snapshot[name] = ("file", path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
        elif path.is_dir():
            snapshot[name] = ("directory", b"", 0)
        else:
            snapshot[name] = ("missing", b"", 0)
    return snapshot


def _snapshot_digest(snapshot: dict[str, tuple[str, bytes, int]]) -> str:
    digest = hashlib.sha256()
    for name, (kind, content, mode) in sorted(snapshot.items()):
        for item in (name.encode(), kind.encode(), f"{mode:o}".encode(), content):
            digest.update(len(item).to_bytes(8, "big"))
            digest.update(item)
    return digest.hexdigest()


def _make_jj_shim(
    shim_directory: Path,
    real_jj: str,
    ready: Path,
    release: Path,
    crash_log: Path,
    pid_file: Path,
) -> None:
    shim_directory.mkdir()
    shim = shim_directory / "jj"
    shim.write_text(
        "#!" + sys.executable + "\n"
        "import os, sys\n"
        "from pathlib import Path\n"
        "args = sys.argv[1:]\n"
        "if args[:1] == ['new'] and any('copyroom:update' in arg for arg in args):\n"
        "    with Path(os.environ['CRASH_LOG']).open('a', encoding='utf-8') as stream:\n"
        "        stream.write('CRASH point=X1j in jj new\\n')\n"
        "        stream.flush()\n"
        "        os.fsync(stream.fileno())\n"
        "    Path(os.environ['JJ_PID_FILE']).write_text(str(os.getpid()), encoding='utf-8')\n"
        "    with open(os.environ['CRASH_READY_FIFO'], 'w', encoding='utf-8') as stream:\n"
        "        stream.write('ready\\n')\n"
        "    with open(os.environ['CRASH_RELEASE_FIFO'], 'r', encoding='utf-8') as stream:\n"
        "        stream.read()\n"
        f"os.execv({real_jj!r}, [{real_jj!r}, *args])\n",
        encoding="utf-8",
    )
    shim.chmod(0o755)


def _wait_for_real_jj(pid_file: Path, real_jj: str, timeout: float = 15) -> int:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pid_file.exists():
            process_id = int(pid_file.read_text(encoding="utf-8"))
            executable = Path(f"/proc/{process_id}/exe")
            try:
                if executable.resolve() == Path(real_jj).resolve():
                    return process_id
            except OSError:
                pass
        time.sleep(0.005)
    raise AssertionError("jj shim did not exec the real jj binary")


@pytest.mark.slow
@pytest.mark.parametrize("case,point,kind,mode,writer", CASES, ids=[case[0] for case in CASES])
def test_publication_crash_matrix(
    tmp_path: Path,
    case: str,
    point: str,
    kind: str,
    mode: str,
    writer: bool,
) -> None:
    source = tmp_path / "source"
    shutil.copytree(FIXTURE, source)
    project = tmp_path / "project"
    temporary_root = tmp_path / "tmp"
    temporary_root.mkdir()
    env = os.environ.copy()
    env["TMPDIR"] = str(temporary_root)
    source_path = str(ROOT / "src")
    env["PYTHONPATH"] = os.pathsep.join(
        [source_path, env.get("PYTHONPATH", "")],
    ).rstrip(os.pathsep)

    _check_cli(
        ["new", str(source), str(project), "--answers", str(source / "answers.json")],
        tmp_path,
        env,
    )
    preview: Path | None = None
    overlay: Path | None = None
    if kind == "update":
        template = source / "templates/settings/template.j2"
        template.write_text(
            template.read_text(encoding="utf-8") + '\nrevision: "v2"\n',
            encoding="utf-8",
        )
        preview = tmp_path / "preview"
        _check_cli(
            ["update", "--source", str(source), "--out", str(preview)], project, env,
        )
        state = json.loads(_sidecar(preview).read_text(encoding="utf-8"))
        prepared_head = str(state["prepared_head"])
        prepared_tree = str(state["preview_tree"])
        prepared_marker_digest = str(state["prepared_marker_digest"])
        workspace_name = str(state["workspace"])
        prepared_snapshot = _tracked_snapshot(preview, JJ(preview))
    else:
        overlay = tmp_path / "overlay"
        _make_overlay(source, overlay)
        prepared_head = ""
        prepared_tree = ""
        prepared_marker_digest = ""
        workspace_name = ""
        prepared_snapshot: dict[str, tuple[str, bytes, int]] = {}

    jj = JJ(project)
    before_tree = tracked_tree_digest(project, jj)
    before_snapshot = _tracked_snapshot(project, jj)
    before_marker = (project / ".copyroom-local.json").read_bytes()
    before_marker_digest = _sha(before_marker)
    layer_journal: Path | None = None

    cli_args = (
        ["apply", "--preview", str(preview)]
        if kind == "update"
        else [
            "layer", "add", "--source", str(overlay), "--answers",
            str(overlay / "answers.json"), "--as", "docs",
        ]
    )
    crash_log = tmp_path / "crash.log"
    ready = tmp_path / "ready.fifo"
    release = tmp_path / "release.fifo"
    barrier = (
        writer or mode == "sigkill" or point == "X1j"
        or kind == "layer" and point != "L0"
    )
    if barrier:
        os.mkfifo(ready)
        os.mkfifo(release)

    if point == "X1j":
        real_jj = shutil.which("jj")
        assert real_jj is not None
        shim_directory = tmp_path / "bin"
        pid_file = tmp_path / "jj.pid"
        _make_jj_shim(shim_directory, real_jj, ready, release, crash_log, pid_file)
        env["PATH"] = str(shim_directory) + os.pathsep + env["PATH"]
        env["CRASH_LOG"] = str(crash_log)
        env["CRASH_READY_FIFO"] = str(ready)
        env["CRASH_RELEASE_FIFO"] = str(release)
        env["JJ_PID_FILE"] = str(pid_file)

    process = subprocess.Popen(
        [
            sys.executable, str(DRIVER), point, mode, str(crash_log),
            str(ready) if barrier else "", str(release) if barrier else "", "--", *cli_args,
        ],
        cwd=project,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )

    lock_stream = None
    writer_readme: bytes | None = None
    writer_head: str | None = None
    try:
        if barrier:
            _wait_ready(ready, process)
        if kind == "layer" and point != "L0":
            journals = list((project / ".copyroom-local/journal").glob("*.json"))
            assert len(journals) == 1
            layer_journal = journals[0]
            data = json.loads(layer_journal.read_text(encoding="utf-8"))
            prepared_head = str(data["prepared_head"])
            prepared_tree = str(data["prepared_tree"])
            prepared_marker_digest = str(data["prepared_marker_digest"])
            workspace_name = str(data["workspace"])
            workspace_path = Path(str(data["workspace_path"]))
            if writer:
                prepared_snapshot = _tracked_snapshot(
                    workspace_path, JJ(project), prepared_head,
                )

        if point == "X1j":
            if writer:
                writer_readme, writer_head, writer_files = _writer_edit(project)
            # Hold jj at its working-copy lock so the test can kill the real binary.
            lock_path = project / ".jj" / "working_copy" / "working_copy.lock"
            lock_stream = lock_path.open("a+b")
            fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX)
            _release(release)
            _wait_for_real_jj(pid_file, str(real_jj))
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate(timeout=30)
            if lock_stream is not None:
                fcntl.flock(lock_stream.fileno(), fcntl.LOCK_UN)
                lock_stream.close()
                lock_stream = None
        else:
            if writer:
                writer_readme, writer_head, writer_files = _writer_edit(project)
            if mode == "sigkill":
                os.killpg(process.pid, signal.SIGKILL)
            elif barrier:
                _release(release)
            stdout, stderr = process.communicate(timeout=30)
    finally:
        if lock_stream is not None:
            fcntl.flock(lock_stream.fileno(), fcntl.LOCK_UN)
            lock_stream.close()
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate(timeout=30)

    driver_log = crash_log.read_text(encoding="utf-8") if crash_log.exists() else ""
    assert "CRASH point=" + point in driver_log, driver_log
    expected_returncode = -signal.SIGKILL if mode == "sigkill" or point == "X1j" else 137
    assert process.returncode == expected_returncode, (
        f"driver rc={process.returncode}; stdout={stdout}; stderr={stderr}; log={driver_log}"
    )

    if kind == "layer" and point != "L0":
        journal_data = json.loads(layer_journal.read_text(encoding="utf-8"))
        prepared_head = str(journal_data["prepared_head"])
        prepared_tree = str(journal_data["prepared_tree"])
        prepared_marker_digest = str(journal_data["prepared_marker_digest"])

    if writer:
        assert writer_readme is not None
        assert writer_head is not None
        assert writer_files is not None

    recovered = _run_cli(
        ["recover", "--json", "--project", str(project)], project, env,
    )
    try:
        report = json.loads(recovered.stdout)
    except ValueError as exc:
        raise AssertionError(
            f"recover emitted invalid JSON: rc={recovered.returncode}; "
            f"stdout={recovered.stdout}; stderr={recovered.stderr}",
        ) from exc

    prepublication = point in {"L0", "X0", "X1", "X1j"}
    unverified_publication = writer and point in {"A1", "L1"}
    if unverified_publication:
        assert recovered.returncode == 1, recovered.stdout + recovered.stderr
        assert report["pending_recovery"]
        assert "unverified" in report["pending_recovery"][0]["action"]
    else:
        assert recovered.returncode == 0, recovered.stdout + recovered.stderr
        assert report["ok"] is True

    if prepublication and preview is not None:
        assert report["pending_review"]
        discarded = _run_cli(
            ["discard", "--preview", str(preview), "--json"], project, env,
        )
        assert discarded.returncode == 0, discarded.stderr or discarded.stdout

    if writer:
        assert (project / "README.md").read_bytes() == writer_readme
        assert (project / "writer-notes.txt").read_bytes() == b"writer notes\n"
        assert (project / "writer-wip.txt").read_bytes() == b"writer uncommitted wip\n"
        current_head = JJ(project).commit_id("@")
        assert _is_ancestor(JJ(project), writer_head, current_head)
        if prepared_head:
            assert _is_ancestor(JJ(project), prepared_head, current_head) is not prepublication
        expected_tree = dict(before_snapshot if prepublication else prepared_snapshot)
        expected_tree.update(writer_files)
        assert _snapshot_digest(_tracked_snapshot(project, JJ(project))) == _snapshot_digest(expected_tree)
        marker_digest = before_marker_digest if prepublication else prepared_marker_digest
        assert _sha((project / ".copyroom-local.json").read_bytes()) == marker_digest
    elif prepublication:
        assert tracked_tree_digest(project, JJ(project)) == before_tree
        assert _sha((project / ".copyroom-local.json").read_bytes()) == before_marker_digest
    else:
        assert tracked_tree_digest(project, JJ(project)) == prepared_tree
        assert _sha((project / ".copyroom-local.json").read_bytes()) == prepared_marker_digest
        assert _is_ancestor(JJ(project), prepared_head, JJ(project).commit_id("@"))

    if unverified_publication:
        second = _run_cli(["recover", "--json", "--project", str(project)], project, env)
        second_report = json.loads(second.stdout)
        assert second.returncode == 1
        assert second_report["pending_recovery"] == report["pending_recovery"]
    else:
        second = _run_cli(["recover", "--json", "--project", str(project)], project, env)
        assert second.returncode == 0, second.stderr or second.stdout
        assert json.loads(second.stdout)["ok"] is True

    if not unverified_publication:
        assert not list((project / ".copyroom-local/journal").glob("*.json"))
        assert [row["name"] for row in JJ(project).workspaces()] == ["default"]
        assert not list(temporary_root.glob("copyroom-layer-*"))
    else:
        assert list((project / ".copyroom-local/journal").glob("*.json"))
        assert sorted(row["name"] for row in JJ(project).workspaces()) == sorted(
            ["default", workspace_name],
        )
        if kind == "update":
            assert preview is not None and preview.is_dir()
            assert _sidecar(preview).is_file()
        else:
            assert workspace_path.is_dir()
