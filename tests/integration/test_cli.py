"""CLI-level regression tests (mode override and the trust gate)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "copyroom", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def test_mode_override_reaches_handler(workshop: Path) -> None:
    """#3: --mode forces a mode so the command dispatches to its handler.

    Previously every command under --no-detect died with "Unknown command".
    With --mode the workshop handler runs and reaches the registry lookup.
    """
    r = _run("--mode", "workshop", "render", "nope", "scenario", cwd=workshop)
    assert r.returncode != 0
    assert "Unknown command" not in r.stderr
    assert "not found in workshop registry" in r.stderr


def test_render_works_from_workshop(workshop: Path) -> None:
    r = _run("render", "demo", "basic", cwd=workshop)
    assert r.returncode == 0, r.stderr
    assert "Rendered demo/basic" in r.stdout


def _add_post_create_hook(template_repo: Path) -> None:
    """Add a post-create hook that drops a marker file, tagged as a new version.

    Copier renders the latest tag, so the hook config must be tagged to appear
    in generated output.
    """
    (template_repo / "copyroom.project.yml").write_text(
        "commands:\n  post_project_create:\n    - \"touch HOOK_RAN\"\n"
    )
    for args in (["add", "-A"], ["commit", "-qm", "hook"], ["tag", "v2.0.0"]):
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
                       cwd=template_repo, check=True)


def test_new_skips_hooks_without_trust(template_repo: Path, tmp_path: Path) -> None:
    """#4.3: post-create hooks are skipped (with a warning) unless --trust."""
    _add_post_create_hook(template_repo)
    target = tmp_path / "out"
    # cwd is unmarked, so force project mode for dispatch (global flag goes first).
    r = _run("--mode", "project", "new", str(template_repo), str(target), cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert "Skipping post-create command" in r.stderr
    assert not (target / "HOOK_RAN").exists()


def test_new_runs_hooks_with_trust(template_repo: Path, tmp_path: Path) -> None:
    _add_post_create_hook(template_repo)
    target = tmp_path / "out"
    r = _run("--mode", "project", "new", str(template_repo), str(target), "--trust", cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert (target / "HOOK_RAN").exists()


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=str(cwd), check=True, capture_output=True, text=True,
    )


def test_update_noop_exits_zero(template_repo: Path, tmp_path: Path) -> None:
    """#P1-2: a no-op `update` (already at latest) exits 0, not 1.

    An idempotent "nothing to do" reported as failure breaks scripting/CI on
    the common case (`copyroom update` in a Makefile/loop).
    """
    from copyroom._compat.copier import copier_copy

    proj = tmp_path / "proj"
    assert copier_copy(str(template_repo), proj).returncode == 0  # generated at v1.0.0 (latest)
    _git("init", cwd=proj)
    _git("add", "-A", cwd=proj)
    _git("commit", "-qm", "generated", cwd=proj)

    r = _run("update", cwd=proj)
    assert r.returncode == 0, r.stderr
    assert "Already at the latest version" in r.stdout


def test_new_bootstraps_without_mode(template_repo: Path, tmp_path: Path) -> None:
    """#P1-1: `new` creates a project from an unmanaged dir, no --mode needed.

    `new` runs to *create* a project, so the project markers it would otherwise
    be gated on don't exist yet. It must bootstrap like adopt/templatize.
    """
    target = tmp_path / "out"
    r = _run("new", str(template_repo), str(target), cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert (target / "README.md").is_file()
    assert (target / ".copier-answers.yml").is_file()
