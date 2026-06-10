"""End-to-end tests for the template-edit workflow.

These drive the public entry points (checkout / validate / preview) against a
real Copier template + generated project, asserting the headline guarantees:
the agent edits an isolated worktree, and the preview shows what the project
would receive on update **without touching the real project tree**.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from copyroom._compat import gitutil
from copyroom._compat.copier import copier_copy
from copyroom.template.model import CheckoutStatus, PreviewStatus
from copyroom.template.preview import run_preview
from copyroom.template.validate import validate_template
from copyroom.template.workspace import (
    CopyRoomError,
    checkout_template,
    discard_template_edit,
)


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path: Path, monkeypatch) -> None:
    """Keep template clones/worktrees out of the real user cache."""
    monkeypatch.setenv("COPYROOM_CACHE_DIR", str(tmp_path / "cr-cache"))


def _project(template_repo: Path, dest: Path) -> Path:
    """Generate a project from *template_repo* (renders its latest tag, v1.0.0)."""
    result = copier_copy(str(template_repo), dest)
    assert result.returncode == 0, result.stderr
    return dest


# ---------------------------------------------------------------------------
# checkout
# ---------------------------------------------------------------------------


def test_checkout_local_creates_isolated_worktree(template_repo: Path, tmp_path: Path) -> None:
    proj = _project(template_repo, tmp_path / "proj")
    before = gitutil.default_branch(template_repo)

    checkout = checkout_template(project_root=proj)

    assert checkout.status == CheckoutStatus.worktree_ready
    assert checkout.worktree_dir is not None and checkout.worktree_dir.is_dir()
    assert gitutil.is_git_repo(checkout.worktree_dir)
    assert checkout.branch and checkout.branch.startswith("copyroom/edit/")
    # The template's own checkout is untouched (worktree is elsewhere, same branch).
    assert checkout.worktree_dir != template_repo
    assert gitutil.default_branch(template_repo) == before


def test_checkout_is_idempotent(template_repo: Path, tmp_path: Path) -> None:
    proj = _project(template_repo, tmp_path / "proj")
    first = checkout_template(project_root=proj)
    # An edit made in the worktree survives a second checkout (same worktree reused).
    (first.worktree_dir / "MARKER").write_text("x\n")
    second = checkout_template(project_root=proj)
    assert second.worktree_dir == first.worktree_dir
    assert (second.worktree_dir / "MARKER").is_file()


def test_checkout_warns_on_reused_branch_with_commits(
    template_repo: Path, tmp_path: Path
) -> None:
    """#P2-4: a second checkout after a committed edit surfaces the pending commits."""
    proj = _project(template_repo, tmp_path / "proj")
    first = checkout_template(project_root=proj)
    assert first.reused_commits == 0  # fresh branch
    # Commit an edit onto the edit branch, then check out again.
    (first.worktree_dir / "NEWFILE").write_text("leftover\n")
    assert gitutil.commit_all(first.worktree_dir, "abandoned edit")

    second = checkout_template(project_root=proj)
    assert second.reused_commits >= 1


def test_discard_resets_edit_branch(template_repo: Path, tmp_path: Path) -> None:
    """#P2-4: template-discard removes the worktree + branch; the next checkout is fresh."""
    proj = _project(template_repo, tmp_path / "proj")
    first = checkout_template(project_root=proj)
    (first.worktree_dir / "NEWFILE").write_text("leftover\n")
    assert gitutil.commit_all(first.worktree_dir, "abandoned edit")

    worktree = discard_template_edit(project_root=proj)
    assert worktree is not None
    assert not worktree.is_dir()  # worktree removed

    # A subsequent checkout starts fresh from the base (0 commits ahead).
    third = checkout_template(project_root=proj)
    assert third.reused_commits == 0


def test_discard_missing_worktree_is_noop(template_repo: Path, tmp_path: Path) -> None:
    """Discarding when nothing has been checked out is a friendly no-op."""
    proj = _project(template_repo, tmp_path / "proj")
    assert discard_template_edit(project_root=proj) is None


def test_checkout_clones_remote_source(template_repo: Path, tmp_path: Path) -> None:
    proj = _project(template_repo, tmp_path / "proj")
    # Rewrite the recorded source to a remote-style URL so checkout must clone.
    answers = proj / ".copier-answers.yml"
    answers.write_text(
        answers.read_text().replace(str(template_repo), f"file://{template_repo}")
    )

    checkout = checkout_template(project_root=proj)

    assert checkout.status == CheckoutStatus.worktree_ready
    assert checkout.repo_dir is not None and checkout.repo_dir.is_dir()
    assert checkout.repo_dir != template_repo  # cloned into the cache, not the original
    assert gitutil.is_git_repo(checkout.repo_dir)


def test_checkout_rejects_non_project(tmp_path: Path) -> None:
    with pytest.raises(CopyRoomError, match="copier-answers"):
        checkout_template(project_root=tmp_path)


# ---------------------------------------------------------------------------
# validate (template-test)
# ---------------------------------------------------------------------------


def test_validate_passes_for_clean_edit(template_repo: Path, tmp_path: Path) -> None:
    proj = _project(template_repo, tmp_path / "proj")
    checkout = checkout_template(project_root=proj)
    (checkout.worktree_dir / "CHANGELOG.md.jinja").write_text("# {{ project_name }}\n")

    result = validate_template(project_root=proj)

    assert result.ok, result.messages


def test_validate_detects_broken_template(template_repo: Path, tmp_path: Path) -> None:
    proj = _project(template_repo, tmp_path / "proj")
    checkout = checkout_template(project_root=proj)
    # Unterminated Jinja → Copier render failure.
    (checkout.worktree_dir / "README.md.jinja").write_text("{{ project_name \n")

    result = validate_template(project_root=proj)

    assert not result.ok
    assert any("render" in m.lower() or "clean" in m.lower() for m in result.messages)


# ---------------------------------------------------------------------------
# preview (template-preview)
# ---------------------------------------------------------------------------


def test_preview_shows_new_file_and_leaves_project_untouched(
    template_repo: Path, tmp_path: Path
) -> None:
    proj = _project(template_repo, tmp_path / "proj")
    checkout = checkout_template(project_root=proj)
    (checkout.worktree_dir / "CHANGELOG.md.jinja").write_text(
        "# Changelog for {{ project_name }}\n"
    )

    preview = run_preview(project_root=proj)

    assert preview.status == PreviewStatus.complete
    assert preview.result is not None
    assert "CHANGELOG.md" in preview.result.added
    # The real project tree is never modified.
    assert not (proj / "CHANGELOG.md").exists()
    # A reviewable patch is written and mentions the change.
    patch = Path(preview.result.patch_path).read_text()
    assert "CHANGELOG.md" in patch


def test_preview_is_relative_to_local_working_state(
    template_repo: Path, tmp_path: Path
) -> None:
    """The user's own files are the baseline — the update neither adds nor removes them."""
    proj = _project(template_repo, tmp_path / "proj")
    (proj / "MY_LOCAL.txt").write_text("my own work\n")
    checkout = checkout_template(project_root=proj)
    (checkout.worktree_dir / "CHANGELOG.md.jinja").write_text("# {{ project_name }}\n")

    preview = run_preview(project_root=proj)

    assert preview.result is not None
    assert "CHANGELOG.md" in preview.result.added
    assert "MY_LOCAL.txt" not in preview.result.added
    assert "MY_LOCAL.txt" not in preview.result.removed
    assert (proj / "MY_LOCAL.txt").read_text() == "my own work\n"  # untouched


def test_preview_reports_collision_with_local_edit(
    template_repo: Path, tmp_path: Path
) -> None:
    proj = _project(template_repo, tmp_path / "proj")
    # User edits the generated README on the same line the template will change.
    (proj / "README.md").write_text(
        "# demo\n\nGenerated by the CopyRoom integration test template (LOCAL EDIT).\n"
    )
    checkout = checkout_template(project_root=proj)
    (checkout.worktree_dir / "README.md.jinja").write_text(
        "# {{ project_name }}\n\nGenerated by the CopyRoom integration test template (v2 TEMPLATE).\n"
    )

    preview = run_preview(project_root=proj)

    assert preview.status == PreviewStatus.complete
    assert preview.result is not None
    # The clash surfaces as a reject and/or a reported conflict.
    assert preview.result.rejects or preview.result.conflicts
