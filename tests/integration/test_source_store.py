"""A project keeps its source in private Git refs, not in the working tree."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from copyroom.local.composer import digest_source
from copyroom.local.jj import JJ
from copyroom.local.source import LEGACY_SOURCE_DIR
from copyroom.local.store import (
    git_directory,
    materialise,
    restore_stored,
    source_ref,
    store_source,
    write_tree_objects,
)

from .test_versioned_sources import (  # noqa: F401  (fixtures)
    SOURCE_FIXTURE,
    Repo,
    _commit,
    _converge,
    _git,
    _invoke,
    _json,
    _marker,
    _new,
    _ok,
    _settings_text,
    no_leaked_sources,
)

REF_PREFIX = "refs/copyroom/sources/"


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    return Repo(tmp_path / "template-repo")


def _layer_records(project: Path) -> dict[str, dict]:
    return _marker(project)["layers"]


def _assert_private_store(project: Path, tmp_path: Path) -> None:
    """No source copy sits in the tree. Each recorded digest has a matching ref."""

    tracked = JJ(project).tracked_paths("@")
    assert not [name for name in tracked if name.startswith(".copyroom-local/sources")]
    assert not (project / LEGACY_SOURCE_DIR).exists()
    for name, record in _layer_records(project).items():
        digest = record["source_digest"]
        tree = _git("rev-parse", "--verify", f"{REF_PREFIX}{digest}^{{tree}}", cwd=project)
        assert len(tree) == 40, name
        stored = tmp_path / f"stored-{name}"
        assert restore_stored(project, digest, stored)
        assert digest_source(stored) == digest


def _answers(repo: Repo, tmp_path: Path, description: str) -> Path:
    answers = json.loads(repo.answers.read_text(encoding="utf-8"))
    answers["description"] = description
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(answers), encoding="utf-8")
    return changed


def _update(project: Path, tmp_path: Path, *args: str) -> object:
    out = tmp_path / f"try-{len(list(tmp_path.glob('try-*')))}"
    return _invoke("update", "--json", "--out", str(out), *args, cwd=project)


def _bookmarks(jj: JJ) -> list[str]:
    """List the names of all bookmarks, local and remote."""

    return jj.run("bookmark", "list", "--all", "-T", 'name ++ "\\n"').split()


def _visible(project: Path) -> set[str]:
    out = JJ(project).run("log", "--no-graph", "-r", "all()", "-T", 'commit_id ++ "\\n"')
    return set(out.split())


# -- no copy in the tree ---------------------------------------------------------------


def test_new_leaves_no_source_copy_in_the_tree(repo: Repo, tmp_path: Path) -> None:
    project = _new(repo, tmp_path, "v1")

    _assert_private_store(project, tmp_path)


def test_new_from_a_path_leaves_no_source_copy_in_the_tree(repo: Repo, tmp_path: Path) -> None:
    project = tmp_path / "project"
    _ok("new", str(repo.source), str(project), "--answers", str(repo.answers))

    _assert_private_store(project, tmp_path)


def test_adopt_write_leaves_no_source_copy_in_the_tree(repo: Repo, tmp_path: Path) -> None:
    from copyroom.local.composer import compose
    from copyroom.local.workflow import write_tree

    project = tmp_path / "existing"
    project.mkdir()
    plan = compose(repo.source, json.loads(repo.answers.read_text("utf-8")))
    write_tree(project, plan.files)
    _git("init", "-q", "-b", "main", cwd=project)
    _commit(project, "init")

    _ok(
        "adopt", str(repo.source), "--answers", str(repo.answers), "--project", str(project),
        "--write",
    )

    _assert_private_store(project, tmp_path)


def test_update_apply_leaves_no_source_copy_in_the_tree(repo: Repo, tmp_path: Path) -> None:
    project = _new(repo, tmp_path, "v1")

    _converge(project, tmp_path, "--ref", "v2")

    _assert_private_store(project, tmp_path)
    assert len(_layer_records(project)) == 1


def test_layer_add_leaves_no_source_copy_in_the_tree(repo: Repo, tmp_path: Path) -> None:
    project = _new(repo, tmp_path, "v1")

    _ok(
        "layer", "add", "--source", str(repo.overlay), "--ref", "v1", "--answers",
        str(repo.answers), "--as", "extra", cwd=project,
    )

    _assert_private_store(project, tmp_path)
    assert set(_layer_records(project)) == {"base", "extra"}


# -- read precedence -------------------------------------------------------------------


def test_pinned_layer_survives_a_deleted_template_repository(repo: Repo, tmp_path: Path) -> None:
    project = _new(repo, tmp_path, "v1")
    shutil.rmtree(repo.root)

    _converge(project, tmp_path, "--answers", str(_answers(repo, tmp_path, "From the ref")))

    assert "From the ref" in _settings_text(project)
    assert "wip" not in _settings_text(project)
    assert _marker(project)["source"] == str(repo.source)
    _assert_private_store(project, tmp_path)


def test_pinned_layer_without_repository_and_ref_exits_with_two(
    repo: Repo, tmp_path: Path,
) -> None:
    project = _new(repo, tmp_path, "v1")
    digest = _marker(project)["source_digest"]
    shutil.rmtree(repo.root)
    _git("update-ref", "-d", REF_PREFIX + digest, cwd=project)

    result = _update(project, tmp_path)

    assert result.exit_code == 2  # type: ignore[attr-defined]
    message = " ".join(result.stderr.split())  # type: ignore[attr-defined]
    assert "no stored copy" in message
    assert "fetch the template repository" in message
    assert "--source PATH --ref REF" in message


def _write_empty_tree_ref(project: Path, digest: str) -> None:
    empty = subprocess.run(
        ["git", "hash-object", "-t", "tree", "-w", "--stdin"], cwd=project, input="",
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    _git("update-ref", REF_PREFIX + digest, empty, cwd=project)


def test_pinned_layer_prefers_the_pinned_commit_over_the_ref(repo: Repo, tmp_path: Path) -> None:
    project = _new(repo, tmp_path, "v1")
    # A damaged ref must not matter while the commit is readable.
    _write_empty_tree_ref(project, _marker(project)["source_digest"])

    assert _converge(project, tmp_path)["result"] == "no-change"


def test_a_ref_with_the_wrong_tree_is_not_used(repo: Repo, tmp_path: Path) -> None:
    project = _new(repo, tmp_path, "v1")
    _write_empty_tree_ref(project, _marker(project)["source_digest"])
    shutil.rmtree(repo.root)

    result = _update(project, tmp_path)

    assert result.exit_code == 2  # type: ignore[attr-defined]


def test_path_layer_follows_a_changed_path_and_falls_back_to_the_ref(
    repo: Repo, tmp_path: Path,
) -> None:
    source = tmp_path / "path-source"
    shutil.copytree(SOURCE_FIXTURE, source)
    project = tmp_path / "project"
    _ok("new", str(source), str(project), "--answers", str(repo.answers))
    old_digest = _marker(project)["source_digest"]

    # A changed path is the new template. The update converges as before.
    template = source / "templates/settings/template.j2"
    template.write_text(template.read_text(encoding="utf-8") + 'revision: "next"\n', "utf-8")
    _converge(project, tmp_path)
    assert 'revision: "next"' in _settings_text(project)
    new_digest = _marker(project)["source_digest"]
    assert new_digest != old_digest
    _assert_private_store(project, tmp_path)
    # Both versions stay in the private store.
    assert _git("rev-parse", "--verify", REF_PREFIX + old_digest, cwd=project)

    # A removed path falls back to the recorded digest.
    shutil.rmtree(source)
    _converge(project, tmp_path, "--answers", str(_answers(repo, tmp_path, "Without the path")))

    assert "Without the path" in _settings_text(project)
    assert 'revision: "next"' in _settings_text(project)
    assert _marker(project)["source"] == str(source)


def test_an_update_heals_a_damaged_ref(repo: Repo, tmp_path: Path) -> None:
    source = tmp_path / "path-source"
    shutil.copytree(SOURCE_FIXTURE, source)
    project = tmp_path / "project"
    _ok("new", str(source), str(project), "--answers", str(repo.answers))
    _write_empty_tree_ref(project, _marker(project)["source_digest"])

    _converge(project, tmp_path, "--answers", str(_answers(repo, tmp_path, "Healed")))

    _assert_private_store(project, tmp_path)


def test_path_layer_without_path_and_ref_exits_with_two(repo: Repo, tmp_path: Path) -> None:
    source = tmp_path / "path-source"
    shutil.copytree(SOURCE_FIXTURE, source)
    project = tmp_path / "project"
    _ok("new", str(source), str(project), "--answers", str(repo.answers))
    shutil.rmtree(source)
    _git("update-ref", "-d", REF_PREFIX + _marker(project)["source_digest"], cwd=project)

    result = _update(project, tmp_path)

    assert result.exit_code == 2  # type: ignore[attr-defined]
    message = " ".join(result.stderr.split())  # type: ignore[attr-defined]
    assert "no stored copy" in message
    assert "update --source PATH" in message


# -- the object round trip -------------------------------------------------------------


def test_modes_and_symlinks_survive_the_round_trip(tmp_path: Path) -> None:
    git = tmp_path / "git"
    subprocess.run(["git", "init", "-q", "--bare", str(git)], check=True)
    source = tmp_path / "source"
    (source / "deep/er").mkdir(parents=True)
    (source / "run.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (source / "run.sh").chmod(0o755)
    (source / "deep/er/plain.txt").write_text("plain\n", encoding="utf-8")
    (source / "deep/er/plain.txt").chmod(0o644)
    (source / "name with space.txt").write_text("space\n", encoding="utf-8")
    (source / "deep/link").symlink_to("er/plain.txt")

    tree = write_tree_objects(git, source)
    destination = tmp_path / "restored"
    materialise(git, tree, "", destination)

    assert (destination / "run.sh").stat().st_mode & 0o777 == 0o755
    assert (destination / "deep/er/plain.txt").stat().st_mode & 0o777 == 0o644
    assert (destination / "name with space.txt").read_text("utf-8") == "space\n"
    assert (destination / "deep/link").is_symlink()
    assert os.readlink(destination / "deep/link") == "er/plain.txt"


def test_a_stored_source_keeps_its_digest_and_executable_bit(
    repo: Repo, tmp_path: Path,
) -> None:
    source = tmp_path / "path-source"
    shutil.copytree(SOURCE_FIXTURE, source)
    # Git keeps only the executable bit. The digest must ignore other bits.
    plain = source / "templates/settings/template.j2"
    plain.chmod(0o664)
    executable = next(path for path in source.rglob("*") if path.is_file() and path.name != plain.name)
    executable.chmod(0o750)
    project = tmp_path / "project"
    _ok("new", str(source), str(project), "--answers", str(repo.answers))
    digest = _marker(project)["source_digest"]
    assert digest == digest_source(source)

    stored = tmp_path / "stored"
    assert restore_stored(project, digest, stored)

    assert (stored / plain.relative_to(source)).stat().st_mode & 0o777 == 0o644
    assert (stored / executable.relative_to(source)).stat().st_mode & 0o777 == 0o755


def test_store_source_refuses_a_changed_source(repo: Repo, tmp_path: Path) -> None:
    project = _new(repo, tmp_path, "v1")
    from copyroom.local.errors import LocalError

    with pytest.raises(LocalError) as caught:
        store_source(project, repo.source, "0" * 64)

    assert caught.value.code == 1


# -- jj, push, and gc ------------------------------------------------------------------


def test_jj_shows_no_private_ref_and_a_push_does_not_send_it(repo: Repo, tmp_path: Path) -> None:
    project = _new(repo, tmp_path, "v1")
    digest = _marker(project)["source_digest"]
    jj = JJ(project)

    assert _bookmarks(jj) == []
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    jj.run("git", "remote", "add", "origin", str(remote))
    jj.run("bookmark", "create", "main", "-r", "@-")
    jj.run("git", "push", "--bookmark", "main")
    _git("push", "origin", "--all", cwd=project)
    _git("push", "origin", "--tags", cwd=project)

    sent = _git("for-each-ref", cwd=remote)
    assert "refs/heads/main" in sent
    assert "copyroom" not in sent
    assert set(_bookmarks(jj)) == {"main"}
    assert _git("rev-parse", "--verify", REF_PREFIX + digest, cwd=project)


def test_garbage_collection_keeps_the_stored_source(repo: Repo, tmp_path: Path) -> None:
    project = _new(repo, tmp_path, "v1")
    digest = _marker(project)["source_digest"]

    _git("gc", "--prune=now", "--aggressive", cwd=project)
    JJ(project).run("util", "gc", "--expire", "now")

    stored = tmp_path / "stored"
    assert restore_stored(project, digest, stored)
    assert git_directory(project).is_dir()
    assert source_ref(digest) == REF_PREFIX + digest


# -- a project from an older CopyRoom --------------------------------------------------


def _legacy_project(repo: Repo, tmp_path: Path) -> Path:
    """Build a project that tracks a source copy in the tree, as before 0.8.4."""

    project = _new(repo, tmp_path, "v1")
    digest = _marker(project)["source_digest"]
    copy = project / LEGACY_SOURCE_DIR / digest
    shutil.copytree(SOURCE_FIXTURE, copy)
    JJ(project).run("commit", "-m", "copyroom:source snapshot (legacy)")
    assert any(name.startswith(LEGACY_SOURCE_DIR) for name in JJ(project).tracked_paths("@-"))
    return project


def test_next_update_removes_a_tracked_source_copy(repo: Repo, tmp_path: Path) -> None:
    project = _legacy_project(repo, tmp_path)

    out = tmp_path / "preview"
    # The source did not change. The copy alone makes the update worth a preview.
    report = _json(_ok("update", "--json", "--out", str(out), cwd=project))

    assert report.get("result") != "no-change"
    assert not (out / LEGACY_SOURCE_DIR).exists()
    assert (project / LEGACY_SOURCE_DIR).exists()
    _ok("update", "--apply", str(out), cwd=project)
    _assert_private_store(project, tmp_path)
    assert _converge(project, tmp_path)["result"] == "no-change"


def test_layer_add_removes_a_tracked_source_copy(repo: Repo, tmp_path: Path) -> None:
    project = _legacy_project(repo, tmp_path)

    _ok(
        "layer", "add", "--source", str(repo.overlay), "--ref", "v1", "--answers",
        str(repo.answers), "--as", "extra", cwd=project,
    )

    _assert_private_store(project, tmp_path)


# -- discard ---------------------------------------------------------------------------


def test_discard_leaves_no_preview_commit_visible(repo: Repo, tmp_path: Path) -> None:
    project = _new(repo, tmp_path, "v1")
    before = _visible(project)
    out = tmp_path / "preview"

    _ok("update", "--json", "--out", str(out), "--ref", "v2", cwd=project)
    assert _visible(project) != before
    _ok("discard", "--preview", str(out), cwd=project)

    assert _visible(project) == before
    log = JJ(project).run("log", "--no-graph", "-r", "all()", "-T", 'description.first_line() ++ "\\n"')
    assert "copyroom:preview" not in log


def test_discard_abandons_a_conflicted_preview(repo: Repo, tmp_path: Path) -> None:
    project = _new(repo, tmp_path, "v1")
    local = project / "config/project.yml"
    local.write_text(local.read_text(encoding="utf-8") + "local: edit\n", encoding="utf-8")
    JJ(project).run("commit", "-m", "local edit")
    before = _visible(project)
    out = tmp_path / "preview"

    result = _invoke("update", "--json", "--out", str(out), "--ref", "v2", cwd=project)
    assert result.exit_code == 1  # a conflict is a finding
    assert _json(result)["conflicts"]
    assert JJ(project).run("log", "--no-graph", "-r", "conflicts()", "-T", "commit_id")
    _ok("discard", "--preview", str(out), cwd=project)

    assert _visible(project) == before
    assert JJ(project).run("log", "--no-graph", "-r", "conflicts()", "-T", "commit_id") == ""
