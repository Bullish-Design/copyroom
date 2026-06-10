"""Detect merge conflicts left by `copier update`.

Copier's default (inline) conflict mode writes git-style <<<<<<< / >>>>>>> markers
into files rather than `.rej` siblings, so a clash shows up as marker text inside
an otherwise-modified file. `.rej` files are also collected for templates
configured with the reject strategy. Shared by project/update, template/preview,
and workshop/simulate so all three report conflicts identically (was: a fragile
stdout grep in update.py — P2-1).
"""

from __future__ import annotations

from pathlib import Path

_CONFLICT_MARKERS = ("<<<<<<<", ">>>>>>>")


def scan_conflict_markers(root: Path, candidates: set[str]) -> set[str]:
    """Return the subset of *candidates* (repo-relative paths) that contain markers."""
    found: set[str] = set()
    for rel in candidates:
        try:
            text = (root / rel).read_text(errors="ignore")
        except OSError:
            continue
        if any(m in text for m in _CONFLICT_MARKERS):
            found.add(rel)
    return found


def scan_rejects(root: Path) -> set[str]:
    """Return all `*.rej` paths under *root* (repo-relative)."""
    return {str(p.relative_to(root)) for p in root.rglob("*.rej")}
