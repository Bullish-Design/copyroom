"""Filesystem helpers shared across CopyRoom.

A single atomic-write primitive so user-facing config files (registry entries,
edited YAML/TOML) are never left half-written if the process dies mid-write
(P3-6). Scratch/sandbox writes don't need this and use plain ``write_text``.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write_text(path: Path, text: str) -> None:
    """Write *text* to *path* via a temp file + os.replace (no torn writes on crash)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)
