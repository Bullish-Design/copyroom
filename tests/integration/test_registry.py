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
