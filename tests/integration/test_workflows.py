"""End-to-end workflow tests against a real Copier template.

These drive the public workflow entry points (not just the transition tables),
which is where the bugs found in review lived. Each test maps to a review
finding and fails before its fix.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from copyroom.project.model import UpdateStatus
from copyroom.project.update import update_project
from copyroom.release.check import run_release_check
from copyroom.workshop.golden import CopyRoomError, golden_diff, refresh_golden
from copyroom.workshop.model import GoldenStatus, RenderStatus, SimStatus
from copyroom.workshop.render import render_scenario
from copyroom.workshop.simulate import run_update_simulation

from .conftest import _git, tag_v2

# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------


def test_render_completes_and_runs_checks(workshop: Path) -> None:
    render = render_scenario("demo", "basic", workshop_root=workshop)
    assert render.status == RenderStatus.complete
    out = workshop / "generated" / "demo" / "basic"
    assert (out / "README.md").read_text().startswith("# demo")


def test_render_from_subdirectory_resolves_root(workshop: Path, monkeypatch) -> None:
    """#4: workshop commands must work from any descendant, not just the root."""
    subdir = workshop / "scenarios" / "demo"
    monkeypatch.chdir(subdir)
    render = render_scenario("demo", "basic")  # workshop_root=None -> detected
    assert render.status == RenderStatus.complete


# ---------------------------------------------------------------------------
# golden  (#1)
# ---------------------------------------------------------------------------


def test_golden_refresh_then_no_diffs(workshop: Path) -> None:
    """#1: refresh_golden(workshop_root=None) used to raise TypeError."""
    render_scenario("demo", "basic", workshop_root=workshop)
    refresh_golden("demo", "basic", workshop_root=workshop)  # no TypeError
    assert (workshop / "golden" / "demo" / "basic").is_dir()

    diff = golden_diff("demo", "basic", workshop_root=workshop)
    assert diff.status == GoldenStatus.no_diffs


def test_golden_refresh_requires_render_first(workshop: Path) -> None:
    """A clean CopyRoomError (not TypeError) when nothing has been rendered."""
    with pytest.raises(CopyRoomError, match="Generated directory not found"):
        refresh_golden("demo", "basic", workshop_root=workshop)


def test_golden_detects_template_change(workshop: Path, template_repo: Path) -> None:
    render_scenario("demo", "basic", workshop_root=workshop)
    refresh_golden("demo", "basic", workshop_root=workshop)
    # Mutate the template and tag a new version — Copier renders the latest tag,
    # so the change must be tagged to show up in the next render.
    (template_repo / "README.md.jinja").write_text("# {{ project_name }} CHANGED\n")
    for args in (["add", "-A"], ["commit", "-qm", "change"], ["tag", "v2.0.0"]):
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
                       cwd=template_repo, check=True)
    diff = golden_diff("demo", "basic", workshop_root=workshop)
    assert diff.status == GoldenStatus.has_diffs
    assert "README.md" in diff.result.modified


# ---------------------------------------------------------------------------
# update simulation  (#2)
# ---------------------------------------------------------------------------


def test_update_test_without_edits_runs_update(workshop: Path, template_repo: Path) -> None:
    """#2: no edits file used to crash; the update must still actually run."""
    tag_v2(template_repo)
    sim = run_update_simulation("demo", "basic", "v1.0.0", "v2.0.0", workshop_root=workshop)
    assert sim.status == SimStatus.complete
    # The v2-only file proves `copier update` actually ran.
    assert (workshop / ".copyroom_sim" / "demo" / "basic" / "CHANGELOG.md").is_file()


def test_update_test_without_checks_reports_pass(workshop: Path, template_repo: Path) -> None:
    """A clean update with no checks configured must report check_passed=True.

    Regression: the no-checks branch left check_passed at its False default
    (seeded by reject capture), so a clean update printed "had issues".
    """
    tag_v2(template_repo)
    # Re-point the registry at the template but drop the `checks:` list.
    (workshop / "copyroom.yml").write_text(
        f"templates:\n  demo:\n    source: {template_repo}\n"
    )
    sim = run_update_simulation("demo", "basic", "v1.0.0", "v2.0.0", workshop_root=workshop)
    assert sim.status == SimStatus.complete
    assert sim.result is not None
    assert sim.result.check_passed is True
    assert sim.result.conflicts == set()
    assert sim.result.rejects == set()


def test_update_test_with_edits(workshop: Path, template_repo: Path) -> None:
    """#2: the user_edited branch with a real edits file."""
    tag_v2(template_repo)
    edits = workshop / "scenarios" / "demo" / "basic-edits.yml"
    edits.write_text(
        "edits:\n"
        "  - file: README.md\n"
        "    action: append\n"
        '    content: "Local edit."\n'
    )
    sim = run_update_simulation("demo", "basic", "v1.0.0", "v2.0.0", workshop_root=workshop)
    assert sim.status == SimStatus.complete
    work = workshop / ".copyroom_sim" / "demo" / "basic"
    assert (work / "CHANGELOG.md").is_file()
    assert "Local edit." in (work / "README.md").read_text()


# ---------------------------------------------------------------------------
# release check  (#5)
# ---------------------------------------------------------------------------


def test_release_check_passes_on_clean_workshop(git_workshop: Path) -> None:
    # Establish a golden baseline and commit it so the tree is clean.
    render_scenario("demo", "basic", workshop_root=git_workshop)
    refresh_golden("demo", "basic", workshop_root=git_workshop)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "add", "-A"], cwd=git_workshop, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "golden"], cwd=git_workshop, check=True)

    check = run_release_check("demo", workshop_root=git_workshop)
    assert check.matrix_passed
    assert check.golden_ok
    assert check.worktree_clean  # #5: render output must not dirty the tree


def test_release_check_worktree_stays_clean_across_runs(git_workshop: Path) -> None:
    """#5: re-running must not flip worktree_clean to False via generated/."""
    c1 = run_release_check("demo", workshop_root=git_workshop)
    assert c1.worktree_clean
    c2 = run_release_check("demo", workshop_root=git_workshop)
    assert c2.worktree_clean


def test_release_check_renders_each_scenario_once(workshop: Path, monkeypatch) -> None:
    """The matrix render output is reused for golden — no second Copier render.

    Both the matrix render and (previously) the golden re-render funnel through
    ``render.copier_copy``; counting it proves the redundant render is gone.
    """
    import copyroom.workshop.render as render_mod

    real_copy = render_mod.copier_copy
    count = 0

    def counting_copy(*args, **kwargs):
        nonlocal count
        count += 1
        return real_copy(*args, **kwargs)

    monkeypatch.setattr(render_mod, "copier_copy", counting_copy)
    run_release_check("demo", workshop_root=workshop)
    # One scenario ("basic") → exactly one Copier render, not two.
    assert count == 1


def test_release_check_non_git_workshop_reports_na(workshop: Path) -> None:
    """A workshop that isn't under git reports worktree N/A, not a false CLEAN."""
    from copyroom.release.check import format_release_report

    check = run_release_check("demo", workshop_root=workshop)  # no git init
    assert check.worktree_is_git is False
    report = format_release_report(check)
    assert "N/A (not a git repository" in report
    assert "✅ CLEAN" not in report


# ---------------------------------------------------------------------------
# golden snapshot portability
# ---------------------------------------------------------------------------


def test_golden_ignores_copier_answers_file(
    workshop: Path, template_repo: Path, tmp_path: Path
) -> None:
    """Golden must be stable when the template lives at a different path.

    Copier records an absolute ``_src_path`` in ``.copier-answers.yml``. If that
    file were part of the snapshot, a different checkout/machine would show a
    spurious diff. The answers file is excluded, so the diff stays clean.
    """
    render_scenario("demo", "basic", workshop_root=workshop)
    refresh_golden("demo", "basic", workshop_root=workshop)

    # Simulate "another machine": same template content, different absolute path.
    moved = tmp_path / "relocated-template"
    shutil.copytree(template_repo, moved)
    (workshop / "copyroom.yml").write_text(
        f"templates:\n  demo:\n    source: {moved}\n"
    )

    diff = golden_diff("demo", "basic", workshop_root=workshop)
    assert diff.status == GoldenStatus.no_diffs, (
        diff.result.modified, diff.result.added, diff.result.removed,
    )


# ---------------------------------------------------------------------------
# project update  (previously untested end-to-end)
# ---------------------------------------------------------------------------


def test_update_project_applies_new_version(template_repo: Path, tmp_path: Path) -> None:
    """`copyroom update` pulls a tagged template change into a clean project."""
    from copyroom._compat.copier import copier_copy

    # Generate a project from v1.0.0 (the only tag at fixture time).
    proj = tmp_path / "proj"
    result = copier_copy(str(template_repo), proj)
    assert result.returncode == 0, result.stderr
    assert not (proj / "CHANGELOG.md").exists()

    # A clean git worktree is a precondition for `copier update`.
    _git("init", cwd=proj)
    _git("add", "-A", cwd=proj)
    _git("commit", "-qm", "generated", cwd=proj)

    # Publish a new template version, then update the project to it.
    tag_v2(template_repo)
    update = update_project(project_root=proj, target_ref="v2.0.0")

    assert update.status == UpdateStatus.complete, update.status
    assert (proj / "CHANGELOG.md").is_file()  # v2-only file proves the update ran


def test_update_project_resolves_latest_tag(template_repo: Path, tmp_path: Path) -> None:
    """A no-ref `copyroom update` resolves and applies the latest semver tag."""
    from copyroom._compat.copier import copier_copy

    proj = tmp_path / "proj"
    assert copier_copy(str(template_repo), proj).returncode == 0
    assert not (proj / "CHANGELOG.md").exists()
    _git("init", cwd=proj)
    _git("add", "-A", cwd=proj)
    _git("commit", "-qm", "generated", cwd=proj)

    tag_v2(template_repo)  # publish v2.0.0 (now the latest)
    update = update_project(project_root=proj, target_ref=None)  # no explicit ref

    assert update.status == UpdateStatus.complete, update.status
    assert update.target_ref == "v2.0.0"
    assert update.resolved_latest is True
    assert (proj / "CHANGELOG.md").is_file()  # v2-only file proves the update ran


def test_update_project_no_ref_already_at_latest_is_clean_noop(
    template_repo: Path, tmp_path: Path
) -> None:
    """When already on the latest tag, a no-ref update is a clean no-op.

    #P1-2: a no-op is a *success* terminal (up_to_date), not a failure, so the
    CLI can exit 0 in a Makefile/CI loop.
    """
    from copyroom._compat.copier import copier_copy

    # The project is generated from v1.0.0, which is also the latest tag.
    proj = tmp_path / "proj"
    assert copier_copy(str(template_repo), proj).returncode == 0
    _git("init", cwd=proj)
    _git("add", "-A", cwd=proj)
    _git("commit", "-qm", "generated", cwd=proj)

    update = update_project(project_root=proj, target_ref=None)

    assert update.status == UpdateStatus.up_to_date
    assert update.resolved_latest is True
    assert update.previous_ref == update.target_ref == "v1.0.0"


def test_update_project_captures_inline_conflict(template_repo: Path, tmp_path: Path) -> None:
    """#P2-1: an inline-marker conflict from `copier update` is reported.

    The old stdout grep missed inline `<<<<<<<` markers Copier writes silently;
    the shared scan over the post-update dirty files catches them.
    """
    from copyroom._compat.copier import copier_copy

    proj = tmp_path / "proj"
    assert copier_copy(str(template_repo), proj).returncode == 0
    _git("init", cwd=proj)
    _git("add", "-A", cwd=proj)
    # Commit a local change to README on the line the template will rewrite in v2.
    (proj / "README.md").write_text("# demo\n\nLOCAL EDIT on the shared line.\n")
    _git("add", "-A", cwd=proj)
    _git("commit", "-qm", "generated + local edit", cwd=proj)

    # Publish a v2 that changes the same README line → 3-way merge conflict.
    (template_repo / "README.md.jinja").write_text(
        "# {{ project_name }}\n\nTEMPLATE V2 on the shared line.\n"
    )
    _git("add", "-A", cwd=template_repo)
    _git("commit", "-qm", "v2", cwd=template_repo)
    _git("tag", "v2.0.0", cwd=template_repo)

    update = update_project(project_root=proj, target_ref="v2.0.0")

    # The clash surfaces as a reported conflict and/or a reject.
    assert update.conflicts or update.rejects


def test_update_project_rejects_dirty_worktree(template_repo: Path, tmp_path: Path) -> None:
    """An uncommitted change blocks the update (RejectDirtyWorktree)."""
    from copyroom._compat.copier import copier_copy

    proj = tmp_path / "proj"
    assert copier_copy(str(template_repo), proj).returncode == 0
    _git("init", cwd=proj)
    _git("add", "-A", cwd=proj)
    _git("commit", "-qm", "generated", cwd=proj)
    (proj / "README.md").write_text("locally modified\n")  # dirty

    tag_v2(template_repo)
    update = update_project(project_root=proj, target_ref="v2.0.0")

    assert update.status == UpdateStatus.failed


def test_update_project_post_tag_commit_is_clean_noop(
    template_repo: Path, tmp_path: Path
) -> None:
    """#P1-2: a project generated at a *post-tag* commit records a describe-form
    `_commit` (vX.Y.Z-N-gsha). A no-arg update to that same latest tag must read
    as a clean no-op, not re-run copier against the version it's already on."""
    from copyroom._compat.copier import copier_copy

    # Add a commit AFTER v1.0.0 (no new tag), so HEAD describes as v1.0.0-1-gsha.
    (template_repo / "EXTRA.md").write_text("post-tag commit\n")
    _git("add", "-A", cwd=template_repo)
    _git("commit", "-qm", "post-tag", cwd=template_repo)

    # Generate from that post-tag commit (vcs_ref=HEAD), not the bare tag.
    proj = tmp_path / "proj"
    assert copier_copy(str(template_repo), proj, vcs_ref="HEAD").returncode == 0
    _git("init", cwd=proj)
    _git("add", "-A", cwd=proj)
    _git("commit", "-qm", "generated", cwd=proj)

    answers = (proj / ".copier-answers.yml").read_text()
    assert "v1.0.0-1-g" in answers, answers  # sanity: it really is describe-form

    update = update_project(project_root=proj, target_ref=None)

    assert update.status == UpdateStatus.up_to_date  # no-op (success terminal)
    assert update.target_ref == "v1.0.0"
    assert update.resolved_latest is True


def test_update_project_divergent_config_still_runs_hooks(
    template_repo: Path, tmp_path: Path
) -> None:
    """#P1-1/#P2-7: a copyroom.project.yml with an invalid *known* field (a future
    `kind`) must not abort the update, and its configured post-update hook must
    still run (not be silently skipped)."""
    from copyroom._compat.copier import copier_copy

    proj = tmp_path / "proj"
    assert copier_copy(str(template_repo), proj).returncode == 0

    # A schema-divergent but readable config, plus a real post-update hook.
    (proj / "copyroom.project.yml").write_text(
        "project:\n"
        "  kind: library\n"            # not a value this CLI's old enum knew
        "commands:\n"
        "  post_template_update:\n"
        "    - touch HOOK_RAN\n"
    )
    _git("init", cwd=proj)
    _git("add", "-A", cwd=proj)
    _git("commit", "-qm", "generated", cwd=proj)

    tag_v2(template_repo)
    update = update_project(project_root=proj, target_ref="v2.0.0", trust=True)

    assert update.status == UpdateStatus.complete, update.status
    assert (proj / "CHANGELOG.md").is_file()       # the update actually ran
    assert (proj / "HOOK_RAN").is_file()            # the hook was NOT skipped


def test_resolve_latest_ref_no_src_path_transitions_failed(tmp_path: Path) -> None:
    """#P2-8: when latest-ref resolution can't proceed (no recorded _src_path),
    the entity must be transitioned to `failed` before the CopyRoomError is
    raised — so a non-CLI caller never sees a non-terminal entity for a run that
    didn't complete."""
    from copyroom.project.model import TemplateUpdate, UpdateStatus
    from copyroom.project.update import resolve_latest_ref

    update = TemplateUpdate(
        project_root=tmp_path,
        template_id="demo",
        previous_ref="v1.0.0",
        target_ref=None,            # no-arg update -> must resolve
        status=UpdateStatus.config_loaded,
    )
    update.template_source = None   # nothing for the resolver to read

    with pytest.raises(CopyRoomError):
        resolve_latest_ref(update)

    assert update.status == UpdateStatus.failed
