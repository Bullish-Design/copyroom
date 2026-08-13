"""Template **layers** — a project managed by more than one template.

A *layer* is one template's management of a repo, recorded in its own Copier
answers file:

======================  ==============================  ==========================
Layer                   Answers file                    Typically ships
======================  ==============================  ==========================
``base``                ``.copier-answers.yml``         the whole repo skeleton
``<name>``              ``.copier-answers.<name>.yml``  a slice of it
======================  ==============================  ==========================

The canonical second layer is the **personal layer** (``my-ai``): the user's
``AGENTS.md`` seed, the ``CLAUDE.md`` symlink, and the personal skills, layered
onto every repo regardless of which genome generated it.

**Discovery, not configuration.** The layer set is a glob over the project root —
never declared anywhere — so it cannot drift out of sync with what Copier
actually recorded, and a layer is removed by deleting one file.

**Layers are independent.** Copier's ``-a/--answers-file`` scopes both ``copy``
and ``update`` to a single answers file: neither layer's update reads, writes, or
merges the other's files (verified empirically —
``.scratch/projects/11-my-ai-personal-layer/SPIKE.md``). CopyRoom therefore never
sequences or arbitrates between layers; it runs the same single-layer workflow
once per layer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from .._compat.errors import CopyRoomError

__all__ = [
    "BASE_LAYER",
    "Layer",
    "answers_filename",
    "discover_layers",
    "layer_name_from_answers_file",
    "resolve_layer",
    "source_status",
    "template_default_layer",
]

#: The reserved name of the layer recorded in the default ``.copier-answers.yml``.
BASE_LAYER = "base"

_PREFIX = ".copier-answers"
_SUFFIX = ".yml"
#: A layer name is a filename fragment, so keep it to safe, path-free characters.
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


# ---------------------------------------------------------------------------
# Names <-> filenames
# ---------------------------------------------------------------------------


def answers_filename(layer: str | None = None) -> str:
    """The answers filename for *layer* (``None``/``base`` → the default file).

    Raises :class:`CopyRoomError` for a name that could escape the project root
    or collide with the base file's own shape.
    """
    if layer is None or layer == BASE_LAYER:
        return f"{_PREFIX}{_SUFFIX}"
    if not _NAME_RE.match(layer) or "/" in layer or layer.endswith("."):
        raise CopyRoomError(
            f"Invalid layer name {layer!r}: use letters, digits, '.', '-' or '_' "
            f"(it becomes part of the filename {_PREFIX}.<name>{_SUFFIX})."
        )
    return f"{_PREFIX}.{layer}{_SUFFIX}"


def layer_name_from_answers_file(filename: str) -> str | None:
    """The layer name recorded by *filename*, or ``None`` if it isn't one.

    ``.copier-answers.yml`` → ``base``; ``.copier-answers.my-ai.yml`` →
    ``my-ai``; anything else → ``None``.
    """
    name = Path(filename).name
    if name == f"{_PREFIX}{_SUFFIX}":
        return BASE_LAYER
    if name.startswith(f"{_PREFIX}.") and name.endswith(_SUFFIX):
        middle = name[len(_PREFIX) + 1 : -len(_SUFFIX)]
        return middle or None
    return None


# ---------------------------------------------------------------------------
# The layer itself
# ---------------------------------------------------------------------------


@dataclass
class Layer:
    """One template layer of a project, as recorded on disk."""

    name: str
    answers_file: Path  # relative to the project root
    template_id: str | None = None  # Copier's ``_template``, when recorded
    template_source: str | None = None  # Copier's ``_src_path``
    ref: str | None = None  # Copier's ``_commit``

    @property
    def is_base(self) -> bool:
        return self.name == BASE_LAYER

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "answers_file": str(self.answers_file),
            "template_id": self.template_id,
            "template_source": self.template_source,
            "ref": self.ref,
        }


def _read_layer(project_root: Path, name: str, answers_rel: Path) -> Layer:
    """Build a :class:`Layer` from an answers file, tolerating a bad read.

    An unreadable or non-mapping answers file yields a layer with empty metadata
    rather than an exception: *listing* layers must never fail because one of
    them is malformed — the commands that act on a layer report that themselves.
    """
    layer = Layer(name=name, answers_file=answers_rel)
    try:
        with open(project_root / answers_rel) as f:
            data = yaml.safe_load(f)
    except (yaml.YAMLError, OSError):
        return layer
    if not isinstance(data, dict):
        return layer
    for attr, key in (("template_id", "_template"), ("template_source", "_src_path"), ("ref", "_commit")):
        value = data.get(key)
        if value is not None:
            setattr(layer, attr, str(value))
    return layer


#: Schemes and shorthands Copier resolves over the network. A remote source
#: cannot be validated offline, so it is reported as ``remote``, never ``missing``.
_REMOTE_PREFIXES = ("gh:", "gl:", "bb:", "git+", "git@")
_REMOTE_SCHEMES = ("://",)


def source_status(layer: Layer, project_root: str | Path) -> tuple[str, str]:
    """Classify a layer's recorded ``_src_path``.

    Returns ``(status, detail)`` where status is one of:

    ``unset``
        No ``_src_path`` recorded — Copier has never linked this layer.
    ``remote``
        A URL or forge shorthand. Not checked: resolving it needs the network.
    ``ok``
        A local path that resolves to a directory.
    ``missing``
        A local path that does not resolve. ``update`` cannot run until it is
        repointed — the failure mode a bare directory name produces, because
        Copier resolves a relative source against the invocation directory.
    """
    src = layer.template_source
    if not src:
        return "unset", "no _src_path recorded"
    if src.startswith(_REMOTE_PREFIXES) or any(s in src for s in _REMOTE_SCHEMES):
        return "remote", src
    candidate = Path(src)
    if not candidate.is_absolute():
        candidate = Path(project_root) / candidate
    if candidate.is_dir():
        return "ok", str(candidate)
    return "missing", f"{src} → {candidate} does not exist"


def discover_layers(project_root: str | Path) -> list[Layer]:
    """Every layer recorded at *project_root*, base first then alphabetical.

    Returns an empty list for a repo Copier has never touched.
    """
    root = Path(project_root)
    found: list[Layer] = []
    try:
        entries = sorted(root.iterdir())
    except OSError:
        return found

    for entry in entries:
        if not entry.is_file():
            continue
        name = layer_name_from_answers_file(entry.name)
        if name is None:
            continue
        found.append(_read_layer(root, name, Path(entry.name)))

    found.sort(key=lambda layer: (not layer.is_base, layer.name))
    return found


def resolve_layer(project_root: str | Path, layer: str | None = None) -> Layer:
    """The named layer at *project_root* (``None`` → ``base``).

    Raises :class:`CopyRoomError` when that layer isn't recorded, naming the
    layers that *are* — the common cause is a typo or a repo that never had the
    layer applied (``copyroom layer add``).
    """
    root = Path(project_root)
    name = layer or BASE_LAYER
    answers_rel = Path(answers_filename(name))

    if (root / answers_rel).is_file():
        return _read_layer(root, name, answers_rel)

    present = [existing.name for existing in discover_layers(root)]
    if not present:
        raise CopyRoomError(
            f"No template layer here: {root} has no {answers_filename(None)} and no "
            f"{_PREFIX}.<name>{_SUFFIX}. Generate with 'copyroom new', or add a layer "
            "with 'copyroom layer add <template>'."
        )
    raise CopyRoomError(
        f"No '{name}' layer here ({answers_rel} not found). Layers present: "
        f"{', '.join(present)}. Add one with 'copyroom layer add <template>'."
    )


# ---------------------------------------------------------------------------
# The template's own opinion about its layer name
# ---------------------------------------------------------------------------


def template_default_layer(template_dir: str | Path) -> str | None:
    """The layer name a template declares via ``_answers_file`` in ``copier.yml``.

    An overlay template that ships ``_answers_file: .copier-answers.my-ai.yml``
    names its own layer, so ``copyroom layer add <template>`` needs no ``--as``.
    Returns ``None`` when the template declares nothing, declares the default
    file, or can't be read — every one of which means "let the caller decide".
    """
    root = Path(template_dir)
    for candidate in ("copier.yml", "copier.yaml"):
        path = root / candidate
        if not path.is_file():
            continue
        try:
            with open(path) as f:
                data = yaml.safe_load(f)
        except (yaml.YAMLError, OSError):
            return None
        if not isinstance(data, dict):
            return None
        declared = data.get("_answers_file")
        if not isinstance(declared, str):
            return None
        name = layer_name_from_answers_file(declared)
        return None if name == BASE_LAYER else name
    return None
