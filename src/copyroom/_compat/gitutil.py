"""Small git helpers shared by the template-edit workflow.

These wrap ``git`` via :mod:`subprocess` (consistent with the rest of CopyRoom,
which shells out to git/copier rather than binding a library). Every call is
defensive: a missing ``git`` binary or a timeout returns ``None`` rather than
raising, so call sites can decide what a failure means.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .semver import select_latest_semver

_DEFAULT_TIMEOUT = 120

# Copier source shorthands → cloneable URLs. Copier understands these prefixes;
# plain ``git clone`` does not, so we expand the common ones before cloning.
_URL_SHORTHANDS = {
    "gh:": "https://github.com/",
    "gl:": "https://gitlab.com/",
}


def run_git(
    *args: str,
    cwd: Path | str | None = None,
    timeout: int = _DEFAULT_TIMEOUT,
) -> subprocess.CompletedProcess[str] | None:
    """Run ``git *args`` and return the result, or ``None`` if git is unavailable."""
    try:
        return subprocess.run(
            ["git", *args],
            cwd=str(cwd) if cwd is not None else None,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def normalize_source_url(source: str) -> str:
    """Expand Copier source shorthands (``gh:`` / ``gl:``) to clone-able URLs.

    Local paths and full URLs (``https://``, ``git@``, ``git+...``, ``file://``)
    pass through unchanged.
    """
    for prefix, expansion in _URL_SHORTHANDS.items():
        if source.startswith(prefix):
            rest = source[len(prefix):]
            if not rest.endswith(".git"):
                rest += ".git"
            return expansion + rest
    return source


def looks_remote(source: str) -> bool:
    """Heuristic: does *source* name a remote template rather than a local path?

    URLs and Copier shorthands (``gh:``/``gl:``/``git@``) are remote. Explicit
    filesystem paths (``/``, ``./``, ``../``, ``~``) are local even when they
    don't exist yet — that yields a clean "path not found" rather than a
    confusing "failed to clone". A bare name that doesn't exist on disk is
    treated as remote.
    """
    if "://" in source or source.startswith(("gh:", "gl:", "git@")):
        return True
    if source.startswith(("/", "./", "../", "~")):
        return False
    return not Path(source).exists()


def is_git_repo(path: Path) -> bool:
    """Return ``True`` only when *path* is inside a git work tree."""
    result = run_git("rev-parse", "--is-inside-work-tree", cwd=path)
    return result is not None and result.returncode == 0 and result.stdout.strip() == "true"


def local_path(source: str) -> Path:
    """Turn a local source string into a real :class:`Path`, expanding ``~``.

    The one place a user-supplied local source becomes a filesystem path, so a
    ``~/templates/foo`` source resolves to the home directory rather than a
    literal ``~`` directory.
    """
    return Path(source).expanduser()


def _porcelain_path(line: str) -> str:
    """Extract the file path from one ``git status --porcelain`` line."""
    # porcelain v1: "XY PATH"; a rename is "XY ORIG -> PATH".
    path = line[3:] if len(line) > 3 else line
    if " -> " in path:
        path = path.split(" -> ", 1)[1]
    return path


def worktree_status(
    path: Path | str,
    *,
    exclude: tuple[str, ...] = (),
) -> list[str] | None:
    """Return the ``git status --porcelain`` lines for *path*.

    ``None`` when *path* isn't a git repo (or git is unavailable) — so callers
    can tell "not a repo" apart from "clean". ``exclude`` drops lines whose path
    starts with any given prefix (e.g. ``("generated/", ".copyroom_sim/")``).
    """
    result = run_git("status", "--porcelain", cwd=path)
    if result is None or result.returncode != 0:
        return None
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    if exclude:
        lines = [ln for ln in lines if not _porcelain_path(ln).startswith(exclude)]
    return lines


def worktree_clean(
    path: Path | str,
    *,
    exclude: tuple[str, ...] = (),
) -> bool | None:
    """Return whether *path*'s worktree is clean, or ``None`` if not a git repo.

    Thin boolean view over :func:`worktree_status`; ``exclude`` is forwarded so
    callers can ignore their own scratch output (``generated/`` etc.).
    """
    lines = worktree_status(path, exclude=exclude)
    if lines is None:
        return None
    return not lines


def changed_paths(
    path: Path | str,
    *,
    exclude: tuple[str, ...] = (),
) -> set[str]:
    """Return the set of dirty (changed/untracked) repo-relative paths in *path*.

    Built on :func:`worktree_status`; a non-repo or missing git yields an empty
    set. Used to find the files ``copier update`` touched (the tree was verified
    clean first) so they can be scanned for inline conflict markers.
    """
    return {_porcelain_path(ln) for ln in (worktree_status(path, exclude=exclude) or [])}


def default_branch(repo: Path) -> str | None:
    """Return the currently checked-out branch name of *repo*, if any."""
    result = run_git("rev-parse", "--abbrev-ref", "HEAD", cwd=repo)
    if result is None or result.returncode != 0:
        return None
    name = result.stdout.strip()
    return name or None


def clone(source: str, dest: Path) -> bool:
    """Full-clone *source* (after shorthand expansion) into *dest*.

    A full clone (no ``--depth``) is required so the project's recorded
    ``_commit`` stays in history for Copier's 3-way merge. Returns ``False`` on
    failure.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    result = run_git("clone", normalize_source_url(source), str(dest))
    return result is not None and result.returncode == 0


def fetch(repo: Path) -> None:
    """Best-effort ``git fetch`` to refresh a cached clone."""
    run_git("fetch", "--all", "--quiet", cwd=repo)


def branch_exists(repo: Path, branch: str) -> bool:
    """Return ``True`` if *branch* exists in *repo*."""
    result = run_git("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", cwd=repo)
    return result is not None and result.returncode == 0


def worktree_add(repo: Path, worktree_dir: Path, branch: str, base: str) -> bool:
    """Add a git worktree at *worktree_dir* on a new *branch* off *base*.

    If *branch* already exists, the worktree is attached to it (idempotent reuse
    across runs). Returns ``False`` on failure.
    """
    worktree_dir.parent.mkdir(parents=True, exist_ok=True)
    if branch_exists(repo, branch):
        result = run_git("worktree", "add", str(worktree_dir), branch, cwd=repo)
    else:
        result = run_git("worktree", "add", "-b", branch, str(worktree_dir), base, cwd=repo)
    return result is not None and result.returncode == 0


def checkout_new_branch(repo: Path, name: str) -> subprocess.CompletedProcess[str] | None:
    """``git checkout -b <name>`` in *repo*.

    Returns the ``CompletedProcess`` (so callers can forward stderr) or ``None``
    when git is unavailable.
    """
    return run_git("checkout", "-b", name, cwd=repo)


def commits_ahead(repo: Path, branch: str, base: str) -> int | None:
    """Number of commits on *branch* not on *base* (``git rev-list --count base..branch``).

    ``None`` when undeterminable (git unavailable or the refs don't resolve).
    Used to warn about a reused, non-empty edit branch.
    """
    result = run_git("rev-list", "--count", f"{base}..{branch}", cwd=repo)
    if result is None or result.returncode != 0:
        return None
    try:
        return int(result.stdout.strip())
    except ValueError:
        return None


def worktree_remove(repo: Path, worktree_dir: Path) -> bool:
    """``git worktree remove --force <dir>``. ``False`` on failure / missing git."""
    result = run_git("worktree", "remove", "--force", str(worktree_dir), cwd=repo)
    return result is not None and result.returncode == 0


def delete_branch(repo: Path, branch: str) -> bool:
    """``git branch -D <branch>``. ``False`` on failure / missing git."""
    result = run_git("branch", "-D", branch, cwd=repo)
    return result is not None and result.returncode == 0


def snapshot(work_dir: Path, message: str) -> bool:
    """Init (if needed) and commit everything in *work_dir*.

    Configures a repo-local identity so commits work without a global git
    identity, and allows empty commits. Returns ``False`` if git is unavailable.
    """
    if not (work_dir / ".git").exists():
        if run_git("init", cwd=work_dir) is None:
            return False
        run_git("config", "user.email", "copyroom@localhost", cwd=work_dir)
        run_git("config", "user.name", "CopyRoom", cwd=work_dir)
        run_git("config", "commit.gpgsign", "false", cwd=work_dir)

    run_git("add", "-A", cwd=work_dir)
    run_git("commit", "--allow-empty", "-m", message, cwd=work_dir)
    return True


def commit_all(repo: Path, message: str) -> bool:
    """Stage and commit all changes in *repo* (no-op commit allowed).

    Used to capture an agent's pending template edits onto the scratch branch
    before previewing. Returns ``False`` if git is unavailable.
    """
    if run_git("add", "-A", cwd=repo) is None:
        return False
    run_git(
        "-c", "user.email=copyroom@localhost", "-c", "user.name=CopyRoom",
        "commit", "--allow-empty", "-m", message, cwd=repo,
    )
    return True


def add_all_and_diff_cached(repo: Path) -> str:
    """Stage everything and return the unified diff of staged changes vs HEAD.

    This surfaces new files (which a plain ``git diff`` omits) alongside
    modifications, giving the full ``baseline → updated`` patch.
    """
    run_git("add", "-A", cwd=repo)
    result = run_git("diff", "--cached", cwd=repo)
    return result.stdout if result is not None else ""


# ---------------------------------------------------------------------------
# Tag inspection + latest-ref resolution
# ---------------------------------------------------------------------------


def list_tags(repo: Path) -> list[str]:
    """List the tags of a local *repo* via ``git tag --list``.

    Defensive: a missing ``git`` binary, a timeout, or a non-repo path yields an
    empty list rather than raising.
    """
    result = run_git("tag", "--list", cwd=repo)
    if result is None or result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def ls_remote_tags(url: str) -> list[str] | None:
    """List a remote's tags via ``git ls-remote --tags`` (no clone).

    *url* is passed through :func:`normalize_source_url` first. Returns ``None``
    when git is unavailable or the remote can't be reached (so callers can tell
    "couldn't ask" apart from "asked, no tags"); peeled ``^{}`` refs are
    collapsed to the underlying tag name.
    """
    result = run_git("ls-remote", "--tags", normalize_source_url(url))
    if result is None or result.returncode != 0:
        return None
    tags: list[str] = []
    for line in result.stdout.splitlines():
        parts = line.split("\trefs/tags/")
        if len(parts) != 2:
            continue
        name = parts[1].strip()
        if name.endswith("^{}"):  # peeled annotated-tag ref
            name = name[: -len("^{}")]
        if name and name not in tags:
            tags.append(name)
    return tags


def resolve_latest_ref(source: str) -> str | None:
    """Resolve *source* to its highest semver tag, or ``None`` if undeterminable.

    Local sources (a path) are read with :func:`list_tags`; remote sources with
    :func:`ls_remote_tags`. The highest ``vX.Y.Z`` tag wins (see
    :func:`._compat.semver.select_latest_semver`). ``None`` means git was
    unavailable, the source couldn't be reached, or it carries no semver tags.
    """
    if looks_remote(source):
        tags = ls_remote_tags(source)
        if tags is None:
            return None
    else:
        tags = list_tags(local_path(source))
    return select_latest_semver(tags)
