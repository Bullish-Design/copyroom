"""Local Templateer workshop workflows."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import yaml
from templateer.api import TemplateRegistry

from .composer import compose, safe_output_path
from .errors import LocalError
from .jj import JJ
from .source import read_json, write_json
from .workflow import discard, new, preview, working_files, write_tree

WORKSHOP_STATE = ".copyroom-workshop"
_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]+\Z")


def _validate_id(value: str, kind: str) -> str:
    """Reject identifiers that can escape their workshop directory."""

    if not _ID_PATTERN.fullmatch(value):
        raise LocalError(f"invalid {kind} id: {value!r}", 3)
    return value


def _workshop(root: Path | None = None) -> Path:
    """Find and validate a local workshop root."""

    if root is None:
        root = Path.cwd()
        for candidate in (root, *root.parents):
            if (
                (candidate / "copyroom.yml").is_file()
                and (candidate / "registry").is_dir()
                and (candidate / "scenarios").is_dir()
            ):
                return candidate
    if not (
        (root / "copyroom.yml").is_file()
        and (root / "registry").is_dir()
        and (root / "scenarios").is_dir()
    ):
        raise LocalError("no local workshop found here")
    return root.resolve()


def _yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise LocalError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise LocalError(f"{path} must contain a mapping")
    return value


def _source(root: Path, template_id: str, override: Path | None = None) -> Path:
    """Resolve a local source. Remote sources are outside the workshop contract."""

    _validate_id(template_id, "template")
    if override is None:
        config = _yaml(root / "copyroom.yml")
        entries = config.get("templates", config.get("registry", {}))
        item = entries.get(template_id) if isinstance(entries, dict) else None
        raw = item.get("source") if isinstance(item, dict) else item
        entry_path = root / "registry" / f"{template_id}.yml"
        if entry_path.is_file():
            entry = _yaml(entry_path)
            raw = entry.get("source")
        if not isinstance(raw, str):
            raise LocalError(f"no local source configured for template {template_id}", 3)
        if "://" in raw or raw.startswith("git@"): 
            raise LocalError(f"workshop sources must be local paths: {raw}", 3)
        path = Path(raw)
        override = path if path.is_absolute() else root / path
    source = override.resolve()
    if not (source / "manifest.json").is_file():
        raise LocalError(f"source is not a local Templateer source: {source}")
    return source


def _registry_entry(root: Path, template_id: str) -> dict[str, Any]:
    """Load one local registry entry from a file or workshop config."""

    _validate_id(template_id, "template")
    entry_path = root / "registry" / f"{template_id}.yml"
    if entry_path.is_file():
        entry = _yaml(entry_path)
        entry.setdefault("id", template_id)
        return entry
    config = _yaml(root / "copyroom.yml")
    entries = config.get("templates", config.get("registry", {}))
    item = entries.get(template_id) if isinstance(entries, dict) else None
    if isinstance(item, str):
        return {"id": template_id, "source": item}
    if isinstance(item, dict):
        return {"id": template_id, **item}
    raise LocalError(f"template {template_id} is not registered", 1)


def registry_list(workshop_root: Path | None = None) -> list[dict[str, Any]]:
    """List local workshop registry entries."""

    root = _workshop(workshop_root)
    config = _yaml(root / "copyroom.yml")
    configured = config.get("templates", config.get("registry", {}))
    ids = set(configured) if isinstance(configured, dict) else set()
    ids.update(path.stem for path in (root / "registry").glob("*.yml"))
    result = []
    for template_id in sorted(ids):
        entry = _registry_entry(root, template_id)
        result.append({
            "id": template_id,
            "source": entry.get("source"),
            "description": entry.get("description"),
        })
    return result


def registry_show(template_id: str, workshop_root: Path | None = None) -> dict[str, Any]:
    """Show one local workshop registry entry."""

    return _registry_entry(_workshop(workshop_root), template_id)


def registry_validate(workshop_root: Path | None = None) -> dict[str, Any]:
    """Check every registered source without rendering a project."""

    root = _workshop(workshop_root)
    problems: dict[str, str] = {}
    entries = registry_list(root)
    for item in entries:
        try:
            _source(root, item["id"])
        except LocalError as exc:
            problems[item["id"]] = str(exc)
    return {"ok": not problems, "entries": entries, "problems": problems}


def registry_add(
    template_id: str,
    source: Path,
    scaffold: bool = False,
    workshop_root: Path | None = None,
) -> dict[str, Any]:
    """Add a local source entry without changing the workshop config."""

    root = _workshop(workshop_root)
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
    if not template_id or any(char not in allowed for char in template_id):
        raise LocalError(f"invalid template id: {template_id!r}", 3)
    source = source.resolve()
    if not (source / "manifest.json").is_file():
        raise LocalError(f"not a local Templateer source: {source}", 3)
    path = root / "registry" / f"{template_id}.yml"
    if path.exists() or template_id in {entry["id"] for entry in registry_list(root)}:
        raise LocalError(f"template {template_id} is already registered", 1)
    path.write_text(yaml.safe_dump({"id": template_id, "source": str(source)}, sort_keys=False), encoding="utf-8")
    scenario_path: Path | None = None
    if scaffold:
        scenario_path = root / "scenarios" / template_id / "default.yml"
        scenario_path.parent.mkdir(parents=True, exist_ok=True)
        answer_file = source / "answers.json"
        if answer_file.is_file():
            try:
                answers = json.loads(answer_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                path.unlink(missing_ok=True)
                raise LocalError(f"cannot read source answers: {exc}") from exc
        else:
            answers = {}
        scenario_path.write_text(yaml.safe_dump(answers, sort_keys=False), encoding="utf-8")
    return {"id": template_id, "registry": str(path), "scenario": str(scenario_path) if scenario_path else None}


def _scenario(root: Path, template_id: str, scenario_id: str) -> dict[str, Any]:
    _validate_id(template_id, "template")
    _validate_id(scenario_id, "scenario")
    path = root / "scenarios" / template_id / f"{scenario_id}.yml"
    return _yaml(path)


def _output(root: Path, template_id: str, scenario_id: str) -> Path:
    _validate_id(template_id, "template")
    _validate_id(scenario_id, "scenario")
    return root / "generated" / template_id / scenario_id


def _golden(root: Path, template_id: str, scenario_id: str) -> Path:
    _validate_id(template_id, "template")
    _validate_id(scenario_id, "scenario")
    return root / "goldens" / template_id / scenario_id


def _tree(root: Path) -> dict[str, tuple[str, bytes, int]]:
    """Read a complete tree, including symlinks and executable bits."""

    return working_files(root)


def _render(root: Path, template_id: str, scenario_id: str, source: Path | None = None) -> tuple[Path, Any]:
    source_path = _source(root, template_id, source)
    answers = _scenario(root, template_id, scenario_id)
    plan = compose(source_path, answers)
    destination = _output(root, template_id, scenario_id)
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    write_tree(destination, plan.files)
    return destination, plan


def render_scenario(
    template_id: str,
    scenario_id: str,
    workshop_root: Path | None = None,
    source: Path | None = None,
) -> dict[str, Any]:
    """Render a scenario with Templateer and validate the full artifact set."""

    root = _workshop(workshop_root)
    output, plan = _render(root, template_id, scenario_id, source)
    return {
        "result": "rendered",
        "template": template_id,
        "scenario": scenario_id,
        "output": str(output),
        "files": sorted(plan.files),
        "render_digest": plan.render_digest,
    }


def _audit(source: Path) -> list[str]:
    """Run Templateer's authoring audit for every declared artifact."""

    from .composer import _read_manifest

    manifest = _read_manifest(source)
    registry = TemplateRegistry.from_paths([source / "templates"])
    findings: list[str] = []
    for name in manifest.get("templates", []):
        report = registry.audit(name)
        if not report.ok:
            findings.extend(f"{name}: {item}" for item in report.findings)
    return findings


def golden_diff(
    template_id: str,
    scenario_id: str,
    workshop_root: Path | None = None,
    refresh: bool = False,
    source: Path | None = None,
) -> dict[str, Any]:
    """Compare a full-tree golden, or refresh it after a Templateer audit."""

    root = _workshop(workshop_root)
    output, plan = _render(root, template_id, scenario_id, source)
    expected = _golden(root, template_id, scenario_id)
    actual_tree = _tree(output)
    if refresh:
        source_path = _source(root, template_id, source)
        findings = _audit(source_path)
        if findings:
            raise LocalError("Templateer audit failed: " + "; ".join(findings), 1)
        if expected.exists():
            shutil.rmtree(expected)
        expected.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(output, expected, symlinks=True)
        return {
            "result": "golden-refreshed",
            "template": template_id,
            "scenario": scenario_id,
            "golden": str(expected),
            "render_digest": plan.render_digest,
            "audit": "passed",
        }
    if not expected.is_dir():
        raise LocalError(f"golden tree not found: {expected}", 1)
    expected_tree = _tree(expected)
    added = sorted(set(actual_tree) - set(expected_tree))
    removed = sorted(set(expected_tree) - set(actual_tree))
    changed = sorted(
        path for path in set(actual_tree) & set(expected_tree)
        if actual_tree[path] != expected_tree[path]
    )
    return {
        "result": "match" if not (added or removed or changed) else "diff",
        "template": template_id,
        "scenario": scenario_id,
        "added": added,
        "removed": removed,
        "changed": changed,
        "render_digest": plan.render_digest,
    }


def run_scenario_tests(
    template_id: str,
    scenario_id: str,
    workshop_root: Path | None = None,
    source: Path | None = None,
    quiet: bool = False,
) -> dict[str, Any]:
    """Run ``devenv test`` from a fresh scenario render and preserve its log."""

    root = _workshop(workshop_root)
    output, plan = _render(root, template_id, scenario_id, source)
    result = subprocess.run(
        ["devenv", "test"], cwd=output, capture_output=True, text=True, check=False,
    )
    state = root / WORKSHOP_STATE / "logs"
    state.mkdir(parents=True, exist_ok=True)
    log = state / f"{template_id}-{scenario_id}.log"
    log.write_text(
        f"exit_code={result.returncode}\n\nstdout:\n{result.stdout}\n\nstderr:\n{result.stderr}",
        encoding="utf-8",
    )
    if not quiet:
        print(result.stdout, end="")
        print(result.stderr, end="", file=__import__("sys").stderr)
    if result.returncode:
        raise LocalError(f"devenv test failed with exit code {result.returncode}; log: {log}", 1)
    return {
        "result": "passed",
        "template": template_id,
        "scenario": scenario_id,
        "render_digest": plan.render_digest,
        "exit_code": result.returncode,
        "log": str(log),
    }


def release_check(
    template_id: str,
    workshop_root: Path | None = None,
    source: Path | None = None,
    quiet: bool = False,
) -> dict[str, Any]:
    """Audit one source, compare all scenario goldens, and run their tests."""

    root = _workshop(workshop_root)
    source_path = _source(root, template_id, source)
    findings = _audit(source_path)
    if findings:
        raise LocalError("Templateer audit failed: " + "; ".join(findings), 1)
    files = sorted((root / "scenarios" / template_id).glob("*.yml"))
    if not files:
        raise LocalError(f"no scenarios found for {template_id}", 3)
    results = []
    for path in files:
        scenario = path.stem
        comparison = golden_diff(template_id, scenario, root, source=source_path)
        if comparison["result"] != "match":
            raise LocalError(f"golden differs for {template_id}/{scenario}: {comparison}", 1)
        results.append(run_scenario_tests(template_id, scenario, root, source_path, quiet))
    return {"result": "ready", "template": template_id, "scenarios": results}


def _candidate_path(root: Path) -> Path:
    return root / WORKSHOP_STATE / "candidate.json"


def template_checkout(
    template_id: str,
    workshop_root: Path | None = None,
) -> dict[str, Any]:
    """Create a separate jj workspace for local candidate template edits."""

    root = _workshop(workshop_root)
    source = _source(root, template_id)
    state_file = _candidate_path(root)
    if state_file.exists():
        state = read_json(state_file)
        if Path(state.get("candidate", "")).is_dir():
            raise LocalError(f"candidate already exists for {state.get('template')}; discard it first", 1)
    jj = JJ(source)
    if not (source / ".jj").is_dir():
        jj.run("git", "init", "--colocate")
        jj.run("commit", "-m", f"copyroom:template {template_id} baseline")
    base_head = jj.commit_id("@").strip()
    candidate = Path(tempfile.mkdtemp(prefix=f"copyroom-{template_id}-"))
    candidate.rmdir()
    try:
        jj.run("workspace", "add", "--name", f"copyroom-{template_id}", str(candidate))
    except LocalError:
        shutil.rmtree(candidate, ignore_errors=True)
        raise
    state = {
        "template": template_id,
        "source": str(source),
        "candidate": str(candidate),
        "base_head": base_head,
    }
    write_json(state_file, state)
    return {"result": "candidate-ready", **state}


def _load_candidate(root: Path, template_id: str | None = None) -> tuple[dict[str, Any], Path]:
    path = _candidate_path(root)
    if not path.is_file():
        raise LocalError("no template candidate is checked out", 3)
    state = read_json(path)
    if template_id and state.get("template") != template_id:
        raise LocalError(f"candidate is for template {state.get('template')}", 3)
    candidate = Path(str(state.get("candidate", "")))
    if not candidate.is_dir():
        raise LocalError("candidate workspace is missing; run template-discard", 2)
    return state, candidate


def template_test(template_id: str, workshop_root: Path | None = None) -> dict[str, Any]:
    """Render and compare every scenario against the candidate workspace."""

    root = _workshop(workshop_root)
    _, candidate = _load_candidate(root, template_id)
    results = []
    for scenario_file in sorted((root / "scenarios" / template_id).glob("*.yml")):
        result = golden_diff(template_id, scenario_file.stem, root, source=candidate)
        if result["result"] != "match":
            raise LocalError(f"candidate golden differs for {scenario_file.stem}: {result}", 1)
        results.append(result)
    if not results:
        raise LocalError(f"no scenarios found for {template_id}", 3)
    return {"result": "candidate-passed", "template": template_id, "scenarios": results}


def update_test(
    template_id: str,
    scenario_id: str,
    workshop_root: Path | None = None,
) -> dict[str, Any]:
    """Exercise a candidate update against a disposable jj project."""

    from .edits import apply_edits, load_edits

    root = _workshop(workshop_root)
    _, candidate = _load_candidate(root, template_id)
    source = _source(root, template_id)
    state_dir = root / WORKSHOP_STATE
    test_root = Path(tempfile.mkdtemp(prefix=f"copyroom-update-{template_id}-{scenario_id}-"))
    project = test_root / "project"
    preview_dir = test_root / "preview"

    answers = _scenario(root, template_id, scenario_id)
    answers_path = test_root / "answers.json"
    write_json(answers_path, answers)
    new(source, project, answers_path)
    edits_path = root / "scenarios" / template_id / f"{scenario_id}-edits.yml"
    edits = load_edits(edits_path)
    for edit in edits:
        safe_output_path(str(edit["file"]), {})
    apply_edits(edits, project)

    state = preview(project, preview_dir, candidate, None, "base")
    if state.get("result") == "no-change":
        # The candidate renders the same tree as the project. Preview made no
        # workspace and no state, so only the disposable test root remains.
        shutil.rmtree(test_root)
        return {
            "result": "no-change",
            "template": template_id,
            "scenario": scenario_id,
        }
    if state["conflicts"]:
        return {
            "result": "conflicts",
            "template": template_id,
            "scenario": scenario_id,
            "conflicts": state["conflicts"],
            "project": str(project),
            "preview": str(preview_dir),
            "workspace": str(test_root),
        }

    result = subprocess.run(
        ["devenv", "test"], cwd=preview_dir, capture_output=True, text=True, check=False,
    )
    log_dir = state_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log = log_dir / f"update-{template_id}-{scenario_id}.log"
    log.write_text(
        f"exit_code={result.returncode}\n\nstdout:\n{result.stdout}\n\nstderr:\n{result.stderr}",
        encoding="utf-8",
    )
    if result.returncode:
        raise LocalError(f"devenv test failed with exit code {result.returncode}; log: {log}", 1)
    discard(preview_dir)
    shutil.rmtree(test_root)
    return {
        "result": "passed",
        "template": template_id,
        "scenario": scenario_id,
        "preview_tree": state["preview_tree"],
        "exit_code": result.returncode,
        "log": str(log),
    }


def template_preview(
    template_id: str,
    project: Path,
    out: Path,
    layer: str = "base",
    workshop_root: Path | None = None,
) -> dict[str, Any]:
    """Preview candidate output in a separate managed-project workspace."""

    from .workflow import preview

    root = _workshop(workshop_root)
    _, candidate = _load_candidate(root, template_id)
    return preview(project, out, candidate, None, layer)


def template_discard(workshop_root: Path | None = None) -> dict[str, Any]:
    """Forget and remove the separate candidate workspace."""

    root = _workshop(workshop_root)
    state_file = _candidate_path(root)
    state, candidate = _load_candidate(root)
    source = Path(str(state["source"]))
    JJ(candidate).run("workspace", "forget", f"copyroom-{state['template']}")
    shutil.rmtree(candidate, ignore_errors=True)
    state_file.unlink(missing_ok=True)
    return {"result": "candidate-discarded", "template": state["template"], "source": str(source)}


__all__ = [
    "golden_diff", "release_check", "render_scenario", "run_scenario_tests", "update_test",
    "template_checkout", "template_discard", "template_preview", "template_test",
]
