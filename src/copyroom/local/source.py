"""Project markers and source snapshots."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .composer import LOCAL_DIRS, digest_source
from .errors import LocalError

MARKER = ".copyroom-local.json"
STATE_DIR = ".copyroom-local"
SOURCE_DIR = f"{STATE_DIR}/sources"
PREVIEW_DIR = f"{STATE_DIR}/previews"
JOURNAL_DIR = f"{STATE_DIR}/journal"
LOCK_FILE = f"{STATE_DIR}/write.lock"
SCHEMA_VERSION = 2
TEMP_PREFIX = ".copyroom-tmp-"
TEMP_EXCLUDE = f"{TEMP_PREFIX}*"


def read_json(path: Path) -> dict[str, Any]:
    """Read a JSON object from disk."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LocalError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise LocalError(f"expected a JSON object in {path}")
    return value


def _fsync_directory(directory: Path) -> None:
    """Flush a directory entry to disk. Skip it where the filesystem refuses."""

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(directory, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def write_json(path: Path, data: dict[str, Any]) -> None:
    """Write JSON with a same-directory atomic replace.

    The temporary file lives next to the target, so the rename stays atomic.
    Its name starts with ``TEMP_PREFIX``. One ignore rule matches that prefix,
    so a crash cannot leave a file that jj snapshots into history.
    Flush each new parent entry, then write, fsync, chmod, rename, and fsync
    the target directory. Do not change the output bytes.
    """

    payload = json.dumps(data, indent=2, sort_keys=True) + "\n"
    temporary: Path | None = None
    try:
        missing_directories: list[Path] = []
        directory = path.parent
        while not directory.exists():
            missing_directories.append(directory)
            directory = directory.parent
        path.parent.mkdir(parents=True, exist_ok=True)
        for created_directory in reversed(missing_directories):
            _fsync_directory(created_directory.parent)
        descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=TEMP_PREFIX)
        temporary = Path(name)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(0o644)
        os.replace(temporary, path)
        temporary = None
        _fsync_directory(path.parent)
    except OSError as exc:
        raise LocalError(f"cannot write {path}: {exc}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def marker(project: Path) -> dict[str, Any]:
    """Load and validate the local project marker."""

    data = read_json(project / MARKER)
    required = {
        "schema", "project_id", "source", "source_digest", "manifest_digest", "answers",
        "owners", "revision", "render_digest", "templateer_version", "templateer_digest",
        "composer_digest",
    }
    if data.get("schema") != SCHEMA_VERSION or not required <= data.keys():
        raise LocalError(f"unsupported {MARKER} schema")
    if not isinstance(data["answers"], dict) or not isinstance(data["owners"], dict):
        raise LocalError(f"invalid {MARKER} inputs")
    if not isinstance(data["revision"], int) or data["revision"] < 0:
        raise LocalError(f"invalid render revision in {MARKER}")
    return data


def snapshot_path(project: Path, source_digest: str) -> Path:
    """Return the project-owned snapshot path for a source digest."""

    return project / SOURCE_DIR / source_digest


def snapshot_source(source: Path, project: Path, expected_digest: str | None = None) -> Path:
    """Copy a source tree into project state and verify its digest."""

    source = source.absolute()
    if source.is_symlink():
        raise LocalError(f"source must not be a symlink: {source}")
    digest = digest_source(source)
    if expected_digest is not None and digest != expected_digest:
        raise LocalError("source digest changed before snapshot", 1)
    destination = snapshot_path(project, digest)
    if destination.exists():
        if digest_source(destination) != digest:
            raise LocalError(f"saved source snapshot has a digest mismatch: {destination}")
        return destination

    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        for path in sorted(source.rglob("*")):
            relative = path.relative_to(source)
            if any(part in LOCAL_DIRS for part in relative.parts) or path.suffix == ".pyc":
                continue
            target = destination / relative
            if path.is_symlink():
                raise LocalError(f"source symlinks are not supported: {relative.as_posix()}")
            if path.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            elif path.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
            else:
                raise LocalError(f"source entry is not a regular file: {relative.as_posix()}")
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    if digest_source(destination) != digest:
        shutil.rmtree(destination, ignore_errors=True)
        raise LocalError("saved source snapshot failed its digest check")
    return destination


def resolve_source(
    project: Path,
    data: dict[str, Any],
    override: Path | None,
    record: dict[str, Any] | None = None,
) -> Path:
    """Resolve an override, source locator, or saved source snapshot."""

    if override is not None:
        source = override.absolute()
        if source.is_symlink():
            raise LocalError(f"source must not be a symlink: {source}")
        return source
    record = record or data
    source = Path(str(record["source"]))
    if source.is_dir() and not source.is_symlink():
        return source
    snapshot = snapshot_path(project, str(record["source_digest"]))
    if snapshot.is_dir() and digest_source(snapshot) == record["source_digest"]:
        return snapshot
    raise LocalError(
        "source locator is unavailable and its saved snapshot is missing or invalid; pass --source",
        2,
    )


def exclude_local_state(project: Path) -> None:
    """Exclude local state and write temporaries from the project tree."""

    git_directory = _git_directory(project)
    jj_git_directory = _jj_git_directory(project)
    if git_directory is not None and (
        jj_git_directory is None or git_directory == jj_git_directory
    ):
        target = git_directory
    elif jj_git_directory is not None:
        target = jj_git_directory
    else:
        return

    exclude = target / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    entries = [
        "/.copyroom-local/previews/", "/.copyroom-local/journal/",
        "/.copyroom-local/write.lock", TEMP_EXCLUDE,
    ]
    missing = [entry for entry in entries if entry not in existing.splitlines()]
    if missing:
        with exclude.open("a", encoding="utf-8") as stream:
            if existing and not existing.endswith("\n"):
                stream.write("\n")
            stream.write("\n".join(missing) + "\n")


def temp_exclude_active(project: Path) -> bool:
    """Return whether jj's backing Git directory has the temp rule."""

    git_directory = _jj_git_directory(project) or _git_directory(project)
    if git_directory is None:
        return False
    exclude = git_directory / "info" / "exclude"
    try:
        return TEMP_EXCLUDE in exclude.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False


def is_colocated(project: Path) -> bool:
    """Return whether jj uses the Git directory attached to this workspace."""

    git_directory = _git_directory(project)
    jj_git_directory = _jj_git_directory(project)
    return git_directory is not None and git_directory == jj_git_directory


def _git_directory(project: Path) -> Path | None:
    """Resolve a workspace's .git directory without creating one."""

    entry = project / ".git"
    if entry.is_dir():
        return entry.resolve()
    if not entry.is_file():
        return None
    try:
        lines = entry.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        key, separator, value = line.partition(":")
        if separator and key.strip().lower() == "gitdir" and value.strip():
            target = Path(value.strip())
            if not target.is_absolute():
                target = entry.parent / target
            resolved = target.resolve()
            return resolved if resolved.is_dir() else None
    return None


def _jj_git_directory(project: Path) -> Path | None:
    """Resolve the Git directory used by jj, when the repository has one."""

    store = project / ".jj" / "repo" / "store"
    target_file = store / "git_target"
    if target_file.is_file():
        try:
            value = target_file.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if not value:
            return None
        target = Path(value)
        if not target.is_absolute():
            target = store / target
        resolved = target.resolve()
        if resolved.is_dir():
            return resolved
    internal = store / "git"
    return internal.resolve() if internal.is_dir() else None


def marker_with_plan(plan: Any, source: Path, project_id: str, revision: int = 0) -> dict[str, Any]:
    """Build the versioned base layer marker from a render plan."""

    record = {
        "source": str(source),
        "source_digest": plan.source_digest,
        "manifest_digest": plan.manifest_digest,
        "templateer_version": plan.templateer_version,
        "templateer_digest": plan.templateer_digest,
        "composer_digest": plan.composer_digest,
        "answers": plan.answers,
        "owners": plan.owners,
        "revision": revision,
        "render_digest": plan.render_digest,
    }
    return {
        "schema": SCHEMA_VERSION,
        "project_id": project_id,
        **record,
        "layers": {"base": record},
    }


__all__ = [
    "JOURNAL_DIR", "LOCK_FILE", "MARKER", "PREVIEW_DIR", "SCHEMA_VERSION", "SOURCE_DIR", "STATE_DIR",
    "TEMP_EXCLUDE", "TEMP_PREFIX",
    "exclude_local_state", "marker", "marker_with_plan", "read_json", "resolve_source",
    "temp_exclude_active",
    "snapshot_path", "snapshot_source", "write_json",
]
