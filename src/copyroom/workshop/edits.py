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

    with open(file_path, "w") as f:
        yaml.safe_dump(doc, f, default_flow_style=False, sort_keys=False)


def _set_field_toml(file_path: Path, path: list[str], value: object) -> None:
    """Set a field in a TOML file at the given path.

    Uses basic string manipulation — proper TOML editing via ``tomllib``
    / ``tomli_w`` is deferred to a future version.
    """
    # Simple implementation: read lines, find/replace or append
    if len(path) >= 2:
        # Table-based path: [table] key = value
        section = path[:-1]
        key = path[-1]
        _set_toml_table_key(file_path, section, key, value)
    elif len(path) == 1:
        # Top-level key = value
        _set_toml_key(file_path, path[0], value)


def _set_toml_key(file_path: Path, key: str, value: object) -> None:
    """Set a top-level key in a TOML file."""
    lines = file_path.read_text().splitlines()
    key_eq = f"{key} ="
    value_str = _toml_value_str(value)
    found = False
    new_lines = []
    for line in lines:
        if line.strip().startswith(key_eq):
            new_lines.append(f"{key} = {value_str}")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"{key} = {value_str}")
    file_path.write_text("\n".join(new_lines) + "\n")


def _set_toml_table_key(file_path: Path, section: list[str], key: str, value: object) -> None:
    """Set a key inside a TOML [table] section."""
    lines = file_path.read_text().splitlines()
    section_str = "[" + ".".join(section) + "]"
    key_eq = f"{key} ="
    value_str = _toml_value_str(value)
    in_section = False
    found = False
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped == section_str:
            in_section = True
            new_lines.append(line)
            continue
        if in_section and (stripped.startswith("[") or not stripped):
            # We left our section; insert key if not found
            if not found:
                new_lines.insert(-1, f"{key} = {value_str}")
                found = True
            in_section = stripped.startswith("[")
            new_lines.append(line)
            continue
        if in_section and stripped.startswith(key_eq):
            new_lines.append(f"{key} = {value_str}")
            found = True
            continue
        new_lines.append(line)
    if not found:
        # Section not found; append it
        new_lines.append("")
        new_lines.append(section_str)
        new_lines.append(f"{key} = {value_str}")
    file_path.write_text("\n".join(new_lines) + "\n")


def _toml_value_str(value: object) -> str:
    """Convert a Python value to a TOML-compatible string."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        items = [_toml_value_str(v) for v in value]
        return "[" + ", ".join(items) + "]"
    if isinstance(value, str):
        # For simple strings, use double quotes
        return f'"{value}"'
    return str(value)


def _apply_patch(file_path: Path, patch_text: str, target_dir: Path) -> None:
    """Apply a unified diff patch to *file_path*.

    Uses ``patch`` command via subprocess.
    """
    import subprocess
    import sys

    if not patch_text:
        return

    # Ensure the directory exists for new files
    file_path.parent.mkdir(parents=True, exist_ok=True)

    # Run patch
    result = subprocess.run(
        ["patch", "--quiet", "--force", str(file_path)],
        input=patch_text,
        capture_output=True,
        text=True,
        cwd=str(target_dir),
    )

    if result.returncode != 0:
        if result.stderr:
            print(f"Warning: patch failed for {file_path}: {result.stderr}", file=sys.stderr)


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
