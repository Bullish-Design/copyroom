"""Adopt a repo into management by a named or extracted template.

``copyroom adopt <template>`` answers: *"if this repo were generated from
<template> with these answers, how does it differ — and let me record the link
so it can receive updates."* It is **report-only**: it renders the template with
the agent's inferred answers into a scratch dir, diffs that against the repo for
a drift report, and (only under ``--write``) drops a ``.copier-answers.yml`` into
the repo. No other repo file is ever modified — drift is information, not a
problem to auto-fix (same philosophy as ``template-preview``).

This is the convergence point of both adoption paths: a user-named template, or
one just extracted by ``templatize`` (which already reproduces the repo, so the
drift is near-empty).
"""

from __future__ import annotations

import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from .._compat import gitutil
from .._compat.copier import copier_copy
from .._compat.errors import CopyRoomError
from .._compat.state_machine import StateMachine
from .._compat.treediff import collect_files, tree_diff
from ..template.workspace import _ensure_local_repo, _template_cache_dir, resolve_project_root
from .model import (
    EXCLUDE_DIRS,
    VALID_ADOPTION_TRANSITIONS,
    Adoption,
    AdoptionStatus,
    DriftResult,
)

__all__ = ["CopyRoomError", "adopt"]

_adoption_sm = StateMachine(VALID_ADOPTION_TRANSITIONS, entity_name="Adoption")

# Repo paths that must not leak into the sandbox used to build the drift patch.
_SANDBOX_IGNORE = shutil.ignore_patterns(*EXCLUDE_DIRS, "*.pyc")

_ANSWERS_FILENAME = ".copier-answers.yml"


def adopt(
    template: str,
    repo_root: str | Path | None = None,
    ref: str | None = None,
    answers_file: str | Path | None = None,
    write: bool = False,
    force: bool = False,
) -> Adoption:
    """Adopt *repo_root* under *template*; report drift, optionally link it.

    Returns the ``Adoption`` in ``complete`` (``result`` populated; answers
    written iff *write*) or raises ``CopyRoomError`` on failure. The repo's
    files are never modified except, under *write*, the added
    ``.copier-answers.yml``.
    """
    root = resolve_project_root(repo_root)
    adoption = Adoption(repo_root=root, template_source=template, template_ref=ref)

    # Refuse an already-managed repo unless forced — adopting twice would
    # silently retarget the project's template.
    if (root / _ANSWERS_FILENAME).is_file() and not force:
        adoption.status = _adoption_sm.transition(
            AdoptionStatus.initiated, AdoptionStatus.failed,
        )
        raise CopyRoomError(
            f"{root} already has {_ANSWERS_FILENAME} (already CopyRoom-managed). "
            "Use --force to re-adopt.",
            state="initiated",
        )

    # --- 1. resolve the template to a local repo (cloning remote sources) ---
    try:
        repo_dir = _ensure_local_repo(template, _template_cache_dir(template))
    except CopyRoomError:
        adoption.status = _adoption_sm.transition(
            AdoptionStatus.initiated, AdoptionStatus.failed,
        )
        raise
    adoption.repo_dir = repo_dir
    adoption.status = _adoption_sm.transition(
        AdoptionStatus.initiated, AdoptionStatus.template_resolved,
    )

    answers_path = Path(answers_file).resolve() if answers_file is not None else None
    if answers_path is not None and not answers_path.is_file():
        adoption.status = _adoption_sm.transition(
            AdoptionStatus.template_resolved, AdoptionStatus.failed,
        )
        raise CopyRoomError(
            f"Answers file not found: {answers_path}", state="template_resolved",
        )

    # --- 2. render the template with the inferred answers into a scratch dir ---
    scratch = Path(tempfile.mkdtemp(prefix="copyroom_adopt_"))
    try:
        rendered = scratch / "rendered"
        try:
            result = copier_copy(
                source=str(repo_dir),
                destination=rendered,
                answers_file=answers_path,
                vcs_ref=ref,
            )
        except Exception as exc:
            adoption.status = _adoption_sm.transition(
                AdoptionStatus.template_resolved, AdoptionStatus.failed,
            )
            raise CopyRoomError(
                f"Copier failed to render the template for adoption: {exc}",
                state="template_resolved",
            ) from exc
        if result.returncode != 0:
            adoption.status = _adoption_sm.transition(
                AdoptionStatus.template_resolved, AdoptionStatus.failed,
            )
            msg = (result.stderr or result.stdout or "").strip() or "no output"
            raise CopyRoomError(
                f"Copier failed to render the template for adoption:\n{msg}",
                state="template_resolved",
            )
        adoption.status = _adoption_sm.transition(
            AdoptionStatus.template_resolved, AdoptionStatus.rendered,
        )

        # --- 3. drift: how the repo differs from the rendered template ---
        added, modified, removed = tree_diff(root, rendered, ignore_dirs=EXCLUDE_DIRS)
        patch_path = _write_drift_patch(root, rendered, removed)
        adoption.result = DriftResult(
            added=added, modified=modified, removed=removed,
            patch_path=str(patch_path) if patch_path else None,
        )
        adoption.status = _adoption_sm.transition(
            AdoptionStatus.rendered, AdoptionStatus.drifted,
        )

        # --- 4. (optional) record the link — the only write into the repo ---
        if write:
            rendered_answers = rendered / _ANSWERS_FILENAME
            if not rendered_answers.is_file():
                adoption.status = _adoption_sm.transition(
                    AdoptionStatus.drifted, AdoptionStatus.failed,
                )
                raise CopyRoomError(
                    "Rendered template produced no .copier-answers.yml; the "
                    "template must include a .copier-answers.yml.jinja.",
                    state="drifted",
                )
            shutil.copyfile(rendered_answers, root / _ANSWERS_FILENAME)
            adoption.wrote_answers = True

        adoption.status = _adoption_sm.transition(
            AdoptionStatus.drifted, AdoptionStatus.complete,
        )
        return adoption
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _write_drift_patch(
    repo_root: Path, rendered: Path, removed: set[str],
) -> Path | None:
    """Write a reviewable ``repo → template`` patch under ``.copyroom/adopt/``.

    Builds the patch by snapshotting a sandbox copy of the repo, overlaying the
    rendered template files (and deleting the repo-only files in *removed*), then
    diffing. The real repo is never touched. Returns ``None`` if git is
    unavailable.
    """
    sandbox = Path(tempfile.mkdtemp(prefix="copyroom_adopt_patch_"))
    try:
        shutil.copytree(repo_root, sandbox, ignore=_SANDBOX_IGNORE, dirs_exist_ok=True)
        # The repo's own answers file (if --force re-adopt) isn't part of the
        # comparison; drop it so it never appears in the patch.
        (sandbox / _ANSWERS_FILENAME).unlink(missing_ok=True)

        if not gitutil.snapshot(sandbox, "copyroom: repo baseline"):
            return None

        # Overlay every rendered file (except the machine-specific answers file)
        # onto the sandbox, then remove the repo-only files.
        for rel in collect_files(rendered):
            dst = sandbox / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(rendered / rel, dst)
        for rel in removed:
            (sandbox / rel).unlink(missing_ok=True)

        patch = gitutil.add_all_and_diff_cached(sandbox)
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)

    adopt_dir = repo_root / ".copyroom" / "adopt"
    adopt_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    patch_path = adopt_dir / f"drift-{stamp}.patch"
    patch_path.write_text(patch)
    return patch_path
