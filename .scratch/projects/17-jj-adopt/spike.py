#!/usr/bin/env python3
"""Test local adoption of an existing jj project in disposable repositories."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path


PASS = 0
LOG: list[str] = []


def jj(cwd: Path, *args: str, ok: bool = True) -> str:
    result = subprocess.run(["jj", *args], cwd=cwd, text=True, capture_output=True)
    LOG.append(f"$ {cwd.name}: jj {' '.join(args)}\nexit {result.returncode}\n{result.stdout}{result.stderr}")
    if ok and result.returncode:
        raise AssertionError(f"jj {' '.join(args)} failed: {result.stderr}")
    return result.stdout


def check(label: str, condition: bool) -> None:
    global PASS
    if not condition:
        raise AssertionError(label)
    PASS += 1
    print(f"PASS {label}")


def commit(cwd: Path, rev: str = "@") -> str:
    return jj(cwd, "log", "--ignore-working-copy", "--no-graph", "-r", rev, "-T", "commit_id").strip()


def files(root: Path) -> dict[str, bytes]:
    result = {}
    for path in root.rglob("*"):
        if not path.is_file() or ".jj" in path.parts or ".git" in path.parts:
            continue
        result[path.relative_to(root).as_posix()] = path.read_bytes()
    return result


def fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    for name, data in sorted(files(root).items()):
        digest.update(name.encode() + b"\0" + data + b"\0")
    return digest.hexdigest()


def drift(template: Path, project: Path) -> list[str]:
    source, target = files(template), files(project)
    report = []
    for name in sorted(source.keys() | target.keys()):
        if name not in target:
            report.append(f"template-only {name}")
        elif name not in source:
            report.append(f"project-only {name}")
        elif source[name] != target[name]:
            report.append(f"changed {name}")
    return report


def write_config(root: Path, value: str) -> None:
    (root / "config.txt").write_text(f"shared={value}\n", encoding="utf-8")


def scenario(root: Path, kind: str, *, conflict: bool) -> None:
    base = root / kind
    project, source, work = base / "project", base / "template", base / "render-workspace"
    project.mkdir(parents=True)
    source.mkdir(parents=True)
    jj(project, "git", "init", "--colocate")
    write_config(source, "old")
    (source / "template-only.txt").write_text("template v1\n")
    write_config(project, "project" if conflict else "old")
    (project / "README.md").write_text("local project file\n")
    jj(project, "commit", "-m", "existing project")
    p0 = commit(project, "@-")
    original = files(project)
    original_hash = fingerprint(project)
    original_head = commit(project)

    report = drift(source, project)
    LOG.append(f"DRIFT {kind}\n" + "\n".join(report) + "\n")
    check(f"{kind}: drift lists project-only path", "project-only README.md" in report)
    check(f"{kind}: drift lists template-only path", "template-only template-only.txt" in report)
    check(f"{kind}: drift identifies changed path", ("changed config.txt" in report) == conflict)
    check(f"{kind}: drift preserves active @", commit(project) == original_head)
    check(f"{kind}: drift preserves project bytes", fingerprint(project) == original_hash)

    jj(project, "workspace", "add", "--name", "render", "-r", "root()", str(work))
    for name, data in files(source).items():
        target = work / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    jj(work, "commit", "-m", "copyroom:render base T0")
    t0 = commit(work, "@-")
    check(f"{kind}: render T0 leaves active @", commit(project) == original_head)
    jj(project, "new", p0, t0, "-m", "adopt project")
    jj(project, "restore", "--from", p0)
    adopted = commit(project)
    parents = jj(project, "log", "--no-graph", "--ignore-working-copy", "-r", "parents(@)", "-T", 'commit_id ++ "\\n"').splitlines()
    check(f"{kind}: adopted commit has P0 and T0 parents", set(parents) == {p0, t0})
    check(f"{kind}: adopted tree equals original bytes", files(project) == original)
    check(f"{kind}: adopted fingerprint equals original", fingerprint(project) == original_hash)

    write_config(source, "template")
    write_config(work, "template")
    (work / "template-only.txt").write_text("template v1\n")
    jj(work, "commit", "-m", "copyroom:render base T1")
    t1 = commit(work, "@-")
    check(f"{kind}: T1 parent is T0", commit(work, f"{t1}-") == t0)
    expression = f"heads(::{adopted} & ::{t1})"
    check(f"{kind}: merge base is T0", commit(project, expression) == t0)
    jj(project, "new", adopted, t1, "-m", "update adopted project")
    conflicts = jj(project, "resolve", "--list", ok=False)
    check(f"{kind}: conflict result matches input", ("config.txt" in conflicts) == conflict)
    check(f"{kind}: project-only path survives update", (project / "README.md").read_text() == "local project file\n")
    check(f"{kind}: original template-only deletion survives update", not (project / "template-only.txt").exists())
    if conflict:
        content = (project / "config.txt").read_text()
        check(f"{kind}: project content remains in conflict", "shared=project" in content)
        check(f"{kind}: template content remains in conflict", "shared=template" in content)
    else:
        check(f"{kind}: template update lands", (project / "config.txt").read_text() == "shared=template\n")
    jj(project, "workspace", "forget", "render")
    shutil.rmtree(work)


def main() -> None:
    print(jj(Path.cwd(), "--version").strip())
    with tempfile.TemporaryDirectory(prefix="copyroom-jj-adopt-") as temp:
        root = Path(temp)
        scenario(root, "clean", conflict=False)
        scenario(root, "conflict", conflict=True)
    print(f"RESULT {PASS} checks passed")
    evidence = Path(__file__).parent / "evidence" / "2026-10-07-transcript.txt"
    evidence.write_text("\n".join(LOG), encoding="utf-8")
    print(f"evidence {evidence}")


if __name__ == "__main__":
    main()
