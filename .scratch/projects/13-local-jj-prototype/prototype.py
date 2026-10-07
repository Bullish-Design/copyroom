#!/usr/bin/env python3
"""Local render-commit prototype. Run only in disposable jj repositories."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

MARKER = ".copyroom-local.json"
VAR = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
RESERVED = {".git", ".jj", ".devenv", ".direnv"}


class PrototypeError(Exception):
    """A local input or jj operation failed."""


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(3, f"error: {message}\n")


def jj(project: Path, *args: str) -> bytes:
    result = subprocess.run(["jj", *args], cwd=project, capture_output=True, check=False)
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise PrototypeError(f"jj {' '.join(args)}: {detail}")
    return result.stdout


def commit_id(project: Path, rev: str) -> str:
    return jj(project, "log", "--no-graph", "-r", rev, "-T", "commit_id").decode().strip()


def load_answers(path: Path) -> dict[str, object]:
    try:
        answers = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PrototypeError(f"cannot read answers {path}: {exc}") from exc
    if not isinstance(answers, dict) or not all(isinstance(key, str) for key in answers):
        raise PrototypeError("answers must be a JSON object with string keys")
    return answers


def substitute(text: str, answers: dict[str, object], source: str) -> str:
    missing: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in answers:
            missing.add(key)
            return ""
        value = answers[key]
        if not isinstance(value, (str, int, float, bool)):
            raise PrototypeError(f"answer {key} must be a scalar")
        return str(value)

    result = VAR.sub(replace, text)
    if missing:
        raise PrototypeError(f"undefined answer {sorted(missing)} in {source}")
    return result


def safe_parts(parts: tuple[str, ...], source: str) -> tuple[str, ...]:
    if not parts or any(
        part in {"", ".", ".."} or "/" in part or "\\" in part or "\x00" in part
        or part in RESERVED
        for part in parts
    ):
        raise PrototypeError(f"unsafe output path from {source}: {'/'.join(parts)}")
    if parts[0] == MARKER:
        raise PrototypeError(f"template cannot write {MARKER}")
    return parts


def source_files(source: Path) -> list[Path]:
    if not source.is_dir() or source.is_symlink():
        raise PrototypeError(f"source must be a local directory: {source}")
    entries = sorted(source.rglob("*"))
    for entry in entries:
        if entry.is_symlink():
            raise PrototypeError(f"symlinks are outside this prototype: {entry}")
    return [entry for entry in entries if entry.is_file()]


def render(source: Path, answers: dict[str, object], out: Path) -> set[str]:
    paths: set[str] = set()
    for entry in source_files(source):
        relative = entry.relative_to(source)
        parts = safe_parts(
            tuple(substitute(part, answers, str(relative)) for part in relative.parts),
            str(relative),
        )
        name = Path(*parts).as_posix()
        if name in paths:
            raise PrototypeError(f"two template files render to {name}")
        paths.add(name)
        try:
            content = substitute(entry.read_text(encoding="utf-8"), answers, name)
        except UnicodeDecodeError as exc:
            raise PrototypeError(f"template file is not UTF-8 text: {entry}") from exc
        if not content.endswith("\n"):
            content += "\n"
        target = out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
        target.chmod(0o755 if entry.stat().st_mode & 0o111 else 0o644)
    return paths


def overlay_generated(source: Path, out: Path) -> list[str]:
    paths: list[str] = []
    for entry in source_files(source):
        relative = entry.relative_to(source)
        safe_parts(relative.parts, str(relative))
        name = relative.as_posix()
        target = out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(entry, target)
        paths.append(name)
    return paths


def retain_generated(
    project: Path, render_head: str, paths: list[str], executable: list[str], out: Path
) -> None:
    for name in paths:
        relative = Path(name)
        safe_parts(relative.parts, name)
        content = jj(project, "file", "show", "-r", render_head, "--", name)
        target = out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        target.chmod(0o755 if name in executable else 0o644)


def executable_paths(root: Path, paths: list[str]) -> list[str]:
    return [name for name in paths if (root / name).stat().st_mode & 0o111]


def fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    for entry in sorted(path for path in root.rglob("*") if path.is_file()):
        name = entry.relative_to(root).as_posix().encode()
        digest.update(len(name).to_bytes(4, "big"))
        digest.update(name)
        digest.update(b"x" if entry.stat().st_mode & 0o111 else b"f")
        content = entry.read_bytes()
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def marker_path(project: Path) -> Path:
    return project / MARKER


def read_marker(project: Path) -> dict[str, object]:
    try:
        data = json.loads(marker_path(project).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PrototypeError(f"cannot read {MARKER}: {exc}") from exc
    if data.get("schema") != 1 or data.get("layer") != "base":
        raise PrototypeError(f"unsupported {MARKER} schema")
    return data


def write_marker(project: Path, data: dict[str, object]) -> None:
    marker_path(project).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def copy_render(out: Path, project: Path) -> None:
    shutil.copytree(out, project, dirs_exist_ok=True)


def wipe_project(project: Path) -> None:
    for entry in project.iterdir():
        if entry.name in {".git", ".jj"}:
            continue
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()


def render_head(project: Path, project_id: str) -> str:
    expression = f'heads(::@ & subject(glob:"copyroom:render base {project_id} *"))'
    heads = jj(project, "log", "--no-graph", "-r", expression, "-T", 'commit_id ++ "\\n"')
    matches = heads.decode().splitlines()
    if len(matches) != 1:
        raise PrototypeError(f"expected one base render head, found {len(matches)}")
    return matches[0]


def merge_base(project: Path, first: str, second: str) -> str:
    expression = f"heads(::{first} & ::{second})"
    bases = jj(project, "log", "--no-graph", "-r", expression, "-T", 'commit_id ++ "\\n"')
    matches = bases.decode().splitlines()
    if len(matches) != 1:
        raise PrototypeError(f"expected one merge base, found {len(matches)}")
    return matches[0]


def conflict_paths(project: Path) -> list[str]:
    result = subprocess.run(
        ["jj", "resolve", "--list"], cwd=project, capture_output=True, check=False
    )
    if result.returncode and b"No conflicts found" not in result.stderr:
        raise PrototypeError(result.stderr.decode(errors="replace").strip())
    return [line.split()[0] for line in result.stdout.decode().splitlines() if line.strip()]


def cmd_new(args: argparse.Namespace) -> int:
    target = args.target.resolve()
    source = args.template.resolve()
    if source == target or target in source.parents or source in target.parents:
        raise PrototypeError("template and project directories must be separate")
    if target.exists() and any(target.iterdir()):
        raise PrototypeError(f"target is not empty: {target}")
    answers = load_answers(args.answers)
    with tempfile.TemporaryDirectory(prefix="copyroom-local-") as temp:
        out = Path(temp)
        render(source, answers, out)
        generated = overlay_generated(args.generated.resolve(), out) if args.generated else []
        executable = executable_paths(out, generated)
        digest = fingerprint(out)
        target.mkdir(parents=True, exist_ok=True)
        jj(target, "git", "init", "--colocate")
        copy_render(out, target)
        project_id = uuid.uuid4().hex
        jj(target, "commit", "-m", f"copyroom:render base {project_id} 0")
        data: dict[str, object] = {
            "schema": 1,
            "layer": "base",
            "project_id": project_id,
            "template": str(source),
            "answers": answers,
            "revision": 0,
            "render_fingerprint": digest,
            "generation": {
                "enabled": args.generated is not None,
                "paths": generated,
                "executable": executable,
            },
        }
        write_marker(target, data)
        jj(target, "commit", "-m", "copyroom:project inputs")
    print(f"result created {target}")
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    project = args.project.resolve()
    data = read_marker(project)
    source = (args.template or Path(str(data["template"]))).resolve()
    if source == project or project in source.parents or source in project.parents:
        raise PrototypeError("template and project directories must be separate")
    if args.generated:
        generated_source = args.generated.resolve()
        if generated_source == project or project in generated_source.parents:
            raise PrototypeError("generated snapshot must be outside the project")
    answers = load_answers(args.answers) if args.answers else data["answers"]
    if not isinstance(answers, dict):
        raise PrototypeError("saved answers are invalid")
    old_render = render_head(project, str(data["project_id"]))
    project_head = commit_id(project, "@")
    with tempfile.TemporaryDirectory(prefix="copyroom-local-") as temp:
        out = Path(temp)
        render(source, answers, out)
        old_generation = data["generation"]
        if not isinstance(old_generation, dict):
            raise PrototypeError("saved generation is invalid")
        if args.generated:
            generated = overlay_generated(args.generated.resolve(), out)
            executable = executable_paths(out, generated)
        else:
            generated = old_generation["paths"]
            if not isinstance(generated, list) or not all(isinstance(p, str) for p in generated):
                raise PrototypeError("saved generated paths are invalid")
            executable = old_generation["executable"]
            if not isinstance(executable, list) or not all(isinstance(p, str) for p in executable):
                raise PrototypeError("saved generated modes are invalid")
            retain_generated(project, old_render, generated, executable, out)
        digest = fingerprint(out)
        next_data = dict(data)
        next_data["template"] = str(source)
        next_data["answers"] = answers
        next_data["render_fingerprint"] = digest
        next_data["generation"] = {
            "enabled": bool(old_generation["enabled"] or args.generated),
            "paths": generated,
            "executable": executable,
        }
        if digest == data["render_fingerprint"]:
            if next_data != data:
                write_marker(project, next_data)
                jj(project, "commit", "-m", "copyroom:project inputs")
                print("result inputs-updated")
            else:
                print("result no-change")
            return 0

        jj(project, "new", old_render)
        wipe_project(project)
        copy_render(out, project)
        revision = int(data["revision"]) + 1
        jj(project, "commit", "-m", f"copyroom:render base {data['project_id']} {revision}")
        next_render = commit_id(project, "@-")
        if commit_id(project, f"{next_render}-") != old_render:
            raise PrototypeError("new render has the wrong parent")
        if merge_base(project, project_head, next_render) != old_render:
            raise PrototypeError("project and new render have the wrong merge base")
        jj(project, "new", project_head, next_render, "-m", "copyroom:update base")
        conflicts = conflict_paths(project)
        next_data["revision"] = revision
        write_marker(project, next_data)
        jj(project, "commit", "-m", "copyroom:project inputs")
    print(f"result updated {project}")
    print(f"render {next_render}")
    print(f"conflicts {len(conflicts)}")
    for path in conflicts:
        print(f"conflict {path}")
    return 1 if conflicts else 0


def cmd_status(args: argparse.Namespace) -> int:
    project = args.project.resolve()
    data = read_marker(project)
    head = render_head(project, str(data["project_id"]))
    conflicts = conflict_paths(project)
    print(f"project {project}")
    print(f"template {data['template']}")
    print(f"revision {data['revision']}")
    print(f"render {head}")
    print(f"generation {str(data['generation']['enabled']).lower()}")
    print(f"conflicts {len(conflicts)}")
    return 1 if conflicts else 0


def main() -> int:
    parser = Parser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True, parser_class=Parser)
    new = commands.add_parser("new")
    new.add_argument("--template", type=Path, required=True)
    new.add_argument("--target", type=Path, required=True)
    new.add_argument("--answers", type=Path, required=True)
    new.add_argument("--generated", type=Path, help="local snapshot from an explicit LLM run")
    new.set_defaults(action=cmd_new)
    update = commands.add_parser("update")
    update.add_argument("--project", type=Path, required=True)
    update.add_argument("--template", type=Path)
    update.add_argument("--answers", type=Path)
    update.add_argument("--generated", type=Path, help="refresh the generated snapshot")
    update.set_defaults(action=cmd_update)
    status = commands.add_parser("status")
    status.add_argument("--project", type=Path, required=True)
    status.set_defaults(action=cmd_status)
    args = parser.parse_args()
    try:
        return args.action(args)
    except PrototypeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
