"""CopyRoom sees a project as jj does: ignored paths are invisible."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from copyroom.cli import app
from copyroom.local import manage as manage_module
from copyroom.local.composer import compose
from copyroom.local.errors import LocalError
from copyroom.local.jj import JJ
from copyroom.local.manage import adopt
from copyroom.local.source import LOCK_FILE, MARKER
from copyroom.local.workflow import project_paths, tree_files, working_files, write_tree

ROOT = Path(__file__).resolve().parents[2]
SOURCE_FIXTURE = ROOT / ".scratch" / "projects" / "26-templateer-jj-slice" / "example"
DEVMAN_LINKS = (".agents", ".claude", "devenv.local.nix")
runner = CliRunner()


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "copyroom", *args], cwd=str(cwd), capture_output=True, text=True,
    )


def _git(*args: str, cwd: Path) -> str:
    result = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True)
    return result.stdout


def _source(tmp_path: Path, name: str = "source") -> Path:
    source = tmp_path / name
    shutil.copytree(SOURCE_FIXTURE, source)
    return source


def _link_devman_files(project: Path, store: Path, ignore: bool = True) -> dict[str, str]:
    """Link the devman paths into a project. Return each link text."""

    store.mkdir(parents=True, exist_ok=True)
    (store / "agents.txt").write_text("central agents\n", encoding="utf-8")
    links: dict[str, str] = {}
    for name in DEVMAN_LINKS:
        target = store / name.lstrip(".")
        if name == "devenv.local.nix":
            target.write_text("{ }\n", encoding="utf-8")
        else:
            target.mkdir(exist_ok=True)
            (target / "note.txt").write_text(name + "\n", encoding="utf-8")
        (project / name).symlink_to(target)
        links[name] = str(target)
    if ignore:
        (project / ".gitignore").write_text("\n".join(DEVMAN_LINKS) + "\n", encoding="utf-8")
    return links


def _existing_project(tmp_path: Path, source: Path, vcs: str) -> Path:
    """Write a rendered tree with a project-owned file and devman links.

    ``vcs`` is ``none``, ``git`` (a Git repository without jj), or ``jj``.
    """

    project = tmp_path / "existing"
    project.mkdir()
    plan = compose(source, json.loads((source / "answers.json").read_text(encoding="utf-8")))
    write_tree(project, plan.files)
    (project / "notes.txt").write_text("Project-owned note\n", encoding="utf-8")
    _link_devman_files(project, tmp_path / "devman-store")
    if vcs == "git":
        _git("init", "--quiet", "-b", "main", cwd=project)
        _git("-c", "user.email=a@b", "-c", "user.name=n", "add", "-A", cwd=project)
        _git("-c", "user.email=a@b", "-c", "user.name=n", "commit", "-qm", "init", cwd=project)
    elif vcs == "jj":
        JJ(project).run("git", "init", "--colocate")
    return project


def _snapshot_links(project: Path) -> dict[str, tuple[str, bytes]]:
    return {
        name: (os.readlink(project / name), _read_target(project / name)) for name in DEVMAN_LINKS
    }


def _read_target(path: Path) -> bytes:
    if path.is_dir():
        return (path / "note.txt").read_bytes()
    return path.read_bytes()


def _git_files(project: Path) -> dict[str, bytes | None]:
    git_directory = project / ".git"
    return {
        name: (git_directory / name).read_bytes() if (git_directory / name).is_file() else None
        for name in ("HEAD", "index", "info/exclude")
    }


@pytest.mark.parametrize("vcs", ["none", "git", "jj"])
def test_adopt_write_ignores_gitignored_devman_links(tmp_path: Path, vcs: str) -> None:
    source = _source(tmp_path)
    project = _existing_project(tmp_path, source, vcs)
    before = _snapshot_links(project)

    result = _run(
        "adopt", str(source), "--answers", str(source / "answers.json"), "--write",
        "--template-only", "keep", cwd=project,
    )

    assert result.returncode == 0, result.stderr
    assert (project / MARKER).is_file()
    assert _snapshot_links(project) == before
    for name in DEVMAN_LINKS:
        assert (project / name).is_symlink()
        assert name not in JJ(project).tracked_paths("@")
    assert LOCK_FILE not in JJ(project).tracked_paths("@")


@pytest.mark.parametrize("vcs", ["none", "git"])
def test_adopt_report_hides_ignored_paths(tmp_path: Path, vcs: str) -> None:
    source = _source(tmp_path)
    project = _existing_project(tmp_path, source, vcs)

    report = adopt(project, source, source / "answers.json")

    assert report["project_only"] == [".gitignore", "notes.txt"]
    assert report["prefix_collisions"] == []
    assert not (project / ".jj").exists()


@pytest.mark.parametrize("vcs", ["none", "git", "jj"])
def test_failed_adopt_write_leaves_the_project_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, vcs: str,
) -> None:
    source = _source(tmp_path)
    project = _existing_project(tmp_path, source, vcs)
    files_before = {name: value for name, value in tree_files(project).items()}
    links_before = _snapshot_links(project)
    git_before = _git_files(project) if vcs != "none" else {}
    jj_head = JJ(project).commit_id("@") if vcs == "jj" else None

    def fail(*args: object, **kwargs: object) -> None:
        raise LocalError("forced failure after the project tree moved", 1)

    monkeypatch.setattr(manage_module, "snapshot_source", fail)
    with pytest.raises(LocalError, match="forced failure"):
        adopt(project, source, source / "answers.json", write=True, template_only_choice="keep")

    assert not (project / MARKER).exists()
    assert not (project / ".copyroom-local").exists()
    assert not (project / LOCK_FILE).exists()
    assert _snapshot_links(project) == links_before
    assert tree_files(project) == files_before
    if vcs == "none":
        assert not (project / ".jj").exists()
        assert not (project / ".git").exists()
    elif vcs == "git":
        assert not (project / ".jj").exists()
        assert not (project / ".git" / "refs" / "jj").exists()
        assert _git_files(project) == git_before
    else:
        assert (project / ".jj").is_dir()
        assert JJ(project).commit_id("@") == jj_head
        assert [item["name"] for item in JJ(project).workspaces()] == ["default"]
        marked = JJ(project).run(
            "log", "--no-graph", "-r", 'subject(glob:"copyroom:*")', "-T", "description",
        )
        assert marked.strip() == ""


def _managed_project(tmp_path: Path, source: Path) -> Path:
    project = tmp_path / "app"
    made = _run("new", str(source), str(project), "--answers", str(source / "answers.json"), cwd=tmp_path)
    assert made.returncode == 0, made.stderr
    return project


def test_update_preview_and_apply_keep_ignored_devman_links(tmp_path: Path) -> None:
    source = _source(tmp_path)
    project = _managed_project(tmp_path, source)
    _link_devman_files(project, tmp_path / "devman-store")
    before = _snapshot_links(project)
    settings = source / "templates" / "settings" / "template.j2"
    settings.write_text(settings.read_text(encoding="utf-8") + '\nrevision: "v2"\n', encoding="utf-8")
    preview = tmp_path / "preview"

    updated = _run("update", "--source", str(source), "--out", str(preview), cwd=project)
    assert updated.returncode == 0, updated.stderr
    applied = _run("update", "--apply", str(preview), cwd=project)
    assert applied.returncode == 0, applied.stderr

    assert 'revision: "v2"' in (project / "config/project.yml").read_text(encoding="utf-8")
    assert _snapshot_links(project) == before
    assert sorted(os.listdir(tmp_path / "devman-store")) == sorted(
        ["agents.txt", "agents", "claude", "devenv.local.nix"],
    )


def _overlay_into(tmp_path: Path, source: Path, output: str) -> Path:
    overlay = tmp_path / "overlay"
    shutil.copytree(source, overlay)
    manifest_path = overlay / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["templates"] = ["settings"]
    manifest["executable"] = []
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    metadata = overlay / "templates" / "settings" / "metadata.yml"
    metadata.write_text(
        metadata.read_text(encoding="utf-8").replace("config/project.yml", output),
        encoding="utf-8",
    )
    return overlay


@pytest.mark.parametrize("ignored", [True, False])
def test_render_path_under_a_symlinked_directory_is_refused(tmp_path: Path, ignored: bool) -> None:
    source = _source(tmp_path)
    project = _managed_project(tmp_path, source)
    store = tmp_path / "devman-store"
    _link_devman_files(project, store, ignore=ignored)
    (store / "vendor" / "skills").mkdir(parents=True)
    (project / "vendor").symlink_to(store / "vendor")
    if ignored:
        with (project / ".gitignore").open("a", encoding="utf-8") as handle:
            handle.write("vendor\n")
    overlay = _overlay_into(tmp_path, source, "vendor/skills/x.md")
    before = sorted(str(path.relative_to(store)) for path in store.rglob("*"))

    result = _run(
        "layer", "add", "--source", str(overlay), "--as", "skills",
        "--answers", str(overlay / "answers.json"), cwd=project,
    )

    assert result.returncode == 1, result.stderr
    assert (
        "render path vendor/skills/x.md is under symlinked directory vendor; "
        "remove it from the source"
    ) in result.stderr
    assert sorted(str(path.relative_to(store)) for path in store.rglob("*")) == before
    assert not (store / "vendor" / "skills" / "x.md").exists()


def test_working_files_lists_a_symlinked_directory_once(tmp_path: Path) -> None:
    source = _source(tmp_path)
    project = _managed_project(tmp_path, source)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "inner.txt").write_text("inner\n", encoding="utf-8")
    (project / "linked").symlink_to(outside, target_is_directory=True)

    files = working_files(project)

    assert files["linked"] == ("symlink", str(outside).encode(), 0)
    assert not [name for name in files if name.startswith("linked/")]
    assert tree_files(project)["linked"] == ("symlink", str(outside).encode(), 0)
    assert not [name for name in tree_files(project) if name.startswith("linked/")]


def test_project_view_hides_ignored_paths_with_and_without_jj(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / ".gitignore").write_text("build/\n*.log\n", encoding="utf-8")
    (plain / "build").mkdir()
    (plain / "build" / "out.bin").write_bytes(b"x")
    (plain / "run.log").write_text("log\n", encoding="utf-8")
    (plain / "keep.txt").write_text("keep\n", encoding="utf-8")

    assert project_paths(plain) == {".gitignore", "keep.txt"}
    assert set(tree_files(plain)) == {".gitignore", "build/out.bin", "run.log", "keep.txt"}

    JJ(plain).run("git", "init", "--colocate")

    assert project_paths(plain) == {".gitignore", "keep.txt"}
    assert set(working_files(plain)) == {".gitignore", "keep.txt"}


def _legacy_directory(path: Path, name: str) -> Path:
    path.mkdir()
    (path / name).write_text("{}\n", encoding="utf-8")
    return path


PROJECT_COMMANDS = [
    ["inspect"],
    ["status"],
    ["recover"],
    ["update"],
    ["apply", "--preview", "preview"],
    ["layer", "list"],
    ["layer", "add", "--source", "src", "--as", "x", "--answers", "a.json"],
    ["generate", "--source", "src", "--template", "t", "--request", "r"],
    ["refresh", "--layer", "x", "--out", "out", "--request", "r"],
]
WORKSHOP_COMMANDS = [
    ["registry", "list"],
    ["render", "t", "s"],
    ["test", "t", "s"],
    ["golden", "t", "s"],
    ["release-check", "t"],
    ["update-test", "t", "s"],
    ["template-checkout", "t"],
    ["template-test", "t"],
    ["template-discard", "t"],
    ["template-preview", "t", "--project", "p", "--out", "o"],
]
LEGACY_MARKERS = [".copier-answers.yml", ".copier-answers.extra.yml"]
LEGACY_TEXT = [
    "Convert the template to a local Templateer source",
    "Write a JSON answers file",
    "copyroom adopt SOURCE --answers FILE.json --write",
]


@pytest.mark.parametrize("marker_name", LEGACY_MARKERS)
@pytest.mark.parametrize("command", PROJECT_COMMANDS + WORKSHOP_COMMANDS, ids=" ".join)
def test_legacy_marker_refuses_every_command_with_the_real_steps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: list[str], marker_name: str,
) -> None:
    monkeypatch.chdir(_legacy_directory(tmp_path / "legacy", marker_name))

    result = runner.invoke(app, command)

    assert result.exit_code == 1, result.output
    for text in LEGACY_TEXT:
        assert text in result.stderr
    assert "Copier answers file" in result.stderr


@pytest.mark.parametrize("command", PROJECT_COMMANDS)
def test_no_project_marker_exits_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: list[str],
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)

    result = runner.invoke(app, command)

    assert result.exit_code == 2, result.output
    assert "no local CopyRoom project marker found" in result.stderr


@pytest.mark.parametrize("command", WORKSHOP_COMMANDS)
def test_no_workshop_marker_exits_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: list[str],
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)

    result = runner.invoke(app, command)

    assert result.exit_code == 2, result.output
    assert "no local workshop markers found" in result.stderr


def test_project_marker_wins_over_a_leftover_copier_answers_file(tmp_path: Path) -> None:
    source = _source(tmp_path)
    project = _managed_project(tmp_path, source)
    (project / ".copier-answers.yml").write_text("{}\n", encoding="utf-8")

    result = _run("inspect", "--json", cwd=project)

    assert result.returncode == 0, result.stderr
    assert "Convert the template" not in result.stderr


def test_legacy_repo_adopts_then_status_and_update_work(tmp_path: Path) -> None:
    source = _source(tmp_path)
    project = _existing_project(tmp_path, source, "git")
    (project / ".copier-answers.yml").write_text("_commit: v0.5.0\n", encoding="utf-8")

    refused = _run("status", cwd=project)
    assert refused.returncode == 1
    assert "copyroom adopt SOURCE --answers FILE.json --write" in refused.stderr

    adopted = _run(
        "adopt", str(source), "--answers", str(source / "answers.json"), "--write",
        "--template-only", "keep", cwd=project,
    )
    assert adopted.returncode == 0, adopted.stderr

    status = _run("status", cwd=project)
    assert status.returncode == 0, status.stderr
    settings = source / "templates" / "settings" / "template.j2"
    settings.write_text(settings.read_text(encoding="utf-8") + '\nrevision: "v2"\n', encoding="utf-8")
    preview = tmp_path / "preview"
    updated = _run("update", "--source", str(source), "--out", str(preview), cwd=project)
    assert updated.returncode == 0, updated.stderr
    applied = _run("update", "--apply", str(preview), cwd=project)
    assert applied.returncode == 0, applied.stderr
    assert 'revision: "v2"' in (project / "config/project.yml").read_text(encoding="utf-8")
