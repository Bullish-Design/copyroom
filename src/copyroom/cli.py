"""Public command line for local Templateer and jj workflows."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import typer


def _usage_error_type() -> type[Exception]:
    try:
        from typer._click.exceptions import UsageError
    except ModuleNotFoundError:
        from click.exceptions import UsageError
    return UsageError


UsageError = _usage_error_type()

app = typer.Typer(
    name="copyroom",
    help="Compose local Templateer sources and converge projects with jj.",
    add_completion=False,
    rich_markup_mode=None,
    no_args_is_help=True,
)
preview_app = typer.Typer(help="Create and recover isolated project previews.", add_completion=False)
layer_app = typer.Typer(help="Manage independent local source layers.", add_completion=False)
app.add_typer(preview_app, name="preview")
app.add_typer(layer_app, name="layer")
_MODE_OVERRIDE: str | None = None


def _error(message: str, code: int = 2) -> None:
    typer.echo(f"Error: {message}", err=True)
    raise typer.Exit(code=code)


def _emit(value: Any, json_output: bool) -> Any:
    if isinstance(value, (dict, list)):
        typer.echo(json.dumps(value, indent=2 if json_output else None, sort_keys=True))
    elif value is not None:
        typer.echo(str(value))
    return value


def _call(function: Any, *args: Any, json_output: bool = False, **kwargs: Any) -> Any:
    from .local.errors import LocalError

    try:
        result = function(*args, **kwargs)
    except LocalError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=exc.code) from exc
    return _emit(result, json_output)


def _project_root() -> Path:
    if _MODE_OVERRIDE == "workshop":
        _error("project command cannot run in workshop mode", 1)
    for path in (Path.cwd(), *Path.cwd().parents):
        if (path / ".copyroom-local.json").is_file():
            return path
        if _has_legacy_project_marker(path):
            _error(
                "legacy project markers need local adoption; use 'copyroom adopt SOURCE --answers FILE --write'",
                1,
            )
        if (
            (path / "copyroom.yml").is_file()
            and (path / "registry").is_dir()
            and (path / "scenarios").is_dir()
        ):
            _error("project command cannot run in workshop mode", 1)
    _error("no local CopyRoom project marker found", 2)


def _workshop_root() -> Path:
    if _MODE_OVERRIDE == "project":
        _error("workshop command cannot run in project mode", 1)
    for path in (Path.cwd(), *Path.cwd().parents):
        if (path / ".copyroom-local.json").is_file():
            _error("workshop command cannot run in project mode", 1)
        if _has_legacy_project_marker(path):
            _error(
                "legacy project markers need local adoption; use 'copyroom adopt SOURCE --answers FILE --write'",
                1,
            )
        if (
            (path / "copyroom.yml").is_file()
            and (path / "registry").is_dir()
            and (path / "scenarios").is_dir()
        ):
            return path
    _error("no local workshop markers found", 2)


def _has_legacy_project_marker(path: Path) -> bool:
    return (path / ".copier-answers.yml").is_file() or any(
        marker.is_file() for marker in path.glob(".copier-answers.*.yml")
    )


def _source(path: Path) -> Path:
    if not (path / "manifest.json").is_file():
        _error(f"not a local Templateer source: {path}", 3)
    return path


def _show_version(value: bool) -> None:
    """Print the version and exit 0 before Click checks for a subcommand."""

    if value:
        from . import __version__

        typer.echo(f"copyroom {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    ctx: typer.Context,
    mode: str | None = typer.Option(None, "--mode", help="Force project or workshop mode"),
    version: bool = typer.Option(
        False,
        "--version",
        callback=_show_version,
        is_eager=True,
        help="Print the version and exit",
    ),
) -> None:
    global _MODE_OVERRIDE
    if mode not in (None, "project", "workshop"):
        _error("--mode must be 'project' or 'workshop'", 3)
    _MODE_OVERRIDE = mode
    ctx.obj = mode


@app.command("new")
def new_command(
    source: Path = typer.Argument(..., help="Local Templateer source directory"),
    target: Path = typer.Argument(Path("."), help="New project directory"),
    answers: Path = typer.Option(..., "--answers", help="JSON answers file"),
    json_output: bool = typer.Option(False, "--json", help="Emit a JSON report"),
) -> None:
    """Create a project from a trusted local source."""
    from .local.workflow import new

    _call(new, _source(source), target, answers, json_output=json_output)


@app.command("update")
def update_command(
    out: Path | None = typer.Option(None, "--out", help="Preview workspace path"),
    apply_preview: Path | None = typer.Option(None, "--apply", help="Apply this reviewed preview"),
    source: Path | None = typer.Option(None, "--source", help="Local source override"),
    answers: Path | None = typer.Option(None, "--answers", help="JSON answers override"),
    layer: str = typer.Option("base", "--layer", help="Layer to converge"),
    json_output: bool = typer.Option(False, "--json", help="Emit a JSON report"),
) -> None:
    """Create a project update preview or apply a reviewed preview."""
    from .local.workflow import apply, preview

    project = _project_root()
    if apply_preview is not None:
        if out is not None or source is not None or answers is not None:
            _error("--apply cannot be combined with preview inputs", 3)
        result = _call(apply, project, apply_preview, json_output=json_output)
    else:
        destination = out or (
            project.parent / ".copyroom-previews"
            / f"{project.name}-{uuid.uuid4().hex[:10]}"
        )
        result = _call(
            preview, project, destination, source, answers, layer, json_output=json_output,
        )
    if isinstance(result, dict) and result.get("conflicts"):
        raise typer.Exit(code=1)


@preview_app.command("create")
def preview_create(
    project: Path = typer.Option(..., "--project", help="Managed project directory"),
    out: Path = typer.Option(..., "--out", help="Preview workspace path"),
    source: Path | None = typer.Option(None, "--source", help="Local source override"),
    answers: Path | None = typer.Option(None, "--answers", help="JSON answers override"),
    layer: str = typer.Option("base", "--layer", help="Layer to converge"),
    json_output: bool = typer.Option(False, "--json", help="Emit a JSON report"),
) -> None:
    from .local.workflow import preview

    _call(preview, project, out, source, answers, layer, json_output=json_output)


@preview_app.command("list")
def preview_list(
    project: Path = typer.Option(..., "--project", help="Managed project directory"),
    json_output: bool = typer.Option(False, "--json", help="Emit a JSON report"),
) -> None:
    from .local.workflow import list_previews

    _call(list_previews, project, json_output=json_output)


@app.command("apply")
def apply_command(
    preview: Path = typer.Option(..., "--preview", help="Reviewed preview workspace"),
    project: Path | None = typer.Option(None, "--project", help="Managed project directory"),
    json_output: bool = typer.Option(False, "--json", help="Emit a JSON report"),
) -> None:
    from .local.workflow import apply

    _call(apply, project or _project_root(), preview, json_output=json_output)


@app.command("discard")
def discard_command(
    preview: Path = typer.Option(..., "--preview", help="Preview workspace to discard"),
    json_output: bool = typer.Option(False, "--json", help="Emit a JSON report"),
) -> None:
    from .local.workflow import discard

    _call(discard, preview, json_output=json_output)


@app.command("inspect")
def inspect_command(
    project: Path | None = typer.Option(None, "--project", help="Managed project directory"),
    json_output: bool = typer.Option(False, "--json", help="Emit a JSON report"),
) -> None:
    from .local.workflow import inspect

    _call(inspect, project or _project_root(), json_output=json_output)


@app.command("status")
def status_command(
    project: Path | None = typer.Option(None, "--project", help="Managed project directory"),
    json_output: bool = typer.Option(False, "--json", help="Emit a JSON report"),
) -> None:
    from .local.workflow import status

    report = _call(status, project or _project_root(), json_output=json_output)
    if isinstance(report, dict) and (
        not report["ok"] or report["has_conflicts"] or report["has_marker_render_mismatch"]
    ):
        raise typer.Exit(code=1)


@app.command("recover")
def recover_command(
    project: Path | None = typer.Option(None, "--project", help="Managed project directory"),
    prune: bool = typer.Option(False, "--prune", help="Remove named orphan workspaces and files"),
    json_output: bool = typer.Option(False, "--json", help="Emit a JSON report"),
) -> None:
    """Report and reconcile interrupted project transactions."""
    from .local.workflow import recover

    report = _call(recover, project or _project_root(), prune, json_output=json_output)
    if isinstance(report, dict) and not report["ok"]:
        raise typer.Exit(code=1)


@app.command("doctor")
def doctor_command(json_output: bool = typer.Option(False, "--json", help="Emit a JSON report")) -> None:
    """Check the Templateer and jj environment."""
    from .local.workflow import doctor

    report = _call(doctor, json_output=json_output)
    if isinstance(report, dict) and not report["ok"]:
        raise typer.Exit(code=2)


@layer_app.command("add")
def layer_add(
    source: Path = typer.Option(..., "--source", help="Local Templateer source"),
    answers: Path = typer.Option(..., "--answers", help="JSON answers file"),
    as_layer: str = typer.Option(..., "--as", help="New layer name"),
    project: Path | None = typer.Option(None, "--project", help="Managed project directory"),
    json_output: bool = typer.Option(False, "--json", help="Emit a JSON report"),
) -> None:
    from .local.workflow import add_layer

    _call(add_layer, project or _project_root(), _source(source), answers, as_layer, json_output=json_output)


@layer_app.command("list")
def layer_list(
    project: Path | None = typer.Option(None, "--project", help="Managed project directory"),
    json_output: bool = typer.Option(False, "--json", help="Emit a JSON report"),
) -> None:
    from .local.workflow import list_layers

    _call(list_layers, project or _project_root(), json_output=json_output)


@app.command("generate")
def generate_command(
    template: str = typer.Option(..., "--template", help="Templateer artifact name"),
    request: str = typer.Option(..., "--request", help="Explicit generation request"),
    source: Path = typer.Option(..., "--source", help="Local Templateer source"),
    model: str = typer.Option("openai:gpt-4.1-mini", "--model", help="Provider model name"),
    context_file: Path | None = typer.Option(None, "--context", help="JSON project facts"),
    max_attempts: int = typer.Option(3, "--max-attempts", min=1, max=10),
    json_output: bool = typer.Option(False, "--json", help="Emit a JSON report"),
) -> None:
    """Call a model explicitly and freeze one validated artifact."""
    from .local.generation import generate
    from .local.source import read_json

    context = read_json(context_file) if context_file else {}
    _call(
        generate, _project_root(), _source(source), template, request, model, context,
        max_attempts, json_output=json_output,
    )


@app.command("refresh")
def refresh_command(
    layer: str = typer.Option(..., "--layer", help="Generated artifact owner"),
    out: Path = typer.Option(..., "--out", help="Preview workspace path"),
    request: str = typer.Option(..., "--request", help="Explicit refresh request"),
    source: Path | None = typer.Option(None, "--source", help="Local source override"),
    model: str = typer.Option("openai:gpt-4.1-mini", "--model", help="Provider model name"),
    context_file: Path | None = typer.Option(None, "--context", help="JSON project facts"),
    max_attempts: int = typer.Option(3, "--max-attempts", min=1, max=10),
    json_output: bool = typer.Option(False, "--json", help="Emit a JSON report"),
) -> None:
    """Call a model explicitly and preview a new frozen artifact."""
    from .local.generation import refresh
    from .local.source import read_json

    context = read_json(context_file) if context_file else {}
    _call(
        refresh, _project_root(), layer, out, request, source, model, context,
        max_attempts, json_output=json_output,
    )


@app.command("adopt")
def adopt_command(
    source: Path = typer.Argument(..., help="Local Templateer source"),
    answers: Path = typer.Option(..., "--answers", help="JSON answers file"),
    project: Path = typer.Option(Path("."), "--project", help="Existing project directory"),
    write: bool = typer.Option(False, "--write", help="Record the source and initialize jj"),
    template_only: str | None = typer.Option(None, "--template-only", help="Keep template-only paths"),
    json_output: bool = typer.Option(False, "--json", help="Emit a JSON report"),
) -> None:
    """Report drift or attach a local source to an existing project."""
    from .local.manage import adopt

    report = _call(
        adopt, project, _source(source), answers, write, template_only,
        json_output=json_output,
    )
    if isinstance(report, dict) and not write and not report["exact"]:
        raise typer.Exit(code=1)


@app.command("templatize")
def templatize_command(
    target: Path = typer.Option(..., "--target", help="New local Templateer source directory"),
    project: Path = typer.Option(Path("."), "--project", help="Project tree to extract"),
    name: str | None = typer.Option(None, "--name", help="Default project name"),
    parameterize: list[str] = typer.Option([], "--parameterize", help="Path to replace with project_name"),
    json_output: bool = typer.Option(False, "--json", help="Emit a JSON report"),
) -> None:
    """Extract a source and verify its exact golden tree."""
    from .local.manage import templatize

    _call(templatize, project, target, name, parameterize, json_output=json_output)


@app.command("registry")
def registry_command(
    action: str = typer.Argument(..., help="list, show, validate, or add"),
    template_id: str | None = typer.Argument(None, help="Template id for show or add"),
    source: Path | None = typer.Option(None, "--source", help="Local source for add"),
    scaffold: bool = typer.Option(False, "--scaffold", help="Create a default scenario file"),
    json_output: bool = typer.Option(False, "--json", help="Emit a JSON report"),
) -> None:
    """Read or update a local workshop registry."""
    from .local.workshop import registry_add, registry_list, registry_show, registry_validate

    if action == "list":
        _call(registry_list, workshop_root=_workshop_root(), json_output=json_output)
    elif action == "show" and template_id:
        _call(registry_show, template_id, workshop_root=_workshop_root(), json_output=json_output)
    elif action == "validate":
        result = _call(registry_validate, workshop_root=_workshop_root(), json_output=json_output)
        if isinstance(result, dict) and not result.get("ok", False):
            for template_id, problem in result.get("problems", {}).items():
                typer.echo(f"{template_id}: {problem}", err=True)
            raise typer.Exit(code=1)
    elif action == "add" and template_id and source:
        _call(
            registry_add, template_id, _source(source), scaffold,
            workshop_root=_workshop_root(), json_output=json_output,
        )
    else:
        if action not in {"list", "show", "validate", "add"}:
            _error(
                f"unknown registry action '{action}'; supported: list, show, validate, add",
                3,
            )
        _error("use list, show ID, validate, or add ID --source PATH", 3)


@app.command("render")
def render_command(template_id: str, scenario_id: str, json_output: bool = typer.Option(False, "--json")) -> None:
    from .local.workshop import render_scenario

    _call(render_scenario, template_id, scenario_id, workshop_root=_workshop_root(), json_output=json_output)


@app.command("test")
def test_command(template_id: str, scenario_id: str, json_output: bool = typer.Option(False, "--json")) -> None:
    from .local.workshop import run_scenario_tests

    _call(
        run_scenario_tests, template_id, scenario_id, workshop_root=_workshop_root(),
        quiet=json_output, json_output=json_output,
    )


@app.command("golden")
def golden_command(
    template_id: str,
    scenario_id: str,
    refresh: bool = typer.Option(False, "--refresh", help="Audit and replace the golden tree"),
    json_output: bool = typer.Option(False, "--json", help="Emit a JSON report"),
) -> None:
    from .local.workshop import golden_diff

    result = _call(
        golden_diff, template_id, scenario_id, workshop_root=_workshop_root(),
        refresh=refresh, json_output=json_output,
    )
    if isinstance(result, dict) and result.get("result") == "diff":
        raise typer.Exit(code=1)


@app.command("release-check")
def release_check_command(
    template_id: str, json_output: bool = typer.Option(False, "--json", help="Emit a JSON report"),
) -> None:
    from .local.workshop import release_check

    _call(
        release_check, template_id, workshop_root=_workshop_root(),
        quiet=json_output, json_output=json_output,
    )


@app.command("update-test")
def update_test_command(
    template_id: str,
    scenario_id: str,
    json_output: bool = typer.Option(False, "--json", help="Emit a JSON report"),
) -> None:
    from .local.workshop import update_test

    result = _call(update_test, template_id, scenario_id, workshop_root=_workshop_root(), json_output=json_output)
    if isinstance(result, dict) and result.get("result") == "conflicts":
        raise typer.Exit(code=1)


@app.command("template-checkout")
def template_checkout_command(template_id: str, json_output: bool = typer.Option(False, "--json")) -> None:
    from .local.workshop import template_checkout

    _call(template_checkout, template_id, workshop_root=_workshop_root(), json_output=json_output)


@app.command("template-test")
def template_test_command(template_id: str, json_output: bool = typer.Option(False, "--json")) -> None:
    from .local.workshop import template_test

    _call(template_test, template_id, workshop_root=_workshop_root(), json_output=json_output)


@app.command("template-preview")
def template_preview_command(
    template_id: str,
    project: Path = typer.Option(..., "--project", help="Managed project directory"),
    out: Path = typer.Option(..., "--out", help="Preview workspace path"),
    layer: str = typer.Option("base", "--layer", help="Project layer to converge"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    from .local.workshop import template_preview

    _call(
        template_preview, template_id, project, out, layer,
        workshop_root=_workshop_root(), json_output=json_output,
    )


@app.command("template-discard")
def template_discard_command(template_id: str, json_output: bool = typer.Option(False, "--json")) -> None:
    from .local.workshop import template_discard

    _call(template_discard, workshop_root=_workshop_root(), json_output=json_output)


def main(argv: list[str] | None = None) -> None:
    """Run the public Templateer and jj command line."""
    UsageError.exit_code = 3
    app(args=argv)


if __name__ == "__main__":
    main()
