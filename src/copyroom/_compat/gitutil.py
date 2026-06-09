"""Small git helpers shared by the template-edit workflow.

These wrap ``git`` via :mod:`subprocess` (consistent with the rest of CopyRoom,
which shells out to git/copier rather than binding a library). Every call is
defensive: a missing ``git`` binary or a timeout returns ``None`` rather than
raising, so call sites can decide what a failure means.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

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


def is_git_repo(path: Path) -> bool:
    """Return ``True`` only when *path* is inside a git work tree."""
    result = run_git("rev-parse", "--is-inside-work-tree", cwd=path)
    return result is not None and result.returncode == 0 and result.stdout.strip() == "true"


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
