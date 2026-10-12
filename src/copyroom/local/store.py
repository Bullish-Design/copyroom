"""The private source store: source trees as Git objects behind private refs.

A project keeps no copy of its template source in the working tree. CopyRoom
writes the source tree into the Git object database that jj uses. One private
ref, ``refs/copyroom/sources/<digest>``, points at the tree. A ref keeps its
objects alive through ``git gc``. jj does not import the ref as a bookmark.
``git push`` and ``jj git push`` do not send it.

The store is machine-local. A fresh clone has no ref. It relies on the pin.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .composer import digest_source, is_local_path
from .errors import LocalError
from .source import backing_git_directory

SOURCE_REF_PREFIX = "refs/copyroom/sources/"
FILE_MODES = {"100644": 0o644, "100755": 0o755}
SYMLINK_MODE = "120000"
_DIGEST = re.compile(r"[0-9a-f]{64}")
_GIT_ENVIRONMENT = {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY"}


def run_git(repo: Path, *args: str, stdin: bytes | None = None) -> bytes:
    """Run one Git command in ``repo``. Raise ``LocalError`` on failure."""

    executable = shutil.which("git")
    if executable is None:
        raise LocalError("git is required for versioned sources", 2)
    environment = {
        name: value for name, value in os.environ.items() if name not in _GIT_ENVIRONMENT
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


def materialise(repo: Path, commit: str, subdir: str, destination: Path) -> None:
    """Write the ``subdir`` tree of ``commit`` into ``destination``.

    ``commit`` is any name for a commit or a tree. Read blobs straight from the
    object store. This keeps ``.gitattributes``, line-ending filters, and
    ``export-ignore`` out of the result. Keep the executable bit and symlinks.
    """

    tree = f"{commit}:{subdir}" if subdir else commit
    try:
        listing = run_git(repo, "ls-tree", "-r", "-z", tree)
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
        if mode == SYMLINK_MODE:
            os.symlink(contents[oid], target)
        elif mode in FILE_MODES:
            target.write_bytes(contents[oid])
            target.chmod(FILE_MODES[mode])
        else:
            raise LocalError(f"unsupported file mode {mode} in source commit: {name}", 2)


def _read_blobs(repo: Path, oids: list[str]) -> dict[str, bytes]:
    """Read many blobs with one ``git cat-file --batch`` process."""

    if not oids:
        return {}
    output = run_git(repo, "cat-file", "--batch", stdin=("\n".join(oids) + "\n").encode())
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


def source_ref(digest: str) -> str:
    """Return the private ref name for a source digest."""

    if not _DIGEST.fullmatch(digest):
        raise LocalError(f"invalid source digest: {digest!r}")
    return SOURCE_REF_PREFIX + digest


def git_directory(project: Path) -> Path:
    """Return the Git directory that holds the private refs of a project."""

    directory = backing_git_directory(project)
    if directory is None:
        raise LocalError(f"project has no Git repository for its source store: {project}", 2)
    return directory


@dataclass
class _Node:
    """One directory of the tree that ``write_tree_objects`` builds."""

    files: dict[str, tuple[str, str]] = field(default_factory=dict)
    directories: dict[str, _Node] = field(default_factory=dict)


def _hash_objects(git: Path, paths: list[Path]) -> list[str]:
    """Write file contents as Git blobs. Return one object id per path."""

    if not paths:
        return []
    if all("\n" not in str(path) for path in paths):
        listing = "\n".join(str(path) for path in paths) + "\n"
        output = run_git(
            git, "hash-object", "-w", "--no-filters", "--stdin-paths", stdin=listing.encode(),
        )
        return output.decode().split()
    return [
        run_git(git, "hash-object", "-w", "--no-filters", "--stdin", stdin=path.read_bytes())
        .decode().strip()
        for path in paths
    ]


def _tree_object(git: Path, node: _Node) -> str:
    """Write one directory node, with its children first. Return the tree id."""

    rows = [f"{mode} blob {oid}\t{name}\0" for name, (mode, oid) in node.files.items()]
    rows += [
        f"040000 tree {_tree_object(git, child)}\t{name}\0"
        for name, child in node.directories.items()
    ]
    return run_git(git, "mktree", "-z", stdin="".join(rows).encode()).decode().strip()


def write_tree_objects(git: Path, source: Path) -> str:
    """Write a source directory as Git objects. Return the tree id.

    A file keeps its executable bit. Git cannot hold other mode bits. A symlink
    keeps its target. A directory with no file leaves no trace.
    """

    regular: list[Path] = []
    symlinks: list[Path] = []
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if is_local_path(relative):
            continue
        if path.is_symlink():
            symlinks.append(path)
        elif path.is_file():
            regular.append(path)
        elif not path.is_dir():
            raise LocalError(f"source entry is not a regular file: {relative.as_posix()}")
    root = _Node()

    def place(path: Path, mode: str, oid: str) -> None:
        *folders, name = path.relative_to(source).parts
        node = root
        for folder in folders:
            node = node.directories.setdefault(folder, _Node())
        node.files[name] = (mode, oid)

    for path, oid in zip(regular, _hash_objects(git, regular), strict=True):
        executable = stat.S_IMODE(path.stat().st_mode) & 0o111
        place(path, "100755" if executable else "100644", oid)
    for path in symlinks:
        oid = run_git(
            git, "hash-object", "-w", "--no-filters", "--stdin",
            stdin=os.readlink(path).encode(),
        ).decode().strip()
        place(path, SYMLINK_MODE, oid)
    return _tree_object(git, root)


def store_source(project: Path, source: Path, expected_digest: str) -> None:
    """Record a source tree in the private store of a project.

    Check the digest of ``source`` first. The same source always gives the same
    tree, so a repeat call changes nothing and a damaged ref heals.
    """

    source = source.absolute()
    if source.is_symlink():
        raise LocalError(f"source must not be a symlink: {source}")
    if digest_source(source) != expected_digest:
        raise LocalError("source digest changed before it was stored", 1)
    ref = source_ref(expected_digest)
    git = git_directory(project)
    tree = write_tree_objects(git, source)
    run_git(git, "update-ref", ref, tree)


def has_stored(project: Path, digest: str) -> bool:
    """Tell whether the private ref for ``digest`` exists."""

    try:
        git = git_directory(project)
        run_git(git, "rev-parse", "--verify", "--quiet", f"{source_ref(digest)}^{{tree}}")
    except LocalError:
        return False
    return True


def drop_stored(project: Path, digest: str) -> None:
    """Delete the private ref for ``digest``. Do nothing when it is absent."""

    try:
        git = git_directory(project)
        run_git(git, "update-ref", "-d", source_ref(digest))
    except LocalError:
        return


def restore_stored(project: Path, digest: str, destination: Path) -> bool:
    """Write the stored tree for ``digest`` to ``destination``.

    Return ``False`` when the ref is absent or its tree does not match the
    digest. A mismatch leaves no files behind.
    """

    if not has_stored(project, digest):
        return False
    try:
        materialise(git_directory(project), source_ref(digest), "", destination)
        valid = digest_source(destination) == digest
    except LocalError:
        valid = False
    if not valid:
        shutil.rmtree(destination, ignore_errors=True)
    return valid


def stored_source_ok(project: Path, digest: str) -> bool:
    """Tell whether the private store holds a valid tree for ``digest``."""

    with tempfile.TemporaryDirectory(prefix="copyroom-store-") as scratch:
        return restore_stored(project, digest, Path(scratch) / "source")


@contextmanager
def open_stored(project: Path, digest: str) -> Iterator[Path | None]:
    """Yield the stored tree in a temporary directory, or ``None``. Clean up afterward."""

    scratch = Path(tempfile.mkdtemp(prefix="copyroom-source-"))
    try:
        destination = scratch / "source"
        yield destination if restore_stored(project, digest, destination) else None
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


__all__ = [
    "SOURCE_REF_PREFIX", "drop_stored", "git_directory", "has_stored", "materialise",
    "open_stored", "restore_stored", "run_git", "source_ref", "store_source",
    "stored_source_ok", "write_tree_objects",
]
