"""Workshop registry lookups shared by all workshop/release workflows.

Resolves a template ID to its source and loads its configured checks from
either ``copyroom.yml`` (a ``templates``/``registry`` mapping) or a
``registry/<template_id>.yml`` file. Also provides workshop-root resolution
so commands work from any descendant directory.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from .._compat import gitutil
from .._compat.errors import CopyRoomError
from .._compat.semver import select_latest_semver
from ..session.detector import detect_workshop_root
from .model import RegistryEntry, RegistryValidation


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


# ---------------------------------------------------------------------------
# Registry CLI operations — list / show / validate / add
#
# These are read-only or a single create. copyroom.yml is NEVER rewritten:
# round-tripping it through PyYAML is lossy (drops comments and ordering), so
# `add` only ever writes a *new* registry/<id>.yml file.
# ---------------------------------------------------------------------------


def _registry_ids(workshop_root: Path) -> list[str]:
    """All known template ids: copyroom.yml map keys + ``registry/*.yml`` stems."""
    ids: list[str] = []
    cfg = _load_yaml(workshop_root / "copyroom.yml")
    if cfg:
        templates = cfg.get("templates", cfg.get("registry")) or {}
        if isinstance(templates, dict):
            ids.extend(str(k) for k in templates)

    registry_dir = workshop_root / "registry"
    if registry_dir.is_dir():
        for entry in sorted(registry_dir.glob("*.yml")):
            if entry.stem not in ids:
                ids.append(entry.stem)
    return ids


def load_entry(workshop_root: Path, template_id: str) -> RegistryEntry:
    """Resolve a single registry entry, raising if *template_id* is unknown."""
    if template_id not in _registry_ids(workshop_root):
        raise CopyRoomError(
            f"Template '{template_id}' not found in workshop registry.",
            state="not_started",
        )
    return RegistryEntry(
        template_id=template_id,
        source=resolve_template_source(workshop_root, template_id),
        checks=load_checks(workshop_root, template_id),
    )


def list_templates(workshop_root: Path) -> list[RegistryEntry]:
    """List every registered template as a resolved :class:`RegistryEntry`."""
    return [load_entry(workshop_root, tid) for tid in _registry_ids(workshop_root)]


def _resolve_local_source(workshop_root: Path, source: str) -> Path:
    """Resolve a (possibly relative) local source path against the workshop root."""
    path = Path(source)
    if not path.is_absolute():
        path = workshop_root / source
    return path


def _validate_entry(workshop_root: Path, entry: RegistryEntry) -> list[str]:
    """Return the list of problems for one entry (empty when it is sound)."""
    problems: list[str] = []

    source = entry.source
    if not source:
        problems.append("no source configured")
    elif gitutil.looks_remote(source):
        tags = gitutil.ls_remote_tags(source)
        if tags is None:
            problems.append(f"remote source unreachable: {source}")
        elif select_latest_semver(tags) is None:
            problems.append(f"remote source has no semver (vX.Y.Z) tags: {source}")
    else:
        path = _resolve_local_source(workshop_root, source)
        if not path.exists():
            problems.append(f"source path not found: {source}")
        elif not gitutil.is_git_repo(path):
            problems.append(f"source is not a git repository: {source}")
        elif select_latest_semver(gitutil.list_tags(path)) is None:
            problems.append(f"source has no semver (vX.Y.Z) tags: {source}")

    scenarios_dir = workshop_root / "scenarios" / entry.template_id
    if not scenarios_dir.is_dir():
        problems.append(f"no scenarios directory: scenarios/{entry.template_id}/")

    return problems


def validate_registry(workshop_root: Path) -> RegistryValidation:
    """Validate every registry entry: source resolves, has tags, has scenarios."""
    validation = RegistryValidation()
    for entry in list_templates(workshop_root):
        validation.problems[entry.template_id] = _validate_entry(workshop_root, entry)
    return validation


def add_template(
    workshop_root: Path,
    template_id: str,
    source: str,
    scaffold: bool = False,
) -> Path:
    """Create a **new** ``registry/<template_id>.yml`` (never touching copyroom.yml).

    Refuses to overwrite an existing entry file. With *scaffold*, also creates a
    ``scenarios/<template_id>/`` skeleton so the template can be rendered. Returns
    the path of the file written.
    """
    registry_dir = workshop_root / "registry"
    target = registry_dir / f"{template_id}.yml"
    if target.exists():
        raise CopyRoomError(
            f"Registry entry already exists: {target.relative_to(workshop_root)}. "
            "Edit it directly, or remove it first.",
            state="not_started",
        )

    registry_dir.mkdir(parents=True, exist_ok=True)
    target.write_text(
        f"id: {template_id}\n"
        f"source: {source}\n"
        "checks: []\n"
    )

    if scaffold:
        scenario_dir = workshop_root / "scenarios" / template_id
        scenario_dir.mkdir(parents=True, exist_ok=True)
        default_scenario = scenario_dir / "default.yml"
        if not default_scenario.exists():
            default_scenario.write_text(
                f"# Default scenario for '{template_id}'.\n"
                "# Fill in the template's Copier prompt answers as a YAML mapping, e.g.:\n"
                "# project_name: example\n"
            )

    return target
