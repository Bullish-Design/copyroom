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

from dataclasses import dataclass, field
from pathlib import Path

from .._compat import gitutil
from .._compat.errors import CopyRoomError
from .._compat.refs import same_version
from ..session.detector import detect_mode
from ..template.workspace import read_answers, resolve_project_root
from .config import load_project_config
from .layers import BASE_LAYER, Layer, discover_layers

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
    agent: dict  # the validated ``agent:`` section (skills_dir, instructions, claude_symlink, overlay)
    # Every template layer managing this repo, base first. The scalar
    # ``template_*``/``commit``/``answers_file`` fields above describe the
    # *primary* layer and are kept for compatibility with single-layer readers.
    layers: list[Layer] = field(default_factory=list)

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
            "agent": self.agent,
            "layers": [layer.to_dict() for layer in self.layers],
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
    agent: dict  # the validated ``agent:`` section (advisory; round-trips)
    #: ``[{name, ref, latest_ref, update_available, template_source}, …]``, base
    #: first. The scalar fields above describe the *primary* layer.
    layers: list[dict] = field(default_factory=list)

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
            "agent": self.agent,
            "layers": self.layers,
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


def _agent_dict(cfg) -> dict:
    """The validated ``agent:`` section as a stable dict (round-trips through JSON)."""
    agent = cfg.agent
    return {
        "skills_dir": str(agent.skills_dir),
        "instructions": str(agent.instructions),
        "claude_symlink": agent.claude_symlink,
        "overlay": list(agent.overlay),
    }




# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def _primary_layer(root: Path) -> Layer:
    """The layer the scalar report fields describe: ``base``, else the first.

    A repo can be managed by an overlay layer alone (the personal layer applied
    to a repo with no genome), and ``inspect``/``status`` must still work there.
    """
    layers = discover_layers(root)
    if not layers:
        raise CopyRoomError(
            "No .copier-answers.yml here — template commands must run from a "
            "project generated by Copier/CopyRoom.",
            state="not_started",
        )
    for layer in layers:
        if layer.name == BASE_LAYER:
            return layer
    return layers[0]


def inspect_project(project_root: str | Path | None = None) -> InspectReport:
    """Build the full :class:`InspectReport` for the project at *project_root*.

    Reads the primary layer's answers file (confirming this is a Copier project),
    the validated ``copyroom.project.yml`` model, and every recorded layer.
    Raises ``CopyRoomError`` when no answers file is present at all.
    """
    root = resolve_project_root(project_root)
    primary = _primary_layer(root)
    answers = read_answers(root, primary.answers_file)

    project_yml = root / "copyroom.project.yml"
    cfg = load_project_config(project_yml)

    commit = answers.get("_commit")
    src = answers.get("_src_path")

    return InspectReport(
        project_root=root,
        template_id=_template_id(answers, cfg.project.template_id),
        template_source=str(src) if src is not None else None,
        commit=str(commit) if commit is not None else None,
        answers_file=str(root / primary.answers_file),
        has_project_config=project_yml.is_file(),
        hooks=dict(cfg.commands),
        agent=_agent_dict(cfg),
        layers=discover_layers(root),
    )


def project_status(project_root: str | Path | None = None) -> StatusReport:
    """Build the terse :class:`StatusReport` for the project at *project_root*.

    Resolves **each layer's** latest semver tag (fetch-class for remote sources)
    so ``update_available`` answers "is anything behind", not just the primary
    layer. Raises ``CopyRoomError`` when no answers file is present.
    """
    root = resolve_project_root(project_root)
    primary = _primary_layer(root)
    answers = read_answers(root, primary.answers_file)

    project_yml = root / "copyroom.project.yml"
    cfg = load_project_config(project_yml)

    layer_rows: list[dict] = []
    for layer in discover_layers(root):
        latest = gitutil.resolve_latest_ref(layer.template_source) if layer.template_source else None
        layer_rows.append(
            {
                **layer.to_dict(),
                "latest_ref": latest,
                "update_available": latest is not None and not same_version(layer.ref, latest),
            }
        )

    primary_row = next((row for row in layer_rows if row["name"] == primary.name), None)
    mode = detect_mode(root)

    return StatusReport(
        project_root=root,
        mode=mode.value if mode is not None else None,
        template_id=_template_id(answers, cfg.project.template_id),
        template_source=primary.template_source,
        current_ref=primary.ref,
        latest_ref=primary_row["latest_ref"] if primary_row else None,
        update_available=any(row["update_available"] for row in layer_rows),
        worktree_clean=gitutil.worktree_clean(root),
        agent=_agent_dict(cfg),
        layers=layer_rows,
    )
