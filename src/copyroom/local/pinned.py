"""Versioned local sources: pin a source directory to a commit of its Git repository.

CopyRoom never fetches. It reads only objects that the local repository holds.
A pin records the repository root, the subdirectory, the ref as the user gave
it, and the commit that the ref named at that time.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .composer import digest_source
from .errors import LocalError
from .source import snapshot_path

PIN_FIELDS = ("repo", "subdir", "ref", "commit")
_VERSION = re.compile(r"v?(\d+)(?:\.(\d+))?(?:\.(\d+))?")
_FILE_MODES = {"100644": 0o644, "100755": 0o755}
_SYMLINK_MODE = "120000"


@dataclass(frozen=True)
class ResolvedSource:
    """A source ready to compose.

    ``path`` is the directory to read. ``locator`` is the text that the marker
    records as ``source``. ``pin`` is the version record, or ``None`` for a
    plain path source.
    """

    path: Path
    locator: str
    pin: dict[str, str] | None = None

    @classmethod
    def of_path(cls, path: Path) -> ResolvedSource:
        """Wrap a plain source directory."""

        return cls(path=path, locator=str(path))


def read_pin(record: dict[str, Any]) -> dict[str, str] | None:
    """Return the pin of a layer record, or ``None`` for a path source."""

    pin = record.get("pin")
    if pin is None:
        return None
    if (
        not isinstance(pin, dict)
        or set(pin) != set(PIN_FIELDS)
        or not all(isinstance(pin[name], str) for name in PIN_FIELDS)
    ):
        raise LocalError("invalid source pin in project marker")
    return pin


def _git(repo: Path, *args: str, stdin: bytes | None = None) -> bytes:
    """Run one read-only Git command in ``repo``. Raise ``LocalError`` on failure."""

    executable = shutil.which("git")
    if executable is None:
        raise LocalError("git is required for versioned sources")
    environment = {
        name: value for name, value in os.environ.items()
        if name not in {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY"}
    }
    try:
        result = subprocess.run(
            [executable, *args], cwd=repo, input=stdin, capture_output=True, check=False,
            env=environment,
        )
    except OSError as exc:
        raise LocalError(f"cannot run git in {repo}: {exc}", 2) from exc
    if result.returncode:
        detail = result.stderr.decode(errors="replace").strip()
        raise LocalError(f"git {' '.join(args[:2])} failed in {repo}: {detail}", 2)
    return result.stdout


def find_repo(source: Path) -> tuple[Path, str]:
    """Return the repository root of ``source`` and its subdirectory (POSIX text)."""

    try:
        top = _git(source, "rev-parse", "--show-toplevel").decode().strip()
    except LocalError as exc:
        raise LocalError(f"--ref needs a source inside a Git repository: {source}", 2) from exc
    repo = Path(top).resolve()
    try:
        subdir = source.resolve().relative_to(repo)
    except ValueError as exc:
        raise LocalError(f"source is outside its Git repository: {source}", 2) from exc
    return repo, "" if str(subdir) == "." else subdir.as_posix()


def resolve_commit(repo: Path, ref: str) -> str:
    """Resolve ``ref`` to a commit id in the local repository."""

    if not ref or ref.startswith("-"):
        raise LocalError(f"invalid ref: {ref!r}", 3)
    try:
        commit = _git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    except LocalError as exc:
        raise LocalError(f"ref {ref} not found in {repo}; fetch it first", 2) from exc
    return commit.decode().strip()


def commit_exists(repo: Path, commit: str) -> bool:
    """Tell whether the repository still holds ``commit``."""

    try:
        _git(repo, "cat-file", "-e", f"{commit}^{{commit}}")
    except LocalError:
        return False
    return True


def materialise(repo: Path, commit: str, subdir: str, destination: Path) -> None:
    """Write the ``subdir`` tree of ``commit`` into ``destination``.

    Read blobs straight from the object store. This keeps ``.gitattributes``,
    line-ending filters, and ``export-ignore`` out of the result. Keep the
    executable bit and symlinks.
    """

    tree = f"{commit}:{subdir}" if subdir else commit
    try:
        listing = _git(repo, "ls-tree", "-r", "-z", tree)
    except LocalError as exc:
        raise LocalError(
            f"commit {commit[:12]} of {repo} has no source directory {subdir or '.'}", 2,
        ) from exc
    entries: list[tuple[str, str, str]] = []
    for row in listing.split(b"\0"):
        if not row:
            continue
        meta, _, raw = row.partition(b"\t")
        mode, kind, oid = meta.decode().split(" ")
        name = raw.decode("utf-8", errors="surrogateescape")
        parts = PurePosixPath(name).parts
        if not parts or PurePosixPath(name).is_absolute() or ".." in parts or ".git" in parts:
            raise LocalError(f"unsafe path in source commit: {name!r}", 2)
        if kind != "blob":
            raise LocalError(f"source commit holds a submodule: {name}", 2)
        entries.append((name, mode, oid))
    contents = _read_blobs(repo, sorted({oid for _, _, oid in entries}))
    destination.mkdir(parents=True, exist_ok=True)
    for name, mode, oid in sorted(entries):
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if mode == _SYMLINK_MODE:
            os.symlink(contents[oid], target)
        elif mode in _FILE_MODES:
            target.write_bytes(contents[oid])
            target.chmod(_FILE_MODES[mode])
        else:
            raise LocalError(f"unsupported file mode {mode} in source commit: {name}", 2)


def _read_blobs(repo: Path, oids: list[str]) -> dict[str, bytes]:
    """Read many blobs with one ``git cat-file --batch`` process."""

    if not oids:
        return {}
    output = _git(repo, "cat-file", "--batch", stdin=("\n".join(oids) + "\n").encode())
    blobs: dict[str, bytes] = {}
    position = 0
    for oid in oids:
        end = output.index(b"\n", position)
        header = output[position:end].split()
        if len(header) != 3 or header[1] != b"blob":
            raise LocalError(f"cannot read source object {oid} in {repo}", 2)
        size = int(header[2])
        blobs[oid] = output[end + 1:end + 1 + size]
        position = end + 1 + size + 1
    return blobs


@contextmanager
def _materialised(
    repo: Path, subdir: str, commit: str, locator: str, pin: dict[str, str],
) -> Iterator[ResolvedSource]:
    """Yield a source that lives in a temporary directory. Remove it afterward."""

    temporary = Path(tempfile.mkdtemp(prefix="copyroom-source-"))
    try:
        materialise(repo, commit, subdir, temporary / "source")
        yield ResolvedSource(temporary / "source", locator, pin)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def _locator(repo: Path, subdir: str) -> str:
    return str(repo / subdir)


@contextmanager
def open_ref(repo: Path, subdir: str, ref: str) -> Iterator[ResolvedSource]:
    """Pin ``ref`` of a known repository and yield its source tree."""

    commit = resolve_commit(repo, ref)
    pin = {"repo": str(repo), "subdir": subdir, "ref": ref, "commit": commit}
    with _materialised(repo, subdir, commit, _locator(repo, subdir), pin) as source:
        yield source


@contextmanager
def open_source(source: Path, ref: str | None) -> Iterator[ResolvedSource]:
    """Yield a path source, or the source tree at ``ref`` of the repository holding it."""

    if ref is None:
        yield ResolvedSource.of_path(source)
        return
    if source.is_symlink():
        raise LocalError(f"source must not be a symlink: {source}")
    repo, subdir = find_repo(source)
    with open_ref(repo, subdir, ref) as resolved:
        yield resolved


@contextmanager
def open_layer_source(
    project: Path,
    data: dict[str, Any],
    record: dict[str, Any],
    override: Path | None,
    ref: str | None,
) -> Iterator[ResolvedSource]:
    """Choose the source for one layer update.

    * ``override`` and ``ref``: switch to that source at that ref.
    * ``override`` only: use the path source.
    * ``ref`` only: move the layer to a new ref of the same repository.
    * Neither: keep the pinned commit, or the recorded path source.
    """

    from .source import resolve_source

    pin = read_pin(record)
    if override is not None:
        with open_source(override, ref) as resolved:
            yield resolved
    elif ref is not None and pin is not None:
        with open_ref(Path(pin["repo"]), pin["subdir"], ref) as resolved:
            yield resolved
    elif ref is not None:
        with open_source(Path(str(record["source"])), ref) as resolved:
            yield resolved
    elif pin is not None:
        with _open_pinned(project, record, pin) as resolved:
            yield resolved
    else:
        # The locator stays as recorded, also when the saved snapshot stands in for it.
        path = resolve_source(project, data, None, record)
        yield ResolvedSource(path, str(record["source"]))


@contextmanager
def _open_pinned(
    project: Path, record: dict[str, Any], pin: dict[str, str],
) -> Iterator[ResolvedSource]:
    """Yield the pinned commit. Prefer the saved snapshot, then read the commit."""

    digest = str(record["source_digest"])
    snapshot = snapshot_path(project, digest)
    locator = str(record["source"])
    if snapshot.is_dir() and digest_source(snapshot) == digest:
        yield ResolvedSource(snapshot, locator, pin)
        return
    repo = Path(pin["repo"])
    if not commit_exists(repo, pin["commit"]):
        raise LocalError(
            f"pinned commit {pin['commit'][:12]} is missing in {repo} and the saved snapshot is "
            "missing or invalid; fetch it, or pass --source and --ref",
            2,
        )
    with _materialised(repo, pin["subdir"], pin["commit"], locator, pin) as resolved:
        if digest_source(resolved.path) != digest:
            raise LocalError(
                f"commit {pin['commit'][:12]} no longer matches the marker digest", 2,
            )
        yield resolved


def _version(name: str) -> tuple[int, int, int] | None:
    match = _VERSION.fullmatch(name)
    if match is None:
        return None
    return tuple(int(part or 0) for part in match.groups())  # type: ignore[return-value]


def newer_tags(pin: dict[str, str]) -> list[str]:
    """List version tags newer than the pinned ref, oldest first.

    Return nothing when the pinned ref is not a version tag. Read the local
    repository only.
    """

    current = _version(pin["ref"])
    if current is None:
        return []
    repo = Path(pin["repo"])
    names = _git(repo, "tag", "--list").decode().split()
    found = [(version, name) for name in names if (version := _version(name)) is not None]
    return [name for version, name in sorted(found) if version > current]


def describe(record: dict[str, Any]) -> dict[str, Any]:
    """Return the version fields that reports show for one layer."""

    pin = read_pin(record)
    if pin is None:
        return {"source_kind": "path", "ref": None, "commit": None, "commit_short": None}
    return {
        "source_kind": "ref",
        "ref": pin["ref"],
        "commit": pin["commit"],
        "commit_short": pin["commit"][:12],
    }


__all__ = [
    "PIN_FIELDS", "ResolvedSource", "commit_exists", "describe", "find_repo", "materialise",
    "newer_tags", "open_layer_source", "open_ref", "open_source", "read_pin", "resolve_commit",
]
