"""Adopt and templatize local project trees."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

import yaml

from .composer import RenderPlan, check_paths, compose, digest_bytes, plan_digest
from .errors import LocalError
from .jj import JJ, project_lock
from .source import (
    MARKER,
    exclude_local_state,
    marker_with_plan,
    read_json,
    snapshot_source,
    write_json,
)
from .workflow import (
    _render_subject,
    _validate_disjoint,
    clear_workspace,
    normalize_path,
    working_digest,
    working_files,
    write_tree,
)

IGNORED_PARTS = {
    ".git", ".jj", ".devenv", ".direnv", ".venv", ".copyroom-local",
    "__pycache__", ".pytest_cache", ".ruff_cache",
}


def _project_files(project: Path) -> dict[str, tuple[str, bytes, int]]:
    """Return the project tree without CopyRoom state."""

    return {
        name: value for name, value in working_files(project).items()
        if name != MARKER and not name.startswith(".copyroom-local/")
    }


def _plan_files(plan: RenderPlan) -> dict[str, tuple[str, bytes, int]]:
    """Convert a render plan to the project tree shape."""

    return {
        name: (entry.kind, entry.content, entry.mode)
        for name, entry in plan.files.items()
    }


def compare(project: Path, plan: RenderPlan) -> dict[str, Any]:
    """Compare a rendered source with an existing project."""

    project_tree = _project_files(project)
    template_tree = _plan_files(plan)
    project_paths = set(project_tree)
    template_paths = set(template_tree)
    common = project_paths & template_paths
    changed = sorted(path for path in common if project_tree[path] != template_tree[path])
    project_only = sorted(project_paths - template_paths)
    template_only = sorted(template_paths - project_paths)
    detail = {
        path: {
            "project_sha256": digest_bytes(project_tree[path][1]),
            "project_mode": f"{project_tree[path][2]:o}",
            "template_sha256": digest_bytes(template_tree[path][1]),
            "template_mode": f"{template_tree[path][2]:o}",
        }
        for path in changed
    }
    return {
        "project": str(normalize_path(project)),
        "source_digest": plan.source_digest,
        "changed": changed,
        "changed_detail": detail,
        "project_only": project_only,
        "template_only": template_only,
        "exact": not changed and not project_only and not template_only,
    }


def adopt(
    project: Path,
    source: Path,
    answers_file: Path,
    write: bool = False,
    template_only_choice: str | None = None,
) -> dict[str, Any]:
    """Report template drift or attach a local source with explicit write."""

    project = normalize_path(project)
    source = normalize_path(source)
    if (project / MARKER).exists():
        raise LocalError("project already has a local marker", 3)
    _validate_disjoint(source, project)
    plan = compose(source, read_json(answers_file))
    report = compare(project, plan)
    project_paths = set(_project_files(project))
    prefix_collisions: list[str] = []
    for template_path in plan.files:
        others = [path for path in project_paths if path != template_path]
        try:
            check_paths([template_path, *others])
        except LocalError as exc:
            prefix_collisions.append(str(exc))
    report["prefix_collisions"] = prefix_collisions
    if not write:
        report["result"] = "report"
        return report
    if prefix_collisions:
        raise LocalError("adoption has output path collisions: " + "; ".join(prefix_collisions), 1)
    if report["template_only"] and template_only_choice != "keep":
        raise LocalError(
            "choose --template-only keep to leave template-only paths outside project ownership",
            3,
        )
    if template_only_choice not in {None, "keep"}:
        raise LocalError("--template-only supports only 'keep'", 3)

    omissions = list(report["template_only"])
    if omissions:
        kept_files = {path: item for path, item in plan.files.items() if path not in omissions}
        kept_owners = {path: owner for path, owner in plan.owners.items() if path not in omissions}
        plan = RenderPlan(
            files=kept_files,
            owners=kept_owners,
            answers=plan.answers,
            source_digest=plan.source_digest,
            manifest_digest=plan.manifest_digest,
            templateer_version=plan.templateer_version,
            templateer_digest=plan.templateer_digest,
            composer_digest=plan.composer_digest,
            render_digest=plan_digest(kept_files),
        )

    jj = JJ(project)
    with project_lock(project):
        if not (project / ".jj").exists():
            jj.run("git", "init", "--colocate")
            exclude_local_state(project)
            jj.run("commit", "-m", "copyroom:adoption baseline")
        else:
            exclude_local_state(project)
        before_tree = working_digest(project)
        project_head = jj.commit_id("@")
        project_id = uuid.uuid4().hex
        temporary_root = Path(tempfile.mkdtemp(prefix="copyroom-adopt-"))
        workspace_path = temporary_root / "workspace"
        workspace_name = f"copyroom-{uuid.uuid4().hex[:12]}"
        workspace_added = False
        operation = jj.operation_id()
        last_operation = operation
        try:
            root = jj.commit_id("root()")
            jj.run("workspace", "add", "--name", workspace_name, "-r", root, str(workspace_path))
            workspace_added = True
            clear_workspace(workspace_path)
            write_tree(workspace_path, plan.files)
            JJ(workspace_path).run(
                "commit", "-m", _render_subject(project_id, "base", 0, plan.source_digest),
            )
            render = JJ(workspace_path).commit_id("@-")
            last_operation = jj.operation_id()
            JJ(workspace_path).run("new", project_head, render, "-m", "copyroom:adoption merge")
            JJ(workspace_path).run("restore", "--from", project_head, "--into", "@")
            JJ(workspace_path).run("commit", "-m", "copyroom:adoption tree")
            merge = JJ(workspace_path).commit_id("@-")
            last_operation = jj.operation_id()
            if working_digest(workspace_path) != before_tree:
                raise LocalError("adoption merge did not preserve the project tree", 1)
            jj.run("new", merge, "-m", "copyroom:adopted project")
            last_operation = jj.operation_id()
            if working_digest(project) != before_tree:
                raise LocalError("adoption changed project files before marker write", 1)
            snapshot_source(source, project, plan.source_digest)
            data = marker_with_plan(plan, source, project_id)
            base_record = {**data["layers"]["base"], "omissions": omissions}
            data["layers"]["base"] = base_record
            data.update(base_record)
            write_json(project / MARKER, data)
            jj.run("commit", "-m", "copyroom:project inputs")
            last_operation = jj.operation_id()
            if jj.render_head(project_id, "base") != render:
                raise LocalError("adopted render head is wrong", 1)
        except Exception as exc:
            current_operation = jj.operation_id()
            if current_operation == last_operation:
                jj.run("op", "restore", operation)
                if workspace_added:
                    jj.run("workspace", "forget", workspace_name)
                shutil.rmtree(temporary_root, ignore_errors=True)
            elif isinstance(exc, LocalError):
                raise LocalError(
                    f"{exc}; repository advanced during adoption (saved operation {operation}, "
                    f"current operation {current_operation}); workspace kept at {workspace_path}",
                    exc.code,
                ) from exc
            else:
                raise LocalError(
                    f"adoption failed; repository advanced (saved operation {operation}, "
                    f"current operation {current_operation}); workspace kept at {workspace_path}",
                ) from exc
            raise
        jj.run("workspace", "forget", workspace_name)
        shutil.rmtree(temporary_root, ignore_errors=True)
    report["result"] = "adopted"
    report["render"] = render
    report["project_tree_preserved"] = True
    return report


def _template_literal(text: str) -> str:
    """Escape MiniJinja opening delimiters in verbatim source text."""

    return text.replace("{{", '{{ "{{" }}').replace("{%", '{{ "{%" }}').replace("{#", '{{ "{#" }}')


def _preserve_template_newline(template: str, original: str) -> str:
    """Keep one final newline after MiniJinja removes the template's last one."""

    if original.endswith(("\r", "\n")):
        return template + "\n"
    return template


def _line_endings(text: str) -> list[str]:
    """Return the source line endings in order."""

    return re.findall(r"\r\n|\r|\n", text)


def _language(path: str) -> str:
    """Choose a Templateer output language from a file suffix."""

    suffix = Path(path).suffix.lower()
    return {
        ".json": "json", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml",
        ".py": "python", ".md": "markdown", ".markdown": "markdown",
    }.get(suffix, "text")


def templatize(
    project: Path,
    target: Path,
    name: str | None = None,
    parameterize: list[str] | None = None,
) -> dict[str, Any]:
    """Extract a local Templateer source and prove an exact golden render."""

    project = normalize_path(project)
    target = normalize_path(target)
    _validate_disjoint(project, target)
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise LocalError(f"template target is not empty: {target}")
    project_name = name or project.name
    if not project_name:
        raise LocalError("project name cannot be empty", 3)
    if project_name != project.name and parameterize:
        raise LocalError("parameterized source must use the current project name as its default", 3)
    selected = set(parameterize or [])
    files = _project_files(project)
    unknown = selected - set(files)
    if unknown:
        raise LocalError("parameterize names missing project paths: " + ", ".join(sorted(unknown)), 3)

    target_existed = target.exists()
    target.mkdir(parents=True, exist_ok=True)
    (target / "templates").mkdir()
    manifest: dict[str, Any] = {
        "templates": [], "executable": [], "static": [], "symlinks": [], "line_endings": {},
    }
    answers = {"project_name": project_name}
    try:
        for index, (relative, (kind, content, mode)) in enumerate(sorted(files.items())):
            if kind == "symlink":
                target_text = content.decode("utf-8")
                manifest["symlinks"].append({"path": relative, "target": target_text})
                continue
            if kind != "file":
                raise LocalError(f"unsupported project file type: {relative}")
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError:
                static_path = f"static/{relative}"
                static_target = target / static_path
                static_target.parent.mkdir(parents=True, exist_ok=True)
                static_target.write_bytes(content)
                manifest["static"].append({
                    "path": relative,
                    "source": static_path,
                    "executable": bool(mode & 0o111),
                })
                continue
            template_name = f"file-{index:04d}"
            template_root = target / "templates" / template_name
            template_root.mkdir()
            template_text = _template_literal(text)
            if relative in selected:
                template_text = template_text.replace(project.name, "{{ project_name }}")
            template_text = _preserve_template_newline(template_text, text)
            manifest["line_endings"][relative] = _line_endings(text)
            (template_root / "template.j2").write_text(template_text, encoding="utf-8")
            (template_root / "schema.py").write_text(
                "from pydantic import BaseModel, Field\n\n\n"
                "class ProjectModel(BaseModel):\n"
                "    project_name: str = Field(min_length=1)\n",
                encoding="utf-8",
            )
            (template_root / "prompt.md").write_text(
                "Render the saved project text from the validated project_name field.\n",
                encoding="utf-8",
            )
            metadata = {
                "name": template_name,
                "description": f"Render {relative}",
                "output": {"kind": "full_file", "path": relative, "language": _language(relative)},
                "schema": {"module": "schema", "class": "ProjectModel"},
                "prompt": {"file": "prompt.md"},
                "renderer": {"engine": "minijinja", "file": "template.j2"},
            }
            (template_root / "metadata.yml").write_text(
                yaml.safe_dump(metadata, sort_keys=False), encoding="utf-8",
            )
            manifest["templates"].append(template_name)
            if mode & 0o111:
                manifest["executable"].append(relative)
        if not manifest["templates"]:
            raise LocalError("templatize needs at least one UTF-8 text file")
        (target / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8",
        )
        (target / "answers.json").write_text(
            json.dumps(answers, indent=2, sort_keys=True) + "\n", encoding="utf-8",
        )
        plan = compose(target, answers)
        current = _project_files(project)
        planned = _plan_files(plan)
        if current != planned:
            changed = sorted(
                path for path in set(current) | set(planned) if current.get(path) != planned.get(path)
            )
            details = {
                path: {
                    "source": (current.get(path, (None, b"", 0))[1][:200], current.get(path, (None, b"", 0))[2]),
                    "render": (planned.get(path, (None, b"", 0))[1][:200], planned.get(path, (None, b"", 0))[2]),
                }
                for path in changed
            }
            raise LocalError(f"templatize golden render differs from source: {details}", 1)
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        if target_existed:
            target.mkdir(parents=True, exist_ok=True)
        raise
    return {
        "source": str(target),
        "files": len(files),
        "templates": len(manifest["templates"]),
        "static": len(manifest["static"]),
        "symlinks": len(manifest["symlinks"]),
        "parameterized": sorted(selected),
        "golden_exact": True,
    }


__all__ = ["adopt", "compare", "templatize"]
