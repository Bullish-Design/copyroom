"""Render a trusted local Templateer source as a checked project tree."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import templateer
from templateer.api import TemplateRegistry
from templateer.renderer import RenderError
from templateer.template import TemplateLoadError, TemplateNotFoundError

from .errors import LocalError

PATH_FIELD = re.compile(r"^\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}$")
RESERVED = {
    ".git", ".jj", ".devenv", ".direnv", ".venv", ".copyroom-local",
    ".copyroom-local.json",
}
LOCAL_DIRS = RESERVED | {"__pycache__", ".pytest_cache", ".ruff_cache"}


@dataclass(frozen=True)
class FileEntry:
    """One output file, directory link, or safe relative symlink."""

    kind: str
    content: bytes
    mode: int


@dataclass(frozen=True)
class RenderPlan:
    """A validated, immutable output plan."""

    files: dict[str, FileEntry]
    owners: dict[str, str]
    answers: dict[str, Any]
    source_digest: str
    manifest_digest: str
    templateer_version: str
    templateer_digest: str
    composer_digest: str
    render_digest: str


def digest_bytes(data: bytes) -> str:
    """Return the SHA-256 digest for bytes."""

    return hashlib.sha256(data).hexdigest()


def _feed(digest: Any, data: bytes) -> None:
    digest.update(len(data).to_bytes(8, "big"))
    digest.update(data)


def digest_source(source: Path) -> str:
    """Digest a local source tree and reject unsupported entries."""

    if not source.is_dir() or source.is_symlink():
        raise LocalError(f"source must be a local directory: {source}")
    manifest = source / "manifest.json"
    templates = source / "templates"
    if not manifest.is_file() or not templates.is_dir() or templates.is_symlink():
        raise LocalError("source needs manifest.json and a regular templates/ directory")
    digest = hashlib.sha256()
    paths = list(source.rglob("*"))
    for path in sorted(paths):
        relative = path.relative_to(source)
        if any(part in LOCAL_DIRS for part in relative.parts) or path.suffix == ".pyc":
            continue
        if path.is_symlink():
            raise LocalError(f"source symlinks are not supported: {relative.as_posix()}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise LocalError(f"source entry is not a regular file: {relative.as_posix()}")
        _feed(digest, relative.as_posix().encode())
        _feed(digest, path.read_bytes())
        _feed(digest, f"{stat.S_IMODE(path.stat().st_mode):o}".encode())
    return digest.hexdigest()


def digest_templateer() -> str:
    """Digest the installed Templateer Python source."""

    root = Path(templateer.__file__).resolve().parent
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        _feed(digest, path.relative_to(root).as_posix().encode())
        _feed(digest, path.read_bytes())
    return digest.hexdigest()


def digest_composer() -> str:
    """Digest the local renderer and path validation code."""

    digest = hashlib.sha256()
    for name in ("composer.py", "source.py"):
        path = Path(__file__).with_name(name)
        _feed(digest, name.encode())
        _feed(digest, path.read_bytes())
    return digest.hexdigest()


def safe_output_path(pattern: str, answers: dict[str, Any]) -> str:
    """Resolve complete path fields and reject unsafe output paths."""

    if not pattern or pattern.startswith("/") or "\\" in pattern or "\x00" in pattern:
        raise LocalError(f"unsafe output path: {pattern!r}")
    parts: list[str] = []
    for part in pattern.split("/"):
        match = PATH_FIELD.fullmatch(part)
        if match:
            value = answers.get(match.group(1))
            if not isinstance(value, str):
                raise LocalError(f"path answer {match.group(1)} must be text")
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
            raise LocalError(f"unsafe output path: {pattern!r}")
        parts.append(part)
    return "/".join(parts)


def safe_symlink_target(path: str, target: str) -> str:
    """Check that a symlink target stays inside the output tree."""

    if not target or target.startswith("/") or "\\" in target or "\x00" in target:
        raise LocalError(f"unsafe symlink target for {path}: {target!r}")
    resolved = PurePosixPath(path).parent
    for part in PurePosixPath(target).parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if not resolved.parts:
                raise LocalError(f"symlink target escapes the output tree: {path} -> {target}")
            resolved = resolved.parent
        else:
            resolved /= part
    return target


def _resolved_symlink_path(path: str, target: str) -> str:
    """Return the normalized in-tree path named by a relative symlink."""

    stack: list[str] = []
    for part in (*PurePosixPath(path).parent.parts, *PurePosixPath(target).parts):
        if part == "..":
            if not stack:
                raise LocalError(f"symlink target escapes output tree: {path} -> {target}")
            stack.pop()
        elif part not in {"", ".", "/"}:
            stack.append(part)
    return "/".join(stack)


def check_paths(names: list[str]) -> None:
    """Reject duplicate, prefix, and case-folded path collisions."""

    folded: dict[str, str] = {}
    for name in names:
        lowered = name.casefold()
        for other_lower, other in folded.items():
            if (
                lowered == other_lower
                or lowered.startswith(other_lower + "/")
                or other_lower.startswith(lowered + "/")
            ):
                raise LocalError(f"output path collision: {name} and {other}")
        folded[lowered] = name


def _read_manifest(source: Path) -> dict[str, Any]:
    try:
        value = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LocalError(f"cannot read source manifest: {exc}") from exc
    if not isinstance(value, dict):
        raise LocalError("manifest.json must contain an object")
    return value


def _static_entries(source: Path, manifest: dict[str, Any]) -> list[tuple[str, FileEntry, str]]:
    raw = manifest.get("static", [])
    if not isinstance(raw, list):
        raise LocalError("manifest static must be a list")
    entries: list[tuple[str, FileEntry, str]] = []
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise LocalError("each static entry needs a path and source")
        if not isinstance(item.get("source"), str):
            raise LocalError(f"static entry {item['path']!r} needs a source path")
        output = safe_output_path(item["path"], {})
        raw_source = PurePosixPath(item["source"])
        if raw_source.is_absolute() or any(part in {"", ".", ".."} for part in raw_source.parts):
            raise LocalError(f"unsafe static source path: {item['source']!r}")
        path = source.joinpath(*raw_source.parts)
        if source.resolve() not in path.resolve().parents or path.is_symlink() or not path.is_file():
            raise LocalError(f"static source must be a regular file in the source: {item['source']}")
        executable = item.get("executable", False)
        if not isinstance(executable, bool):
            raise LocalError(f"static executable must be boolean: {item['path']}")
        mode = 0o755 if executable else 0o644
        entries.append((output, FileEntry("file", path.read_bytes(), mode), f"static:{item['source']}"))
    return entries


def _symlink_entries(manifest: dict[str, Any]) -> list[tuple[str, FileEntry, str]]:
    raw = manifest.get("symlinks", [])
    if not isinstance(raw, list):
        raise LocalError("manifest symlinks must be a list")
    entries: list[tuple[str, FileEntry, str]] = []
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise LocalError("each symlink entry needs a path and target")
        if not isinstance(item.get("target"), str):
            raise LocalError(f"symlink entry {item['path']!r} needs a target")
        output = safe_output_path(item["path"], {})
        target = safe_symlink_target(output, item["target"])
        entries.append((output, FileEntry("symlink", target.encode(), 0), f"symlink:{target}"))
    return entries


def plan_digest(files: dict[str, FileEntry]) -> str:
    """Digest output paths, kinds, modes, and bytes or link targets."""

    digest = hashlib.sha256()
    for name, entry in sorted(files.items()):
        for item in (
            name.encode(), entry.kind.encode(), f"{entry.mode:o}".encode(), entry.content,
        ):
            _feed(digest, item)
    return digest.hexdigest()


def _restore_line_endings(path: str, content: bytes, endings: Any) -> bytes:
    """Restore a templatized file's saved line endings after artifact validation."""

    if not isinstance(endings, dict) or path not in endings:
        return content
    values = endings[path]
    if not isinstance(values, list) or any(value not in {"\n", "\r\n", "\r"} for value in values):
        raise LocalError(f"manifest line_endings for {path!r} must be a list of line endings")
    parts = content.split(b"\n")
    if len(parts) - 1 != len(values):
        raise LocalError(
            f"manifest line_endings for {path!r} has {len(values)} entries, "
            f"but the rendered artifact has {len(parts) - 1} line breaks",
        )
    restored = bytearray()
    for part, ending in zip(parts, (*values, ""), strict=True):
        restored.extend(part)
        restored.extend(ending.encode("ascii"))
    return bytes(restored)


def compose(source: Path, answers_input: dict[str, Any]) -> RenderPlan:
    """Render and validate every artifact before any project write."""

    source = source.resolve()
    before_source = digest_source(source)
    before_templateer = digest_templateer()
    manifest = _read_manifest(source)
    names = manifest.get("templates")
    executable = manifest.get("executable", [])
    if not isinstance(names, list) or not names or any(not isinstance(item, str) for item in names):
        raise LocalError("manifest templates must be a nonempty text list")
    if len(names) != len(set(names)):
        raise LocalError("manifest names a template twice")
    if not isinstance(executable, list) or any(not isinstance(item, str) for item in executable):
        raise LocalError("manifest executable must be a text list")

    try:
        registry = TemplateRegistry.from_paths([source / "templates"])
    except (OSError, ValueError, TypeError, TemplateLoadError) as exc:
        raise LocalError(f"cannot load Templateer source: {exc}") from exc
    files: dict[str, FileEntry] = {}
    owners: dict[str, str] = {}
    schema: str | None = None
    normalized: dict[str, Any] | None = None
    for name in names:
        try:
            template = registry.get_template(name)
        except (TemplateLoadError, TemplateNotFoundError, OSError, ValueError) as exc:
            raise LocalError(f"cannot load Templateer artifact {name}: {exc}") from exc
        if template.metadata.output.kind != "full_file":
            raise LocalError(f"{name}: output must be full_file")
        current_schema = json.dumps(template.get_schema_json(), sort_keys=True)
        if schema is not None and current_schema != schema:
            raise LocalError(f"{name}: model schema differs from the first template")
        schema = current_schema
        if normalized is None:
            try:
                normalized = template.get_schema_class().model_validate(answers_input).model_dump(mode="json")
            except Exception as exc:
                raise LocalError(f"answers do not match the shared template schema: {exc}", 3) from exc
        path = safe_output_path(template.metadata.output.path, normalized)
        check_paths([*files, path])
        try:
            artifact = registry.render_from_model(name, normalized)
            errors, warnings = registry.validate_artifact(name, artifact, model_data=normalized)
        except (RenderError, TemplateLoadError, TemplateNotFoundError, OSError, ValueError) as exc:
            raise LocalError(f"Templateer failed for {name}: {exc}") from exc
        if errors or warnings:
            raise LocalError(f"{name}: validation findings: errors={errors!r}; warnings={warnings!r}")
        artifact_bytes = _restore_line_endings(
            path, artifact.encode("utf-8"), manifest.get("line_endings", {}),
        )
        mode = 0o755 if path in executable else 0o644
        files[path] = FileEntry("file", artifact_bytes, mode)
        owners[path] = name

    for path, entry, owner in (*_static_entries(source, manifest), *_symlink_entries(manifest)):
        check_paths([*files, path])
        files[path] = entry
        owners[path] = owner
    if set(executable) - set(files):
        raise LocalError("manifest executable names a path with no output")
    for path in executable:
        if files[path].kind == "symlink":
            raise LocalError(f"manifest marks a symlink executable: {path}")
        files[path] = FileEntry(files[path].kind, files[path].content, 0o755)

    symlink_targets = {
        path: _resolved_symlink_path(path, entry.content.decode())
        for path, entry in files.items() if entry.kind == "symlink"
    }
    for path, first_target in symlink_targets.items():
        target = first_target
        chain = [path]
        visited = {path}
        while True:
            if target not in files:
                raise LocalError(f"symlink target does not exist in output: {path} -> {target}")
            if files[target].kind != "symlink":
                break
            if target in visited:
                cycle = " -> ".join((*chain, target))
                raise LocalError(f"symlink cycle in output: {cycle}")
            visited.add(target)
            chain.append(target)
            target = symlink_targets[target]

    if normalized is None:
        raise LocalError("manifest has no templates")
    after_source = digest_source(source)
    after_templateer = digest_templateer()
    if before_source != after_source or before_templateer != after_templateer:
        raise LocalError("source or Templateer changed during render", 1)
    return RenderPlan(
        files=files,
        owners=owners,
        answers=normalized,
        source_digest=before_source,
        manifest_digest=digest_bytes((source / "manifest.json").read_bytes()),
        templateer_version=importlib.metadata.version("templateer"),
        templateer_digest=before_templateer,
        composer_digest=digest_composer(),
        render_digest=plan_digest(files),
    )


__all__ = [
    "FileEntry", "LOCAL_DIRS", "RenderPlan", "RESERVED", "check_paths", "compose",
    "digest_bytes", "digest_composer", "digest_source", "digest_templateer", "plan_digest",
    "safe_output_path", "safe_symlink_target",
]
