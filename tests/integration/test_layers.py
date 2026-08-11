"""End-to-end tests for template layers — real Copier, real git.

The scenario throughout is the motivating one: a project generated from a
genome, with a **personal layer** (my-ai's shape: agent files, an ``AGENTS.md``
seed protected by ``_skip_if_exists``, a ``CLAUDE.md`` symlink) applied on top.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from copyroom._compat.copier import copier_copy
from copyroom._compat.errors import CopyRoomError
from copyroom.manage.layer import add_layer
from copyroom.project.inspect import inspect_project, project_status
from copyroom.project.layers import discover_layers
from copyroom.project.model import UpdateStatus
from copyroom.project.update import update_all_layers, update_project
from copyroom.session.detector import is_project


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", "-c", "user.email=test@test", "-c", "user.name=test", *args],
        cwd=cwd, check=True, capture_output=True, text=True,
    )


def _commit(repo: Path, message: str) -> None:
    _git("add", "-A", cwd=repo)
    _git("commit", "-qm", message, cwd=repo)


@pytest.fixture
def personal_template(tmp_path: Path) -> Path:
    """A my-ai-shaped overlay template repo, tagged ``v1.0.0``.

    Ships exactly what the personal layer ships: the personal skill (always
    converged), an ``AGENTS.md`` seed (never clobbering a repo that has one), and
    the ``CLAUDE.md`` symlink.
    """
    repo = tmp_path / "my-ai"
    (repo / "template" / ".agents" / "skills" / "my-ai").mkdir(parents=True)
    (repo / "copier.yml").write_text(
        "_subdirectory: template\n"
        "_answers_file: .copier-answers.my-ai.yml\n"
        "_preserve_symlinks: true\n"
        '_copy_without_render: [".agents/skills/**"]\n'
        '_skip_if_exists: ["AGENTS.md"]\n'
    )
    (repo / "template" / "{{ _copier_conf.answers_file }}.jinja").write_text(
        "# Changes here will be overwritten by Copier\n{{ _copier_answers|to_nice_yaml -}}\n"
    )
    (repo / "template" / "AGENTS.md").write_text("# AGENTS.md — seeded by the personal layer\n")
    (repo / "template" / "CLAUDE.md").symlink_to("AGENTS.md")
    (repo / "template" / ".agents" / "skills" / "my-ai" / "SKILL.md").write_text(
        "# my-ai — personal law v1\n"
    )
    _git("init", cwd=repo)
    _commit(repo, "my-ai v1")
    _git("tag", "v1.0.0", cwd=repo)
    return repo


def _bump_personal(repo: Path) -> None:
    """Publish v2 of the personal layer: an edited skill and a brand-new one."""
    (repo / "template" / ".agents" / "skills" / "my-ai" / "SKILL.md").write_text(
        "# my-ai — personal law v2\n"
    )
    (repo / "template" / ".agents" / "skills" / "my-ai-review").mkdir()
    (repo / "template" / ".agents" / "skills" / "my-ai-review" / "SKILL.md").write_text(
        "# my-ai-review — new personal skill\n"
    )
    (repo / "template" / "AGENTS.md").write_text("# AGENTS.md — seed v2 (must never land on a repo that has one)\n")
    _commit(repo, "my-ai v2")
    _git("tag", "v2.0.0", cwd=repo)


@pytest.fixture
def layered_project(tmp_path: Path, template_repo: Path, personal_template: Path) -> Path:
    """A project generated from the genome, with the personal layer applied."""
    proj = tmp_path / "proj"
    assert copier_copy(str(template_repo), proj).returncode == 0
    _git("init", cwd=proj)
    _commit(proj, "generated from the genome")

    add_layer(str(personal_template), repo_root=proj, ref="v1.0.0")
    _commit(proj, "apply the personal layer")
    return proj


# ---------------------------------------------------------------------------
# layer add
# ---------------------------------------------------------------------------


class TestLayerAdd:
    def test_lands_the_layer_alongside_the_genome(self, layered_project: Path) -> None:
        assert (layered_project / ".copier-answers.yml").is_file()  # genome, untouched
        assert (layered_project / ".copier-answers.my-ai.yml").is_file()
        assert (layered_project / ".agents" / "skills" / "my-ai" / "SKILL.md").is_file()
        # ...and the genome's own skill is still there.
        assert (layered_project / ".agents" / "skills" / "copyroom" / "SKILL.md").is_file()

    def test_the_repos_own_agents_md_survives(self, layered_project: Path) -> None:
        # _skip_if_exists: the genome's AGENTS.md is the repo's, not the layer's.
        assert "seeded by the personal layer" not in (layered_project / "AGENTS.md").read_text()

    def test_claude_md_is_still_a_symlink(self, layered_project: Path) -> None:
        assert (layered_project / "CLAUDE.md").is_symlink()

    def test_layer_name_comes_from_the_template(
        self, tmp_path: Path, template_repo: Path, personal_template: Path,
    ) -> None:
        proj = tmp_path / "p2"
        assert copier_copy(str(template_repo), proj).returncode == 0
        # No --as: the template's _answers_file names its own layer.
        result = add_layer(str(personal_template), repo_root=proj, ref="v1.0.0")
        assert result.layer == "my-ai"
        assert str(result.answers_file) == ".copier-answers.my-ai.yml"
        assert ".agents/skills/my-ai/SKILL.md" in result.written

    def test_reapplying_the_same_template_is_allowed(
        self, layered_project: Path, personal_template: Path,
    ) -> None:
        result = add_layer(str(personal_template), repo_root=layered_project, ref="v1.0.0")
        assert result.replaced is True

    def test_retargeting_needs_force(
        self, layered_project: Path, tmp_path: Path, personal_template: Path,
    ) -> None:
        other = tmp_path / "other-my-ai"
        other.mkdir()
        for item in personal_template.iterdir():
            if item.name != ".git":
                subprocess.run(["cp", "-r", str(item), str(other)], check=True)
        _git("init", cwd=other)
        _commit(other, "other v1")
        _git("tag", "v1.0.0", cwd=other)

        with pytest.raises(CopyRoomError, match="--force to retarget"):
            add_layer(str(other), repo_root=layered_project, ref="v1.0.0")

        # ...and --force goes through.
        result = add_layer(str(other), repo_root=layered_project, ref="v1.0.0", force=True)
        assert result.layer == "my-ai"

    def test_a_layer_with_no_recorded_source_is_not_a_retarget(
        self, layered_project: Path, personal_template: Path,
    ) -> None:
        # An incomplete answers file must not block re-applying the layer —
        # re-applying is the fix for that state, not something to refuse.
        (layered_project / ".copier-answers.my-ai.yml").write_text("_commit: v1.0.0\n")
        result = add_layer(str(personal_template), repo_root=layered_project, ref="v1.0.0")
        assert result.replaced is True

    def test_refuses_to_masquerade_as_the_base_layer(
        self, layered_project: Path, personal_template: Path,
    ) -> None:
        with pytest.raises(CopyRoomError, match="'copyroom new'"):
            add_layer(str(personal_template), repo_root=layered_project, layer="base")

    def test_applies_to_a_repo_with_no_genome_at_all(
        self, tmp_path: Path, personal_template: Path,
    ) -> None:
        # The personal layer must land on an unmanaged repo too — that is most of
        # the fleet before adoption.
        bare = tmp_path / "bare"
        bare.mkdir()
        (bare / "README.md").write_text("# bare\n")
        _git("init", cwd=bare)
        _commit(bare, "bare")

        add_layer(str(personal_template), repo_root=bare, ref="v1.0.0")
        assert (bare / ".agents" / "skills" / "my-ai" / "SKILL.md").is_file()
        # With no AGENTS.md of its own, the repo gets the seed.
        assert "seeded by the personal layer" in (bare / "AGENTS.md").read_text()
        assert (bare / "CLAUDE.md").is_symlink()
        # ...and it is now a project as far as mode detection is concerned.
        assert is_project(bare)


# ---------------------------------------------------------------------------
# update --layer / --all-layers
# ---------------------------------------------------------------------------


class TestLayerUpdate:
    def test_updating_one_layer_leaves_the_other_alone(
        self, layered_project: Path, personal_template: Path, template_repo: Path,
    ) -> None:
        genome_answers = (layered_project / ".copier-answers.yml").read_text()
        _bump_personal(personal_template)

        update = update_project(project_root=layered_project, layer="my-ai")
        assert update.status == UpdateStatus.complete, update.status
        assert update.target_ref == "v2.0.0"

        skills = layered_project / ".agents" / "skills"
        assert "personal law v2" in (skills / "my-ai" / "SKILL.md").read_text()
        assert (skills / "my-ai-review" / "SKILL.md").is_file()  # a new skill converged
        # The genome's layer record is byte-identical — layers are independent.
        assert (layered_project / ".copier-answers.yml").read_text() == genome_answers

    def test_the_agents_md_seed_never_lands_on_update(
        self, layered_project: Path, personal_template: Path,
    ) -> None:
        _bump_personal(personal_template)
        update_project(project_root=layered_project, layer="my-ai")
        assert "seed v2" not in (layered_project / "AGENTS.md").read_text()

    def test_an_unknown_layer_fails_cleanly(self, layered_project: Path) -> None:
        update = update_project(project_root=layered_project, layer="nope")
        assert update.status == UpdateStatus.failed

    def test_base_is_still_the_default(
        self, layered_project: Path, template_repo: Path,
    ) -> None:
        from .conftest import tag_v2

        tag_v2(template_repo)
        update = update_project(project_root=layered_project)  # no layer= argument
        assert update.status == UpdateStatus.complete
        assert update.layer == "base"
        assert (layered_project / "CHANGELOG.md").is_file()

    def test_all_layers_converges_each_to_its_own_latest(
        self, layered_project: Path, personal_template: Path, template_repo: Path,
    ) -> None:
        from .conftest import tag_v2

        tag_v2(template_repo)
        _bump_personal(personal_template)

        results = update_all_layers(project_root=layered_project)
        assert [r.layer for r in results] == ["base", "my-ai"]
        assert all(r.status == UpdateStatus.complete for r in results), [r.status for r in results]
        assert (layered_project / "CHANGELOG.md").is_file()  # from the genome
        assert "personal law v2" in (
            layered_project / ".agents" / "skills" / "my-ai" / "SKILL.md"
        ).read_text()

    def test_all_layers_commits_between_layers(
        self, layered_project: Path, personal_template: Path, template_repo: Path,
    ) -> None:
        # Copier refuses a dirty destination, so each layer's output must be
        # committed before the next runs — one reviewable commit per layer.
        from .conftest import tag_v2

        tag_v2(template_repo)
        _bump_personal(personal_template)

        before = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"], cwd=layered_project,
            capture_output=True, text=True, check=True,
        ).stdout.strip()

        update_all_layers(project_root=layered_project)

        log = subprocess.run(
            ["git", "log", "--format=%s", f"-{int(before) + 2}"], cwd=layered_project,
            capture_output=True, text=True, check=True,
        ).stdout
        assert "copyroom: update layer 'base' to v2.0.0" in log
        # The last layer is left uncommitted, for review — same as a single update.
        assert (layered_project / ".agents" / "skills" / "my-ai-review").is_dir()
        assert subprocess.run(
            ["git", "status", "--porcelain"], cwd=layered_project,
            capture_output=True, text=True, check=True,
        ).stdout.strip()

    def test_all_layers_refuses_an_unmanaged_repo(self, tmp_path: Path) -> None:
        bare = tmp_path / "bare"
        bare.mkdir()
        with pytest.raises(CopyRoomError, match="No template layer here"):
            update_all_layers(project_root=bare)

    def test_all_layers_checks_the_worktree_once_up_front(self, layered_project: Path) -> None:
        # The guard is the run's, not the layer's: a dirty tree at the start is
        # refused outright, so the "clean before we began" invariant holds for
        # the whole run even though layer 2 sees layer 1's output.
        (layered_project / "scratch.txt").write_text("uncommitted\n")
        with pytest.raises(CopyRoomError, match="Worktree is not clean"):
            update_all_layers(project_root=layered_project)


# ---------------------------------------------------------------------------
# The read-only reports
# ---------------------------------------------------------------------------


class TestLayerReports:
    def test_inspect_lists_every_layer(self, layered_project: Path) -> None:
        report = inspect_project(layered_project)
        assert [layer.name for layer in report.layers] == ["base", "my-ai"]
        # The scalar fields still describe the base layer (single-layer readers).
        assert report.answers_file.endswith(".copier-answers.yml")
        assert report.to_dict()["layers"][1]["answers_file"] == ".copier-answers.my-ai.yml"

    def test_status_reports_per_layer_update_availability(
        self, layered_project: Path, personal_template: Path,
    ) -> None:
        _bump_personal(personal_template)
        report = project_status(layered_project)
        rows = {row["name"]: row for row in report.layers}
        assert rows["my-ai"]["update_available"] is True
        assert rows["base"]["update_available"] is False
        # "anything behind" — not just the primary layer.
        assert report.update_available is True

    def test_discovery_survives_a_layer_with_no_metadata(self, layered_project: Path) -> None:
        (layered_project / ".copier-answers.hand-written.yml").write_text("{}\n")
        names = [layer.name for layer in discover_layers(layered_project)]
        assert names == ["base", "hand-written", "my-ai"]
