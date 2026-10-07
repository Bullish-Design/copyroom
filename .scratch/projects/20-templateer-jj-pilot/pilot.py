#!/usr/bin/env python3
"""Test a Templateer tree update with plain jj in disposable repos."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

from templateer.api import TemplateRegistry

ROOT = Path(__file__).resolve().parent
COPYROOM = ROOT.parents[2]
TREE_SPIKE = COPYROOM / ".scratch/projects/14-templateer-tree"
sys.path.insert(0, str(TREE_SPIKE))

from spike import fingerprint, output_path, plan, write_tree  # noqa: E402

JJ = Path(os.environ["JJ_BIN"]).resolve()
LOG: list[str] = []
PASSED = 0


def jj(cwd: Path, *args: str, ok: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run([str(JJ), *args], cwd=cwd, capture_output=True, text=True)
    LOG.append(f"$ {cwd.name}: jj {' '.join(args)}\nexit {result.returncode}\n{result.stdout}{result.stderr}")
    if ok and result.returncode:
        raise AssertionError(f"jj {' '.join(args)}: {result.stderr}")
    return result


def check(label: str, condition: bool) -> None:
    global PASSED
    if not condition:
        raise AssertionError(label)
    PASSED += 1
    print(f"PASS {label}")


def rev(cwd: Path, expression: str) -> str:
    return jj(cwd, "log", "--no-graph", "--ignore-working-copy", "-r", expression, "-T", "commit_id").stdout.strip()


def conflicts(cwd: Path) -> list[str]:
    result = jj(cwd, "resolve", "--list", ok=False)
    if result.returncode == 2 and "No conflicts found at this revision" in result.stderr:
        return []
    if result.returncode:
        raise AssertionError(f"jj resolve --list: {result.stderr}")
    return [line.split()[0] for line in result.stdout.splitlines() if line.strip()]


def files(root: Path) -> dict[str, tuple[bytes, int]]:
    return {
        path.relative_to(root).as_posix(): (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
        for path in root.rglob("*")
        if path.is_file() and ".jj" not in path.parts and ".git" not in path.parts
    }


def capture_tree(root: Path, label: str) -> None:
    destination = ROOT / "evidence/2026-10-07/snapshots" / label
    if destination.exists():
        shutil.rmtree(destination)
    for name, (content, mode) in files(root).items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        target.chmod(mode)


def digest_source(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        relative = path.relative_to(root).as_posix().encode("utf-8")
        content = path.read_bytes()
        for piece in (relative, content):
            digest.update(len(piece).to_bytes(8, "big"))
            digest.update(piece)
    return digest.hexdigest()


def digest_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metadata(source: Path, manifest: Path, answers: Path, revision: int) -> dict[str, object]:
    return {
        "schema": 1,
        "revision": revision,
        "source": str(source.resolve()),
        "source_digest": digest_source(source),
        "manifest_digest": digest_file(manifest),
        "answers_digest": digest_file(answers),
        "composer_digest": digest_file(TREE_SPIKE / "spike.py"),
        "templateer_version": importlib.metadata.version("templateer"),
    }


def render(source: Path, destination: Path) -> str:
    manifest = TREE_SPIKE / "manifest.json"
    answers = TREE_SPIKE / "answers.json"
    output = plan(
        source,
        json.loads(manifest.read_text(encoding="utf-8")),
        json.loads(answers.read_text(encoding="utf-8")),
    )
    with tempfile.TemporaryDirectory(prefix="templateer-pilot-render-") as staged:
        stage = Path(staged)
        write_tree(output, stage)
        digest = fingerprint(stage)
        shutil.copytree(stage, destination, dirs_exist_ok=True)
    return digest


def validate_project_tree(source: Path, project: Path) -> list[str]:
    manifest = json.loads((TREE_SPIKE / "manifest.json").read_text(encoding="utf-8"))
    answers = json.loads((TREE_SPIKE / "answers.json").read_text(encoding="utf-8"))
    registry = TemplateRegistry.from_paths([source])
    findings: list[str] = []
    for name in manifest["templates"]:
        template = registry.get_template(name)
        path = output_path(template.metadata.output.path, answers)
        artifact = (project / path).read_text(encoding="utf-8")
        errors, warnings = registry.validate_artifact(name, artifact, model_data=answers)
        findings.extend(f"{name}: {finding}" for finding in [*errors, *warnings])
    return findings


def wipe_working_copy(workspace: Path) -> None:
    for entry in workspace.iterdir():
        if entry.name in {".jj", ".git"}:
            continue
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()


def write_marker(project: Path, source: Path, revision: int) -> None:
    data = metadata(source, TREE_SPIKE / "manifest.json", TREE_SPIKE / "answers.json", revision)
    (project / ".copyroom-pilot.json").write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def prep_sources(root: Path, *, conflict: bool) -> tuple[Path, Path]:
    original = TREE_SPIKE / "fixtures"
    v1 = root / "template-v1"
    v2 = root / "template-v2"
    shutil.copytree(original, v1)
    shutil.copytree(original, v2)
    pyproject = v2 / "pyproject" / "template.j2"
    pyproject.write_text(pyproject.read_text() + '\nclassifiers = ["Development Status :: 3 - Alpha"]\n')
    settings = v2 / "settings" / "template.j2"
    settings.write_text(settings.read_text() + 'revision: "v2"\n')
    if conflict:
        readme = v2 / "readme" / "template.j2"
        readme.write_text(readme.read_text().replace("# {{ project_name }}", "# Project {{ project_name }}"))
    return v1, v2


def scenario(root: Path, name: str, *, conflict: bool) -> None:
    area = root / name
    area.mkdir()
    v1, v2 = prep_sources(area, conflict=conflict)
    project = area / "project"
    project.mkdir()
    jj(project, "git", "init", "--colocate")
    t0_fingerprint = render(v1, project)
    jj(project, "commit", "-m", "render T0")
    t0 = rev(project, "@-")
    check(f"{name}: T0 contains five Templateer artifacts", len(files(project)) == 5)

    write_marker(project, v1, 0)
    (project / "notes.txt").write_text("project owned\n", encoding="utf-8")
    if conflict:
        readme = project / "README.md"
        readme.write_text(readme.read_text().replace("# cedar-lab", "# Local cedar-lab"))
    else:
        pyproject = project / "pyproject.toml"
        pyproject.write_text(pyproject.read_text().replace('version = "0.1.0"', 'version = "0.1.1"'))
    jj(project, "commit", "-m", "project changes and render inputs")
    p0 = rev(project, "@-")
    active_before = rev(project, "@")
    bytes_before = files(project)
    marker_before = json.loads((project / ".copyroom-pilot.json").read_text())
    check(f"{name}: marker pins v1 source digest", marker_before["source_digest"] == digest_source(v1))
    check(
        f"{name}: marker pins Templateer version",
        marker_before["templateer_version"] == importlib.metadata.version("templateer"),
    )
    check(
        f"{name}: marker pins composer digest",
        marker_before["composer_digest"] == digest_file(TREE_SPIKE / "spike.py"),
    )

    work = area / "preview-workspace"
    jj(project, "workspace", "add", "--name", "pilot-preview", "-r", t0, str(work))
    try:
        check(f"{name}: workspace add keeps active @", rev(project, "@") == active_before)
        check(f"{name}: workspace add keeps active bytes", files(project) == bytes_before)
        wipe_working_copy(work)
        t1_fingerprint = render(v2, work)
        check(f"{name}: T1 render bytes differ from T0", t1_fingerprint != t0_fingerprint)
        jj(work, "commit", "-m", "render T1")
        t1 = rev(work, "@-")
        base = rev(work, f"heads(::{p0} & ::{t1})")
        check(f"{name}: merge base is T0", base == t0)
        check(f"{name}: render keeps active @", rev(project, "@") == active_before)
        check(f"{name}: render keeps active bytes", files(project) == bytes_before)

        jj(work, "new", p0, t1, "-m", "preview")
        diff = jj(work, "diff", "--from", p0, "--to", "@").stdout
        LOG.append(f"preview {name}:\n{diff}")
        check(f"{name}: preview shows template change", "revision: " in diff)
        check(f"{name}: preview keeps active @", rev(project, "@") == active_before)
        check(f"{name}: preview keeps active bytes", files(project) == bytes_before)
        conflict_paths = conflicts(work)
        check(f"{name}: conflict report matches case", bool(conflict_paths) == conflict)
        if conflict:
            check(f"{name}: conflict report names README", "README.md" in conflict_paths)
        capture_tree(work, f"{name}-preview")
        check(f"{name}: preview keeps project-only file", (work / "notes.txt").read_text() == "project owned\n")
        if conflict:
            check(f"{name}: conflict holds local heading", "# Local cedar-lab" in (work / "README.md").read_text())
            check(f"{name}: conflict holds template heading", "# Project cedar-lab" in (work / "README.md").read_text())
            print(f"CONFLICT {name} README.md")
            return

        preview_files = files(work)
        check(f"{name}: merged preview passes Templateer validators", not validate_project_tree(v2, work))
        check(f"{name}: local TOML edit survives", b'version = "0.1.1"' in preview_files["pyproject.toml"][0])
        check(f"{name}: template TOML edit arrives", b"classifiers" in preview_files["pyproject.toml"][0])
        check(f"{name}: executable mode survives preview", preview_files["scripts/about.py"][1] == 0o755)
        module_path = "src/cedar_lab/__init__.py"
        check(
            f"{name}: generated module bytes survive preview",
            preview_files[module_path] == bytes_before[module_path],
        )

        jj(project, "new", p0, t1, "-m", "apply Templateer update")
        check(f"{name}: explicit apply changes active @", rev(project, "@") != active_before)
        check(f"{name}: applied bytes match preview", files(project) == preview_files)
        write_marker(project, v2, 1)
        jj(project, "commit", "-m", "save new render inputs")
        marker_after = json.loads((project / ".copyroom-pilot.json").read_text())
        check(f"{name}: marker records v2 source digest", marker_after["source_digest"] == digest_source(v2))
        check(
            f"{name}: marker records Templateer version",
            marker_after["templateer_version"] == importlib.metadata.version("templateer"),
        )
        check(f"{name}: marker source digest changed", marker_after["source_digest"] != marker_before["source_digest"])
        applied_files = files(project)
        check(f"{name}: applied content differs only by marker", {
            key: value for key, value in applied_files.items() if key != ".copyroom-pilot.json"
        } == {
            key: value for key, value in preview_files.items() if key != ".copyroom-pilot.json"
        })
        check(f"{name}: applied script stays executable", applied_files["scripts/about.py"][1] == 0o755)
        check(f"{name}: applied project-only file survives", applied_files["notes.txt"][0] == b"project owned\n")
        check(f"{name}: applied merge has no conflicts", not conflicts(project))
        check(f"{name}: applied tree passes Templateer validators", not validate_project_tree(v2, project))
        capture_tree(project, "clean-applied")
    finally:
        jj(project, "workspace", "forget", "pilot-preview")
        shutil.rmtree(work)
    check(f"{name}: preview workspace removed", not work.exists())


def main() -> None:
    evidence = ROOT / "evidence/2026-10-07"
    evidence.mkdir(parents=True, exist_ok=True)
    print("jj", jj(ROOT, "--version").stdout.strip())
    print("python", sys.version.split()[0])
    print("templateer", importlib.metadata.version("templateer"))
    print("jj binary", JJ)
    try:
        with tempfile.TemporaryDirectory(prefix="copyroom-templateer-jj-") as temp:
            disposable = Path(temp)
            scenario(disposable, "clean", conflict=False)
            scenario(disposable, "conflict", conflict=True)
        print(f"RESULT {PASSED} checks passed")
    finally:
        (evidence / "jj-transcript.txt").write_text("\n".join(LOG), encoding="utf-8")


if __name__ == "__main__":
    main()
