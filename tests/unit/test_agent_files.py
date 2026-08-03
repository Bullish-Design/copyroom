"""Unit tests for the agent-files convention module (copyroom/agent/files.py).

Covers target resolution, idempotent export (never clobbering AGENTS.md), the
CLAUDE.md symlink rules (recreate if missing; never replace a regular file), the
overlay carve-out, and the conformance check's warn paths.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from copyroom.agent.files import (
    canonical_skills,
    check_agent_files,
    export_agent_files,
    resolve_target,
)


@pytest.fixture
def exported(tmp_path: Path) -> Path:
    """A target dir that has gone through export once."""
    export_agent_files(tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# canonical set
# ---------------------------------------------------------------------------


def test_canonical_skills_are_the_three_expected() -> None:
    assert canonical_skills() == ["copyroom", "copyroom-adopt", "copyroom-template-edit"]
    for name in canonical_skills():
        assert (
            Path(__file__).parents[2] / "src" / "copyroom" / "agent" / "assets" / "skills" / name / "SKILL.md"
        ).is_file()


# ---------------------------------------------------------------------------
# target resolution
# ---------------------------------------------------------------------------


def test_resolve_target_explicit_wins(tmp_path: Path) -> None:
    assert resolve_target(tmp_path) == tmp_path.resolve()


def test_resolve_target_git_root(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    (repo / "sub").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    monkeypatch.chdir(repo / "sub")
    assert resolve_target(None) == repo.resolve()


def test_resolve_target_devenv_root(tmp_path: Path, monkeypatch) -> None:
    bare = tmp_path / "bare"
    bare.mkdir()
    monkeypatch.chdir(bare)
    monkeypatch.setenv("DEVENV_ROOT", str(tmp_path / "devenv-root"))
    assert resolve_target(None) == (tmp_path / "devenv-root").resolve()


def test_resolve_target_falls_back_to_cwd(tmp_path: Path, monkeypatch) -> None:
    bare = tmp_path / "bare"
    bare.mkdir()
    monkeypatch.chdir(bare)
    monkeypatch.delenv("DEVENV_ROOT", raising=False)
    assert resolve_target(None) == bare.resolve()


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------


def test_export_materializes_skills_and_symlink(exported: Path) -> None:
    for name in canonical_skills():
        assert (exported / ".agents" / "skills" / name / "SKILL.md").is_file()
    assert (exported / "AGENTS.md").is_file()
    assert (exported / "CLAUDE.md").is_symlink()
    assert (exported / "CLAUDE.md").resolve() == (exported / "AGENTS.md").resolve()


def test_export_is_idempotent_and_never_clobbers_agents_md(exported: Path) -> None:
    first = (exported / "AGENTS.md").read_text()
    result = export_agent_files(exported)
    assert result.instructions_written is False
    assert (exported / "AGENTS.md").read_text() == first  # untouched


def test_export_preserves_user_agents_md(tmp_path: Path) -> None:
    """An existing AGENTS.md (user-authored) is never overwritten."""
    custom = "# My own instructions\ncustom content\n"
    (tmp_path / "AGENTS.md").write_text(custom)
    result = export_agent_files(tmp_path)
    assert result.instructions_written is False
    assert (tmp_path / "AGENTS.md").read_text() == custom
    assert (tmp_path / "CLAUDE.md").is_symlink()  # still ensured


def test_export_recreates_broken_symlink(exported: Path) -> None:
    (exported / "CLAUDE.md").unlink()
    (exported / "CLAUDE.md").symlink_to("GONE.md")  # broken symlink
    result = export_agent_files(exported)
    assert result.claude_symlink == "created"
    assert (exported / "CLAUDE.md").resolve() == (exported / "AGENTS.md").resolve()


def test_export_never_replaces_regular_file_claude(tmp_path: Path) -> None:
    """A regular-file CLAUDE.md is a possible deliberate divergence — never
    replaced, only flagged (the check reports it; export leaves it)."""
    (tmp_path / "AGENTS.md").write_text("# agents\n")
    (tmp_path / "CLAUDE.md").write_text("# locally diverged\n")
    result = export_agent_files(tmp_path)
    assert result.claude_symlink == "refused"
    assert (tmp_path / "CLAUDE.md").is_file()
    assert not (tmp_path / "CLAUDE.md").is_symlink()
    assert (tmp_path / "CLAUDE.md").read_text() == "# locally diverged\n"


def test_export_skips_overlay_declared_skills(tmp_path: Path) -> None:
    (tmp_path / "copyroom.project.yml").write_text("agent:\n  overlay:\n    - copyroom\n")
    result = export_agent_files(tmp_path)
    assert result.skipped_overlay == ["copyroom"]
    assert not (tmp_path / ".agents" / "skills" / "copyroom").exists()
    assert (tmp_path / ".agents" / "skills" / "copyroom-adopt").is_dir()


def test_export_respects_custom_skills_dir(tmp_path: Path) -> None:
    (tmp_path / "copyroom.project.yml").write_text("agent:\n  skills_dir: skills\n")
    export_agent_files(tmp_path)
    assert (tmp_path / "skills" / "copyroom" / "SKILL.md").is_file()


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------


def test_check_passes_after_export(exported: Path) -> None:
    report = check_agent_files(exported)
    assert report.ok is True
    assert report.agents_md is True
    assert report.claude_symlink == "ok"
    assert all(s.present and s.current for s in report.skills)


def test_check_warns_on_missing_skill(exported: Path) -> None:
    (exported / ".agents" / "skills" / "copyroom" / "SKILL.md").unlink()
    report = check_agent_files(exported)
    assert report.ok is False
    stale = next(s for s in report.skills if s.name == "copyroom")
    assert stale.present is False


def test_check_warns_on_stale_skill(exported: Path) -> None:
    skill = exported / ".agents" / "skills" / "copyroom" / "SKILL.md"
    skill.write_text("# locally edited copyroom\n")
    report = check_agent_files(exported)
    assert report.ok is False
    stale = next(s for s in report.skills if s.name == "copyroom")
    assert stale.present is True and stale.current is False


def test_check_warns_on_regular_file_claude(tmp_path: Path) -> None:
    export_agent_files(tmp_path)
    (tmp_path / "CLAUDE.md").unlink()
    (tmp_path / "CLAUDE.md").write_text("# divergence\n")
    report = check_agent_files(tmp_path)
    assert report.claude_symlink == "warn-regular-file"
    assert report.ok is False


def test_check_reports_extras_as_present(tmp_path: Path) -> None:
    export_agent_files(tmp_path)
    extra = tmp_path / ".agents" / "skills" / "repo-local"
    extra.mkdir(parents=True)
    (extra / "SKILL.md").write_text("# local\n")
    report = check_agent_files(tmp_path)
    assert report.extras == ["repo-local"]
    assert report.ok is True  # extras are legal — reported, not judged


def test_check_overlay_skill_exempt_from_staleness(tmp_path: Path) -> None:
    export_agent_files(tmp_path)
    (tmp_path / "copyroom.project.yml").write_text("agent:\n  overlay:\n    - copyroom\n")
    skill = tmp_path / ".agents" / "skills" / "copyroom" / "SKILL.md"
    skill.write_text("# my own copyroom\n")
    report = check_agent_files(tmp_path)
    assert report.ok is True  # divergence is declared — expected
    overlaid = next(s for s in report.skills if s.name == "copyroom")
    assert overlaid.overlay is True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "copyroom", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def test_cli_export_and_check_roundtrip(tmp_path: Path) -> None:
    export = _run("agent-files", "export", "--target", str(tmp_path), cwd=tmp_path)
    assert export.returncode == 0, export.stderr
    assert "Agent-files export" in export.stdout

    check = _run("agent-files", "check", "--target", str(tmp_path), cwd=tmp_path)
    assert check.returncode == 0, check.stderr
    assert "✓ present" in check.stdout
    assert "✓ symlink" in check.stdout


def test_cli_check_reports_warnings(tmp_path: Path) -> None:
    """Warn-level: a non-conformant target still exits 0 (flipping to fail is a
    later decision) but the report shows the findings."""
    r = _run("agent-files", "check", "--target", str(tmp_path), cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert "⚠️  MISSING" in r.stdout


def test_cli_unknown_action_is_usage_error(tmp_path: Path) -> None:
    r = _run("agent-files", "frobnicate", cwd=tmp_path)
    assert r.returncode != 0
    assert "frobnicate" in r.stderr
