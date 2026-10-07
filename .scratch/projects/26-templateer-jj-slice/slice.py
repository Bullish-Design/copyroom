#!/usr/bin/env python3
"""Create and update a local project with Templateer and plain jj."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import templateer
from templateer.api import TemplateRegistry
from templateer.renderer import RenderError
from templateer.template import TemplateLoadError, TemplateNotFoundError

MARKER = ".copyroom-local.json"
PREVIEW_SUFFIX = ".copyroom-preview.json"
PATH_FIELD = re.compile(r"^\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}$")
RESERVED = {".git", ".jj", ".devenv", ".direnv", ".venv", MARKER}
LOCAL_DIRS = {".git", ".jj", ".devenv", ".direnv", ".venv", "__pycache__"}


class SliceError(Exception):
    """A local input or jj action failed."""

    def __init__(self, message: str, code: int = 2) -> None:
        super().__init__(message)
        self.code = code


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(3, f"error: {message}\n")


def jj(project: Path, *args: str, allow_no_conflicts: bool = False) -> str:
    result = subprocess.run(
        ["jj", *args], cwd=project, text=True, capture_output=True, check=False
    )
    if allow_no_conflicts and result.returncode == 2 and "No conflicts found" in result.stderr:
        return ""
    if result.returncode:
        raise SliceError(f"jj {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout


def commit_id(project: Path, rev: str) -> str:
    value = jj(project, "log", "--no-graph", "-r", rev, "-T", "commit_id").strip()
    if len(value) != 40:
        raise SliceError(f"expected one commit for {rev}")
    return value


def current_operation(project: Path) -> str:
    return jj(
        project, "op", "log", "--at-op=@", "--ignore-working-copy",
        "--no-graph", "-n", "1", "-T", "id",
    ).strip()


def conflicts(project: Path) -> list[str]:
    output = jj(project, "resolve", "--list", allow_no_conflicts=True)
    return [line.split()[0] for line in output.splitlines() if line.strip()]


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SliceError(f"cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SliceError(f"expected a JSON object in {path}")
    return data


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_source(source: Path) -> str:
    if not source.is_dir() or source.is_symlink():
        raise SliceError(f"source must be a local directory: {source}")
    if (
        not (source / "manifest.json").is_file()
        or not (source / "templates").is_dir()
        or (source / "templates").is_symlink()
    ):
        raise SliceError("source needs manifest.json and templates/")
    digest = hashlib.sha256()
    paths = [source / "manifest.json", *(source / "templates").rglob("*")]
    for path in sorted(paths):
        relative = path.relative_to(source)
        if any(part in LOCAL_DIRS for part in relative.parts) or path.suffix == ".pyc":
            continue
        if path.is_symlink():
            raise SliceError(f"source symlink is outside this slice: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise SliceError(f"source entry is not a regular file: {path}")
        for item in (relative.as_posix().encode(), path.read_bytes()):
            digest.update(len(item).to_bytes(8, "big"))
            digest.update(item)
    return digest.hexdigest()


def digest_templateer() -> str:
    root = Path(templateer.__file__).resolve().parent
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root).as_posix().encode()
        content = path.read_bytes()
        for item in (relative, content):
            digest.update(len(item).to_bytes(8, "big"))
            digest.update(item)
    return digest.hexdigest()


def safe_output_path(pattern: str, answers: dict[str, Any]) -> str:
    if not pattern or pattern.startswith("/") or "\\" in pattern or "\x00" in pattern:
        raise SliceError(f"unsafe output path: {pattern!r}")
    parts: list[str] = []
    for part in pattern.split("/"):
        match = PATH_FIELD.fullmatch(part)
        if match:
            value = answers.get(match.group(1))
            if not isinstance(value, str):
                raise SliceError(f"path answer {match.group(1)} must be text")
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
            raise SliceError(f"unsafe output path: {pattern!r}")
        parts.append(part)
    return "/".join(parts)


def check_paths(names: list[str]) -> None:
    folded: dict[str, str] = {}
    for name in names:
        lowered = name.casefold()
        for other_lower, other in folded.items():
            if (
                lowered == other_lower
                or lowered.startswith(other_lower + "/")
                or other_lower.startswith(lowered + "/")
            ):
                raise SliceError(f"output path collision: {name} and {other}")
        folded[lowered] = name


def compose(
    source: Path, answers: dict[str, Any]
) -> tuple[dict[str, tuple[bytes, int]], dict[str, str], dict[str, Any]]:
    manifest = read_json(source / "manifest.json")
    names = manifest.get("templates")
    executable = manifest.get("executable", [])
    if not isinstance(names, list) or not names or any(not isinstance(x, str) for x in names):
        raise SliceError("manifest templates must be a nonempty text list")
    if not isinstance(executable, list) or any(not isinstance(x, str) for x in executable):
        raise SliceError("manifest executable must be a text list")
    if len(names) != len(set(names)):
        raise SliceError("manifest names a template twice")
    registry = TemplateRegistry.from_paths([source / "templates"])
    files: dict[str, tuple[bytes, int]] = {}
    owners: dict[str, str] = {}
    schema: str | None = None
    normalized: dict[str, Any] | None = None
    for name in names:
        template = registry.get_template(name)
        if template.metadata.output.kind != "full_file":
            raise SliceError(f"{name}: output must be full_file")
        current_schema = json.dumps(template.get_schema_json(), sort_keys=True)
        if schema is not None and current_schema != schema:
            raise SliceError(f"{name}: model schema differs from the first template")
        schema = current_schema
        if normalized is None:
            normalized = template.get_schema_class().model_validate(answers).model_dump(mode="json")
        path = safe_output_path(template.metadata.output.path, normalized)
        check_paths([*files, path])
        artifact = registry.render_from_model(name, normalized)
        errors, warnings = registry.validate_artifact(name, artifact, model_data=normalized)
        if errors or warnings:
            raise SliceError(f"{name}: validation failed: {errors!r}; warnings: {warnings!r}")
        files[path] = (artifact.encode("utf-8"), 0o755 if path in executable else 0o644)
        owners[path] = name
    if set(executable) - set(files):
        raise SliceError("manifest executable names a path with no artifact")
    if normalized is None:
        raise SliceError("manifest has no templates")
    return files, owners, normalized


def plan_digest(files: dict[str, tuple[bytes, int]]) -> str:
    digest = hashlib.sha256()
    for name, (content, mode) in sorted(files.items()):
        for item in (name.encode(), f"{mode:o}".encode(), content):
            digest.update(len(item).to_bytes(8, "big"))
            digest.update(item)
    return digest.hexdigest()


def working_files(root: Path) -> dict[str, tuple[str, bytes, int]]:
    files: dict[str, tuple[str, bytes, int]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in LOCAL_DIRS for part in relative.parts):
            continue
        name = relative.as_posix()
        if path.is_symlink():
            files[name] = ("link", os.readlink(path).encode(), 0)
        elif path.is_file():
            files[name] = ("file", path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
    return files


def working_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for name, (kind, content, mode) in working_files(root).items():
        for item in (name.encode(), kind.encode(), f"{mode:o}".encode(), content):
            digest.update(len(item).to_bytes(8, "big"))
            digest.update(item)
    return digest.hexdigest()


def write_tree(root: Path, files: dict[str, tuple[bytes, int]]) -> None:
    for name, (content, mode) in sorted(files.items()):
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        target.chmod(mode)


def clear_workspace(root: Path) -> None:
    for entry in root.iterdir():
        if entry.name in {".jj", ".git"}:
            continue
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()


def marker(project: Path) -> dict[str, Any]:
    data = read_json(project / MARKER)
    required = {
        "schema", "project_id", "source", "source_digest", "answers", "owners",
        "revision", "render_digest", "templateer_digest",
    }
    if data.get("schema") != 1 or not required <= data.keys():
        raise SliceError(f"unsupported {MARKER} schema")
    if not isinstance(data["answers"], dict) or not isinstance(data["owners"], dict):
        raise SliceError(f"invalid {MARKER} inputs")
    return data


def render_head(project: Path, project_id: str) -> str:
    expression = f'heads(::@ & subject(glob:"copyroom:render {project_id} *"))'
    lines = jj(
        project, "log", "--no-graph", "-r", expression, "-T", 'commit_id ++ "\\n"'
    ).splitlines()
    if len(lines) != 1:
        raise SliceError(f"expected one render head, found {len(lines)}")
    return lines[0]


def merge_base(project: Path, first: str, second: str) -> str:
    expression = f"heads(::{first} & ::{second})"
    return commit_id(project, expression)


def source_path(project: Path, data: dict[str, Any], override: Path | None) -> Path:
    raw = override if override is not None else Path(str(data["source"]))
    source = raw.resolve()
    if source == project or project in source.parents or source in project.parents:
        raise SliceError("source and project directories must be separate")
    return source


def new(args: argparse.Namespace) -> int:
    source = args.source.resolve()
    target = args.target.resolve()
    if source == target or target in source.parents or source in target.parents:
        raise SliceError("source and project directories must be separate")
    if target.exists() and any(target.iterdir()):
        raise SliceError(f"target is not empty: {target}")
    answers = read_json(args.answers)
    before = digest_source(source)
    renderer_digest = digest_templateer()
    files, owners, answers = compose(source, answers)
    if digest_source(source) != before or digest_templateer() != renderer_digest:
        raise SliceError("source or Templateer changed during render", 1)
    existed = target.exists()
    target.mkdir(parents=True, exist_ok=True)
    try:
        jj(target, "git", "init", "--colocate")
        write_tree(target, files)
        project_id = uuid.uuid4().hex
        jj(target, "commit", "-m", f"copyroom:render {project_id} 0 {before}")
        render = commit_id(target, "@-")
        data = {
            "schema": 1,
            "project_id": project_id,
            "source": str(source),
            "source_digest": before,
            "manifest_digest": digest_bytes((source / "manifest.json").read_bytes()),
            "templateer_version": importlib.metadata.version("templateer"),
            "templateer_digest": renderer_digest,
            "composer_digest": digest_bytes(Path(__file__).read_bytes()),
            "answers": answers,
            "owners": owners,
            "revision": 0,
            "render_digest": plan_digest(files),
        }
        write_json(target / MARKER, data)
        jj(target, "commit", "-m", "copyroom:project inputs")
    except Exception:
        clear_workspace(target)
        for name in (".jj", ".git"):
            path = target / name
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            elif path.exists() or path.is_symlink():
                path.unlink()
        if not existed:
            target.rmdir()
        raise
    print(f"result created {target}")
    print(f"render {render}")
    return 0


def preview_sidecar(out: Path) -> Path:
    return out.with_name(out.name + PREVIEW_SUFFIX)


def preflight_new_paths(
    project: Path, old_owners: dict[str, str], new_owners: dict[str, str]
) -> None:
    project_only = set(working_files(project)) - set(old_owners) - {MARKER}
    for new_path in new_owners:
        if new_path not in old_owners:
            check_paths([new_path, *project_only])


def preview(args: argparse.Namespace) -> int:
    project = args.project.resolve()
    data = marker(project)
    source = source_path(project, data, args.source)
    out = args.out.resolve()
    if out.exists() or preview_sidecar(out).exists():
        raise SliceError(f"preview path already exists: {out}")
    if project == out or project in out.parents or out in project.parents:
        raise SliceError("preview must be outside the project")
    if source == out or source in out.parents or out in source.parents:
        raise SliceError("preview must be outside the source")
    answers = read_json(args.answers) if args.answers else data["answers"]
    source_digest = digest_source(source)
    renderer_digest = digest_templateer()
    files, owners, answers = compose(source, answers)
    if digest_source(source) != source_digest or digest_templateer() != renderer_digest:
        raise SliceError("source or Templateer changed during render", 1)
    preflight_new_paths(project, data["owners"], owners)
    manifest_digest = digest_bytes((source / "manifest.json").read_bytes())
    composer_digest = digest_bytes(Path(__file__).read_bytes())
    planned_digest = plan_digest(files)
    if (
        planned_digest == data["render_digest"]
        and source_digest == data["source_digest"]
        and answers == data["answers"]
        and renderer_digest == data["templateer_digest"]
        and composer_digest == data["composer_digest"]
    ):
        print("result no-change")
        return 0
    old_render = render_head(project, str(data["project_id"]))
    active_head = commit_id(project, "@")
    active_tree = working_digest(project)
    workspace_name = "copyroom-" + uuid.uuid4().hex[:12]
    added = False
    try:
        jj(project, "workspace", "add", "--name", workspace_name, "-r", old_render, str(out))
        added = True
        clear_workspace(out)
        write_tree(out, files)
        revision = int(data["revision"]) + 1
        jj(out, "commit", "-m", f"copyroom:render {data['project_id']} {revision} {source_digest}")
        next_render = commit_id(out, "@-")
        if commit_id(out, f"{next_render}-") != old_render:
            raise SliceError("new render has the wrong parent")
        if merge_base(out, active_head, next_render) != old_render:
            raise SliceError("project and render have the wrong merge base")
        jj(out, "new", active_head, next_render, "-m", "copyroom:preview")
        conflict_paths = conflicts(out)
        preview_tree = working_digest(out)
        if commit_id(project, "@") != active_head or working_digest(project) != active_tree:
            raise SliceError("active project changed during preview", 1)
        state = {
            "schema": 1,
            "project": str(project),
            "project_id": data["project_id"],
            "workspace": workspace_name,
            "active_head": active_head,
            "active_tree": active_tree,
            "old_render": old_render,
            "next_render": next_render,
            "preview_head": commit_id(out, "@"),
            "preview_tree": preview_tree,
            "revision": revision,
            "source": str(source),
            "source_digest": source_digest,
            "manifest_digest": manifest_digest,
            "templateer_version": importlib.metadata.version("templateer"),
            "templateer_digest": renderer_digest,
            "composer_digest": composer_digest,
            "answers": answers,
            "owners": owners,
            "render_digest": planned_digest,
            "conflicts": conflict_paths,
        }
        write_json(preview_sidecar(out), state)
    except Exception:
        if added:
            jj(project, "workspace", "forget", workspace_name)
        if out.exists():
            shutil.rmtree(out)
        preview_sidecar(out).unlink(missing_ok=True)
        raise
    print(f"result preview {out}")
    print(f"render {next_render}")
    print(f"conflicts {len(conflict_paths)}")
    for path in conflict_paths:
        print(f"conflict {path}")
    print(jj(out, "diff", "--from", active_head, "--to", "@"), end="")
    return 1 if conflict_paths else 0


def load_preview(out: Path) -> dict[str, Any]:
    if not out.is_dir() or not (out / ".jj").exists():
        raise SliceError(f"preview workspace is missing: {out}")
    state = read_json(preview_sidecar(out))
    required = {
        "schema", "project", "project_id", "workspace", "active_head", "active_tree",
        "old_render", "next_render", "preview_head", "preview_tree", "revision",
        "source", "source_digest", "manifest_digest", "templateer_version",
        "templateer_digest", "composer_digest", "answers", "owners",
        "render_digest", "conflicts",
    }
    if (
        state.get("schema") != 1 or not required <= state.keys()
        or not str(state["workspace"]).startswith("copyroom-")
    ):
        raise SliceError("unsupported preview state")
    return state


def discard_workspace(project: Path, out: Path, state: dict[str, Any]) -> None:
    jj(project, "workspace", "forget", str(state["workspace"]))
    shutil.rmtree(out)
    preview_sidecar(out).unlink()


def update(args: argparse.Namespace) -> int:
    project = args.project.resolve()
    out = args.preview.resolve()
    state = load_preview(out)
    data = marker(project)
    if state["project"] != str(project) or state["project_id"] != data["project_id"]:
        raise SliceError("preview belongs to another project", 1)
    if state["conflicts"]:
        raise SliceError("preview has conflicts; this slice cannot apply it", 1)
    if (
        commit_id(project, "@") != state["active_head"]
        or working_digest(project) != state["active_tree"]
    ):
        raise SliceError("active project changed after preview", 1)
    if render_head(project, str(data["project_id"])) != state["old_render"]:
        raise SliceError("render head changed after preview", 1)
    if commit_id(out, "@") != state["preview_head"] or working_digest(out) != state["preview_tree"]:
        raise SliceError("preview workspace changed after preview", 1)
    if commit_id(out, f"{state['next_render']}-") != state["old_render"]:
        raise SliceError("preview render has the wrong parent", 1)
    operation = current_operation(project)
    changed = False
    try:
        changed = True
        jj(project, "new", state["active_head"], state["next_render"], "-m", "copyroom:update")
        if conflicts(project) or working_digest(project) != state["preview_tree"]:
            raise SliceError("applied tree differs from preview", 1)
        next_data = {
            **data,
            "source": state["source"],
            "source_digest": state["source_digest"],
            "manifest_digest": state["manifest_digest"],
            "templateer_version": state["templateer_version"],
            "templateer_digest": state["templateer_digest"],
            "composer_digest": state["composer_digest"],
            "answers": state["answers"],
            "owners": state["owners"],
            "revision": state["revision"],
            "render_digest": state["render_digest"],
        }
        write_json(project / MARKER, next_data)
        jj(project, "commit", "-m", "copyroom:project inputs")
        if render_head(project, str(data["project_id"])) != state["next_render"]:
            raise SliceError("applied render head is wrong", 1)
    except Exception:
        if changed:
            jj(project, "op", "restore", operation)
        raise
    discard_workspace(project, out, state)
    print(f"result updated {project}")
    print(f"render {state['next_render']}")
    return 0


def discard(args: argparse.Namespace) -> int:
    out = args.preview.resolve()
    state = load_preview(out)
    project = Path(str(state["project"]))
    if marker(project)["project_id"] != state["project_id"]:
        raise SliceError("preview belongs to another project", 1)
    discard_workspace(project, out, state)
    print(f"result discarded {out}")
    return 0


def status(args: argparse.Namespace) -> int:
    project = args.project.resolve()
    data = marker(project)
    print(f"project {project}")
    print(f"source {data['source']}")
    print(f"source_digest {data['source_digest']}")
    print(f"revision {data['revision']}")
    print(f"render {render_head(project, str(data['project_id']))}")
    found = conflicts(project)
    print(f"conflicts {len(found)}")
    return 1 if found else 0


def main() -> int:
    parser = Parser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True, parser_class=Parser)
    create = commands.add_parser("new")
    create.add_argument("--source", type=Path, required=True)
    create.add_argument("--target", type=Path, required=True)
    create.add_argument("--answers", type=Path, required=True)
    create.set_defaults(action=new)
    view = commands.add_parser("preview")
    view.add_argument("--project", type=Path, required=True)
    view.add_argument("--out", type=Path, required=True)
    view.add_argument("--source", type=Path)
    view.add_argument("--answers", type=Path)
    view.set_defaults(action=preview)
    apply = commands.add_parser("update")
    apply.add_argument("--project", type=Path, required=True)
    apply.add_argument("--preview", type=Path, required=True)
    apply.set_defaults(action=update)
    drop = commands.add_parser("discard")
    drop.add_argument("--preview", type=Path, required=True)
    drop.set_defaults(action=discard)
    inspect = commands.add_parser("status")
    inspect.add_argument("--project", type=Path, required=True)
    inspect.set_defaults(action=status)
    args = parser.parse_args()
    try:
        return args.action(args)
    except SliceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.code
    except (
        OSError, ValueError, TypeError, RenderError, TemplateLoadError, TemplateNotFoundError
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
