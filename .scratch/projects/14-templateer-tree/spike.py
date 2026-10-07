#!/usr/bin/env python3
"""Compose local Templateer artifacts into one project tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import stat
import tempfile
from pathlib import Path

from templateer.api import TemplateRegistry

ROOT = Path(__file__).resolve().parent
SEGMENT = re.compile(r"^\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}$")
RESERVED = {".git", ".jj", ".devenv", ".direnv"}


class CompositionError(Exception):
    """The project tree cannot be rendered safely."""


def output_path(pattern: str, answers: dict[str, object]) -> Path:
    if not pattern or pattern.startswith("/") or "\\" in pattern or "\x00" in pattern:
        raise CompositionError(f"unsafe output path: {pattern!r}")
    parts: list[str] = []
    for part in pattern.split("/"):
        match = SEGMENT.fullmatch(part)
        if match:
            value = answers.get(match.group(1))
            if not isinstance(value, str):
                raise CompositionError(f"path answer {match.group(1)!r} must be text")
            part = value
        if (
            part in {"", ".", ".."}
            or part in RESERVED
            or "/" in part
            or "\\" in part
            or "\x00" in part
            or "{{" in part
            or "}}" in part
        ):
            raise CompositionError(f"unsafe output path: {pattern!r}")
        parts.append(part)
    return Path(*parts)


def plan(
    fixture_root: Path, manifest: dict[str, object], answers: dict[str, object]
) -> dict[str, tuple[bytes, int]]:
    names = manifest.get("templates")
    executables = manifest.get("executable")
    if not isinstance(names, list) or not names or not all(isinstance(n, str) for n in names):
        raise CompositionError("manifest templates must be a nonempty text list")
    if not isinstance(executables, list) or not all(isinstance(p, str) for p in executables):
        raise CompositionError("manifest executable must be a text list")

    registry = TemplateRegistry.from_paths([fixture_root])
    files: dict[str, tuple[bytes, int]] = {}
    schema_json: str | None = None
    for name in names:
        template = registry.get_template(name)
        if template.metadata.output.kind != "full_file":
            raise CompositionError(f"{name}: only full_file outputs form a project tree")
        actual_schema = json.dumps(template.get_schema_json(), sort_keys=True)
        if schema_json is not None and actual_schema != schema_json:
            raise CompositionError(f"{name}: model schema differs from the first template")
        schema_json = actual_schema

        relative = output_path(template.metadata.output.path, answers)
        path = relative.as_posix()
        if path in files:
            raise CompositionError(f"two templates own {path}")
        for previous in files:
            if path.startswith(previous + "/") or previous.startswith(path + "/"):
                raise CompositionError(f"file and directory collide: {path} and {previous}")

        artifact = registry.render_from_model(name, answers)
        errors, warnings = registry.validate_artifact(name, artifact, model_data=answers)
        if errors or warnings:
            raise CompositionError(f"{name}: errors={errors!r}; warnings={warnings!r}")
        mode = 0o755 if path in executables else 0o644
        files[path] = (artifact.encode("utf-8"), mode)

    if set(executables) - set(files):
        raise CompositionError(f"executable path has no artifact: {set(executables) - set(files)}")
    return files


def write_tree(files: dict[str, tuple[bytes, int]], destination: Path) -> None:
    if destination.exists() and any(destination.iterdir()):
        raise CompositionError(f"destination is not empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    for name, (content, mode) in sorted(files.items()):
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        target.chmod(mode)


def fingerprint(destination: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in destination.rglob("*") if p.is_file()):
        relative = path.relative_to(destination).as_posix().encode("utf-8")
        content = path.read_bytes()
        mode = stat.S_IMODE(path.stat().st_mode)
        for piece in (relative, f"{mode:o}".encode(), content):
            digest.update(len(piece).to_bytes(8, "big"))
            digest.update(piece)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixtures", type=Path, default=ROOT / "fixtures")
    parser.add_argument("--manifest", type=Path, default=ROOT / "manifest.json")
    parser.add_argument("--answers", type=Path, default=ROOT / "answers.json")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    answers = json.loads(args.answers.read_text(encoding="utf-8"))
    if not isinstance(answers, dict):
        raise CompositionError("saved answers must be a JSON object")
    files = plan(args.fixtures, manifest, answers)
    with tempfile.TemporaryDirectory(prefix="templateer-tree-") as staged:
        stage = Path(staged)
        write_tree(files, stage)
        if args.out.exists() and any(args.out.iterdir()):
            raise CompositionError(f"destination is not empty: {args.out}")
        shutil.copytree(stage, args.out, dirs_exist_ok=True)
        print(f"sha256 {fingerprint(args.out)}")
        for name in sorted(files):
            print(f"{files[name][1]:04o} {name}")


if __name__ == "__main__":
    main()
