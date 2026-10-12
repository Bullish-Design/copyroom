"""A source can be pinned to a ref of the local Git repository that holds it."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from copyroom.cli import app
from copyroom.local.composer import digest_source
from copyroom.local.errors import LocalError
from copyroom.local.jj import JJ
from copyroom.local.pinned import find_repo, materialise, resolve_commit
from copyroom.local.source import MARKER
from copyroom.local.store import restore_stored

ROOT = Path(__file__).resolve().parents[2]
SOURCE_FIXTURE = ROOT / ".scratch" / "projects" / "26-templateer-jj-slice" / "example"
runner = CliRunner()
SETTINGS = "templates/settings/template.j2"


def _git(*args: str, cwd: Path) -> str:
    result = subprocess.run(
        ["git", "-c", "user.email=a@b", "-c", "user.name=n", *args],
        cwd=str(cwd), capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def _commit(repo: Path, message: str) -> str:
    _git("add", "-A", cwd=repo)
    _git("commit", "-qm", message, cwd=repo)
    return _git("rev-parse", "HEAD", cwd=repo)


def _append_settings(source: Path, text: str) -> None:
    path = source / SETTINGS
    path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")


def _make_overlay(source: Path, overlay: Path) -> None:
    """Copy a source and cut it to one template that renders docs/guide.md."""

    shutil.copytree(source, overlay)
    manifest_path = overlay / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["templates"] = ["settings"]
    manifest["executable"] = []
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    metadata = overlay / "templates/settings/metadata.yml"
    metadata.write_text(
        metadata.read_text(encoding="utf-8").replace("config/project.yml", "docs/guide.md"),
        encoding="utf-8",
    )


class Repo:
    """A template repository. The source sits in ``template-py/source``.

    Tag ``v1`` is the first commit. Annotated tag ``v2`` adds ``revision: "v2"``.
    Branch ``main`` then moves on to a work-in-progress commit.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.source = root / "template-py" / "source"
        self.overlay = root / "template-py" / "overlay"
        self.answers = root.parent / "answers.json"
        root.mkdir()
        _git("init", "-q", "-b", "main", cwd=root)
        shutil.copytree(SOURCE_FIXTURE, self.source)
        _make_overlay(self.source, self.overlay)
        shutil.copy(self.source / "answers.json", self.answers)
        self.v1 = _commit(root, "first")
        _git("tag", "v1", cwd=root)
        _append_settings(self.source, 'revision: "v2"\n')
        self.v2 = _commit(root, "second")
        _git("tag", "-a", "v2", "-m", "release v2", cwd=root)
        _append_settings(self.source, 'revision: "wip"\n')
        self.wip = _commit(root, "work in progress")

    def advance(self, text: str) -> str:
        """Commit one more change to the moving branch."""

        _append_settings(self.source, text)
        return _commit(self.root, "more work")


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    return Repo(tmp_path / "template-repo")


@pytest.fixture(autouse=True)
def no_leaked_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Every command removes the temporary tree it materialised."""

    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    yield
    assert list(scratch.glob("copyroom-source-*")) == []


def _invoke(*args: str, cwd: Path | None = None) -> Any:
    previous = Path.cwd()
    if cwd is not None:
        os.chdir(cwd)
    try:
        return runner.invoke(app, list(args))
    finally:
        os.chdir(previous)


def _ok(*args: str, cwd: Path | None = None) -> Any:
    result = _invoke(*args, cwd=cwd)
    assert result.exit_code == 0, result.stderr or result.output
    return result


def _json(result: Any) -> Any:
    return json.loads(result.stdout)


def _marker(project: Path) -> dict[str, Any]:
    return json.loads((project / MARKER).read_text(encoding="utf-8"))


def _new(repo: Repo, tmp_path: Path, ref: str, name: str = "project") -> Path:
    project = tmp_path / name
    _ok("new", str(repo.source), str(project), "--answers", str(repo.answers), "--ref", ref)
    return project


def _converge(project: Path, tmp_path: Path, *args: str) -> Any:
    """Preview an update, then apply it. Return the preview report."""

    out = tmp_path / f"preview-{len(list(tmp_path.glob('preview-*')))}"
    report = _json(_ok("update", "--json", "--out", str(out), *args, cwd=project))
    if report.get("result") != "no-change":
        _ok("update", "--apply", str(out), cwd=project)
    return report


def _settings_text(project: Path) -> str:
    return (project / "config/project.yml").read_text(encoding="utf-8")


def test_new_with_a_ref_pins_the_commit(repo: Repo, tmp_path: Path) -> None:
    project = _new(repo, tmp_path, "v1")

    pin = _marker(project)["layers"]["base"]["pin"]
    assert pin == {
        "repo": str(repo.root), "subdir": "template-py/source", "ref": "v1", "commit": repo.v1,
    }
    assert _marker(project)["pin"] == pin
    assert _marker(project)["source"] == str(repo.source)
    assert "revision:" not in _settings_text(project)
    # The private ref holds the pinned tree, not the working tree.
    stored = tmp_path / "stored"
    assert restore_stored(project, _marker(project)["source_digest"], stored)
    assert "wip" not in (stored / SETTINGS).read_text(encoding="utf-8")


def test_annotated_tag_pins_its_commit(repo: Repo, tmp_path: Path) -> None:
    project = _new(repo, tmp_path, "v2")

    pin = _marker(project)["pin"]
    assert pin["ref"] == "v2"
    assert pin["commit"] == repo.v2
    assert 'revision: "v2"' in _settings_text(project)


def test_new_without_a_ref_keeps_a_path_source(repo: Repo, tmp_path: Path) -> None:
    project = tmp_path / "project"
    _ok("new", str(repo.source), str(project), "--answers", str(repo.answers))

    assert "pin" not in _marker(project)
    assert 'revision: "wip"' in _settings_text(project)
    layer = _json(_ok("layer", "list", "--json", cwd=project))[0]
    assert layer["source_kind"] == "path"
    assert layer["ref"] is None


def test_update_keeps_the_pinned_commit_when_the_branch_moves(repo: Repo, tmp_path: Path) -> None:
    project = _new(repo, tmp_path, "main")
    assert _marker(project)["pin"]["commit"] == repo.wip

    repo.advance('revision: "later"\n')
    _append_settings(repo.source, 'revision: "uncommitted"\n')

    assert _converge(project, tmp_path)["result"] == "no-change"
    assert _marker(project)["pin"]["commit"] == repo.wip
    assert "later" not in _settings_text(project)


def test_update_re_renders_the_pinned_commit_with_new_answers(repo: Repo, tmp_path: Path) -> None:
    project = _new(repo, tmp_path, "v1")
    repo.advance('revision: "later"\n')
    answers = json.loads(repo.answers.read_text(encoding="utf-8"))
    answers["description"] = "Changed answer"
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(answers), encoding="utf-8")

    _converge(project, tmp_path, "--answers", str(changed))

    assert "Changed answer" in _settings_text(project)
    assert "later" not in _settings_text(project)
    assert _marker(project)["pin"]["commit"] == repo.v1


def test_update_uses_the_private_ref_when_the_repository_is_gone(repo: Repo, tmp_path: Path) -> None:
    project = _new(repo, tmp_path, "v1")
    shutil.rmtree(repo.root)

    assert _converge(project, tmp_path)["result"] == "no-change"


def test_update_ref_moves_the_layer_to_a_new_ref(repo: Repo, tmp_path: Path) -> None:
    project = _new(repo, tmp_path, "v1")

    _converge(project, tmp_path, "--ref", "v2")

    pin = _marker(project)["layers"]["base"]["pin"]
    assert (pin["ref"], pin["commit"]) == ("v2", repo.v2)
    assert 'revision: "v2"' in _settings_text(project)
    assert _json(_ok("status", "--json", cwd=project))["ok"] is True
    assert _converge(project, tmp_path)["result"] == "no-change"


def test_update_ref_to_the_same_tree_still_records_the_new_pin(repo: Repo, tmp_path: Path) -> None:
    _git("tag", "v1-again", repo.v1, cwd=repo.root)
    project = _new(repo, tmp_path, "v1")

    _converge(project, tmp_path, "--ref", "v1-again")

    assert _marker(project)["pin"]["ref"] == "v1-again"


def test_update_moves_a_path_source_project_onto_a_versioned_source(
    repo: Repo, tmp_path: Path,
) -> None:
    old = tmp_path / "v0.5.0-source"
    shutil.copytree(SOURCE_FIXTURE, old)
    project = tmp_path / "project"
    _ok("new", str(old), str(project), "--answers", str(repo.answers))
    assert "pin" not in _marker(project)

    _converge(project, tmp_path, "--source", str(repo.source), "--ref", "v2")

    marker = _marker(project)
    assert marker["layers"]["base"]["pin"]["commit"] == repo.v2
    assert marker["pin"]["ref"] == "v2"
    assert marker["source"] == str(repo.source)
    assert 'revision: "v2"' in _settings_text(project)
    layer = _json(_ok("layer", "list", "--json", cwd=project))[0]
    assert (layer["source_kind"], layer["ref"], layer["commit"]) == ("ref", "v2", repo.v2)


def test_update_ref_alone_pins_a_path_source_that_lives_in_a_repository(
    repo: Repo, tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    _ok("new", str(repo.source), str(project), "--answers", str(repo.answers))

    _converge(project, tmp_path, "--ref", "v1")

    assert _marker(project)["pin"]["commit"] == repo.v1
    assert "wip" not in _settings_text(project)


def test_update_source_without_a_ref_returns_to_a_path_source(repo: Repo, tmp_path: Path) -> None:
    project = _new(repo, tmp_path, "v1")

    _converge(project, tmp_path, "--source", str(repo.source))

    assert "pin" not in _marker(project)
    assert "pin" not in _marker(project)["layers"]["base"]
    assert 'revision: "wip"' in _settings_text(project)


def test_update_apply_refuses_a_ref(repo: Repo, tmp_path: Path) -> None:
    project = _new(repo, tmp_path, "v1")

    result = _invoke("update", "--apply", str(tmp_path / "x"), "--ref", "v2", cwd=project)

    assert result.exit_code == 3


def test_preview_create_takes_a_ref(repo: Repo, tmp_path: Path) -> None:
    project = _new(repo, tmp_path, "v1")
    out = tmp_path / "preview"

    report = _json(_ok(
        "preview", "create", "--project", str(project), "--out", str(out), "--ref", "v2",
        "--json",
    ))

    assert report["pin"]["commit"] == repo.v2
    assert report["source"] == str(repo.source)
    _ok("discard", "--preview", str(out))


def test_adopt_with_a_ref_pins_the_commit(repo: Repo, tmp_path: Path) -> None:
    archive = tmp_path / "v1-tree"
    archive.mkdir()
    tar = subprocess.run(
        ["git", "archive", "v1", "template-py/source"], cwd=repo.root, capture_output=True,
        check=True,
    )
    subprocess.run(["tar", "-x", "-C", str(archive)], input=tar.stdout, check=True)
    project = tmp_path / "existing"
    project.mkdir()
    from copyroom.local.composer import compose
    from copyroom.local.workflow import write_tree

    plan = compose(archive / "template-py/source", json.loads(repo.answers.read_text("utf-8")))
    write_tree(project, plan.files)
    _git("init", "-q", "-b", "main", cwd=project)
    _commit(project, "init")

    report = _json(_ok(
        "adopt", str(repo.source), "--ref", "v1", "--answers", str(repo.answers),
        "--project", str(project), "--json",
    ))
    assert report["exact"] is True
    _ok(
        "adopt", str(repo.source), "--ref", "v1", "--answers", str(repo.answers),
        "--project", str(project), "--write",
    )

    pin = _marker(project)["pin"]
    assert (pin["ref"], pin["commit"]) == ("v1", repo.v1)
    assert _converge(project, tmp_path)["result"] == "no-change"
    _converge(project, tmp_path, "--ref", "v2")
    assert 'revision: "v2"' in _settings_text(project)


def test_adopt_report_with_a_ref_shows_drift_against_that_commit(
    repo: Repo, tmp_path: Path,
) -> None:
    project = tmp_path / "existing"
    project.mkdir()
    (project / "notes.txt").write_text("note\n", encoding="utf-8")

    result = _invoke(
        "adopt", str(repo.source), "--ref", "v1", "--answers", str(repo.answers),
        "--project", str(project), "--json",
    )

    assert result.exit_code == 1
    assert not (project / MARKER).exists()


def test_layer_add_with_a_ref_pins_the_layer(repo: Repo, tmp_path: Path) -> None:
    project = _new(repo, tmp_path, "v1")

    _ok(
        "layer", "add", "--source", str(repo.overlay), "--ref", "v1", "--answers",
        str(repo.answers), "--as", "extra", cwd=project,
    )

    layers = {row["layer"]: row for row in _json(_ok("layer", "list", "--json", cwd=project))}
    assert layers["extra"]["source_kind"] == "ref"
    assert layers["extra"]["commit"] == repo.v1
    assert layers["base"]["commit"] == repo.v1
    assert _marker(project)["layers"]["extra"]["pin"]["subdir"] == "template-py/overlay"
    assert (project / "docs/guide.md").is_file()
    assert _converge(project, tmp_path, "--layer", "extra")["result"] == "no-change"
    _converge(project, tmp_path, "--layer", "extra", "--ref", "v2")
    assert _marker(project)["layers"]["extra"]["pin"]["ref"] == "v2"
    assert _marker(project)["layers"]["base"]["pin"]["ref"] == "v1"


def test_a_missing_ref_exits_two(repo: Repo, tmp_path: Path) -> None:
    project = tmp_path / "project"

    result = _invoke(
        "new", str(repo.source), str(project), "--answers", str(repo.answers), "--ref", "v0.9.0",
    )

    assert result.exit_code == 2
    assert f"ref v0.9.0 not found in {repo.root}; fetch it first" in result.stderr
    assert not project.exists()

    existing = _new(repo, tmp_path, "v1", "existing")
    result = _invoke("update", "--ref", "v0.9.0", cwd=existing)
    assert result.exit_code == 2
    assert "ref v0.9.0 not found" in result.stderr


def test_a_ref_that_starts_with_a_dash_is_a_usage_error(repo: Repo, tmp_path: Path) -> None:
    result = _invoke(
        "new", str(repo.source), str(tmp_path / "p"), "--answers", str(repo.answers),
        "--ref=--output=x",
    )

    assert result.exit_code == 3


def test_a_source_outside_a_repository_with_a_ref_exits_two(tmp_path: Path) -> None:
    source = tmp_path / "plain-source"
    shutil.copytree(SOURCE_FIXTURE, source)

    result = _invoke(
        "new", str(source), str(tmp_path / "project"), "--answers", str(source / "answers.json"),
        "--ref", "v1",
    )

    assert result.exit_code == 2
    assert "Git repository" in result.stderr
    assert not (tmp_path / "project").exists()


def test_a_symlinked_source_with_a_ref_is_refused(repo: Repo, tmp_path: Path) -> None:
    link = tmp_path / "link"
    link.symlink_to(repo.source)

    result = _invoke(
        "new", str(link), str(tmp_path / "project"), "--answers", str(repo.answers),
        "--ref", "v1",
    )

    assert result.exit_code == 2
    assert "symlink" in result.stderr


def test_a_ref_with_no_source_directory_exits_two(repo: Repo, tmp_path: Path) -> None:
    early = repo.root / "template-py" / "later"
    shutil.copytree(repo.source, early)
    _commit(repo.root, "add later")

    result = _invoke(
        "new", str(early), str(tmp_path / "project"), "--answers", str(repo.answers), "--ref", "v1",
    )

    assert result.exit_code == 2
    assert "has no source directory template-py/later" in result.stderr


def test_materialise_keeps_modes_and_symlinks_and_ignores_attributes(
    repo: Repo, tmp_path: Path,
) -> None:
    script = repo.source / "static" / "run.sh"
    script.parent.mkdir()
    script.write_text("#!/bin/sh\n", encoding="utf-8")
    script.chmod(0o755)
    (repo.source / "static" / "plain.txt").write_text("plain\n", encoding="utf-8")
    (repo.source / "static" / "link").symlink_to("run.sh")
    (repo.source / "static" / "hidden.txt").write_text("hidden\n", encoding="utf-8")
    (repo.root / ".gitattributes").write_text("*/hidden.txt export-ignore\n", encoding="utf-8")
    _commit(repo.root, "static files")
    destination = tmp_path / "out"

    root, subdir = find_repo(repo.source)
    materialise(root, resolve_commit(root, "HEAD"), subdir, destination)

    assert os.access(destination / "static/run.sh", os.X_OK)
    assert not os.access(destination / "static/plain.txt", os.X_OK)
    assert (destination / "static/link").is_symlink()
    assert os.readlink(destination / "static/link") == "run.sh"
    assert (destination / "static/hidden.txt").read_text(encoding="utf-8") == "hidden\n"
    assert (destination / "manifest.json").read_bytes() == (repo.source / "manifest.json").read_bytes()


def test_materialised_tree_has_the_digest_of_the_clean_working_tree(
    repo: Repo, tmp_path: Path,
) -> None:
    script = repo.source / "tool.sh"
    script.write_text("#!/bin/sh\n", encoding="utf-8")
    script.chmod(0o755)
    _commit(repo.root, "add an executable")
    destination = tmp_path / "out"

    root, subdir = find_repo(repo.source)
    materialise(root, resolve_commit(root, "main"), subdir, destination)

    assert digest_source(destination) == digest_source(repo.source)


def test_source_symlinks_are_refused_like_a_path_source(repo: Repo, tmp_path: Path) -> None:
    (repo.source / "link").symlink_to("manifest.json")
    _commit(repo.root, "add a symlink")

    result = _invoke(
        "new", str(repo.source), str(tmp_path / "project"), "--answers", str(repo.answers),
        "--ref", "main",
    )

    assert result.exit_code == 2
    assert "source symlinks are not supported: link" in result.stderr


def test_source_in_a_colocated_jj_repository(repo: Repo, tmp_path: Path) -> None:
    JJ(repo.root).run("git", "init", "--colocate")

    project = _new(repo, tmp_path, "v1")

    assert _marker(project)["pin"]["commit"] == repo.v1


def test_source_at_the_repository_root(tmp_path: Path) -> None:
    root = tmp_path / "root-repo"
    shutil.copytree(SOURCE_FIXTURE, root)
    _git("init", "-q", "-b", "main", cwd=root)
    commit = _commit(root, "first")
    _git("tag", "v1", cwd=root)

    project = tmp_path / "project"
    _ok("new", str(root), str(project), "--answers", str(root / "answers.json"), "--ref", "v1")

    pin = _marker(project)["pin"]
    assert (pin["subdir"], pin["commit"]) == ("", commit)
    assert _marker(project)["source"] == str(root)


def test_status_shows_the_ref_the_commit_and_newer_tags(repo: Repo, tmp_path: Path) -> None:
    project = _new(repo, tmp_path, "v1")
    _git("tag", "v1.1.0", repo.v2, cwd=repo.root)
    _git("tag", "v2.0.0-rc1", repo.v2, cwd=repo.root)
    _git("tag", "not-a-version", repo.v2, cwd=repo.root)

    result = _ok("status", "--json", cwd=project)

    report = _json(result)
    layer = report["layers"]["base"]
    assert layer["source_kind"] == "ref"
    assert layer["ref"] == "v1"
    assert layer["commit_short"] == repo.v1[:12]
    assert layer["updates_available"] == ["v1.1.0", "v2"]
    assert report["updates_available"] == [
        {"layer": "base", "ref": "v1", "newer": ["v1.1.0", "v2"]},
    ]
    assert report["ok"] is True
    assert "update available: base v1 -> v1.1.0, v2" in result.stderr


def test_status_reports_no_update_at_the_newest_tag_or_on_a_branch(
    repo: Repo, tmp_path: Path,
) -> None:
    newest = _new(repo, tmp_path, "v2", "newest")
    branch = _new(repo, tmp_path, "main", "branch")

    assert _json(_ok("status", "--json", cwd=newest))["updates_available"] == []
    assert _json(_ok("status", "--json", cwd=branch))["updates_available"] == []


def test_status_shows_a_path_source(repo: Repo, tmp_path: Path) -> None:
    project = tmp_path / "project"
    _ok("new", str(repo.source), str(project), "--answers", str(repo.answers))

    report = _json(_ok("status", "--json", cwd=project))

    layer = report["layers"]["base"]
    assert (layer["source_kind"], layer["ref"], layer["commit"]) == ("path", None, None)
    assert report["updates_available"] == []


def test_status_survives_an_unreadable_repository(repo: Repo, tmp_path: Path) -> None:
    project = _new(repo, tmp_path, "v1")
    shutil.move(str(repo.root), str(tmp_path / "moved"))

    result = _ok("status", "--json", cwd=project)

    layer = _json(result)["layers"]["base"]
    assert layer["updates_error"]
    assert layer["updates_available"] == []
    assert layer["source_reachable"] is False
    assert layer["ref_reachable"] is True
    assert "cannot check updates: base" in result.stderr


def test_resolve_commit_rejects_a_missing_ref(repo: Repo) -> None:
    with pytest.raises(LocalError) as caught:
        resolve_commit(repo.root, "nope")

    assert caught.value.code == 2
