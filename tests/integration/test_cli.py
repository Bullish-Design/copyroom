"""Public CLI routes for local project and workshop workflows."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from typer.testing import CliRunner

from copyroom.cli import app

ROOT = Path(__file__).resolve().parents[2]
SOURCE_FIXTURE = ROOT / ".scratch" / "projects" / "26-templateer-jj-slice" / "example"


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "copyroom", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def _source(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "source"
    shutil.copytree(SOURCE_FIXTURE, source)
    return source, source / "answers.json"


def test_new_and_update_use_local_source(tmp_path: Path) -> None:
    source, answers = _source(tmp_path)
    project = tmp_path / "project"
    created = _run("new", str(source), str(project), "--answers", str(answers), cwd=tmp_path)
    assert created.returncode == 0, created.stderr
    assert (project / ".copyroom-local.json").is_file()

    settings = source / "templates" / "settings" / "template.j2"
    settings.write_text(settings.read_text(encoding="utf-8") + '\nrevision: "v2"\n', encoding="utf-8")
    preview = tmp_path / "preview"
    updated = _run("update", "--source", str(source), "--out", str(preview), cwd=project)
    assert updated.returncode == 0, updated.stderr
    applied = _run("apply", "--preview", str(preview), cwd=project)
    assert applied.returncode == 0, applied.stderr
    assert 'revision: "v2"' in (project / "config/project.yml").read_text(encoding="utf-8")


def test_inspect_and_status_emit_local_json(tmp_path: Path) -> None:
    source, answers = _source(tmp_path)
    project = tmp_path / "project"
    created = _run("new", str(source), str(project), "--answers", str(answers), cwd=tmp_path)
    assert created.returncode == 0, created.stderr

    for command in ("inspect", "status"):
        result = _run(command, "--json", cwd=project)
        assert result.returncode == 0, result.stderr
        report = json.loads(result.stdout)
        assert report["project"] == str(project)
        assert report["source_digest"]


def test_status_exits_one_on_render_mismatch_and_inspect_reports_it(tmp_path: Path) -> None:
    source, answers = _source(tmp_path)
    project = tmp_path / "project"
    created = _run("new", str(source), str(project), "--answers", str(answers), cwd=tmp_path)
    assert created.returncode == 0, created.stderr
    marker_path = project / ".copyroom-local.json"
    marker_data = json.loads(marker_path.read_text(encoding="utf-8"))
    marker_data["layers"]["base"]["revision"] += 1
    marker_path.write_text(json.dumps(marker_data), encoding="utf-8")

    reported = _run("status", "--json", cwd=project)
    assert reported.returncode == 1
    assert "mismatch: base marker=copyroom:render" in reported.stderr
    assert json.loads(reported.stdout)["marker_render_mismatches"]

    inspected = _run("inspect", "--json", cwd=project)
    assert inspected.returncode == 0
    assert json.loads(inspected.stdout)["marker_render_mismatches"]


def test_jj_warning_stays_off_json_stdout(tmp_path: Path, monkeypatch) -> None:
    from copyroom.local import workflow
    from copyroom.local.jj import JJ

    def report_with_warning(
        project: Path, out: Path, source: Path | None, answers: Path | None, layer: str,
    ) -> dict[str, str]:
        return {"result": "warning-test", "path": JJ(project).run("new", "preview")}

    monkeypatch.setattr(workflow, "preview", report_with_warning)
    completed = subprocess.CompletedProcess(
        ["jj", "new"], 0, "preview output\n", "Warning: Refused to snapshot some files: large.bin\n",
    )
    with (
        patch("copyroom.local.jj.shutil.which", return_value="/usr/bin/jj"),
        patch("copyroom.local.jj.subprocess.run", return_value=completed),
    ):
        result = CliRunner().invoke(
            app,
            [
                "preview", "create", "--project", str(tmp_path), "--out",
                str(tmp_path / "out"), "--json",
            ],
        )
    assert result.exit_code == 0
    assert json.loads(result.stdout)["result"] == "warning-test"
    assert result.stderr == "Warning: Refused to snapshot some files: large.bin\n"


def test_recover_pending_preview_exits_zero(tmp_path: Path) -> None:
    source, answers = _source(tmp_path)
    project = tmp_path / "project"
    created = _run("new", str(source), str(project), "--answers", str(answers), cwd=tmp_path)
    assert created.returncode == 0, created.stderr
    settings = source / "templates" / "settings" / "template.j2"
    settings.write_text(settings.read_text(encoding="utf-8") + '\nrevision: "v2"\n')
    prepared = _run(
        "update", "--source", str(source), "--out", str(tmp_path / "preview"), cwd=project,
    )
    assert prepared.returncode == 0, prepared.stderr

    recovered = _run("recover", "--json", cwd=project)

    assert recovered.returncode == 0, recovered.stderr
    report = json.loads(recovered.stdout)
    assert report["ok"] is True
    assert len(report["pending_review"]) == 1
    assert report["pending_recovery"] == []


def test_workshop_registry_and_golden_use_local_source(tmp_path: Path) -> None:
    source, _ = _source(tmp_path)
    workshop = tmp_path / "workshop"
    (workshop / "registry").mkdir(parents=True)
    (workshop / "scenarios").mkdir()
    (workshop / "copyroom.yml").write_text("name: test\ntemplates: {}\n", encoding="utf-8")

    added = _run("registry", "add", "demo", "--source", str(source), "--scaffold", cwd=workshop)
    assert added.returncode == 0, added.stderr
    rendered = _run("render", "demo", "default", cwd=workshop)
    assert rendered.returncode == 0, rendered.stderr
    refreshed = _run("golden", "demo", "default", "--refresh", cwd=workshop)
    assert refreshed.returncode == 0, refreshed.stderr
    compared = _run("golden", "demo", "default", cwd=workshop)
    assert compared.returncode == 0, compared.stderr
    assert '"result": "match"' in compared.stdout


def test_mode_override_requires_a_marked_workshop(tmp_path: Path) -> None:
    (tmp_path / "registry").mkdir()
    (tmp_path / "scenarios").mkdir()
    (tmp_path / "copyroom.yml").write_text("name: test\ntemplates: {}\n", encoding="utf-8")

    result = _run("--mode", "workshop", "registry", "show", "missing", cwd=tmp_path)

    assert result.returncode == 1
    assert "not registered" in result.stderr


def test_cli_usage_errors_exit_three(tmp_path: Path) -> None:
    result = _run("new", cwd=tmp_path)

    assert result.returncode == 3
    assert "Missing argument 'SOURCE'" in result.stderr


def test_workshop_scenario_path_traversal_cannot_delete_outside_output(tmp_path: Path) -> None:
    source, _ = _source(tmp_path)
    workshop = tmp_path / "workshop"
    (workshop / "registry").mkdir(parents=True)
    (workshop / "scenarios" / "demo").mkdir(parents=True)
    (workshop / "generated" / "demo").mkdir(parents=True)
    (workshop / "copyroom.yml").write_text(
        f"name: test\ntemplates:\n  demo:\n    source: {source}\n",
        encoding="utf-8",
    )
    outside = workshop / "target"
    outside.mkdir()
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("keep this tree\n", encoding="utf-8")
    (workshop / "target.yml").write_text((source / "answers.json").read_text(), encoding="utf-8")

    result = _run("render", "demo", "../../target", cwd=workshop)

    assert result.returncode == 3
    assert "invalid scenario id" in result.stderr
    assert sentinel.read_text(encoding="utf-8") == "keep this tree\n"


def test_workshop_json_reports_contain_only_json(tmp_path: Path, monkeypatch) -> None:
    source, _ = _source(tmp_path)
    workshop = tmp_path / "workshop"
    (workshop / "registry").mkdir(parents=True)
    (workshop / "scenarios" / "demo").mkdir(parents=True)
    (workshop / "copyroom.yml").write_text(
        f"name: test\ntemplates:\n  demo:\n    source: {source}\n",
        encoding="utf-8",
    )
    (workshop / "registry" / "demo.yml").write_text(
        f"id: demo\nsource: {source}\n", encoding="utf-8",
    )
    (workshop / "scenarios" / "demo" / "basic.yml").write_text(
        (source / "answers.json").read_text(encoding="utf-8"), encoding="utf-8",
    )
    monkeypatch.chdir(workshop)
    runner = CliRunner()
    command = SimpleNamespace(returncode=0, stdout="test output\n", stderr="test diagnostic\n")

    with patch("copyroom.local.workshop.subprocess.run", return_value=command):
        tested = runner.invoke(app, ["test", "demo", "basic", "--json"])
    assert tested.exit_code == 0, tested.output
    assert json.loads(tested.stdout)["result"] == "passed"
    log = workshop / ".copyroom-workshop" / "logs" / "demo-basic.log"
    assert "test output" in log.read_text(encoding="utf-8")

    golden = runner.invoke(app, ["golden", "demo", "basic", "--refresh"])
    assert golden.exit_code == 0, golden.output
    with patch("copyroom.local.workshop.subprocess.run", return_value=command):
        checked = runner.invoke(app, ["release-check", "demo", "--json"])
    assert checked.exit_code == 0, checked.output
    assert json.loads(checked.stdout)["result"] == "ready"
    release_log = workshop / ".copyroom-workshop" / "logs" / "demo-basic.log"
    assert "test output" in release_log.read_text(encoding="utf-8")


def test_legacy_project_is_not_silently_converted(tmp_path: Path) -> None:
    (tmp_path / ".copier-answers.yml").write_text("{}\n", encoding="utf-8")

    result = _run("inspect", cwd=tmp_path)

    assert result.returncode == 1
    assert "legacy project markers need local adoption" in result.stderr


def test_update_test_no_change_exits_zero_with_structured_report(
    tmp_path: Path, monkeypatch,
) -> None:
    source, answers = _source(tmp_path)
    workshop = tmp_path / "workshop"
    (workshop / "registry").mkdir(parents=True)
    (workshop / "scenarios" / "demo").mkdir(parents=True)
    (workshop / "copyroom.yml").write_text("templates: {}\n", encoding="utf-8")
    (workshop / "registry" / "demo.yml").write_text(
        f"id: demo\nsource: {source}\n", encoding="utf-8",
    )
    (workshop / "scenarios" / "demo" / "basic.yml").write_text(
        answers.read_text(encoding="utf-8"), encoding="utf-8",
    )
    monkeypatch.chdir(workshop)
    runner = CliRunner()

    checkout = runner.invoke(app, ["template-checkout", "demo", "--json"])
    assert checkout.exit_code == 0, checkout.output
    result = runner.invoke(app, ["update-test", "demo", "basic", "--json"])

    assert result.exit_code == 0, result.output
    assert "Traceback" not in result.output
    assert json.loads(result.stdout) == {
        "result": "no-change", "template": "demo", "scenario": "basic",
    }
    runner.invoke(app, ["template-discard", "demo"])
