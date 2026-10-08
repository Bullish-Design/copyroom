"""Public CLI mode and migration messages."""

from __future__ import annotations

import builtins
from pathlib import Path

import click
import pytest
from typer.testing import CliRunner

from copyroom.cli import _usage_error_type, app, main

runner = CliRunner()


def test_help_lists_public_local_commands() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "templateer" in result.stdout.lower()
    assert "new" in result.stdout
    assert "apply" in result.stdout
    assert not any(line.strip().startswith("local ") for line in result.stdout.splitlines())


def test_usage_error_type_falls_back_to_public_click(monkeypatch) -> None:
    original_import = builtins.__import__

    def import_without_typer_click(name, *args, **kwargs):
        if name == "typer._click.exceptions":
            raise ModuleNotFoundError(name)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_typer_click)

    assert _usage_error_type() is click.exceptions.UsageError


def test_legacy_project_marker_gives_migration_refusal(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".copier-answers.yml").write_text("{}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["inspect"])

    assert result.exit_code == 1
    assert "legacy project markers need local adoption" in result.stderr


def test_nested_project_marker_takes_precedence_over_outer_workshop(
    tmp_path: Path, monkeypatch,
) -> None:
    (tmp_path / "copyroom.yml").write_text("name: outer\ntemplates: {}\n", encoding="utf-8")
    (tmp_path / "registry").mkdir()
    (tmp_path / "scenarios").mkdir()
    project = tmp_path / "nested-project"
    project.mkdir()
    (project / ".copyroom-local.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.chdir(project)

    result = runner.invoke(app, ["registry", "list"])

    assert result.exit_code == 1
    assert "workshop command cannot run in project mode" in result.stderr


def test_nested_workshop_marker_takes_precedence_over_outer_project(
    tmp_path: Path, monkeypatch,
) -> None:
    (tmp_path / ".copyroom-local.json").write_text("{}\n", encoding="utf-8")
    workshop = tmp_path / "nested-workshop"
    workshop.mkdir()
    (workshop / "copyroom.yml").write_text("name: inner\ntemplates: {}\n", encoding="utf-8")
    (workshop / "registry").mkdir()
    (workshop / "scenarios").mkdir()
    monkeypatch.chdir(workshop)

    result = runner.invoke(app, ["inspect"])

    assert result.exit_code == 1
    assert "project command cannot run in workshop mode" in result.stderr


def test_version_option_prints_one_line_and_exits_zero() -> None:
    from copyroom import __version__

    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout == f"copyroom {__version__}\n"


def test_bare_command_still_exits_three(capsys) -> None:
    with pytest.raises(SystemExit) as raised:
        main([])

    assert raised.value.code == 3
    captured = capsys.readouterr()
    assert "Usage:" in captured.out + captured.err


def test_version_option_exits_zero_through_main(capsys) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["--version"])

    assert raised.value.code == 0
    assert capsys.readouterr().out.startswith("copyroom ")


def test_mode_option_still_works_with_subcommand() -> None:
    result = runner.invoke(app, ["--mode", "bogus", "update"])

    assert result.exit_code == 3
    assert "--mode must be" in result.output
