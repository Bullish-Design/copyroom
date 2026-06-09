"""Preview the update a project would receive from the edited template.

``copyroom template-preview`` answers: *"if I updated my project to the template
I just edited, what would change?"* It works on a disposable copy of the
project's **current working tree** (your local edits included), so the real
project is never touched.

Algorithm (a cousin of ``workshop/simulate.py``, but on a copy of the real
project instead of a rendered scenario):

    1. resolve the scratch worktree/branch; commit the agent's pending edits
    2. copy the project working tree into a temp sandbox; snapshot it (S0)
    3. ``copier update --vcs-ref <edit-branch>`` in the sandbox
    4. diff S0 -> post-update; capture conflicts/rejects; write a .patch
"""

from __future__ import annotations

import shutil
import tempfile
from datetime import datetime
from pathlib import Path

import yaml

from .._compat import gitutil
from .._compat.copier import copier_update
from .._compat.errors import CopyRoomError
from .._compat.state_machine import StateMachine
from .model import (
    VALID_PREVIEW_TRANSITIONS,
    PreviewResult,
    PreviewStatus,
    TemplatePreview,
)
from .workspace import checkout_template, resolve_project_root

__all__ = ["CopyRoomError", "run_preview"]

_preview_sm = StateMachine(VALID_PREVIEW_TRANSITIONS, entity_name="TemplatePreview")

# Project paths that must not leak into the sandbox copy.
_SANDBOX_IGNORE = shutil.ignore_patterns(
    ".git", ".copyroom", "generated", ".copyroom_sim", "__pycache__", "*.pyc",
)


def run_preview(
    project_root: str | Path | None = None,
    from_ref: str | None = None,
) -> TemplatePreview:
    """Simulate updating this project to the edited template; return the result.

    Returns a ``TemplatePreview`` in ``complete`` (``result`` populated, patch
    written under ``.copyroom/preview/``) or ``failed``. The real project tree
    is never modified.
    """
    root = resolve_project_root(project_root)

    checkout = checkout_template(root, from_ref)
    assert (
        checkout.worktree_dir is not None
        and checkout.branch is not None
        and checkout.repo_dir is not None
    )
    worktree = checkout.worktree_dir
    branch = checkout.branch
    repo = checkout.repo_dir

    # Commit the agent's pending edits onto the edit branch so the update sees them.
    gitutil.commit_all(worktree, "copyroom: template edits (preview)")

    preview = TemplatePreview(project_root=root, worktree_dir=worktree, branch=branch)

    # --- 1. sandbox = copy of the project's current working tree ---
    sandbox = Path(tempfile.mkdtemp(prefix="copyroom_preview_"))
    try:
        shutil.copytree(root, sandbox, ignore=_SANDBOX_IGNORE, dirs_exist_ok=True)

        # Point the sandbox's answers at our edit repo (before snapshotting, so
        # this rewrite never appears in the diff), keeping _commit as the 3-way
        # merge base. The edit branch lives in this repo.
        _retarget_answers(sandbox / ".copier-answers.yml", repo)

        if not gitutil.snapshot(sandbox, "copyroom: project baseline"):
            preview.status = _preview_sm.transition(
                PreviewStatus.initiated, PreviewStatus.failed,
            )
            raise CopyRoomError(
                "git is required to preview a template update but is unavailable.",
                state="initiated",
            )
        preview.status = _preview_sm.transition(
            PreviewStatus.initiated, PreviewStatus.sandbox_prepared,
        )

        # --- 2. apply the update in the sandbox ---
        try:
            updated = copier_update(destination=sandbox, vcs_ref=branch)
        except Exception as exc:
            preview.status = _preview_sm.transition(
                PreviewStatus.sandbox_prepared, PreviewStatus.failed,
            )
            raise CopyRoomError(
                f"Copier update failed during preview: {exc}",
                state="sandbox_prepared",
            ) from exc

        # --- 3. diff S0 -> post-update ---
        patch = gitutil.add_all_and_diff_cached(sandbox)
        added, modified, removed = _name_status(sandbox)
        rejects = {
            str(p.relative_to(sandbox)) for p in sandbox.rglob("*.rej")
        }
        # Copier's default conflict mode writes inline git markers into the file
        # (not .rej), so scan the changed files for them.
        conflicts = _scan_conflict_markers(sandbox, added | modified)

        # A non-zero exit with nothing applied is a real error, not a conflict.
        if updated.returncode != 0 and not patch.strip() and not rejects:
            preview.status = _preview_sm.transition(
                PreviewStatus.sandbox_prepared, PreviewStatus.failed,
            )
            msg = (updated.stderr or "").strip() or "Copier update produced no output."
            raise CopyRoomError(
                f"Copier update failed during preview:\n{msg}",
                state="sandbox_prepared",
            )

        preview.status = _preview_sm.transition(
            PreviewStatus.sandbox_prepared, PreviewStatus.update_simulated,
        )

        # --- 4. persist the patch + finalize ---
        patch_path = _write_patch(root, patch)
        preview.status = _preview_sm.transition(
            PreviewStatus.update_simulated, PreviewStatus.diffed,
        )

        preview.result = PreviewResult(
            added=added,
            modified=modified,
            removed=removed,
            conflicts=conflicts,
            rejects=rejects,
            patch_path=str(patch_path),
        )
        preview.status = _preview_sm.transition(
            PreviewStatus.diffed, PreviewStatus.complete,
        )
        return preview
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _retarget_answers(answers_path: Path, worktree: Path) -> None:
    """Rewrite ``_src_path`` in the sandbox answers to point at the edit worktree."""
    if not answers_path.is_file():
        return
    try:
        data = yaml.safe_load(answers_path.read_text())
    except (yaml.YAMLError, OSError):
        return
    if not isinstance(data, dict):
        return
    data["_src_path"] = str(worktree)
    answers_path.write_text(yaml.safe_dump(data, sort_keys=False))


def _name_status(sandbox: Path) -> tuple[set[str], set[str], set[str]]:
    """Return (added, modified, removed) from the staged diff in *sandbox*."""
    added: set[str] = set()
    modified: set[str] = set()
    removed: set[str] = set()
    result = gitutil.run_git("diff", "--cached", "--name-status", cwd=sandbox)
    if result is None or result.returncode != 0:
        return added, modified, removed
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        code, path = parts[0], parts[-1]
        if code.startswith("A"):
            added.add(path)
        elif code.startswith("D"):
            removed.add(path)
        elif code.startswith("R"):
            removed.add(parts[1])
            added.add(parts[-1])
        else:  # M, C, T, ...
            modified.add(path)
    return added, modified, removed


_CONFLICT_MARKERS = ("<<<<<<<", ">>>>>>>")


def _scan_conflict_markers(sandbox: Path, candidates: set[str]) -> set[str]:
    """Return changed files that contain git-style conflict markers.

    Copier's default (inline) conflict mode leaves ``<<<<<<<`` / ``>>>>>>>``
    markers in files rather than writing ``.rej`` siblings, so a clash with the
    user's local edits shows up as marker text inside an otherwise-modified file.
    """
    found: set[str] = set()
    for rel in candidates:
        try:
            text = (sandbox / rel).read_text(errors="ignore")
        except OSError:
            continue
        if any(marker in text for marker in _CONFLICT_MARKERS):
            found.add(rel)
    return found


def _write_patch(project_root: Path, patch: str) -> Path:
    """Write *patch* under ``<project>/.copyroom/preview/`` and return its path."""
    preview_dir = project_root / ".copyroom" / "preview"
    preview_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    patch_path = preview_dir / f"preview-{stamp}.patch"
    patch_path.write_text(patch)
    return patch_path
