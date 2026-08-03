"""End-to-end agent-files tests: the convention survives new/update.

These drive the real workflow entry points (``create_project`` /
``update_project``) against the fixture template, which now ships the agent
files: ``.agents/skills/copyroom/SKILL.md`` (with literal ``{{ }}`` content),
``AGENTS.md``, and a ``CLAUDE.md`` symlink to it, plus the template-side
declarations (``_preserve_symlinks`` / ``_copy_without_render``).

Assertions map to the spike conclusions recorded in
``.scratch/projects/07-agent-files/SPIKE.md``:

* with ``_preserve_symlinks: true``, Copier preserves the symlink through
  ``new`` and ``update`` (git mode ``120000``);
* ``_copy_without_render`` keeps skill content byte-for-byte;
* ``agent.overlay`` maps to ``--exclude`` so a permanently-diverging skill
  survives the next update untouched.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from copyroom.project.create import create_project
from copyroom.project.inspect import inspect_project, project_status
from copyroom.project.model import UpdateStatus
from copyroom.project.update import update_project

from .conftest import _git

AGENTS_SKILL = ".agents/skills/copyroom/SKILL.md"


def _generate(template_repo: Path, dest: Path) -> Path:
    creation = create_project(source=str(template_repo), target_dir=str(dest))
    assert creation.status.value == "complete", creation.result_suggestions
    _git("init", cwd=dest)
    _git("add", "-A", cwd=dest)
    _git("commit", "-qm", "generated", cwd=dest)
    return dest


def _tag(template_repo: Path, message: str) -> None:
    _git("add", "-A", cwd=template_repo)
    _git("commit", "-qm", message, cwd=template_repo)
    _git("tag", "v2.0.0", cwd=template_repo)


# ---------------------------------------------------------------------------
# new — the fixture ships agent files; they survive generation
# ---------------------------------------------------------------------------


def test_new_materializes_agent_files(template_repo: Path, tmp_path: Path) -> None:
    proj = _generate(template_repo, tmp_path / "proj")

    # Skill present and copied verbatim — literal {{ }} survives (no rendering).
    skill = proj / AGENTS_SKILL
    assert skill.is_file()
    assert "{{ project_name | lower }}" in skill.read_text()

    # AGENTS.md present and CLAUDE.md is a symlink to it.
    assert (proj / "AGENTS.md").is_file()
    assert (proj / "CLAUDE.md").is_symlink()
    assert (proj / "CLAUDE.md").resolve() == (proj / "AGENTS.md").resolve()

    # The symlink is committed as a git symlink (mode 120000).
    mode = subprocess.run(
        ["git", "ls-files", "-s", "CLAUDE.md"],
        cwd=proj,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()[0]
    assert mode == "120000"

    # The symlink reads through to AGENTS.md content.
    assert (proj / "CLAUDE.md").read_text() == (proj / "AGENTS.md").read_text()


# ---------------------------------------------------------------------------
# update — a template ref that adds a skill converges cleanly
# ---------------------------------------------------------------------------


def test_update_converges_new_skill(template_repo: Path, tmp_path: Path) -> None:
    proj = _generate(template_repo, tmp_path / "proj")

    # v2: template adds a second skill.
    new_skill = template_repo / ".agents" / "skills" / "newskill" / "SKILL.md"
    new_skill.parent.mkdir(parents=True)
    new_skill.write_text("# new skill\n")
    _tag(template_repo, "v2")

    update = update_project(project_root=proj, target_ref="v2.0.0")
    assert update.status == UpdateStatus.complete, update.status

    # New skill converged; the original skill and the symlink are intact.
    assert (proj / ".agents" / "skills" / "newskill" / "SKILL.md").is_file()
    assert (proj / AGENTS_SKILL).read_text().startswith("---")
    assert (proj / "CLAUDE.md").is_symlink()
    assert (proj / "CLAUDE.md").resolve() == (proj / "AGENTS.md").resolve()


# ---------------------------------------------------------------------------
# overlay — agent.overlay maps to --exclude; the next update stops managing it
# ---------------------------------------------------------------------------


def test_overlay_skill_survives_update(template_repo: Path, tmp_path: Path) -> None:
    proj = _generate(template_repo, tmp_path / "proj")

    # The project permanently diverges on the canonical skill: declare it.
    (proj / "copyroom.project.yml").write_text("agent:\n  overlay:\n    - copyroom\n")
    _git("add", "-A", cwd=proj)
    _git("commit", "-qm", "declare overlay", cwd=proj)

    # v2: the template modifies the overlaid skill AND adds a new one.
    (template_repo / ".agents" / "skills" / "copyroom" / "SKILL.md").write_text("# copyroom v2 — changed by template\n")
    new_skill = template_repo / ".agents" / "skills" / "newskill" / "SKILL.md"
    new_skill.parent.mkdir(parents=True)
    new_skill.write_text("# new skill\n")
    _tag(template_repo, "v2")

    update = update_project(project_root=proj, target_ref="v2.0.0")
    assert update.status == UpdateStatus.complete, update.status

    # The overlaid skill keeps the project's local version (template change
    # NOT applied) while the new skill converges normally.
    assert (proj / AGENTS_SKILL).read_text().startswith("---")
    assert (proj / ".agents" / "skills" / "newskill" / "SKILL.md").is_file()
    assert "changed by template" not in (proj / AGENTS_SKILL).read_text()
    assert (proj / "CLAUDE.md").is_symlink()


# ---------------------------------------------------------------------------
# inspect / status — the agent: section round-trips
# ---------------------------------------------------------------------------


def test_inspect_status_roundtrip_agent_section(template_repo: Path, tmp_path: Path) -> None:
    proj = _generate(template_repo, tmp_path / "proj")
    (proj / "copyroom.project.yml").write_text(
        "agent:\n  skills_dir: .agents/skills\n  overlay:\n    - copyroom-adopt\n"
    )
    _git("add", "-A", cwd=proj)
    _git("commit", "-qm", "agent config", cwd=proj)

    inspect = inspect_project(project_root=proj)
    assert inspect.agent["skills_dir"] == ".agents/skills"
    assert inspect.agent["instructions"] == "AGENTS.md"
    assert inspect.agent["claude_symlink"] is True
    assert inspect.agent["overlay"] == ["copyroom-adopt"]

    status = project_status(project_root=proj)
    assert status.agent["overlay"] == ["copyroom-adopt"]

    # Defaults when no project config is present.
    plain = _generate(template_repo, tmp_path / "plain")
    assert inspect_project(project_root=plain).agent == {
        "skills_dir": ".agents/skills",
        "instructions": "AGENTS.md",
        "claude_symlink": True,
        "overlay": [],
    }
