"""Workshop registry lookups shared by all workshop/release workflows.

Resolves a template ID to its source and loads its configured checks from
either ``copyroom.yml`` (a ``templates``/``registry`` mapping) or a
``registry/<template_id>.yml`` file. Also provides workshop-root resolution
so commands work from any descendant directory.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from .._compat.errors import CopyRoomError
from ..session.detector import detect_workshop_root


def _load_yaml(path: Path) -> dict | None:
    """Load a YAML file as a dict, or return ``None`` on any error/non-mapping."""
    if not path.is_file():
        return None
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
    except (yaml.YAMLError, OSError):
        return None
    return data if isinstance(data, dict) else None


def resolve_template_source(workshop_root: Path, template_id: str) -> str | None:
    """Resolve a template ID to its source path/URL from the workshop registry.

    Looks in ``copyroom.yml`` (``templates`` or ``registry`` mapping) first,
    then falls back to ``registry/<template_id>.yml``.
    """
    cfg = _load_yaml(workshop_root / "copyroom.yml")
    if cfg:
        templates = cfg.get("templates", cfg.get("registry")) or {}
        if isinstance(templates, dict):
            src = templates.get(template_id)
            if isinstance(src, str):
                return src
            if isinstance(src, dict):
                return src.get("source", src.get("url"))

    tpl = _load_yaml(workshop_root / "registry" / f"{template_id}.yml")
    if tpl:
        src = tpl.get("source", tpl.get("url"))
        if isinstance(src, str):
            return src

    return None


def load_checks(workshop_root: Path, template_id: str) -> list[str]:
    """Load the list of test-check commands for a template from the registry."""
    candidates = (
        (_load_yaml(workshop_root / "copyroom.yml"),
         lambda c: (c.get("templates") or {}).get(template_id)),
        (_load_yaml(workshop_root / "registry" / f"{template_id}.yml"),
         lambda c: c),
    )
    for cfg, getter in candidates:
        if not cfg:
            continue
        tpl = getter(cfg)
        if isinstance(tpl, dict):
            raw = tpl.get("checks", [])
            if isinstance(raw, list):
                return [str(c) for c in raw]
    return []


def require_workshop_root(workshop_root: Path | None) -> Path:
    """Return *workshop_root*, or detect it from the cwd, raising if none found."""
    if workshop_root is not None:
        return workshop_root
    detected = detect_workshop_root()
    if detected is None:
        raise CopyRoomError(
            "No CopyRoom workshop found here. Run this from a workshop "
            "directory or any descendant.",
            state="not_started",
        )
    return detected
