"""Versioned local sources: pin a source directory to a commit of its Git repository.

CopyRoom never fetches. It reads only objects that the local repository holds.
A pin records the repository root, the subdirectory, the ref as the user gave
it, and the commit that the ref named at that time.
"""

from __future__ import annotations

import re
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .composer import digest_source
from .errors import LocalError
from .store import materialise, open_stored, run_git

PIN_FIELDS = ("repo", "subdir", "ref", "commit")
_VERSION = re.compile(r"v?(\d+)(?:\.(\d+))?(?:\.(\d+))?")


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


def find_repo(source: Path) -> tuple[Path, str]:
    """Return the repository root of ``source`` and its subdirectory (POSIX text)."""

    try:
        top = run_git(source, "rev-parse", "--show-toplevel").decode().strip()
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
        commit = run_git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    except LocalError as exc:
        raise LocalError(f"ref {ref} not found in {repo}; fetch it first", 2) from exc
    return commit.decode().strip()


def commit_exists(repo: Path, commit: str) -> bool:
    """Tell whether the repository still holds ``commit``."""

    try:
        run_git(repo, "cat-file", "-e", f"{commit}^{{commit}}")
    except LocalError:
        return False
    return True


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
      When that source is gone, read the private copy of the project.
    """

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
    else:
        with _open_recorded(project, record, pin) as resolved:
            yield resolved


def _pinned_tree(pin: dict[str, str], digest: str, destination: Path) -> str | None:
    """Write the pinned commit to ``destination``. Return why it fails, or ``None``."""

    repo = Path(pin["repo"])
    if not repo.is_dir():
        return f"repository {repo} is missing"
    if not commit_exists(repo, pin["commit"]):
        return f"commit {pin['commit'][:12]} is missing in {repo}"
    try:
        materialise(repo, pin["commit"], pin["subdir"], destination)
        if digest_source(destination) == digest:
            return None
    except LocalError as exc:
        shutil.rmtree(destination, ignore_errors=True)
        return str(exc)
    shutil.rmtree(destination, ignore_errors=True)
    return f"commit {pin['commit'][:12]} of {repo} does not match the recorded digest"


@contextmanager
def _open_recorded(
    project: Path, record: dict[str, Any], pin: dict[str, str] | None,
) -> Iterator[ResolvedSource]:
    """Yield the source that the marker records.

    A pinned layer reads its commit first. Its tree must match the recorded
    digest. The private ref of the project comes next. A path layer reads its
    recorded path while that directory exists. When the directory is gone, the
    private ref stands in. The locator stays as recorded.
    """

    digest = str(record["source_digest"])
    locator = str(record["source"])
    reason: str
    if pin is None:
        path = Path(locator)
        if path.is_dir() and not path.is_symlink():
            yield ResolvedSource(path, locator)
            return
        reason = f"source directory {path} is missing"
    else:
        scratch = Path(tempfile.mkdtemp(prefix="copyroom-source-"))
        try:
            failure = _pinned_tree(pin, digest, scratch / "source")
            if failure is None:
                yield ResolvedSource(scratch / "source", locator, pin)
                return
            reason = failure
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
    with open_stored(project, digest) as stored:
        if stored is None:
            raise LocalError(
                f"{reason}, and the project has no stored copy of source {digest[:12]}; "
                "fetch the template repository, or run update --source PATH"
                + (" --ref REF" if pin is not None else ""),
                2,
            )
        yield ResolvedSource(stored, locator, pin)


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
    names = run_git(repo, "tag", "--list").decode().split()
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
