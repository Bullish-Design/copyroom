#!/usr/bin/env python3
"""Test a local jj template workshop in disposable repositories."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROTOTYPE_PATH = HERE.parent / "13-local-jj-prototype/prototype.py"
GOLDEN = HERE / "fixtures/golden"
EVIDENCE = HERE / "evidence.json"
LOG: list[dict[str, object]] = []
CHECKS: list[str] = []


def command(cwd: Path, *args: str, expected: int = 0) -> str:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)
    LOG.append({
        "cwd": cwd.name,
        "argv": list(args),
        "exit": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    })
    if result.returncode != expected:
        raise AssertionError(
            f"{' '.join(args)} returned {result.returncode}, expected {expected}:\n"
            f"{result.stdout}{result.stderr}"
        )
    return result.stdout


def jj(cwd: Path, *args: str) -> str:
    return command(cwd, "jj", *args)


def revision(cwd: Path, expression: str) -> str:
    return jj(cwd, "log", "--no-graph", "--ignore-working-copy", "-r", expression, "-T", "commit_id").strip()


def manifest(root: Path) -> dict[str, tuple[str, bool]]:
    files: dict[str, tuple[str, bool]] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(part in {".jj", ".git"} for part in path.relative_to(root).parts):
            continue
        files[path.relative_to(root).as_posix()] = (
            hashlib.sha256(path.read_bytes()).hexdigest(),
            bool(path.stat().st_mode & 0o111),
        )
    return files


def check(label: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(label)
    CHECKS.append(label)
    print(f"PASS {label}")


def prototype(*args: str, cwd: Path) -> str:
    return command(cwd, sys.executable, str(PROTOTYPE_PATH), *args)


def main() -> None:
    spec = importlib.util.spec_from_file_location("prototype13", PROTOTYPE_PATH)
    assert spec is not None and spec.loader is not None
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)

    with tempfile.TemporaryDirectory(prefix="copyroom-workshop-") as temporary:
        root = Path(temporary)
        template = root / "template"
        template.mkdir()
        jj(template, "git", "init", "--colocate")
        files = template / "files"
        (files / "src/{{ module }}").mkdir(parents=True)
        (files / "README.md").write_text("# {{ module }}\n\nScenario: workshop\n", encoding="utf-8")
        (files / "src/{{ module }}/config.txt").write_text(
            "version=1\n\nname={{ module }}\n\nowner=template\n", encoding="utf-8"
        )
        jj(template, "commit", "-m", "template v1")
        base_template_revision = revision(template, "@")
        base_template_tree = manifest(template)

        answers = root / "scenario.json"
        answers.write_text(json.dumps({"module": "demo"}) + "\n", encoding="utf-8")
        project = root / "project"
        prototype(
            "new", "--template", str(files), "--target", str(project),
            "--answers", str(answers), cwd=root,
        )
        project_config = project / "src/demo/config.txt"
        project_config.write_text(
            project_config.read_text(encoding="utf-8").replace("owner=template", "owner=project"),
            encoding="utf-8",
        )
        jj(project, "commit", "-m", "project edits template-owned file")
        project_revision = revision(project, "@")
        project_tree = manifest(project)

        candidate = root / "template-candidate"
        jj(template, "workspace", "add", "--name", "candidate", "-r", "@", str(candidate))
        candidate_files = candidate / "files"
        candidate_config = candidate_files / "src/{{ module }}/config.txt"
        candidate_config.write_text(
            candidate_config.read_text(encoding="utf-8").replace("version=1", "version=2"),
            encoding="utf-8",
        )
        (candidate_files / "checks").mkdir()
        (candidate_files / "checks/ready.txt").write_text("ready={{ module }}\n", encoding="utf-8")
        jj(candidate, "commit", "-m", "template candidate v2")
        candidate_revision = revision(candidate, "@-")
        check("template edit stays in candidate workspace", manifest(template) == base_template_tree)
        check("template active revision stays at v1", revision(template, "@") == base_template_revision)

        rendered = root / "rendered-scenario"
        rendered.mkdir()
        paths = renderer.render(candidate_files, {"module": "demo"}, rendered)
        expected = manifest(GOLDEN)
        check("scenario render matches full-tree golden", manifest(rendered) == expected)
        check("scenario golden checks every rendered path", paths == set(expected))

        preview = root / "project-preview"
        jj(project, "workspace", "add", "--name", "preview", "-r", "@", str(preview))
        update = prototype(
            "update", "--project", str(preview), "--template", str(candidate_files), cwd=root,
        )
        check("update-test reports no conflict", "conflicts 0" in update)
        merged = (preview / "src/demo/config.txt").read_text(encoding="utf-8")
        check("update-test receives template change", "version=2" in merged)
        check("update-test keeps project edit", "owner=project" in merged)
        check("update-test receives added file", (preview / "checks/ready.txt").read_text() == "ready=demo\n")
        diff = jj(preview, "diff", "--from", project_revision, "--to", "@")
        check("preview diff names candidate changes", "version=2" in diff and "checks/ready.txt" in diff)
        check("preview leaves active project files unchanged", manifest(project) == project_tree)
        check("preview leaves active project revision unchanged", revision(project, "@") == project_revision)
        check("preview leaves active template files unchanged", manifest(template) == base_template_tree)

        jj(project, "workspace", "forget", "preview")
        shutil.rmtree(preview)
        check("preview cleanup keeps active project", manifest(project) == project_tree)
        check("preview cleanup keeps active template", manifest(template) == base_template_tree)

        jj(template, "new", candidate_revision, "-m", "apply template candidate")
        check("explicit template apply changes active template", manifest(template) != base_template_tree)
        applied = prototype(
            "update", "--project", str(project), "--template", str(template / "files"), cwd=root,
        )
        check("explicit project apply reports no conflict", "conflicts 0" in applied)
        check("explicit project apply receives template change", "version=2" in project_config.read_text())
        check("explicit project apply keeps local edit", "owner=project" in project_config.read_text())
        check("explicit project apply matches preview file", project_config.read_bytes() == merged.encode())

    EVIDENCE.write_text(json.dumps({
        "checks": CHECKS,
        "commands": LOG,
        "golden_manifest": expected,
        "template_candidate_revision": candidate_revision,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"RESULT {len(CHECKS)} checks passed")


if __name__ == "__main__":
    main()
