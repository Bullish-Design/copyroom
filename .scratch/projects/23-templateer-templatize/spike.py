#!/usr/bin/env python3
"""Extract a local project into Templateer artifacts and compare whole trees."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from templateer.api import TemplateRegistry

HERE = Path(__file__).resolve().parent
EVIDENCE = HERE / "evidence.json"
CHECKS: list[str] = []


def check(label: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(label)
    CHECKS.append(label)
    print(f"PASS {label}")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def manifest(root: Path) -> dict[str, dict[str, object]]:
    entries: dict[str, dict[str, object]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            entries[relative] = {"type": "symlink", "target": str(path.readlink())}
        elif path.is_file():
            entries[relative] = {
                "type": "file",
                "sha256": digest(path.read_bytes()),
                "executable": bool(path.stat().st_mode & 0o111),
            }
    return entries


def source_project(root: Path) -> Path:
    project = root / "existing-project"
    (project / "src").mkdir(parents=True)
    (project / "scripts").mkdir()
    (project / "assets").mkdir()
    (project / "docs").mkdir()
    (project / "pyproject.toml").write_text(
        '[project]\nname = "alpha"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    (project / "README.md").write_text("# alpha\n\nLocal example.\n", encoding="utf-8")
    (project / "src/main.py").write_text('MESSAGE = "ready"\n', encoding="utf-8")
    script = project / "scripts/hello.sh"
    script.write_text("#!/bin/sh\nprintf '%s\\n' 'hello'\n", encoding="utf-8")
    script.chmod(0o755)
    (project / "assets/pixel.bin").write_bytes(bytes([0, 255, 1, 2]))
    (project / "docs/current").symlink_to("../README.md")
    return project


def language(path: Path) -> str:
    return {".toml": "toml", ".md": "markdown", ".py": "python"}.get(path.suffix, "text")


def extract(source: Path, root: Path) -> list[dict[str, object]]:
    catalog = root / "templates"
    static = root / "static"
    catalog.mkdir(parents=True)
    static.mkdir()
    plan: list[dict[str, object]] = []
    for index, path in enumerate(sorted(source.rglob("*"))):
        relative = path.relative_to(source)
        if path.is_symlink():
            destination = static / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.symlink_to(path.readlink())
            plan.append({"path": relative.as_posix(), "kind": "symlink", "target": str(path.readlink())})
            continue
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            destination = static / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
            plan.append({"path": relative.as_posix(), "kind": "binary", "sha256": digest(path.read_bytes())})
            continue
        name = f"artifact_{index:02d}"
        template = catalog / name
        template.mkdir()
        metadata = {
            "name": name,
            "description": f"File extracted from {relative.as_posix()}",
            "output": {"path": relative.as_posix(), "language": language(path)},
            "schema": {"module": "schema", "class": "Inputs"},
            "prompt": {"file": "prompt.md"},
            "renderer": {"engine": "minijinja", "file": "template.j2"},
        }
        (template / "metadata.yml").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        (template / "schema.py").write_text(
            "from pydantic import BaseModel\n\nclass Inputs(BaseModel):\n    project_name: str\n",
            encoding="utf-8",
        )
        (template / "prompt.md").write_text("Generate this project artifact.\n", encoding="utf-8")
        # MiniJinja removes one trailing newline. Add one in the source so
        # the rendered artifact keeps the original file's exact byte count.
        (template / "template.j2").write_text(
            text + ("\n" if text.endswith("\n") else ""), encoding="utf-8"
        )
        plan.append({
            "path": relative.as_posix(), "kind": "templateer", "template": name,
            "language": language(path), "executable": bool(path.stat().st_mode & 0o111),
        })
    (root / "plan.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    return plan


def render(root: Path, plan: list[dict[str, object]], project_name: str, output: Path) -> None:
    registry = TemplateRegistry.from_paths([root / "templates"])
    for item in plan:
        relative = Path(str(item["path"]))
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if item["kind"] == "templateer":
            name = str(item["template"])
            artifact = registry.render_from_model(name, {"project_name": project_name})
            errors, warnings = registry.validate_artifact(name, artifact)
            if errors or warnings:
                raise AssertionError(f"{relative}: {errors}; {warnings}")
            destination.write_bytes(artifact.encode("utf-8"))
            destination.chmod(0o755 if item["executable"] else 0o644)
        elif item["kind"] == "binary":
            shutil.copy2(root / "static" / relative, destination)
        else:
            os.symlink(str(item["target"]), destination)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="templateer-templatize-") as temporary:
        root = Path(temporary)
        original = source_project(root)
        golden = manifest(original)
        extracted = root / "extracted"
        plan = extract(original, extracted)
        check("extracts four Templateer text artifacts", sum(item["kind"] == "templateer" for item in plan) == 4)
        check("classifies one binary for static copy", sum(item["kind"] == "binary" for item in plan) == 1)
        check("classifies one symlink for static copy", sum(item["kind"] == "symlink" for item in plan) == 1)

        first = root / "initial-render"
        render(extracted, plan, "alpha", first)
        check("initial extraction matches full project tree", manifest(first) == golden)
        check("executable script mode survives", manifest(first)["scripts/hello.sh"]["executable"] is True)
        check("binary bytes survive", (first / "assets/pixel.bin").read_bytes() == bytes([0, 255, 1, 2]))
        check("relative symlink survives", (first / "docs/current").readlink() == Path("../README.md"))

        templates_by_path = {
            str(item["path"]): extracted / "templates" / str(item["template"]) / "template.j2"
            for item in plan if item["kind"] == "templateer"
        }
        pyproject = templates_by_path["pyproject.toml"]
        pyproject.write_text(
            pyproject.read_text(encoding="utf-8").replace('name = "alpha"', 'name = "{{ project_name }}"'),
            encoding="utf-8",
        )
        readme = templates_by_path["README.md"]
        readme.write_text(
            readme.read_text(encoding="utf-8").replace("# alpha", "# {{ project_name }}"),
            encoding="utf-8",
        )
        original_after_parameterization = root / "golden-render"
        render(extracted, plan, "alpha", original_after_parameterization)
        check("parameterized original still matches golden tree", manifest(original_after_parameterization) == golden)

        probe = root / "probe-render"
        render(extracted, plan, "beta", probe)
        probe_manifest = manifest(probe)
        differences = sorted(path for path in golden if golden[path] != probe_manifest.get(path))
        check("probe changes exactly two text files", differences == ["README.md", "pyproject.toml"])
        check("probe substitutes TOML project name", 'name = "beta"' in (probe / "pyproject.toml").read_text())
        check("probe substitutes Markdown heading", (probe / "README.md").read_text().startswith("# beta\n"))
        check("probe preserves executable mode", probe_manifest["scripts/hello.sh"]["executable"] is True)
        check("probe preserves binary and symlink", all(
            probe_manifest[path] == golden[path] for path in ("assets/pixel.bin", "docs/current")
        ))

    EVIDENCE.write_text(json.dumps({
        "checks": CHECKS,
        "golden_manifest": golden,
        "probe_changed_paths": differences,
        "probe_manifest": probe_manifest,
        "extraction_plan": plan,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"RESULT {len(CHECKS)} checks passed")


if __name__ == "__main__":
    main()
