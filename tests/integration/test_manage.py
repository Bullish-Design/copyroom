"""End-to-end tests for the repo-adoption / templatization workflow.

These drive the public entry points (``templatize`` / ``adopt``) against real
Copier renders, asserting the headline guarantees: a verbatim template repo
converges its golden immediately, parameterization preserves the match, and
adoption links a repo without ever touching its files.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from copyroom.manage.adopt import CopyRoomError, adopt
from copyroom.manage.model import AdoptionStatus, TemplatizationStatus
from copyroom.manage.templatize import templatize
from copyroom.session.detector import detect_mode
from copyroom.workshop.golden import golden_diff
from copyroom.workshop.model import GoldenStatus, RenderStatus
from copyroom.workshop.render import render_scenario


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path: Path, monkeypatch) -> None:
    """Keep template clones out of the real user cache."""
    monkeypatch.setenv("COPYROOM_CACHE_DIR", str(tmp_path / "cr-cache"))


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=cwd, check=True, capture_output=True, text=True,
    )


def _make_repo(root: Path) -> Path:
    """A tiny hand-written repo named after *root*."""
    root.mkdir(parents=True)
    (root / "README.md").write_text(f"# {root.name}\n\nHello from {root.name}.\n")
    (root / "app.py").write_text('def main():\n    print("hi")\n')
    (root / "sub").mkdir()
    (root / "sub" / "notes.txt").write_text("some notes\n")
    return root


def _finalize_git(home_dir: Path) -> None:
    """Turn the plain template repo into a git repo tagged v0.1.0."""
    _git("init", cwd=home_dir)
    _git("add", "-A", cwd=home_dir)
    _git("commit", "-qm", "template v0.1.0", cwd=home_dir)
    _git("tag", "v0.1.0", cwd=home_dir)


# ---------------------------------------------------------------------------
# templatize
# ---------------------------------------------------------------------------


def test_templatize_produces_home_a_and_golden_no_diffs(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "myrepo")
    home = tmp_path / "myrepo-template"

    tz = templatize(repo_root=repo, into=home, name="myrepo")

    assert tz.status == TemplatizationStatus.complete
    assert tz.template_id == "myrepo"
    # Home A layout.
    assert (home / "copier.yml").is_file()
    assert (home / "copyroom.yml").is_file()
    assert (home / "registry" / ".gitkeep").is_file()
    assert (home / "template" / "README.md").is_file()  # verbatim copy
    assert (home / "template" / ".copier-answers.yml.jinja").is_file()
    assert (home / "scenarios" / "myrepo" / "default.yml").is_file()
    assert (home / "scenarios" / "myrepo" / "probe.yml").is_file()
    assert (home / "golden" / "myrepo" / "default" / "README.md").is_file()
    # The scaffold is workshop-detectable and a plain (non-git) dir.
    assert detect_mode(home) is not None
    assert not (home / ".git").exists()

    # The verbatim template reproduces the repo → golden is clean immediately.
    diff = golden_diff("myrepo", "default", workshop_root=home)
    assert diff.status == GoldenStatus.no_diffs


def test_templatize_refuses_nonempty_target(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "myrepo")
    home = tmp_path / "occupied"
    home.mkdir()
    (home / "stuff.txt").write_text("x")

    with pytest.raises(CopyRoomError, match="not empty"):
        templatize(repo_root=repo, into=home)


# ---------------------------------------------------------------------------
# parameterize (the golden loop)
# ---------------------------------------------------------------------------


def test_parameterize_keeps_golden_and_probe_renders_distinct(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "myrepo")
    home = tmp_path / "myrepo-template"
    templatize(repo_root=repo, into=home, name="myrepo")

    # Parameterize: rename README to a Jinja template and substitute the name.
    (home / "template" / "README.md").unlink()
    (home / "template" / "README.md.jinja").write_text(
        "# {{ project_name }}\n\nHello from {{ project_name }}.\n"
    )

    # Rendering with the default answer (= repo name) reproduces the literal,
    # so the golden match is preserved while a parameter is introduced.
    diff = golden_diff("myrepo", "default", workshop_root=home)
    assert diff.status == GoldenStatus.no_diffs

    # The probe scenario uses a distinct name → repo name absent in its output.
    render = render_scenario("myrepo", "probe", workshop_root=home)
    assert render.status == RenderStatus.complete
    probe_readme = (home / "generated" / "myrepo" / "probe" / "README.md").read_text()
    assert "copyroom-probe-xyz" in probe_readme
    assert "myrepo" not in probe_readme


# ---------------------------------------------------------------------------
# finalize + adopt (full arc)
# ---------------------------------------------------------------------------


def test_finalize_and_adopt_end_to_end(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "myrepo")
    _git("init", cwd=repo)
    _git("add", "-A", cwd=repo)
    _git("commit", "-qm", "initial", cwd=repo)

    home = tmp_path / "myrepo-template"
    templatize(repo_root=repo, into=home, name="myrepo")
    # Parameterize then finalize to a tagged git repo.
    (home / "template" / "README.md").unlink()
    (home / "template" / "README.md.jinja").write_text(
        "# {{ project_name }}\n\nHello from {{ project_name }}.\n"
    )
    _finalize_git(home)

    answers = tmp_path / "answers.yml"
    answers.write_text("project_name: myrepo\n")

    adoption = adopt(
        template=str(home), repo_root=repo, ref="v0.1.0",
        answers_file=answers, write=True,
    )

    assert adoption.status == AdoptionStatus.complete
    assert adoption.result is not None and not adoption.result.has_drift
    assert adoption.wrote_answers
    # The repo is now a managed project…
    assert (repo / ".copier-answers.yml").is_file()
    assert detect_mode(repo) is not None
    # …and only the answers file (+ .copyroom scratch) was added: no source
    # file was modified or removed.
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True,
    ).stdout
    changed = {line[3:] for line in status.splitlines()}
    assert changed <= {".copier-answers.yml", ".copyroom/"}
    assert (repo / "README.md").read_text() == "# myrepo\n\nHello from myrepo.\n"


# ---------------------------------------------------------------------------
# adopt under a named (fixture) template
# ---------------------------------------------------------------------------


def test_adopt_under_named_template_reports_drift(template_repo: Path, tmp_path: Path) -> None:
    # A repo that resembles the template's output but diverges: edited README
    # plus an extra hand-written file the template does not produce.
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / "README.md").write_text("# proj\n\nHand-edited, not the template text.\n")
    (repo / "EXTRA.md").write_text("my own file\n")

    answers = tmp_path / "answers.yml"
    answers.write_text("project_name: proj\n")

    adoption = adopt(
        template=str(template_repo), repo_root=repo, answers_file=answers, write=True,
    )

    assert adoption.status == AdoptionStatus.complete
    result = adoption.result
    assert result is not None and result.has_drift
    assert "README.md" in result.modified          # diverged content
    assert "EXTRA.md" in result.removed             # repo-only file
    # Report-only on the repo's own files: README keeps the hand-edited text,
    # the extra file survives, only the answers file is added.
    assert (repo / "README.md").read_text().startswith("# proj\n\nHand-edited")
    assert (repo / "EXTRA.md").is_file()
    assert (repo / ".copier-answers.yml").is_file()


def test_adopt_refuses_already_managed(template_repo: Path, tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / ".copier-answers.yml").write_text("_src_path: somewhere\nproject_name: x\n")

    with pytest.raises(CopyRoomError, match="already"):
        adopt(template=str(template_repo), repo_root=repo)


def test_adopt_force_allows_remanaging(template_repo: Path, tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / "README.md").write_text("# proj\n")
    (repo / ".copier-answers.yml").write_text("_src_path: old\nproject_name: x\n")

    adoption = adopt(
        template=str(template_repo), repo_root=repo, force=True,
    )
    assert adoption.status == AdoptionStatus.complete
