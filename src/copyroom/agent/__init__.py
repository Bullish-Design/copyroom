"""The agent-files convention: canonical skills + AGENTS.md + CLAUDE.md symlink.

CopyRoom is the reference implementation of the ``*man`` family's agent-files
convention:

* skills live at ``.agents/skills/<name>/SKILL.md``;
* repo instructions live in a root ``AGENTS.md`` (canonical);
* ``CLAUDE.md`` is a symlink to ``AGENTS.md`` — one source, every tool reads it.

The canonical skill set ships as **package assets** under
``agent/assets/skills/`` (CopyRoom owns them — one source of truth).
``copyroom agent-files export`` materializes them into a target's
``.agents/skills/``, writes a blueprint ``AGENTS.md`` only when absent, and
ensures the ``CLAUDE.md`` symlink. ``copyroom agent-files check`` reports
conformance; ``copyroom doctor`` reuses the same check at warn-level.
"""

from .files import (
    AGENTS_BLUEPRINT,
    AgentFilesCheck,
    AgentFilesExport,
    SkillStatus,
    canonical_skills,
    check_agent_files,
    export_agent_files,
    resolve_target,
    skills_source_root,
)

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
