"""Apply a template to an existing repo as a **layer** — ``copyroom layer add``.

``adopt`` and ``layer add`` are the two ways a repo comes under a template's
management, and they answer different questions:

* ``adopt`` — *"this repo already looks like the template; record the link."*
  Report-only: it renders into a scratch dir, reports drift, and writes nothing
  but the answers file.
* ``layer add`` — *"this repo does **not** have these files yet; put them here
  and record the link."* That is a ``copier copy``, so the template's files land
  in the repo.

The motivating case is the **personal layer**: `my-ai` ships the user's
``AGENTS.md`` seed, the ``CLAUDE.md`` symlink, and the personal skills, and every
repo needs them regardless of which genome generated it. Because the layer
writes to its own answers file, it composes with whatever template already
manages the repo instead of replacing it.

Idempotence and safety come from Copier, not from us: re-running is a re-copy,
and a layer template protects the repo's own files with ``_skip_if_exists``.
The one thing this module guards is **retargeting** — silently pointing an
existing layer at a different template would strand the repo's history.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .._compat.copier import copier_copy
from .._compat.errors import CopyRoomError
from ..project.layers import (
    BASE_LAYER,
    Layer,
    answers_filename,
    discover_layers,
    layer_name_from_answers_file,
    template_default_layer,
)
from ..template.workspace import _ensure_local_repo, _template_cache_dir, resolve_project_root

__all__ = ["LayerAdd", "add_layer", "list_layers"]


@dataclass
class LayerAdd:
    """Outcome of :func:`add_layer` — what landed, and where."""

    repo_root: Path
    layer: str
    answers_file: Path  # relative to repo_root
    template_source: str
    template_ref: str | None = None
    replaced: bool = False  # the layer already existed and was re-applied
    written: list[str] = field(default_factory=list)  # repo-relative paths Copier touched

    def to_dict(self) -> dict:
        return {
            "command": "layer-add",
            "repo_root": str(self.repo_root),
            "layer": self.layer,
            "answers_file": str(self.answers_file),
            "template_source": self.template_source,
            "template_ref": self.template_ref,
            "replaced": self.replaced,
            "written": sorted(self.written),
        }


def _resolve_layer_name(repo_dir: Path, template: str, requested: str | None) -> str:
    """Pick the layer name: ``--as`` wins, else the template's own declaration.

    An overlay template declares ``_answers_file: .copier-answers.<name>.yml`` in
    its ``copier.yml``, which *is* its layer name — so the usual call needs no
    ``--as`` at all. Falling back to the template directory's name keeps a
    template that declared nothing usable without forcing a flag.
    """
    if requested is not None:
        if requested == BASE_LAYER:
            raise CopyRoomError(
                "The 'base' layer is the project's own template — create it with "
                "'copyroom new' or link it with 'copyroom adopt', not 'layer add'."
            )
        return requested

    declared = template_default_layer(repo_dir)
    if declared:
        return declared

    fallback = layer_name_from_answers_file(Path(template).name) or Path(template.rstrip("/")).name
    if not fallback or fallback == BASE_LAYER:
        raise CopyRoomError(
            f"Cannot infer a layer name for {template!r}: it declares no "
            "'_answers_file' in copier.yml. Name it explicitly: --as <name>."
        )
    return fallback


def add_layer(
    template: str,
    repo_root: str | Path | None = None,
    layer: str | None = None,
    ref: str | None = None,
    force: bool = False,
) -> LayerAdd:
    """Apply *template* to *repo_root* as a layer; return what landed.

    The layer name defaults to the one the template declares (see
    :func:`_resolve_layer_name`). Re-applying an existing layer is allowed and
    idempotent; pointing it at a *different* template requires *force*.
    """
    root = resolve_project_root(repo_root)
    if not root.is_dir():
        raise CopyRoomError(f"Not a directory: {root}")

    repo_dir = _ensure_local_repo(template, _template_cache_dir(template))
    name = _resolve_layer_name(repo_dir, template, layer)
    answers_rel = Path(answers_filename(name))

    existing: Layer | None = next(
        (candidate for candidate in discover_layers(root) if candidate.name == name), None
    )
    if existing is not None and not force and _is_retarget(existing.template_source, template, repo_dir):
        raise CopyRoomError(
            f"Layer '{name}' is already recorded in {answers_rel}, managed by "
            f"{existing.template_source}. Re-run with --force to retarget it to {template}."
        )

    before = _snapshot(root)
    try:
        result = copier_copy(
            # The source string the CALLER gave us, not the local clone above.
            # Copier records this verbatim as `_src_path`, and that recorded
            # value is what every future `update --layer` resolves against —
            # so handing it the cache directory would pin each repo to a
            # machine-local path that no other machine (or CI) can resolve, and
            # that pruning the cache would break. `copyroom new` has always
            # passed the original string for the same reason. The clone above
            # exists only to read the template's copier.yml.
            source=template,
            destination=root,
            vcs_ref=ref,
            answers_file=answers_rel,
            # A layer lands in a repo that already has files, so Copier would
            # otherwise prompt per conflict and fail outright when stdin isn't a
            # terminal. The layer owns the files it ships; the ones it must not
            # touch are the template's `_skip_if_exists`, which still wins.
            overwrite=True,
        )
    except Exception as exc:
        raise CopyRoomError(f"Copier failed to apply layer '{name}': {exc}") from exc
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip() or "no output"
        raise CopyRoomError(f"Copier failed to apply layer '{name}':\n{message}")

    after = _snapshot(root)
    changed = {path for path in after.keys() & before.keys() if after[path] != before[path]}
    written = sorted((after.keys() - before.keys()) | changed)

    return LayerAdd(
        repo_root=root,
        layer=name,
        answers_file=answers_rel,
        template_source=template,
        template_ref=ref,
        replaced=existing is not None,
        written=written,
    )


def list_layers(repo_root: str | Path | None = None) -> tuple[Path, list[Layer]]:
    """``(repo_root, layers)`` for *repo_root* — the read behind ``layer list``."""
    root = resolve_project_root(repo_root)
    return root, discover_layers(root)


def _is_retarget(recorded: str | None, template: str, repo_dir: Path) -> bool:
    """Is *template* a **different** source than the one this layer recorded?

    ``_src_path`` may hold either the string the user passed (``gh:org/repo``, a
    relative path) or the resolved local checkout, depending on who wrote it —
    so a match against *either* form means "same template". Only a mismatch on
    both is a genuine retarget. An empty ``_src_path`` is treated as a match:
    refusing to re-apply a layer because its answers file is incomplete would be
    the wrong failure.
    """
    if not recorded:
        return False
    if recorded == template:
        return False
    resolved = Path(str(repo_dir)).resolve(strict=False)
    return Path(recorded).resolve(strict=False) != resolved


def _snapshot(root: Path) -> dict[str, tuple[int, int]]:
    """Cheap ``path -> (size, mtime_ns)`` map of the repo's tracked-ish files.

    Used only to report *what a layer wrote*. Machine-state directories are
    **pruned** rather than filtered — descending into a multi-gigabyte
    ``.devenv/`` just to discard it would dominate the command's runtime. A
    missed file means a less complete report, never a wrong write, so a
    best-effort walk is the right trade here.
    """
    import os

    from .model import EXCLUDE_DIRS

    seen: dict[str, tuple[int, int]] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        here = Path(dirpath)
        for filename in filenames:
            path = here / filename
            try:
                stat = path.lstat()
            except OSError:
                continue
            seen[str(path.relative_to(root))] = (stat.st_size, stat.st_mtime_ns)
    return seen
