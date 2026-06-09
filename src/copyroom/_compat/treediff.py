"""Shared file-tree comparison used by golden testing and adoption.

Both ``workshop/golden.py`` (rendered output vs golden snapshot) and
``manage/adopt.py`` (rendered template vs the real repo) need the same
question answered: *which files were added, modified, or removed between two
directory trees?* This module is the single answer.

Copier's ``.copier-answers.yml`` is always excluded from the comparison: it
records a machine-specific ``_src_path`` / ``_commit`` and would otherwise
produce spurious diffs (see ``_is_copier_answers_file``).
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["tree_diff", "collect_files"]


def _is_copier_answers_file(name: str) -> bool:
    """Return True for Copier's answers file (default or multi-template form).

    Copier writes ``.copier-answers.yml`` (or ``.copier-answers.<name>.yml``)
    into every rendered project, recording an absolute ``_src_path`` and a
    ``_commit`` that differ across machines/checkouts. Including it would
    produce spurious diffs, so it is excluded from every comparison.
    """
    return name.startswith(".copier-answers") and name.endswith(".yml")


def collect_files(
    directory: Path,
    *,
    relative_to: Path | None = None,
    ignore_dirs: frozenset[str] = frozenset(),
) -> set[str]:
    """Collect the comparable files under *directory* as relative path strings.

    Every regular file is included except Copier's answers file. Any file whose
    path passes through a directory named in *ignore_dirs* (e.g. ``.git``,
    ``__pycache__``) is skipped — this is what lets the same helper compare a
    clean rendered tree and a real working repo.
    """
    if relative_to is None:
        relative_to = directory

    files: set[str] = set()
    for item in sorted(directory.rglob("*")):
        if not item.is_file():
            continue
        if _is_copier_answers_file(item.name):
            continue
        rel = item.relative_to(relative_to)
        if ignore_dirs and any(part in ignore_dirs for part in rel.parts):
            continue
        files.add(str(rel))
    return files


def _file_content_differs(path_a: Path, path_b: Path) -> bool:
    """Return True if the two files have different byte content."""
    try:
        return path_a.read_bytes() != path_b.read_bytes()
    except OSError:
        return True


def tree_diff(
    a: Path,
    b: Path,
    *,
    ignore_dirs: frozenset[str] = frozenset(),
) -> tuple[set[str], set[str], set[str]]:
    """Diff tree *a* (baseline) against tree *b* (target).

    Returns ``(added, modified, removed)`` describing how to get from *a* to
    *b*:

    - ``added`` — files present in *b* but not *a*;
    - ``removed`` — files present in *a* but not *b*;
    - ``modified`` — files in both whose content differs.

    Copier answers files are excluded; *ignore_dirs* skips whole subtrees.
    """
    a_files = collect_files(a, relative_to=a, ignore_dirs=ignore_dirs)
    b_files = collect_files(b, relative_to=b, ignore_dirs=ignore_dirs)

    added = b_files - a_files
    removed = a_files - b_files
    modified = {
        rel
        for rel in (a_files & b_files)
        if _file_content_differs(a / rel, b / rel)
    }
    return added, modified, removed
