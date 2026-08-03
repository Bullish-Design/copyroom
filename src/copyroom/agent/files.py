"""Agent-files export/check — materialize and verify the convention files.

The canonical skill set ships as package data under ``agent/assets/skills/``.
:func:`export_agent_files` materializes it into a target's ``.agents/skills/``
(idempotent), writes a blueprint ``AGENTS.md`` **only if absent** (never
clobber), and ensures ``CLAUDE.md`` is a symlink to ``AGENTS.md`` (recreate if
missing; never replace a regular file). :func:`check_agent_files` reports
conformance: presence of ``AGENTS.md``, a correct ``CLAUDE.md`` symlink, the
canonical skills at the current CopyRoom version, and any extra files
(template-shipped or local overlay — reported as present, not judged).

Both honor a ``copyroom.project.yml`` ``agent:`` section when present
(``skills_dir``, ``instructions``, ``claude_symlink``, ``overlay``) so a
project's declared divergence is respected: skills listed in ``agent.overlay``
are repo-owned and export/check leave them alone.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from importlib.resources import files as _pkg_files
from pathlib import Path

from .._compat.errors import CopyRoomError
from ..project.config import load_project_config

__all__ = [
    "AGENTS_BLUEPRINT",
    "AgentFilesCheck",
    "AgentFilesExport",
    "SkillStatus",
    "canonical_skills",
    "check_agent_files",
    "export_agent_files",
    "resolve_target",
    "skills_source_root",
]

# Defaults mirror the family convention and the project-config defaults.
DEFAULT_SKILLS_DIR = ".agents/skills"
DEFAULT_INSTRUCTIONS = "AGENTS.md"
DEFAULT_CLAUDE_SYMLINK = True

#: The blueprint ``AGENTS.md`` written by export — only when the target has none.
AGENTS_BLUEPRINT = """\
# AGENTS.md — project instructions

> Seeded by `copyroom agent-files export` (CopyRoom {version}). This is the
> canonical instructions file for this repo: edit it freely — every agent tool
> reads it via the `CLAUDE.md` symlink.

What this project is, how to build and test it, and where things live go here.
Keep it concise and factual; deeper detail belongs in `docs/`.

## Agent-files convention

- **Skills** live at `.agents/skills/<name>/SKILL.md` — imperative + short, and
  they link to the docs rather than repeat them.
- **`CLAUDE.md`** is a symlink to this file — one source, every tool reads it.
- **Canonical skills** (the CopyRoom set) are re-materialized by
  `copyroom agent-files export`; anything else under `.agents/skills/` is a
  template-shipped skill or a local overlay. Permanently diverging on a skill?
  Declare it in `copyroom.project.yml` `agent.overlay` so updates leave it alone.
"""


# ---------------------------------------------------------------------------
# Asset resolution
# ---------------------------------------------------------------------------


def skills_source_root() -> Path:
    """Path to the shipped canonical skills (editable install or wheel)."""
    return Path(_pkg_files("copyroom.agent")) / "assets" / "skills"


def canonical_skills() -> list[str]:
    """Canonical skill directory names (each ships a ``SKILL.md``)."""
    root = skills_source_root()
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if (p / "SKILL.md").is_file())


def _skill_file(name: str) -> Path:
    return skills_source_root() / name / "SKILL.md"


# ---------------------------------------------------------------------------
# Target resolution
# ---------------------------------------------------------------------------


def resolve_target(target: str | Path | None = None) -> Path:
    """Resolve where export/check operate: ``--target``, else repo root.

    Default resolution order (first hit wins):

    1. ``--target DIR`` when given;
    2. the nearest ancestor of the cwd that is a git repo root (``.git``);
    3. ``$DEVENV_ROOT`` when set;
    4. the cwd itself.

    This makes the natural call ``copyroom agent-files export`` work inside a
    project, a template repo (including a `template/` subdir), or an unmanaged
    dir — the canonical seeding call for a template repo.
    """
    if target is not None:
        return Path(target).expanduser().resolve()

    cwd = Path.cwd().resolve()
    for parent in (cwd, *cwd.parents):
        if (parent / ".git").exists():
            return parent

    devenv_root = os.environ.get("DEVENV_ROOT")
    if devenv_root:
        return Path(devenv_root).expanduser().resolve()

    return cwd


# ---------------------------------------------------------------------------
# Per-target agent config (advisory; defaults when no project config present)
# ---------------------------------------------------------------------------


def _agent_config(target: Path) -> tuple[Path, Path, bool, list[str]]:
    """Read the ``agent:`` section of ``copyroom.project.yml`` at *target*.

    Returns ``(skills_dir, instructions, claude_symlink, overlay)`` with the
    documented defaults when the file is absent (or its ``agent:`` section
    unset). A malformed config is *not* fatal here — export/check degrade to
    defaults rather than refuse to run (config is advisory).
    """
    skills_dir = Path(DEFAULT_SKILLS_DIR)
    instructions = Path(DEFAULT_INSTRUCTIONS)
    claude_symlink = DEFAULT_CLAUDE_SYMLINK
    overlay: list[str] = []
    try:
        cfg = load_project_config(target / "copyroom.project.yml")
        agent = cfg.agent
        skills_dir = agent.skills_dir
        instructions = agent.instructions
        claude_symlink = agent.claude_symlink
        overlay = list(agent.overlay)
    except (CopyRoomError, OSError):
        # Config is advisory for export/check: a schema-divergent file degrades
        # to the documented defaults rather than blocking materialization or
        # the doctor check.
        pass
    return (
        skills_dir,
        instructions,
        claude_symlink,
        overlay,
    )


def _ensure_claude_symlink(instructions: Path) -> str:
    """Ensure ``CLAUDE.md`` (next to *instructions*) is a symlink to it.

    Returns one of: ``"ok"`` (already a correct symlink), ``"created"`` (was
    missing/broken, recreated), or ``"refused"`` (a regular file exists — a
    possible deliberate divergence; never replace it).
    """
    claude = instructions.with_name("CLAUDE.md")
    if claude.is_symlink():
        if claude.resolve() == instructions.resolve():
            return "ok"
        claude.unlink()  # broken or wrong target — recreate below
    elif claude.exists():
        return "refused"
    claude.symlink_to(instructions.name)
    return "created"


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


@dataclass
class AgentFilesExport:
    """Outcome of :func:`export_agent_files`."""

    target: Path
    skills_dir: Path
    materialized: list[str] = field(default_factory=list)
    skipped_overlay: list[str] = field(default_factory=list)
    instructions: Path | None = None
    instructions_written: bool = False
    claude_symlink: str = "refused"  # ok | created | refused

    def to_dict(self) -> dict:
        return {
            "command": "agent-files-export",
            "target": str(self.target),
            "skills_dir": str(self.skills_dir),
            "materialized": sorted(self.materialized),
            "skipped_overlay": sorted(self.skipped_overlay),
            "instructions": str(self.instructions) if self.instructions else None,
            "instructions_written": self.instructions_written,
            "claude_symlink": self.claude_symlink,
        }


def export_agent_files(target: str | Path | None = None) -> AgentFilesExport:
    """Idempotently materialize the convention files into *target*.

    * copies every canonical skill under ``<target>/<skills_dir>/`` (skipping
      any listed in ``agent.overlay``);
    * writes the blueprint ``AGENTS.md`` **only if absent** — never clobbers an
      existing file;
    * ensures ``CLAUDE.md`` is a symlink to ``AGENTS.md`` (a regular file is
      never replaced).

    Returns :class:`AgentFilesExport` describing what happened. Raises
    :class:`CopyRoomError` on hard failures (missing assets, unwritable
    target).
    """
    target_path = resolve_target(target)
    skills_dir, instructions_rel, claude_symlink, overlay = _agent_config(target_path)

    skills_dir_path = target_path / skills_dir
    instructions = target_path / instructions_rel
    result = AgentFilesExport(
        target=target_path,
        skills_dir=skills_dir_path,
        instructions=instructions,
    )

    src_root = skills_source_root()
    if not src_root.is_dir():
        raise CopyRoomError(f"Canonical skill assets not found: {src_root}")

    try:
        for name in canonical_skills():
            if name in overlay:
                result.skipped_overlay.append(name)
                continue
            dst = skills_dir_path / name
            dst.mkdir(parents=True, exist_ok=True)
            (dst / "SKILL.md").write_text((_skill_file(name)).read_text())
            result.materialized.append(name)

        if not instructions.is_file():
            blueprint = AGENTS_BLUEPRINT.format(version=_version())
            instructions.write_text(blueprint)
            result.instructions_written = True

        if claude_symlink:
            result.claude_symlink = _ensure_claude_symlink(instructions)
        else:
            result.claude_symlink = "refused"
    except OSError as exc:
        raise CopyRoomError(f"agent-files export failed: {exc}") from exc

    return result


def _version() -> str:
    from .. import __version__

    return __version__


# ---------------------------------------------------------------------------
# Check
# ---------------------------------------------------------------------------


@dataclass
class SkillStatus:
    """One canonical skill's conformance state."""

    name: str
    present: bool = False
    current: bool = False
    overlay: bool = False

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "present": self.present,
            "current": self.current,
            "overlay": self.overlay,
        }


@dataclass
class AgentFilesCheck:
    """Conformance report for :func:`check_agent_files`."""

    target: Path
    skills_dir: Path
    instructions: Path | None
    agents_md: bool
    claude_symlink: str  # ok | warn-regular-file | missing
    claude_target: str | None
    skills: list[SkillStatus] = field(default_factory=list)
    extras: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when every check passed (warnings included)."""
        return self.agents_md and self.claude_symlink == "ok" and all(s.current for s in self.skills if not s.overlay)

    def to_dict(self) -> dict:
        return {
            "command": "agent-files-check",
            "target": str(self.target),
            "skills_dir": str(self.skills_dir),
            "instructions": str(self.instructions) if self.instructions else None,
            "agents_md": self.agents_md,
            "claude_symlink": self.claude_symlink,
            "claude_target": self.claude_target,
            "skills": [s.to_dict() for s in self.skills],
            "extras": sorted(self.extras),
            "ok": self.ok,
        }


def check_agent_files(target: str | Path | None = None) -> AgentFilesCheck:
    """Report the target's conformance with the agent-files convention.

    Checks, in order: ``AGENTS.md`` present; ``CLAUDE.md`` is a symlink to it (a
    regular file is a WARN — it may be a genuine local divergence, flagged not
    fixed); every canonical skill present **and** matching the shipped asset at
    the current CopyRoom version (skills declared in ``agent.overlay`` are
    exempt — divergence is deliberate); and any extra files under
    ``.agents/skills/`` are listed as present (template-shipped or overlay —
    can't be distinguished statically).

    This is a **report**, not a gate: conformance findings are warnings. Callers
    (``doctor``) decide severity.
    """
    target_path = resolve_target(target)
    skills_dir, instructions_rel, _claude_symlink, overlay = _agent_config(target_path)

    skills_dir_path = target_path / skills_dir
    instructions = target_path / instructions_rel
    report = AgentFilesCheck(
        target=target_path,
        skills_dir=skills_dir_path,
        instructions=instructions,
        agents_md=instructions.is_file(),
        claude_symlink="missing",
        claude_target=None,
    )

    # CLAUDE.md symlink status (next to the instructions file).
    claude = instructions.with_name("CLAUDE.md")
    if claude.is_symlink():
        if claude.resolve() == instructions.resolve():
            report.claude_symlink = "ok"
            report.claude_target = claude.name
        else:
            report.claude_symlink = "warn-regular-file"
            report.claude_target = claude.name
    elif claude.exists():
        report.claude_symlink = "warn-regular-file"
        report.claude_target = claude.name

    # Canonical skills: present + current against the shipped assets.
    for name in canonical_skills():
        status = SkillStatus(name=name, overlay=name in overlay)
        local = skills_dir_path / name / "SKILL.md"
        status.present = local.is_file()
        if status.present:
            try:
                status.current = local.read_text() == (_skill_file(name)).read_text()
            except OSError:
                status.current = False
        report.skills.append(status)

    # Extra skills (template-shipped or overlay — report, don't judge).
    canonical = set(canonical_skills())
    if skills_dir_path.is_dir():
        for entry in sorted(skills_dir_path.iterdir()):
            if entry.is_dir() and entry.name not in canonical and (entry / "SKILL.md").is_file():
                report.extras.append(entry.name)

    return report


# ---------------------------------------------------------------------------
# Report formatting (plain text, matching the family report style)
# ---------------------------------------------------------------------------


def format_export_report(result: AgentFilesExport) -> str:
    """Render the export outcome as plain text."""
    lines = [f"Agent-files export → {result.target}"]
    lines.append(f"  Skills:     {', '.join(result.materialized) if result.materialized else '(none)'}")
    if result.skipped_overlay:
        lines.append(f"  Overlay:    {', '.join(result.skipped_overlay)} (declared in agent.overlay — untouched)")
    if result.instructions:
        state = "written (blueprint)" if result.instructions_written else "already present — untouched"
        lines.append(f"  {result.instructions.name}: {state}")
    if result.claude_symlink == "created":
        lines.append("  CLAUDE.md:  symlink ensured → AGENTS.md")
    elif result.claude_symlink == "ok":
        lines.append("  CLAUDE.md:  symlink ok → AGENTS.md")
    elif result.claude_symlink == "refused":
        lines.append("  CLAUDE.md:  regular file present — not replaced (may be a deliberate divergence)")
    return "\n".join(lines)


def format_check_report(report: AgentFilesCheck) -> str:
    """Render the conformance report as plain text (✓ / ⚠️ per line)."""
    labels = ["AGENTS.md", "CLAUDE.md"] + [s.name for s in report.skills]
    width = max(len(label) for label in labels) if labels else 9

    def pad(label: str) -> str:
        return label.ljust(width)

    lines = [f"Agent-files check → {report.target}"]
    lines.append(
        f"  {pad(report.instructions.name if report.instructions else 'AGENTS.md')}:"
        f" {'✓ present' if report.agents_md else '⚠️  MISSING'}"
    )
    if report.claude_symlink == "ok":
        lines.append(f"  {pad('CLAUDE.md')}: ✓ symlink → {report.claude_target}")
    elif report.claude_symlink == "warn-regular-file":
        lines.append(f"  {pad('CLAUDE.md')}: ⚠️  regular file (not a symlink) — flagged, not fixed")
    else:
        lines.append(f"  {pad('CLAUDE.md')}: ⚠️  MISSING symlink")
    for s in report.skills:
        if s.overlay:
            lines.append(f"  {pad(s.name)}: ⚠️  declared in agent.overlay — divergence expected")
        elif s.present and s.current:
            lines.append(f"  {pad(s.name)}: ✓ present, current")
        elif s.present:
            lines.append(f"  {pad(s.name)}: ⚠️  present but stale — run 'copyroom agent-files export'")
        else:
            lines.append(f"  {pad(s.name)}: ⚠️  MISSING — run 'copyroom agent-files export'")
    if report.extras:
        note = " (template-shipped or overlay — reported, not judged)"
        lines.append(f"  {'Extras':<{width}}: {', '.join(report.extras)}{note}")
    return "\n".join(lines)
