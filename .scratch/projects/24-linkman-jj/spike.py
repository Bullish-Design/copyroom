#!/usr/bin/env python3
"""Test Linkman links alongside local jj render commits in disposable repos."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
LINKMAN = Path("/home/andrew/Documents/Projects/linkman")
PROTOTYPE = ROOT.parent / "13-local-jj-prototype" / "prototype.py"
WORK = ROOT / ".devenv" / "state" / "run"
LOG: list[str] = []
PASS = 0


def command(cwd: Path, args: list[str], *, expected: set[int] = {0}) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)
    LOG.append(f"$ {cwd}: {' '.join(args)}\nexit {result.returncode}\n{result.stdout}{result.stderr}")
    if result.returncode not in expected:
        raise AssertionError(f"{' '.join(args)}: exit {result.returncode}: {result.stderr}")
    return result


def check(label: str, condition: bool) -> None:
    global PASS
    if not condition:
        raise AssertionError(label)
    PASS += 1
    print(f"PASS {label}")


def jj(repo: Path, *args: str) -> str:
    return command(repo, ["jj", *args]).stdout.strip()


def head(repo: Path) -> str:
    return jj(repo, "log", "--no-graph", "-r", "@", "-T", "commit_id")


def linkman(repo: Path, verb: str, overlay: Path, *, expected: set[int] = {0}) -> dict:
    result = command(
        LINKMAN,
        [
            "devenv", "shell", "--", "linkman", verb,
            "--repo-root", str(repo), "--config", str(repo / "links.yaml"),
            "--overlay", str(overlay), "--json",
        ],
        expected=expected,
    )
    output = result.stdout or result.stderr
    start = output.find('{\n  "schema_version"')
    if start < 0:
        raise AssertionError(f"Linkman returned no JSON: {result.stdout!r} {result.stderr!r}")
    return json.loads(output[start:])


def config(repo: Path, target: Path) -> None:
    (repo / "links.yaml").write_text(
        json.dumps({"version": 1, "links": {"ruff.toml": {"target": str(target)}}}) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    print(jj(ROOT, "--version"))
    if WORK.exists():
        marker = WORK / ".spike-owned"
        if not marker.exists():
            raise AssertionError("refuse to remove run directory without spike marker")
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)
    (WORK / ".spike-owned").write_text("spike-owned\n")
    shared = WORK / "shared"
    shared.mkdir()
    target = shared / "style.toml"
    target.write_text("line-length = 100\n")
    overlay = WORK / "empty-overlay"
    overlay.mkdir()

    template_v1 = WORK / "template-v1"
    template_v2 = WORK / "template-v2"
    template_v1.mkdir()
    template_v2.mkdir()
    (template_v1 / "README.md").write_text("project={{ name }}\nversion=1\n")
    (template_v2 / "README.md").write_text("project={{ name }}\nversion=2\n")
    answers = WORK / "answers.json"
    answers.write_text('{"name": "example"}\n')

    first = WORK / "project-a"
    second = WORK / "project-b"
    command(
        ROOT,
        [sys.executable, str(PROTOTYPE), "new", "--template", str(template_v1),
         "--target", str(first), "--answers", str(answers)],
    )
    second.mkdir()
    jj(second, "git", "init", "--colocate")
    (second / "README.md").write_text("plain jj project\n")
    jj(second, "commit", "-m", "initial project")

    for project in (first, second):
        config(project, target)
        result = linkman(project, "apply", overlay)
        check(f"{project.name}: Linkman applied link", not result.get("failed") and (project / "ruff.toml").is_symlink())
        check(f"{project.name}: target content visible", (project / "ruff.toml").read_text() == "line-length = 100\n")
        check(f"{project.name}: link has declared target", os.readlink(project / "ruff.toml") == str(target))
        jj(project, "commit", "-m", "add Linkman declaration and link")
        tracked = jj(project, "file", "list", "-r", "@-")
        check(f"{project.name}: jj tracks link path", "ruff.toml" in tracked.splitlines())
        patch = jj(project, "show", "-r", "@-", "--git")
        check(f"{project.name}: jj stores symlink and target path", "new file mode 120000" in patch and f"+{target}" in patch)

    heads = {project.name: head(project) for project in (first, second)}
    target.write_text("line-length = 120\n")
    for project in (first, second):
        check(f"{project.name}: shared edit propagates", (project / "ruff.toml").read_text() == "line-length = 120\n")
        jj(project, "status")
        check(f"{project.name}: shared edit leaves jj @ unchanged", head(project) == heads[project.name])
        check(f"{project.name}: Linkman remains clean", linkman(project, "check", overlay)["clean"])

    moved = shared / "style-moved.toml"
    target.rename(moved)
    for project in (first, second):
        check(f"{project.name}: source move breaks link", (project / "ruff.toml").is_symlink() and not (project / "ruff.toml").exists())
        check(f"{project.name}: Linkman check sees raw link as correct", linkman(project, "check", overlay)["clean"])
        linkman(project, "apply", overlay)
        check(f"{project.name}: apply does not repair missing target", not (project / "ruff.toml").exists())

    for project in (first, second):
        config(project, moved)
        linkman(project, "apply", overlay)
        check(f"{project.name}: changed declaration repoints link", os.readlink(project / "ruff.toml") == str(moved))
        check(f"{project.name}: repointed content visible", (project / "ruff.toml").read_text() == "line-length = 120\n")
        jj(project, "commit", "-m", "repoint shared link")

    check("template omits Linkman path at v1", not (template_v1 / "ruff.toml").exists())
    check("template omits Linkman path at v2", not (template_v2 / "ruff.toml").exists())
    command(
        ROOT,
        [sys.executable, str(PROTOTYPE), "update", "--project", str(first),
         "--template", str(template_v2)],
    )
    check("prototype update lands template content", "version=2" in (first / "README.md").read_text())
    check("prototype update keeps project-owned link", (first / "ruff.toml").is_symlink())
    check("prototype update keeps target content", (first / "ruff.toml").read_text() == "line-length = 120\n")
    check("Linkman check is clean after template update", linkman(first, "check", overlay)["clean"])

    owning_template = WORK / "template-owns-link"
    owning_template.mkdir()
    (owning_template / "README.md").write_text("project={{ name }}\n")
    (owning_template / "ruff.toml").write_text("generated content\n")
    third = WORK / "project-c"
    command(
        ROOT,
        [sys.executable, str(PROTOTYPE), "new", "--template", str(owning_template),
         "--target", str(third), "--answers", str(answers)],
    )
    config(third, moved)
    refused = linkman(third, "apply", overlay, expected={11})
    check("Linkman refuses a template-owned regular file", bool(refused["refused"]))
    check("Linkman preserves template-owned bytes", (third / "ruff.toml").read_text() == "generated content\n")
    check("collision leaves regular file in place", not (third / "ruff.toml").is_symlink())

    print(f"RESULT {PASS} checks passed")
    evidence = ROOT / "evidence" / "2026-10-07-transcript.txt"
    evidence.write_text("\n".join(LOG), encoding="utf-8")
    print(f"evidence {evidence}")


if __name__ == "__main__":
    main()
