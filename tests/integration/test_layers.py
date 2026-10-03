"""End-to-end tests for template layers — real Copier and fixture repos.

The scenario uses a documentation overlay beside a generated project. It checks
that each template keeps its own answers, files, and update history.
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
def docs_template(tmp_path: Path) -> Path:
    """A documentation overlay template repo, tagged ``v1.0.0``."""
    repo = tmp_path / "project-docs"
    (repo / "template" / "docs").mkdir(parents=True)
    (repo / "copier.yml").write_text(
        "_subdirectory: template\n"
        "_answers_file: .copier-answers.docs.yml\n"
        "_preserve_symlinks: true\n"
        '_skip_if_exists: ["README.md"]\n'
    )
    (repo / "template" / "{{ _copier_conf.answers_file }}.jinja").write_text(
        "# Changes here will be overwritten by Copier\n{{ _copier_answers|to_nice_yaml -}}\n"
    )
    (repo / "template" / "README.md").write_text("# Overlay README\n")
    (repo / "template" / "docs" / "guide.md").write_text("# Project guide v1\n")
    (repo / "template" / "docs" / "index.md").symlink_to("guide.md")
    _git("init", cwd=repo)
    _commit(repo, "docs overlay v1")
    _git("tag", "v1.0.0", cwd=repo)
    return repo


def _bump_docs(repo: Path) -> None:
    """Publish v2 of the docs overlay with an edit and a new file."""
    (repo / "template" / "docs" / "guide.md").write_text("# Project guide v2\n")
    (repo / "template" / "docs" / "review.md").write_text("# Review guide\n")
    (repo / "template" / "README.md").write_text("# Overlay README v2\n")
    _commit(repo, "docs overlay v2")
    _git("tag", "v2.0.0", cwd=repo)


@pytest.fixture
def layered_project(tmp_path: Path, template_repo: Path, docs_template: Path) -> Path:
    """A project generated from the genome, with the docs overlay applied."""
    proj = tmp_path / "proj"
    assert copier_copy(str(template_repo), proj).returncode == 0
    _git("init", cwd=proj)
    _commit(proj, "generated from the genome")

    add_layer(str(docs_template), repo_root=proj, ref="v1.0.0")
    _commit(proj, "apply the docs overlay")
    return proj


# ---------------------------------------------------------------------------
# layer add
# ---------------------------------------------------------------------------


class TestLayerAdd:
    def test_lands_the_layer_alongside_the_genome(self, layered_project: Path) -> None:
        assert (layered_project / ".copier-answers.yml").is_file()  # genome, untouched
        assert (layered_project / ".copier-answers.docs.yml").is_file()
        assert (layered_project / "docs" / "guide.md").is_file()

    def test_repo_readme_survives(self, layered_project: Path) -> None:
        # _skip_if_exists protects the README that the genome already wrote.
        assert (layered_project / "README.md").read_text().startswith("# ")
        assert "Overlay README" not in (layered_project / "README.md").read_text()

    def test_index_remains_a_symlink(self, layered_project: Path) -> None:
        assert (layered_project / "docs" / "index.md").is_symlink()

    def test_layer_name_comes_from_the_template(
        self, tmp_path: Path, template_repo: Path, docs_template: Path,
    ) -> None:
        proj = tmp_path / "p2"
        assert copier_copy(str(template_repo), proj).returncode == 0
        # No --as: the template's _answers_file names its own layer.
        result = add_layer(str(docs_template), repo_root=proj, ref="v1.0.0")
        assert result.layer == "docs"
        assert str(result.answers_file) == ".copier-answers.docs.yml"
        assert "docs/guide.md" in result.written

    def test_records_the_source_the_caller_gave_not_the_local_clone(
        self, tmp_path: Path, docs_template: Path,
    ) -> None:
        # `_src_path` is what every future `update --layer` resolves against.
        # Recording the resolved clone would pin the repo to a machine-local
        # cache path — unresolvable on another machine or in CI, and broken by
        # a cache prune. It must be the string the caller passed.
        proj = tmp_path / "srcpath"
        proj.mkdir()
        _git("init", cwd=proj)
        (proj / "README.md").write_text("# x\n")
        _commit(proj, "base")

        add_layer(str(docs_template), repo_root=proj, ref="v1.0.0")
        answers = (proj / ".copier-answers.docs.yml").read_text()
        assert f"_src_path: {docs_template}" in answers, answers
        assert "cache" not in answers

    def test_reapplying_the_same_template_is_allowed(
        self, layered_project: Path, docs_template: Path,
    ) -> None:
        result = add_layer(str(docs_template), repo_root=layered_project, ref="v1.0.0")
        assert result.replaced is True

    def test_lands_over_a_locally_diverged_copy_of_its_own_file(
        self, tmp_path: Path, template_repo: Path, docs_template: Path,
    ) -> None:
        # The repo already has a layer-owned file with different content.
        # Copier prompts per conflict and fails without a terminal, so `add`
        # must pass --overwrite.
        proj = tmp_path / "diverged"
        assert copier_copy(str(template_repo), proj).returncode == 0
        guide = proj / "docs" / "guide.md"
        guide.parent.mkdir(parents=True, exist_ok=True)
        guide.write_text("# Hand-written guide\n")
        _git("init", cwd=proj)
        _commit(proj, "with a local guide")

        add_layer(str(docs_template), repo_root=proj, ref="v1.0.0")
        assert guide.read_text() == "# Project guide v1\n"

    def test_retargeting_needs_force(
        self, layered_project: Path, tmp_path: Path, docs_template: Path,
    ) -> None:
        other = tmp_path / "other-docs"
        other.mkdir()
        for item in docs_template.iterdir():
            if item.name != ".git":
                subprocess.run(["cp", "-r", str(item), str(other)], check=True)
        _git("init", cwd=other)
        _commit(other, "other docs v1")
        _git("tag", "v1.0.0", cwd=other)

        with pytest.raises(CopyRoomError, match="--force to retarget"):
            add_layer(str(other), repo_root=layered_project, ref="v1.0.0")

        # --force permits the caller to replace the recorded source.
        result = add_layer(str(other), repo_root=layered_project, ref="v1.0.0", force=True)
        assert result.layer == "docs"

    def test_a_layer_with_no_recorded_source_is_not_a_retarget(
        self, layered_project: Path, docs_template: Path,
    ) -> None:
        # Reapplying the template repairs an incomplete answers file.
        (layered_project / ".copier-answers.docs.yml").write_text("_commit: v1.0.0\n")
        result = add_layer(str(docs_template), repo_root=layered_project, ref="v1.0.0")
        assert result.replaced is True

    def test_refuses_to_masquerade_as_the_base_layer(
        self, layered_project: Path, docs_template: Path,
    ) -> None:
        with pytest.raises(CopyRoomError, match="'copyroom new'"):
            add_layer(str(docs_template), repo_root=layered_project, layer="base")

    def test_applies_to_a_repo_with_no_genome_at_all(
        self, tmp_path: Path, docs_template: Path,
    ) -> None:
        bare = tmp_path / "bare"
        bare.mkdir()
        (bare / "NOTES.txt").write_text("existing repo content\n")
        _git("init", cwd=bare)
        _commit(bare, "bare")

        add_layer(str(docs_template), repo_root=bare, ref="v1.0.0")
        assert (bare / "docs" / "guide.md").is_file()
        assert (bare / "README.md").read_text() == "# Overlay README\n"
        assert (bare / "docs" / "index.md").is_symlink()
        assert is_project(bare)


# ---------------------------------------------------------------------------
# update --layer / --all-layers
# ---------------------------------------------------------------------------


class TestLayerUpdate:
    def test_updating_one_layer_leaves_the_other_alone(
        self, layered_project: Path, docs_template: Path, template_repo: Path,
    ) -> None:
        genome_answers = (layered_project / ".copier-answers.yml").read_text()
        _bump_docs(docs_template)

        update = update_project(project_root=layered_project, layer="docs")
        assert update.status == UpdateStatus.complete, update.status
        assert update.target_ref == "v2.0.0"

        assert (layered_project / "docs" / "guide.md").read_text() == "# Project guide v2\n"
        assert (layered_project / "docs" / "review.md").is_file()
        assert (layered_project / "README.md").read_text().startswith("# ")
        assert "Overlay README" not in (layered_project / "README.md").read_text()
        assert (layered_project / "docs" / "index.md").is_symlink()
        # The genome's layer record is byte-identical — layers are independent.
        assert (layered_project / ".copier-answers.yml").read_text() == genome_answers

    def test_a_skipped_file_stays_unchanged_on_update(
        self, layered_project: Path, docs_template: Path,
    ) -> None:
        readme = (layered_project / "README.md").read_text()
        _bump_docs(docs_template)
        update_project(project_root=layered_project, layer="docs")
        assert (layered_project / "README.md").read_text() == readme

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
        self, layered_project: Path, docs_template: Path, template_repo: Path,
    ) -> None:
        from .conftest import tag_v2

        tag_v2(template_repo)
        _bump_docs(docs_template)

        results = update_all_layers(project_root=layered_project)
        assert [r.layer for r in results] == ["base", "docs"]
        assert all(r.status == UpdateStatus.complete for r in results), [r.status for r in results]
        assert (layered_project / "CHANGELOG.md").is_file()  # from the genome
        assert (layered_project / "docs" / "guide.md").read_text() == "# Project guide v2\n"

    def test_all_layers_commits_between_layers(
        self, layered_project: Path, docs_template: Path, template_repo: Path,
    ) -> None:
        # Copier refuses a dirty destination, so each layer's output must be
        # committed before the next runs — one reviewable commit per layer.
        from .conftest import tag_v2

        tag_v2(template_repo)
        _bump_docs(docs_template)

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
        assert (layered_project / "docs" / "review.md").is_file()
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
        # The guard checks the starting tree, not each layer's output.
        (layered_project / "scratch.txt").write_text("uncommitted\n")
        with pytest.raises(CopyRoomError, match="Worktree is not clean"):
            update_all_layers(project_root=layered_project)


# ---------------------------------------------------------------------------
# The read-only reports
# ---------------------------------------------------------------------------


class TestLayerReports:
    def test_inspect_lists_every_layer(self, layered_project: Path) -> None:
        report = inspect_project(layered_project)
        assert [layer.name for layer in report.layers] == ["base", "docs"]
        # The scalar fields still describe the base layer (single-layer readers).
        assert report.answers_file.endswith(".copier-answers.yml")
        assert report.to_dict()["layers"][1]["answers_file"] == ".copier-answers.docs.yml"

    def test_status_reports_per_layer_update_availability(
        self, layered_project: Path, docs_template: Path,
    ) -> None:
        _bump_docs(docs_template)
        report = project_status(layered_project)
        rows = {row["name"]: row for row in report.layers}
        assert rows["docs"]["update_available"] is True
        assert rows["base"]["update_available"] is False
        # "Anything behind" means any layer, not only the base.
        assert report.update_available is True

    def test_discovery_survives_a_layer_with_no_metadata(self, layered_project: Path) -> None:
        (layered_project / ".copier-answers.hand-written.yml").write_text("{}\n")
        names = [layer.name for layer in discover_layers(layered_project)]
        assert names == ["base", "docs", "hand-written"]
