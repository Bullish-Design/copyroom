"""Deterministic edit file parser for ``-edits.yml`` DSL.

Implements the edit file format described in §6.5 of the implementation plan.
Edit files live alongside scenario answers as
``scenarios/<template_id>/<scenario_id>-edits.yml``.

Supported actions:

    ``append``
        Append content to the end of a file.

    ``set-field``
        Modify a TOML/YAML field by path.

    ``create``
        Create a new file with given content.

    ``patch``
        Apply a unified diff.

When no edits file exists, no edits are applied (returns an empty list).
"""

from __future__ import annotations

from pathlib import Path

import yaml

from .._compat.fsutil import atomic_write_text

# ---------------------------------------------------------------------------
# Edits DSL types
# ---------------------------------------------------------------------------

# Action names supported by the DSL
_VALID_ACTIONS = frozenset({"append", "set-field", "create", "patch"})


class EditsParseError(Exception):
    """Raised when an edits file cannot be parsed."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_edits(edits_path: Path) -> list[dict]:
    """Load and validate an edits file.

    Parameters
    ----------
    edits_path:
        Path to a ``<scenario>-edits.yml`` file.

    Returns
    -------
    list[dict]
        A list of edit operations. Each operation is a dict with keys
        ``file``, ``action``, and action-specific fields.

    Raises
    ------
    EditsParseError
        If the file cannot be parsed or contains invalid edits.

    Notes
    -----
    If the file does not exist, returns an empty list (no edits to apply).
    """
    if not edits_path.is_file():
        return []

    try:
        with open(edits_path) as f:
            raw = yaml.safe_load(f)
    except (yaml.YAMLError, OSError) as exc:
        raise EditsParseError(f"Failed to parse edits file {edits_path}: {exc}") from exc

    if raw is None:
        return []

    if not isinstance(raw, dict):
        raise EditsParseError(
            f"Edits file {edits_path}: expected a mapping, got {type(raw).__name__}",
        )

    edits = raw.get("edits", raw.get("edit", None))
    if edits is None:
        raise EditsParseError(
            f"Edits file {edits_path}: missing 'edits' key",
        )

    if not isinstance(edits, list):
        raise EditsParseError(
            f"Edits file {edits_path}: 'edits' must be a list, got {type(edits).__name__}",
        )

    return _validate_edits(edits, edits_path)


def apply_edits(edits: list[dict], target_dir: Path) -> None:
    """Apply a list of edit operations to files in *target_dir*.

    Parameters
    ----------
    edits:
        List of edit operations (from :func:`load_edits`).
    target_dir:
        Root directory to apply edits within.
    """
    if not edits:
        return

    for op in edits:
        action = op["action"]
        file_path = target_dir / op["file"]

        if action == "append":
            _apply_append(file_path, op.get("content", ""))
        elif action == "set-field":
            _apply_set_field(file_path, op.get("path", []), op.get("value"))
        elif action == "create":
            _apply_create(file_path, op.get("content", ""), op.get("mode"))
        elif action == "patch":
            _apply_patch(file_path, op.get("patch", ""), target_dir)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate_edits(edits: list, path: Path) -> list[dict]:
    """Validate edit operations and return them as typed dicts."""
    result: list[dict] = []
    for i, op in enumerate(edits, 1):
        if not isinstance(op, dict):
            raise EditsParseError(
                f"Edits file {path}: edit #{i} must be a mapping, got {type(op).__name__}",
            )
        if "file" not in op:
            raise EditsParseError(
                f"Edits file {path}: edit #{i} missing required 'file' key",
            )
        if "action" not in op:
            raise EditsParseError(
                f"Edits file {path}: edit #{i} (file={op.get('file')}) missing required 'action' key",
            )
        if op["action"] not in _VALID_ACTIONS:
            raise EditsParseError(
                f"Edits file {path}: edit #{i} has unknown action '{op['action']}'. "
                f"Valid actions: {sorted(_VALID_ACTIONS)}",
            )
        result.append(dict(op))
    return result


# ---------------------------------------------------------------------------
# Action implementations
# ---------------------------------------------------------------------------


def _apply_append(file_path: Path, content: str) -> None:
    """Append *content* to the end of *file_path*."""
    content = str(content)
    if not file_path.exists():
        _apply_create(file_path, content)
        return

    text = file_path.read_text()
    if not text.endswith("\n"):
        text += "\n"
    text += content
    if not content.endswith("\n"):
        text += "\n"
    file_path.write_text(text)


def _apply_create(file_path: Path, content: str, mode: str | None = None) -> None:
    """Create *file_path* with *content*."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    content = str(content)
    if not content.endswith("\n"):
        content += "\n"
    file_path.write_text(content)
    # Apply execute permission if mode indicates
    if mode and "x" in mode:
        file_path.chmod(0o755)


def _apply_set_field(file_path: Path, path: list[str], value: object) -> None:
    """Set a field at *path* in a TOML or YAML file.

    Currently supports YAML files; TOML support is deferred.
    """
    if not file_path.exists():
        raise EditsParseError(
            f"set-field: file {file_path} does not exist. Use 'create' to create new files.",
        )

    suffix = file_path.suffix.lower()

    if suffix in (".yml", ".yaml"):
        _set_field_yaml(file_path, path, value)
    elif suffix == ".toml":
        _set_field_toml(file_path, path, value)
    else:
        raise EditsParseError(
            f"set-field: unsupported file type {suffix!r} for {file_path}. "
            f"Supported: .yml, .yaml, .toml",
        )


def _set_field_yaml(file_path: Path, path: list[str], value: object) -> None:
    """Set a field in a YAML file at the given path."""
    try:
        with open(file_path) as f:
            doc = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise EditsParseError(f"set-field: failed to parse {file_path}: {exc}") from exc

    if not isinstance(doc, dict):
        raise EditsParseError(
            f"set-field: {file_path} root must be a mapping, got {type(doc).__name__}",
        )

    _set_nested_value(doc, path, value)

    atomic_write_text(
        file_path,
        yaml.safe_dump(doc, default_flow_style=False, sort_keys=False),
    )


def _set_field_toml(file_path: Path, path: list[str], value: object) -> None:
    """Set a field at *path* in a TOML file, preserving comments and formatting.

    Parses with :mod:`tomlkit` (a round-tripping TOML library), sets the nested
    key, and writes the document back. Tables along *path* are created as needed.
    Unlike the previous hand-rolled string writer, this survives inline tables,
    arrays-of-tables, quoted keys, and comments mid-section — a botched edit can
    no longer silently produce a misleading simulation (P2-2).
    """
    import tomlkit
    from tomlkit.exceptions import TOMLKitError

    try:
        doc = tomlkit.parse(file_path.read_text())
    except TOMLKitError as exc:
        raise EditsParseError(f"set-field: failed to parse {file_path}: {exc}") from exc

    _set_nested_value(doc, path, value)

    atomic_write_text(file_path, tomlkit.dumps(doc))


def _apply_patch(file_path: Path, patch_text: str, target_dir: Path) -> None:
    """Apply a unified diff patch to *file_path* via the system ``patch`` binary.

    The ``patch`` binary is an external dependency; its absence, or a failed
    apply, is **fatal** (raises :class:`EditsParseError`) rather than a warning.
    A silently-skipped patch would yield a wrong ``update-test`` simulation that
    looks authoritative (P2-2). ``apply_user_edits`` wraps this in a try/except
    that fails the simulation, so the error is surfaced, not swallowed.
    """
    import shutil
    import subprocess

    if not patch_text:
        return

    if shutil.which("patch") is None:
        raise EditsParseError(
            "the 'patch' binary is required to apply a 'patch' edit but was not "
            "found on PATH.",
        )

    # Ensure the directory exists for new files
    file_path.parent.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        ["patch", "--quiet", "--force", str(file_path)],
        input=patch_text,
        capture_output=True,
        text=True,
        cwd=str(target_dir),
    )

    if result.returncode != 0:
        raise EditsParseError(
            f"patch failed for {file_path}: {result.stderr.strip() or 'no output'}",
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _set_nested_value(doc: dict, path: list[str], value: object) -> None:
    """Set a nested value in a dict by path.

    For lists, path elements may be integer indices as strings (e.g., "0").
    """
    if not path:
        return
    current: object = doc
    for key in path[:-1]:
        if isinstance(current, dict):
            if key not in current:
                current[key] = {}
            current = current[key]
        elif isinstance(current, list):
            idx = int(key)
            while len(current) <= idx:
                current.append({})
            current = current[idx]
        else:
            raise EditsParseError(
                f"set-field: cannot traverse into {type(current).__name__} at path segment '{key}'",
            )
    if isinstance(current, dict):
        current[path[-1]] = value
    elif isinstance(current, list):
        idx = int(path[-1])
        while len(current) <= idx:
            current.append(None)
        current[idx] = value
    else:
        raise EditsParseError(
            f"set-field: cannot set value on {type(current).__name__}",
        )
