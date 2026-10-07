#!/usr/bin/env python3
"""Test render and preview workspaces in disposable jj repositories."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


LOG: list[str] = []
PASS = 0


def run(cwd: Path, *args: str, ok: bool = True) -> str:
    command = ["jj", *args]
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    LOG.append(f"$ {cwd.name}: {' '.join(command)}\nexit {result.returncode}\n{result.stdout}{result.stderr}")
    if ok and result.returncode:
        raise AssertionError(f"{' '.join(command)} failed:\n{result.stderr}")
    return result.stdout


def check(label: str, condition: bool) -> None:
    global PASS
    if not condition:
        raise AssertionError(label)
    PASS += 1
    print(f"PASS {label}")


def head(repo: Path) -> str:
    return run(repo, "log", "--no-graph", "--ignore-working-copy", "-r", "@", "-T", "commit_id").strip()


def tree(repo: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in repo.rglob("*") if p.is_file() and ".jj" not in p.parts and ".git" not in p.parts):
        relative = path.relative_to(repo).as_posix().encode()
        digest.update(relative + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def write(repo: Path, content: str) -> None:
    (repo / "config.txt").write_text(content, encoding="utf-8")


def forget(repo: Path, work: Path, name: str) -> None:
    run(repo, "workspace", "forget", name)
    shutil.rmtree(work)


def scenario(root: Path, name: str, *, conflict: bool, failure: str | None = None) -> None:
    project = root / name / "project"
    work = root / name / "render-workspace"
    project.mkdir(parents=True)
    run(project, "git", "init", "--colocate")
    write(project, "shared=old\n")
    run(project, "commit", "-m", "render T0")
    t0 = run(project, "log", "--no-graph", "-r", "@-", "-T", "commit_id").strip()
    if conflict:
        write(project, "shared=project\n")
    else:
        (project / "local.txt").write_text("project only\n", encoding="utf-8")
    run(project, "commit", "-m", "project work")
    p0 = run(project, "log", "--no-graph", "-r", "@-", "-T", "commit_id").strip()
    baseline_head, baseline_tree = head(project), tree(project)
    run(project, "workspace", "add", "--name", "render", "-r", t0, str(work))
    check(f"{name}: workspace add keeps active @", head(project) == baseline_head)
    check(f"{name}: workspace add keeps active files", tree(project) == baseline_tree)
    try:
        if failure == "preflight":
            raise RuntimeError("injected preflight failure")
        write(work, "shared=template\n")
        (work / "added.txt").write_text("new template file\n", encoding="utf-8")
        run(work, "commit", "-m", "render T1")
        t1 = run(work, "log", "--no-graph", "-r", "@-", "-T", "commit_id").strip()
        check(f"{name}: render keeps active @", head(project) == baseline_head)
        check(f"{name}: render keeps active files", tree(project) == baseline_tree)
        if failure == "after-render":
            raise RuntimeError("injected failure after render commit")
        run(work, "new", p0, t1, "-m", "preview")
        preview = run(work, "diff", "--from", p0, "--to", "@")
        check(f"{name}: preview shows template change", "shared=template" in preview)
        check(f"{name}: preview shows added file", "added.txt" in preview)
        check(f"{name}: preview keeps active @", head(project) == baseline_head)
        check(f"{name}: preview keeps active files", tree(project) == baseline_tree)
        conflicts = run(work, "resolve", "--list", ok=False)
        check(f"{name}: conflict result matches input", ("config.txt" in conflicts) == conflict)
        if conflict:
            check(f"{name}: project side remains in conflict", "shared=project" in (work / "config.txt").read_text())
            check(f"{name}: template side remains in conflict", "shared=template" in (work / "config.txt").read_text())
        else:
            check(f"{name}: local file survives preview", (work / "local.txt").read_text() == "project only\n")
        LOG.append(f"preview for {name}:\n{preview}")
        if failure == "after-apply":
            operation = run(
                project, "op", "log", "--at-op=@", "--ignore-working-copy",
                "--no-graph", "-n", "1", "-T", "id",
            ).strip()
            run(project, "new", p0, t1, "-m", "apply update")
            check(f"{name}: apply changes active @", head(project) != baseline_head)
            check(f"{name}: apply changes active files", tree(project) != baseline_tree)
            (project / ".copyroom-local.json").write_text('{"revision": 1}\n')
            run(project, "commit", "-m", "save inputs")
            check(f"{name}: marker commit changes active files", tree(project) != baseline_tree)
            run(project, "op", "restore", operation)
            check(f"{name}: operation restore recovers active @", head(project) == baseline_head)
            check(f"{name}: operation restore recovers active files", tree(project) == baseline_tree)
            raise RuntimeError("injected failure after active apply")
    except RuntimeError as exc:
        check(f"{name}: expected failure injected", failure is not None and "injected" in str(exc))
    finally:
        forget(project, work, "render")
    check(f"{name}: cleanup keeps active @", head(project) == baseline_head)
    check(f"{name}: cleanup keeps active files", tree(project) == baseline_tree)
    check(f"{name}: cleanup removes workspace", not work.exists())
    check(f"{name}: active workspace stays registered", "default" in run(project, "workspace", "list"))
    check(f"{name}: render workspace unregistered", "render" not in run(project, "workspace", "list"))


def relocation(root: Path) -> None:
    template = root / "origin" / "template"
    project = root / "origin" / "project"
    template.mkdir(parents=True)
    project.mkdir(parents=True)
    (template / "config.txt").write_text("v1\n", encoding="utf-8")
    marker = {"template": str(template.resolve()), "revision": 0}
    (project / ".copyroom-local.json").write_text(json.dumps(marker), encoding="utf-8")
    new = root / "moved"
    shutil.move(str(root / "origin"), str(new))
    saved = json.loads((new / "project" / ".copyroom-local.json").read_text())
    check("relocation: saved absolute template path breaks", not Path(saved["template"]).exists())
    relative = Path("../template")
    check("relocation: relative sibling template path resolves", (new / "project" / relative / "config.txt").read_text() == "v1\n")
    only_project = root / "project-only"
    shutil.copytree(new / "project", only_project)
    check("relocation: project alone lacks sibling template", not (only_project / relative).exists())


def prototype_relocation(root: Path) -> None:
    prototype = Path(__file__).parent.parent / "13-local-jj-prototype" / "prototype.py"
    origin = root / "prototype-origin"
    template = origin / "template"
    project = origin / "project"
    template.mkdir(parents=True)
    (template / "config.txt").write_text("name={{ name }}\nversion=1\n", encoding="utf-8")
    answers = origin / "answers.json"
    answers.write_text('{"name":"example"}\n', encoding="utf-8")

    def command(*args: str) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [sys.executable, str(prototype), *args], cwd=root,
            capture_output=True, text=True, check=False,
        )
        LOG.append(
            f"$ prototype {' '.join(args)}\nexit {result.returncode}\n"
            f"{result.stdout}{result.stderr}"
        )
        return result

    created = command(
        "new", "--template", str(template), "--target", str(project),
        "--answers", str(answers),
    )
    check("prototype relocation: create succeeds", created.returncode == 0)
    moved = root / "prototype-moved"
    shutil.move(str(origin), str(moved))
    template = moved / "template"
    project = moved / "project"
    (template / "config.txt").write_text("name={{ name }}\nversion=2\n", encoding="utf-8")
    failed = command("update", "--project", str(project))
    check("prototype relocation: saved absolute source fails", failed.returncode == 2)
    check("prototype relocation: failure names missing local source", "source must be a local directory" in failed.stderr)
    recovered = command("update", "--project", str(project), "--template", str(template))
    check("prototype relocation: explicit source recovers", recovered.returncode == 0)
    check("prototype relocation: updated content appears", "version=2" in (project / "config.txt").read_text())


def main() -> None:
    print(run(Path.cwd(), "--version").strip())
    with tempfile.TemporaryDirectory(prefix="copyroom-jj-workspace-") as temp:
        root = Path(temp)
        scenario(root, "clean", conflict=False)
        scenario(root, "conflict", conflict=True)
        scenario(root, "preflight-failure", conflict=False, failure="preflight")
        scenario(root, "after-render-failure", conflict=False, failure="after-render")
        scenario(root, "after-apply-failure", conflict=False, failure="after-apply")
        relocation(root)
        prototype_relocation(root)
    print(f"RESULT {PASS} checks passed")
    evidence = Path(__file__).parent / "evidence" / "2026-10-07-transcript.txt"
    evidence.write_text("\n".join(LOG), encoding="utf-8")
    print(f"evidence {evidence}")


if __name__ == "__main__":
    main()
