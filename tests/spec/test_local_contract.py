"""Black-box checks for the local Templateer and jj contract."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from copyroom.local.errors import LocalError
from copyroom.local.jj import JJ
from copyroom.local.source import SCHEMA_VERSION, marker, snapshot_path
from copyroom.local.workflow import apply, new, preview, working_digest, working_files

ROOT = Path(__file__).resolve().parents[2]
SLICE = ROOT / ".scratch" / "projects" / "26-templateer-jj-slice"


def _source(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "source"
    shutil.copytree(SLICE / "example", source)
    return source, source / "answers.json"


def test_new_records_a_replayable_source_snapshot(tmp_path: Path) -> None:
    source, answers = _source(tmp_path)
    project = tmp_path / "project"

    new(source, project, answers)

    state = marker(project)
    assert state["schema"] == SCHEMA_VERSION
    assert state["layers"]["base"]["answers"]["project_name"] == "cedar-lab"
    assert snapshot_path(project, state["source_digest"]).is_dir()
    assert JJ(project).render_head(state["project_id"], "base")


def test_preview_preserves_active_project_and_apply_uses_reviewed_tree(tmp_path: Path) -> None:
    source, answers = _source(tmp_path)
    project = tmp_path / "project"
    new(source, project, answers)
    template = source / "templates/settings/template.j2"
    template.write_text(template.read_text(encoding="utf-8") + '\nrevision: "v2"\n', encoding="utf-8")
    preview_path = tmp_path / "preview"
    active_head = JJ(project).commit_id("@")
    active_tree = working_digest(project)

    preview(project, preview_path)

    assert JJ(project).commit_id("@") == active_head
    assert working_digest(project) == active_tree
    reviewed = {
        name: value for name, value in working_files(preview_path).items()
        if name != ".copyroom-local.json"
    }
    apply(project, preview_path)
    applied = {
        name: value for name, value in working_files(project).items()
        if name != ".copyroom-local.json"
    }
    assert applied == reviewed


def test_stale_preview_is_refused_without_advancing_jj(tmp_path: Path) -> None:
    source, answers = _source(tmp_path)
    project = tmp_path / "project"
    new(source, project, answers)
    template = source / "templates/settings/template.j2"
    template.write_text(template.read_text(encoding="utf-8") + '\nrevision: "v2"\n', encoding="utf-8")
    preview_path = tmp_path / "preview"
    preview(project, preview_path)
    (project / "local-note.txt").write_text("local change\n", encoding="utf-8")
    active_head = JJ(project).commit_id("@")
    active_tree = working_digest(project)

    with pytest.raises(LocalError, match="active project changed") as error:
        apply(project, preview_path)

    assert error.value.code == 1
    assert JJ(project).commit_id("@") == active_head
    assert working_digest(project) == active_tree


def test_unresolved_conflict_is_reported_as_a_finding(tmp_path: Path) -> None:
    source, answers = _source(tmp_path)
    project = tmp_path / "project"
    new(source, project, answers)
    (project / "README.md").write_text("# Local edit\n", encoding="utf-8")
    template = source / "templates/readme/template.j2"
    template.write_text("# Template edit\n", encoding="utf-8")
    active_head = JJ(project).commit_id("@")
    active_tree = working_digest(project)
    preview_path = tmp_path / "conflict-preview"

    result = subprocess.run(
        [sys.executable, "-m", "copyroom", "update", "--source", str(source), "--out", str(preview_path)],
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "README.md" in result.stdout
    assert JJ(preview_path).conflicts() == ["README.md"]
    assert JJ(project).commit_id("@") == active_head
    assert working_digest(project) == active_tree
