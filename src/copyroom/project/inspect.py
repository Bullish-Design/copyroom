"""Read-only project reports — ``copyroom inspect`` and ``copyroom status``.

Both are **pure reads**: they look at ``.copier-answers.yml`` and
``copyroom.project.yml`` (through the validated config model) and report what
they find. Unlike the create/update workflows there is no lifecycle to guard —
nothing mutates and nothing can be left half-done — so these intentionally
return a plain result dataclass instead of driving a state machine.

* ``inspect`` — the full, ``--json``-friendly project report.
* ``status``  — a terse "where am I": mode, template + recorded ref, worktree
  cleanliness, and whether an update is available (via the shared latest-ref
  resolver).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .._compat import gitutil
from .._compat.errors import CopyRoomError
from .._compat.refs import same_version
from ..session.detector import detect_mode
from ..template.workspace import read_answers, resolve_project_root
from .config import load_project_config

__all__ = ["CopyRoomError", "InspectReport", "StatusReport", "inspect_project", "project_status"]


# ---------------------------------------------------------------------------
# Result dataclasses (pure reads — no state machine; see module docstring)
# ---------------------------------------------------------------------------


@dataclass
class InspectReport:
    """Full project report produced by ``copyroom inspect``."""

    project_root: Path
    template_id: str | None
    template_source: str | None
    commit: str | None
    answers_file: str
    has_project_config: bool
    hooks: dict[str, list[str]]

    def to_dict(self) -> dict:
        """Stable ``--json`` shape (tagged with the producing command)."""
        return {
            "command": "inspect",
            "project_root": str(self.project_root),
            "template_id": self.template_id,
            "template_source": self.template_source,
            "commit": self.commit,
            "answers_file": self.answers_file,
            "has_project_config": self.has_project_config,
            "hooks": self.hooks,
        }


@dataclass
class StatusReport:
    """Terse project status produced by ``copyroom status``."""

    project_root: Path
    mode: str | None
    template_id: str | None
    template_source: str | None
    current_ref: str | None
    latest_ref: str | None
    update_available: bool
    worktree_clean: bool | None  # None → not a git repository

    def to_dict(self) -> dict:
        """Stable ``--json`` shape (tagged with the producing command)."""
        return {
            "command": "status",
            "project_root": str(self.project_root),
            "mode": self.mode,
            "template_id": self.template_id,
            "template_source": self.template_source,
            "current_ref": self.current_ref,
            "latest_ref": self.latest_ref,
            "update_available": self.update_available,
            "worktree_clean": self.worktree_clean,
        }


# ---------------------------------------------------------------------------
# Shared reads
# ---------------------------------------------------------------------------


def _template_id(answers: dict, cfg_template_id: str | None) -> str | None:
    """Prefer copyroom.project.yml's template_id, else the answers ``_template``."""
    if cfg_template_id:
        return cfg_template_id
    raw = answers.get("_template")
    return str(raw) if raw is not None else None




# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def inspect_project(project_root: str | Path | None = None) -> InspectReport:
    """Build the full :class:`InspectReport` for the project at *project_root*.

    Reads ``.copier-answers.yml`` (confirming this is a Copier project) and the
    validated ``copyroom.project.yml`` model. Raises ``CopyRoomError`` when no
    answers file is present.
    """
    root = resolve_project_root(project_root)
    answers = read_answers(root)

    project_yml = root / "copyroom.project.yml"
    cfg = load_project_config(project_yml)

    commit = answers.get("_commit")
    src = answers.get("_src_path")

    return InspectReport(
        project_root=root,
        template_id=_template_id(answers, cfg.project.template_id),
        template_source=str(src) if src is not None else None,
        commit=str(commit) if commit is not None else None,
        answers_file=str(root / ".copier-answers.yml"),
        has_project_config=project_yml.is_file(),
        hooks=dict(cfg.commands),
    )


def project_status(project_root: str | Path | None = None) -> StatusReport:
    """Build the terse :class:`StatusReport` for the project at *project_root*.

    Resolves the template's latest semver tag (fetch-class for remote sources)
    to compute ``update_available``. Raises ``CopyRoomError`` when no answers
    file is present.
    """
    root = resolve_project_root(project_root)
    answers = read_answers(root)

    project_yml = root / "copyroom.project.yml"
    cfg = load_project_config(project_yml)

    commit = answers.get("_commit")
    current_ref = str(commit) if commit is not None else None
    src = answers.get("_src_path")
    template_source = str(src) if src is not None else None

    latest_ref = gitutil.resolve_latest_ref(template_source) if template_source else None
    update_available = latest_ref is not None and not same_version(current_ref, latest_ref)

    mode = detect_mode(root)

    return StatusReport(
        project_root=root,
        mode=mode.value if mode is not None else None,
        template_id=_template_id(answers, cfg.project.template_id),
        template_source=template_source,
        current_ref=current_ref,
        latest_ref=latest_ref,
        update_available=update_available,
        worktree_clean=gitutil.worktree_clean(root),
    )
