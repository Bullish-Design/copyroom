"""Integration tests for the `copyroom registry` subcommands."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from copyroom.workshop.registry import (
    CopyRoomError,
    add_template,
    list_templates,
    load_entry,
    validate_registry,
)

from .conftest import _git


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "copyroom", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


# ---------------------------------------------------------------------------
# list / show
# ---------------------------------------------------------------------------


def test_list_templates(workshop: Path, template_repo: Path) -> None:
    entries = list_templates(workshop)
    assert [e.template_id for e in entries] == ["demo"]
    assert entries[0].source == str(template_repo)
    assert entries[0].checks == ["test -f README.md"]


def test_show_known_entry(workshop: Path, template_repo: Path) -> None:
    entry = load_entry(workshop, "demo")
    assert entry.template_id == "demo"
    assert entry.source == str(template_repo)


def test_show_unknown_entry_raises(workshop: Path) -> None:
    with pytest.raises(CopyRoomError, match="not found"):
        load_entry(workshop, "nope")


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


def test_validate_happy(workshop: Path) -> None:
    report = validate_registry(workshop)
    assert report.ok
    assert report.problems["demo"] == []


def test_validate_flags_broken_entry(workshop: Path) -> None:
    (workshop / "registry" / "broken.yml").write_text(
        "id: broken\nsource: /nonexistent/template\nchecks: []\n"
    )
    report = validate_registry(workshop)
    assert not report.ok
    problems = report.problems["broken"]
    assert any("source path not found" in p for p in problems)
    assert any("no scenarios directory" in p for p in problems)
    # The sound entry stays clean.
    assert report.problems["demo"] == []


def test_validate_cli_nonzero_on_failure(workshop: Path) -> None:
    (workshop / "registry" / "broken.yml").write_text(
        "id: broken\nsource: /nonexistent/template\nchecks: []\n"
    )
    r = _run("registry", "validate", cwd=workshop)
    assert r.returncode != 0
    assert "broken" in r.stderr


# ---------------------------------------------------------------------------
# add (create-only)
# ---------------------------------------------------------------------------


def test_add_creates_new_entry(workshop: Path, template_repo: Path) -> None:
    path = add_template(workshop, "newtmpl", str(template_repo))
    assert path == workshop / "registry" / "newtmpl.yml"
    assert path.is_file()
    assert "id: newtmpl" in path.read_text()
    # copyroom.yml is untouched.
    assert "newtmpl" not in (workshop / "copyroom.yml").read_text()


def test_add_refuses_overwrite(workshop: Path, template_repo: Path) -> None:
    add_template(workshop, "newtmpl", str(template_repo))
    with pytest.raises(CopyRoomError, match="already exists"):
        add_template(workshop, "newtmpl", str(template_repo))


def test_add_scaffold_creates_scenario(workshop: Path, template_repo: Path) -> None:
    add_template(workshop, "scaffolded", str(template_repo), scaffold=True)
    assert (workshop / "scenarios" / "scaffolded" / "default.yml").is_file()


def test_add_refuses_id_already_in_copyroom_yml(workshop: Path, template_repo: Path) -> None:
    """#P1-3: 'demo' is defined inline in copyroom.yml; a registry/demo.yml would
    be shadowed by the resolver, so `add` must refuse rather than write a dead file."""
    with pytest.raises(CopyRoomError, match="already registered"):
        add_template(workshop, "demo", str(template_repo))
    assert not (workshop / "registry" / "demo.yml").exists()


def test_add_round_trips_special_characters(workshop: Path) -> None:
    """#P2-4: a source needing YAML quoting must survive write -> reload."""
    tricky = "gh:org/repo  # comment-like"
    add_template(workshop, "tricky", tricky)
    # Reload through the resolver: a hand-formatted line would have truncated at ` #`.
    assert load_entry(workshop, "tricky").source == tricky


def test_add_round_trips_flow_indicator_source(workshop: Path) -> None:
    """#P2-4: a source starting with a YAML flow indicator round-trips."""
    tricky = "{not-a-mapping}"
    add_template(workshop, "flowy", tricky)
    assert load_entry(workshop, "flowy").source == tricky


def test_registry_keyed_workshop_reports_checks(tmp_path: Path, template_repo: Path) -> None:
    """#P2-5: a `registry:`-keyed copyroom.yml (alias of `templates:`) must still
    surface the configured checks, not an empty list."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "copyroom.yml").write_text(
        "registry:\n"
        "  demo:\n"
        f"    source: {template_repo}\n"
        "    checks:\n"
        '      - "test -f README.md"\n'
    )
    entry = load_entry(ws, "demo")
    assert entry.checks == ["test -f README.md"]
    assert entry.source == str(template_repo)


def test_tilde_local_source_resolves(tmp_path: Path, monkeypatch) -> None:
    """#P2-6: a `~/...` local source must be expanded, not used literally."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    tmpl = home / "tmpl"
    tmpl.mkdir()
    (tmpl / "README.md.jinja").write_text("# {{ project_name }}\n")
    _git("init", cwd=tmpl)
    _git("add", "-A", cwd=tmpl)
    _git("commit", "-qm", "v1", cwd=tmpl)
    _git("tag", "v1.0.0", cwd=tmpl)

    ws = tmp_path / "ws"
    (ws / "scenarios" / "demo").mkdir(parents=True)
    (ws / "copyroom.yml").write_text(
        "templates:\n  demo:\n    source: ~/tmpl\n"
    )
    report = validate_registry(ws)
    # A literal-`~` path can't exist; expansion makes the repo + its tag resolvable.
    assert report.problems["demo"] == []


def test_relative_source_resolves_from_descendant(tmp_path: Path, monkeypatch) -> None:
    """#P3-2: a relative `source: .` (as templatize writes) must resolve against the
    workshop root, so render + validate work from any descendant directory."""
    from copyroom.workshop.model import RenderStatus
    from copyroom.workshop.render import render_scenario

    # A self-contained template+workshop: the workshop root *is* the template repo.
    ws = tmp_path / "selfws"
    (ws / "template").mkdir(parents=True)
    (ws / "template" / "README.md.jinja").write_text("# {{ project_name }}\n")
    (ws / "copier.yml").write_text(
        "_subdirectory: template\n"
        "project_name:\n  type: str\n  default: demo\n"
    )
    (ws / "registry").mkdir()
    (ws / "scenarios" / "selftmpl").mkdir(parents=True)
    (ws / "scenarios" / "selftmpl" / "default.yml").write_text("project_name: demo\n")
    (ws / "copyroom.yml").write_text(
        "templates:\n  selftmpl:\n    source: .\n"
    )
    _git("init", cwd=ws)
    _git("add", "-A", cwd=ws)
    _git("commit", "-qm", "v1", cwd=ws)
    _git("tag", "v1.0.0", cwd=ws)

    # validate resolves `.` against the workshop root (not the cwd).
    assert validate_registry(ws).problems["selftmpl"] == []

    # render from a *descendant* dir with workshop_root auto-detected.
    subdir = ws / "scenarios" / "selftmpl"
    monkeypatch.chdir(subdir)
    render = render_scenario("selftmpl", "default")
    assert render.status == RenderStatus.complete, render.status
    assert (ws / "generated" / "selftmpl" / "default" / "README.md").read_text() == "# demo\n"


# ---------------------------------------------------------------------------
# CLI happy path + unknown action
# ---------------------------------------------------------------------------


def test_registry_list_cli(workshop: Path) -> None:
    r = _run("registry", "list", cwd=workshop)
    assert r.returncode == 0, r.stderr
    assert "demo" in r.stdout


def test_registry_unknown_action_rejected(workshop: Path) -> None:
    r = _run("registry", "frobnicate", cwd=workshop)
    assert r.returncode != 0
    assert "unknown registry action" in r.stderr
    assert "list, show, validate, add" in r.stderr
