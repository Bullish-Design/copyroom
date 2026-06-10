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
from .._compat.fsutil import atomic_write_text
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


def _registry_map(cfg: dict | None) -> dict:
    """The one definition of where templates are declared in ``copyroom.yml``.

    Accepts either the ``templates:`` or the ``registry:`` top-level key (a
    documented alias). Returns ``{}`` when neither is a mapping.
    """
    if not isinstance(cfg, dict):
        return {}
    templates = cfg.get("templates", cfg.get("registry"))
    return templates if isinstance(templates, dict) else {}


def _source_of(value: object) -> str | None:
    """Extract a source string from an inline value or a registry-file dict."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        src = value.get("source", value.get("url"))
        return src if isinstance(src, str) else None
    return None


def _checks_of(value: object) -> list[str] | None:
    """Extract a checks list from a dict value, or ``None`` if none is declared.

    ``None`` (rather than ``[]``) signals "this file doesn't declare checks for
    this id", so the caller can fall through to the other source.
    """
    if isinstance(value, dict):
        raw = value.get("checks", [])
        if isinstance(raw, list):
            return [str(c) for c in raw]
    return None


def load_registry(workshop_root: Path) -> dict[str, RegistryEntry]:
    """Read the whole workshop registry once into normalized entries by id.

    ``copyroom.yml`` (its ``templates``/``registry`` map) and each
    ``registry/<id>.yml`` file are each parsed exactly once. ``copyroom.yml``
    wins for source precedence; checks come from whichever file declares them
    (an inline mapping, else the per-id file). This is the single backing store
    for :func:`resolve_template_source`, :func:`load_checks`, :func:`load_entry`,
    and :func:`list_templates`.
    """
    inline = {str(k): v for k, v in _registry_map(_load_yaml(workshop_root / "copyroom.yml")).items()}

    registry_files: dict[str, dict] = {}
    registry_dir = workshop_root / "registry"
    if registry_dir.is_dir():
        for entry_file in sorted(registry_dir.glob("*.yml")):
            data = _load_yaml(entry_file)
            if data is not None:
                registry_files[entry_file.stem] = data

    # copyroom.yml ids first (declaration order), then registry-only ids.
    ordered_ids = list(inline) + [s for s in sorted(registry_files) if s not in inline]

    entries: dict[str, RegistryEntry] = {}
    for tid in ordered_ids:
        file_val = registry_files.get(tid)

        # Source: copyroom.yml owns the id if it declares it, else the per-id file.
        source = _source_of(inline[tid]) if tid in inline else _source_of(file_val)

        # Checks: an inline mapping wins; otherwise the per-id file.
        checks = _checks_of(inline[tid]) if tid in inline else None
        if checks is None:
            checks = _checks_of(file_val)
        if checks is None:
            checks = []

        entries[tid] = RegistryEntry(template_id=tid, source=source, checks=checks)

    return entries


def resolve_template_source(workshop_root: Path, template_id: str) -> str | None:
    """Resolve a template ID to its source path/URL from the workshop registry.

    Looks in ``copyroom.yml`` (``templates`` or ``registry`` mapping) first,
    then falls back to ``registry/<template_id>.yml``.
    """
    entry = load_registry(workshop_root).get(template_id)
    return entry.source if entry is not None else None


def load_checks(workshop_root: Path, template_id: str) -> list[str]:
    """Load the list of test-check commands for a template from the registry."""
    entry = load_registry(workshop_root).get(template_id)
    return entry.checks if entry is not None else []


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


def load_entry(workshop_root: Path, template_id: str) -> RegistryEntry:
    """Resolve a single registry entry, raising if *template_id* is unknown."""
    registry = load_registry(workshop_root)
    if template_id not in registry:
        raise CopyRoomError(
            f"Template '{template_id}' not found in workshop registry.",
            state="not_started",
        )
    return registry[template_id]


def list_templates(workshop_root: Path) -> list[RegistryEntry]:
    """List every registered template as a resolved :class:`RegistryEntry`."""
    return list(load_registry(workshop_root).values())


def _resolve_local_source(workshop_root: Path, source: str) -> Path:
    """Resolve a (possibly relative) local source path against the workshop root.

    Expands ``~`` first (via :func:`gitutil.local_path`); a relative path is then
    joined onto the workshop root.
    """
    path = gitutil.local_path(source)
    if not path.is_absolute():
        path = workshop_root / path
    return path


def resolve_source_for_copier(workshop_root: Path, source: str) -> str:
    """Return the source to hand to ``copier copy`` for a registry entry.

    A *local* source is resolved to an absolute path against the workshop root,
    so a relative source (e.g. ``source: .``) works no matter which descendant
    directory the command runs from (the copier-facing callers used to pass the
    raw source, which only worked when ``cwd == workshop root`` — P3-2). Remote
    sources pass through unchanged.
    """
    if gitutil.looks_remote(source):
        return source
    return str(_resolve_local_source(workshop_root, source))


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
    # A new registry/<id>.yml would be shadowed by an inline copyroom.yml entry
    # (the resolver reads copyroom.yml first), so refuse rather than silently
    # writing a dead file.
    if template_id in load_registry(workshop_root):
        raise CopyRoomError(
            f"Template '{template_id}' is already registered (in copyroom.yml "
            "or registry/). Edit the existing definition instead.",
            state="not_started",
        )

    registry_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        target,
        yaml.safe_dump(
            {"id": template_id, "source": source, "checks": []},
            sort_keys=False,
        ),
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
