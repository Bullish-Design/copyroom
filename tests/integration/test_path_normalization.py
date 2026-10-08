"""Relative paths and missing preview parents work through the real CLI."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE_FIXTURE = ROOT / ".scratch" / "projects" / "26-templateer-jj-slice" / "example"


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "copyroom", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def _make(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Create ws/source and ws/app, and return (ws, source, app)."""

    ws = tmp_path / "ws"
    ws.mkdir()
    source = ws / "source"
    shutil.copytree(SOURCE_FIXTURE, source)
    app = ws / "app"
    made = _run("new", str(source), str(app), "--answers", str(source / "answers.json"), cwd=ws)
    assert made.returncode == 0, made.stderr
    return ws, source, app


def _change_settings(source: Path) -> None:
    settings = source / "templates" / "settings" / "template.j2"
    settings.write_text(settings.read_text(encoding="utf-8") + '\nrevision: "v2"\n', encoding="utf-8")


def _overlay(ws: Path, source: Path, name: str) -> Path:
    overlay = ws / name
    shutil.copytree(source, overlay)
    manifest_path = overlay / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["templates"] = ["settings"]
    manifest["executable"] = []
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    metadata = overlay / "templates" / "settings" / "metadata.yml"
    metadata.write_text(
        metadata.read_text(encoding="utf-8").replace("config/project.yml", "docs/guide.md"),
        encoding="utf-8",
    )
    return overlay


def test_update_without_out_uses_the_default_destination(tmp_path: Path) -> None:
    ws, source, app = _make(tmp_path)
    _change_settings(source)
    result = _run("update", "--source", str(source), cwd=app)
    assert result.returncode == 0, result.stderr
    previews = [path for path in (ws / ".copyroom-previews").iterdir() if path.is_dir()]
    assert len(previews) == 1
    assert previews[0].name.startswith("app-")
    applied = _run("update", "--apply", str(previews[0]), cwd=app)
    assert applied.returncode == 0, applied.stderr


def test_out_with_missing_parent_is_created(tmp_path: Path) -> None:
    ws, source, app = _make(tmp_path)
    _change_settings(source)
    out = ws / "deep" / "er" / "preview"
    result = _run("update", "--source", str(source), "--out", str(out), cwd=app)
    assert result.returncode == 0, result.stderr
    assert (out / ".jj").exists()


def test_relative_source_out_and_apply_paths_from_inside_the_project(tmp_path: Path) -> None:
    ws, source, app = _make(tmp_path)
    _change_settings(source)
    created = _run("update", "--source", "../source", "--out", "../rel-preview", cwd=app)
    assert created.returncode == 0, created.stderr
    applied = _run("update", "--apply", "../rel-preview", cwd=app)
    assert applied.returncode == 0, applied.stderr
    assert 'revision: "v2"' in (app / "config/project.yml").read_text(encoding="utf-8")
    assert not (ws / "rel-preview").exists()


def test_preview_with_relative_out_applies_by_relative_and_absolute_path(tmp_path: Path) -> None:
    ws, source, app = _make(tmp_path)
    _change_settings(source)
    for spelling in ("relative", "absolute"):
        out_name = f"{spelling}-preview"
        made = _run("update", "--source", "../source", "--out", f"../{out_name}", cwd=app)
        assert made.returncode == 0, made.stderr
        target = f"../{out_name}" if spelling == "relative" else str(ws / out_name)
        if spelling == "relative":
            # A project reached through a path with ``..`` must still match.
            target = f"../app/../{out_name}"
        applied = _run("update", "--apply", target, cwd=app)
        assert applied.returncode == 0, applied.stderr
        _change_settings(source)


def test_preview_create_with_dotdot_project_and_absolute_out(tmp_path: Path) -> None:
    ws, source, app = _make(tmp_path)
    _change_settings(source)
    other = ws / "other"
    other.mkdir()
    out = ws / "abs-preview"
    made = _run(
        "preview", "create", "--project", "../app", "--source", "../source",
        "--out", str(out), cwd=other,
    )
    assert made.returncode == 0, made.stderr
    applied = _run("apply", "--preview", str(out), "--project", str(app), cwd=other)
    assert applied.returncode == 0, applied.stderr


def test_layer_add_adopt_and_templatize_accept_relative_paths(tmp_path: Path) -> None:
    ws, source, app = _make(tmp_path)
    overlay = _overlay(ws, source, "docs-template")
    added = _run(
        "layer", "add", "--source", "../docs-template", "--as", "docs",
        "--answers", str(overlay / "answers.json"), cwd=app,
    )
    assert added.returncode == 0, added.stderr

    existing = ws / "existing"
    existing.mkdir()
    (existing / "notes.txt").write_text("note\n", encoding="utf-8")
    adopted = _run(
        "adopt", "../source", "--answers", str(source / "answers.json"), cwd=existing,
    )
    assert adopted.returncode in {0, 1}, adopted.stderr
    assert "must be separate" not in adopted.stderr

    legacy = ws / "legacy"
    legacy.mkdir()
    (legacy / "README.md").write_text("# legacy\n", encoding="utf-8")
    extracted = _run("templatize", "--target", "../legacy-template", cwd=legacy)
    assert extracted.returncode == 0, extracted.stderr
    assert (ws / "legacy-template" / "manifest.json").is_file()


def test_out_inside_the_project_is_still_refused(tmp_path: Path) -> None:
    _, source, app = _make(tmp_path)
    _change_settings(source)
    for out in ("inside", "../app/inside", str(app / "nested" / "inside")):
        result = _run("update", "--source", str(source), "--out", out, cwd=app)
        assert result.returncode == 2
        assert "preview must be outside the project" in result.stderr
    assert not (app / "nested").exists()


def test_symlinked_source_is_still_refused(tmp_path: Path) -> None:
    ws, source, app = _make(tmp_path)
    link = ws / "source-link"
    link.symlink_to(source, target_is_directory=True)
    overlay = _overlay(ws, source, "docs-template")
    overlay_link = ws / "docs-link"
    overlay_link.symlink_to(overlay, target_is_directory=True)

    made = _run(
        "new", "../source-link", "../fresh", "--answers", str(source / "answers.json"), cwd=app,
    )
    assert made.returncode == 2
    assert "must not be a symlink" in made.stderr

    layer = _run(
        "layer", "add", "--source", "../docs-link", "--as", "docs",
        "--answers", str(overlay / "answers.json"), cwd=app,
    )
    assert layer.returncode == 2
    assert "must not be a symlink" in layer.stderr

    updated = _run("update", "--source", "../source-link", "--out", "../link-preview", cwd=app)
    assert updated.returncode == 2
    assert "must not be a symlink" in updated.stderr
    assert not (ws / "link-preview").exists()
