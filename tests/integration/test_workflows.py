"""End-to-end workflow tests against a real Copier template.

These drive the public workflow entry points (not just the transition tables),
which is where the bugs found in review lived. Each test maps to a review
finding and fails before its fix.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from copyroom.release.check import run_release_check
from copyroom.workshop.golden import CopyRoomError, golden_diff, refresh_golden
from copyroom.workshop.model import GoldenStatus, RenderStatus, SimStatus
from copyroom.workshop.render import render_scenario
from copyroom.workshop.simulate import run_update_simulation

from .conftest import tag_v2

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
