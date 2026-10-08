"""Local project lifecycle built on Templateer and plain jj."""

from __future__ import annotations

import base64
import hashlib
import os
import re
import shutil
import stat
import tempfile
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

from .composer import (
    FileEntry,
    RenderPlan,
    check_paths,
    compose,
    digest_bytes,
    digest_source,
    plan_digest,
)
from .errors import LocalError
from .jj import JJ, project_lock
from .source import (
    LOCK_FILE,
    MARKER,
    PREVIEW_DIR,
    SOURCE_DIR,
    exclude_local_state,
    marker,
    marker_with_plan,
    read_json,
    resolve_source,
    snapshot_path,
    snapshot_source,
    write_json,
)

PREVIEW_SUFFIX = ".copyroom-preview.json"
WORKSPACE_PREFIX = "copyroom-"
STATE_EXCLUDES = {".git", ".jj", ".devenv", ".direnv", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache"}


def normalize_path(path: Path) -> Path:
    """Return an absolute path with no ``..`` segment and no symlinked parent.

    Apply this rule at every entry point that takes a user path. The last
    segment keeps its name, so ``is_symlink()`` still sees a symlinked
    source. Check ``is_symlink()`` on the user path before you call this
    function, then use the result for all comparisons and stored values.
    """

    path = Path(path)
    if path.name in {"", ".", ".."}:
        return path.resolve()
    return path.parent.resolve() / path.name


def _refuse_symlink(source: Path) -> Path:
    """Reject a symlinked source, then return the normalized path."""

    if Path(source).is_symlink():
        raise LocalError(f"source must not be a symlink: {normalize_path(source)}")
    return normalize_path(source)


def _feed(digest: Any, data: bytes) -> None:
    digest.update(len(data).to_bytes(8, "big"))
    digest.update(data)


def working_files(root: Path) -> dict[str, tuple[str, bytes, int]]:
    """Read project files and symlinks, excluding jj and local preview state."""

    files: dict[str, tuple[str, bytes, int]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in STATE_EXCLUDES for part in relative.parts):
            continue
        if relative.as_posix() == LOCK_FILE or relative.parts[:2] == (".copyroom-local", "previews"):
            continue
        name = relative.as_posix()
        if path.is_symlink():
            files[name] = ("symlink", os.readlink(path).encode(), 0)
        elif path.is_file():
            files[name] = ("file", path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
    return files


def working_digest(root: Path) -> str:
    """Digest all project file paths, kinds, modes, and bytes."""

    digest = hashlib.sha256()
    for name, (kind, content, mode) in working_files(root).items():
        for item in (name.encode(), kind.encode(), f"{mode:o}".encode(), content):
            _feed(digest, item)
    return digest.hexdigest()


def _write_entry(root: Path, name: str, entry: FileEntry) -> None:
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() or target.exists():
        if target.is_dir() and not target.is_symlink():
            raise LocalError(f"cannot replace output file with a directory: {name}")
        target.unlink()
    if entry.kind == "symlink":
        link_target = entry.content.decode("utf-8")
        resolved = (target.parent / link_target).resolve(strict=False)
        if root.resolve() not in resolved.parents and resolved != root.resolve():
            raise LocalError(f"symlink target escapes the output tree: {name} -> {link_target}")
        target.symlink_to(link_target)
        return
    if entry.kind != "file":
        raise LocalError(f"unsupported output kind: {entry.kind}")
    target.write_bytes(entry.content)
    target.chmod(entry.mode)


def write_tree(root: Path, files: dict[str, FileEntry]) -> None:
    """Write a fully validated plan to a workspace."""

    for name, entry in sorted(files.items()):
        _write_entry(root, name, entry)


def clear_workspace(root: Path) -> None:
    """Remove tracked project files while preserving jj and git metadata."""

    for entry in root.iterdir():
        if entry.name in {".jj", ".git"}:
            continue
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()


def _validate_disjoint(source: Path, project: Path, allow_snapshot: bool = False) -> None:
    """Reject paths that can cause a render to consume or replace its source."""

    source = normalize_path(source)
    project = normalize_path(project)
    if source == project or project in source.parents or source in project.parents:
        if allow_snapshot and source.is_relative_to(project / SOURCE_DIR):
            return
        raise LocalError("source and project directories must be separate")


def _layer_record(data: dict[str, Any], layer: str) -> dict[str, Any]:
    """Return the marker record for one layer."""

    records = data.get("layers", {})
    if isinstance(records, dict) and isinstance(records.get(layer), dict):
        return records[layer]
    if layer == "base":
        return data
    raise LocalError(f"unknown layer: {layer}", 3)


def _owner_map(data: dict[str, Any]) -> dict[str, str]:
    """Return every active path owner."""

    records = data.get("layers", {})
    if not isinstance(records, dict):
        records = {"base": data}
    owners: dict[str, str] = {}
    for name, record in records.items():
        if not isinstance(record, dict) or not isinstance(record.get("owners"), dict):
            raise LocalError(f"invalid owner record for layer {name}")
        for path in record["owners"]:
            if path in owners:
                raise LocalError(f"path has multiple owners: {path} ({owners[path]}, {name})")
            owners[path] = str(name)
    return owners


def _preflight_paths(
    project: Path,
    data: dict[str, Any],
    layer: str,
    new_owners: dict[str, str],
) -> None:
    """Check a layer plan against all owners and project files."""

    records = data.get("layers", {"base": data})
    if not isinstance(records, dict):
        raise LocalError("invalid layer records in project marker")
    old_record = records.get(layer, {})
    if layer == "base" and not old_record:
        old_record = data
    if not isinstance(old_record, dict):
        raise LocalError(f"invalid layer record: {layer}")
    old_paths = set(old_record.get("owners", {}))
    other_paths = {
        path for name, record in records.items() if name != layer and isinstance(record, dict)
        for path in record.get("owners", {})
    }
    project_files = set(working_files(project))
    internal = {MARKER}
    internal.update(name for name in project_files if name.startswith(f"{SOURCE_DIR}/"))
    all_owned = other_paths | old_paths
    project_only = project_files - all_owned - internal
    for new_path in new_owners:
        collisions = other_paths | project_only
        check_paths([new_path, *collisions])


def _plan_record(plan: RenderPlan, source: Path, revision: int = 0) -> dict[str, Any]:
    """Build the marker data for one layer render."""

    return {
        "source": str(source),
        "source_digest": plan.source_digest,
        "manifest_digest": plan.manifest_digest,
        "templateer_version": plan.templateer_version,
        "templateer_digest": plan.templateer_digest,
        "composer_digest": plan.composer_digest,
        "answers": plan.answers,
        "owners": plan.owners,
        "revision": revision,
        "render_digest": plan.render_digest,
    }


def _frozen_plan(record: dict[str, Any]) -> RenderPlan:
    """Build a render plan from a frozen generated artifact."""

    generation = record.get("generation")
    if not isinstance(generation, dict):
        raise LocalError("generated layer has no frozen artifact")
    try:
        path = str(generation["output_path"])
        content = base64.b64decode(str(generation["artifact_base64"]), validate=True)
        mode = int(generation.get("mode", 0o644))
    except (KeyError, ValueError, TypeError) as exc:
        raise LocalError(f"invalid frozen generated artifact: {exc}") from exc
    files = {path: FileEntry("file", content, mode)}
    return RenderPlan(
        files=files,
        owners={path: f"generated:{generation['template_name']}"},
        answers=record["answers"],
        source_digest=record["source_digest"],
        manifest_digest=record["manifest_digest"],
        templateer_version=record["templateer_version"],
        templateer_digest=record["templateer_digest"],
        composer_digest=record["composer_digest"],
        render_digest=record["render_digest"],
    )


def _apply_omissions(plan: RenderPlan, record: dict[str, Any]) -> RenderPlan:
    """Keep adopted template-only paths out of every later render."""

    omissions = record.get("omissions", [])
    if not isinstance(omissions, list) or any(not isinstance(path, str) for path in omissions):
        raise LocalError("invalid conditional omissions in layer marker")
    if not omissions:
        return plan
    files = {path: entry for path, entry in plan.files.items() if path not in omissions}
    owners = {path: owner for path, owner in plan.owners.items() if path not in omissions}
    return replace(plan, files=files, owners=owners, render_digest=plan_digest(files))


def _render_subject(project_id: str, layer: str, revision: int, source_digest: str) -> str:
    return f"copyroom:render {project_id} {layer} {revision} {source_digest}"


def _check_operation_parent(jj: JJ, expected: str, action: str) -> str:
    """Reject a jj operation that another writer inserted into this action."""

    current = jj.operation_id()
    parents = jj.operation_parents(current)
    if parents != [expected]:
        found = ", ".join(parents) or "none"
        raise LocalError(
            f"{action} overlapped a jj operation: expected parent operation {expected}; "
            f"current operation {current} has parent(s) {found}. The preview is kept. "
            "Inspect jj op log and recover the foreign operation before retrying.",
            1,
        )
    return current


def _check_active_state(
    jj: JJ,
    project: Path,
    expected_head: str,
    expected_tree: str,
    expected_operation: str,
    action: str,
) -> None:
    """Check that the active project still matches its captured state."""

    current_head = jj.commit_id("@")
    current_tree = working_digest(project)
    current_operation = jj.operation_id()
    if (
        current_head != expected_head
        or current_tree != expected_tree
        or current_operation != expected_operation
    ):
        raise LocalError(
            f"active project changed during {action}: expected head {expected_head} and "
            f"operation {expected_operation}; found head {current_head} and operation "
            f"{current_operation}. Inspect jj op log and recover any concurrent work.",
            1,
        )


def _state_path(project: Path, workspace: str) -> Path:
    return project / PREVIEW_DIR / f"{workspace}.json"


def _preview_sidecar(out: Path) -> Path:
    return out.with_name(out.name + PREVIEW_SUFFIX)


def _store_preview_state(project: Path, out: Path, state: dict[str, Any]) -> None:
    write_json(_state_path(project, str(state["workspace"])), state)
    write_json(_preview_sidecar(out), state)


def _remove_preview_state(project: Path, out: Path, workspace: str) -> None:
    _state_path(project, workspace).unlink(missing_ok=True)
    _preview_sidecar(out).unlink(missing_ok=True)


def _snapshot_for_plan(source: Path, project: Path, out: Path, plan: RenderPlan) -> bool:
    """Put the source snapshot in the reviewed workspace when it is new."""

    target = snapshot_path(out, plan.source_digest)
    if target.exists():
        if digest_source(target) != plan.source_digest:
            raise LocalError(f"saved source snapshot has a digest mismatch: {target}")
        return False
    snapshot_source(source, out, plan.source_digest)
    return True


def new(source: Path, target: Path, answers_file: Path) -> dict[str, str]:
    """Create a project from one local Templateer source."""

    source = _refuse_symlink(source)
    target = normalize_path(target)
    _validate_disjoint(source, target)
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise LocalError(f"target is not empty: {target}")
    answers = read_json(answers_file)
    plan = compose(source, answers)
    existed = target.exists()
    target.mkdir(parents=True, exist_ok=True)
    jj = JJ(target)
    try:
        jj.run("git", "init", "--colocate")
        exclude_local_state(target)
        write_tree(target, plan.files)
        project_id = uuid.uuid4().hex
        jj.run("commit", "-m", _render_subject(project_id, "base", 0, plan.source_digest))
        render = jj.commit_id("@-")
        snapshot_source(source, target, plan.source_digest)
        data = marker_with_plan(plan, source, project_id)
        write_json(target / MARKER, data)
        jj.run("commit", "-m", "copyroom:project inputs")
    except Exception:
        clear_workspace(target)
        for name in (".jj", ".git"):
            path = target / name
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            elif path.exists() or path.is_symlink():
                path.unlink()
        if not existed:
            target.rmdir()
        raise
    return {"project": str(target), "project_id": project_id, "render": render}


def _attach_layer(
    project: Path,
    source: Path,
    plan: RenderPlan,
    layer: str,
    record_metadata: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Attach one prevalidated render as an independent layer."""

    project = normalize_path(project)
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", layer) or layer == "base":
        raise LocalError("layer name must start with a letter and use letters, digits, '_' or '-'", 3)
    source = _refuse_symlink(source)
    _validate_disjoint(source, project)
    jj = JJ(project)
    temporary_root = Path(tempfile.mkdtemp(prefix="copyroom-layer-"))
    workspace_path = temporary_root / "workspace"
    workspace_name = WORKSPACE_PREFIX + uuid.uuid4().hex[:12]
    workspace_added = False
    with project_lock(project):
        # Backfill the ignore rules before any JSON write. An older project lacks them.
        exclude_local_state(project)
        data = marker(project)
        records = data.get("layers", {"base": data})
        if not isinstance(records, dict):
            shutil.rmtree(temporary_root, ignore_errors=True)
            raise LocalError("invalid layer records in project marker")
        if layer in records:
            shutil.rmtree(temporary_root, ignore_errors=True)
            raise LocalError(f"layer already exists: {layer}", 3)
        _preflight_paths(project, data, layer, plan.owners)
        if digest_source(source) != plan.source_digest:
            shutil.rmtree(temporary_root, ignore_errors=True)
            raise LocalError("source changed after render", 1)
        operation = jj.operation_id()
        last_operation = operation
        try:
            root = jj.commit_id("root()")
            jj.run("workspace", "add", "--name", workspace_name, "-r", root, str(workspace_path))
            workspace_added = True
            clear_workspace(workspace_path)
            write_tree(workspace_path, plan.files)
            JJ(workspace_path).run(
                "commit", "-m", _render_subject(str(data["project_id"]), layer, 0, plan.source_digest),
            )
            render = JJ(workspace_path).commit_id("@-")
            last_operation = jj.operation_id()
            active_head = jj.commit_id("@")
            active_tree = working_digest(project)
            JJ(workspace_path).run("new", active_head, render, "-m", f"copyroom:layer {layer}")
            conflicts = JJ(workspace_path).conflicts()
            if conflicts:
                raise LocalError("layer add has conflicts: " + ", ".join(conflicts), 1)
            has_snapshot = snapshot_path(workspace_path, plan.source_digest).exists()
            snapshot_source(source, workspace_path, plan.source_digest)
            if not has_snapshot:
                JJ(workspace_path).run("commit", "-m", f"copyroom:source snapshot {plan.source_digest}")
            last_operation = jj.operation_id()
            reviewed_tree = working_digest(workspace_path)
            merge_head = JJ(workspace_path).commit_id("@")
            active_operation = jj.operation_id()
            _check_active_state(
                jj, project, active_head, active_tree, active_operation, "layer add",
            )
            jj.run("new", merge_head, "-m", f"copyroom:layer add {layer}")
            applied_head = jj.commit_id("@")
            last_operation = _check_operation_parent(jj, active_operation, "layer add")
            if jj.commit_id(f"{applied_head}-") != merge_head:
                raise LocalError("layer add did not apply its reviewed merge head", 1)
            if jj.conflicts() or working_digest(project) != reviewed_tree:
                raise LocalError("layer tree differs from its reviewed merge", 1)
            record = {
                **_plan_record(plan, source),
                "kind": "generated" if record_metadata else "template",
            }
            if record_metadata:
                record["generation"] = record_metadata
            next_data = {**data, "layers": {**records, layer: record}}
            write_json(project / MARKER, next_data)
            jj.run("commit", "-m", f"copyroom:layer marker {layer}")
            last_operation = jj.operation_id()
            if jj.render_head(str(data["project_id"]), layer) != render:
                raise LocalError("added layer render head is wrong", 1)
        except Exception as exc:
            current_operation = jj.operation_id()
            if current_operation == last_operation:
                jj.run("op", "restore", operation)
                if workspace_added:
                    jj.run("workspace", "forget", workspace_name)
                shutil.rmtree(temporary_root, ignore_errors=True)
            elif isinstance(exc, LocalError):
                raise LocalError(
                    f"{exc}; repository advanced during layer add (saved operation {operation}, "
                    f"current operation {current_operation}); workspace kept at {workspace_path}",
                    exc.code,
                ) from exc
            else:
                raise LocalError(
                    f"layer add failed; repository advanced (saved operation {operation}, "
                    f"current operation {current_operation}); workspace kept at {workspace_path}",
                ) from exc
            raise
        jj.run("workspace", "forget", workspace_name)
        shutil.rmtree(temporary_root, ignore_errors=True)
    return {"project": str(project), "layer": layer, "render": render}


def add_layer(
    project: Path,
    source: Path,
    answers_file: Path,
    layer: str,
) -> dict[str, str]:
    """Render and attach one independent local Templateer layer."""

    source = _refuse_symlink(source)
    plan = compose(source, read_json(answers_file))
    return _attach_layer(project, source, plan, layer)


def list_layers(project: Path) -> list[dict[str, Any]]:
    """List layer render heads and path owners."""

    project = normalize_path(project)
    data = marker(project)
    records = data.get("layers", {"base": data})
    if not isinstance(records, dict):
        raise LocalError("invalid layer records in project marker")
    jj = JJ(project)
    return [
        {
            "layer": name,
            "source": record["source"],
            "source_digest": record["source_digest"],
            "revision": record["revision"],
            "render_head": jj.render_head(str(data["project_id"]), str(name)),
            "owners": record["owners"],
        }
        for name, record in sorted(records.items())
    ]


def preview(
    project: Path,
    out: Path,
    source_override: Path | None = None,
    answers_file: Path | None = None,
    layer: str = "base",
    plan_override: RenderPlan | None = None,
    record_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Render and merge in a separate jj workspace."""

    project = normalize_path(project)
    out = normalize_path(out)
    if source_override is not None:
        source_override = _refuse_symlink(source_override)
    data = marker(project)
    record = _layer_record(data, layer)
    source = normalize_path(resolve_source(project, data, source_override, record))
    _validate_disjoint(source, project, allow_snapshot=source.is_relative_to(project / SOURCE_DIR))
    if out.exists() or _preview_sidecar(out).exists():
        raise LocalError(f"preview path already exists: {out}")
    if project == out or project in out.parents or out in project.parents:
        raise LocalError("preview must be outside the project")
    if source == out or source in out.parents or out in source.parents:
        raise LocalError("preview must be outside the source")
    answers = read_json(answers_file) if answers_file else record["answers"]
    if plan_override is not None:
        plan = plan_override
    elif record.get("kind") == "generated":
        plan = _frozen_plan(record)
    else:
        plan = compose(source, answers)
    plan = _apply_omissions(plan, record)
    _preflight_paths(project, data, layer, plan.owners)
    if (
        plan.render_digest == record["render_digest"]
        and plan.source_digest == record["source_digest"]
        and plan.answers == record["answers"]
        and plan.templateer_digest == record["templateer_digest"]
        and plan.composer_digest == record["composer_digest"]
        and (record_metadata is None or record_metadata == record.get("generation"))
    ):
        return {"result": "no-change", "project": str(project)}

    jj = JJ(project)
    with project_lock(project):
        # Backfill the ignore rules before any JSON write. An older project lacks them.
        exclude_local_state(project)
        # Read all active state after taking the lock.
        data = marker(project)
        record = _layer_record(data, layer)
        current_source = normalize_path(resolve_source(project, data, source_override, record))
        if current_source != source:
            raise LocalError("project source locator changed during render", 1)
        old_render = jj.render_head(str(data["project_id"]), layer)
        active_head = jj.commit_id("@")
        active_tree = working_digest(project)
        workspace_name = WORKSPACE_PREFIX + uuid.uuid4().hex[:12]
        added = False
        try:
            # A new workspace needs an existing parent directory.
            try:
                out.parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise LocalError(f"cannot create preview parent directory: {exc}", 2) from exc
            jj.run("workspace", "add", "--name", workspace_name, "-r", old_render, str(out))
            added = True
            clear_workspace(out)
            write_tree(out, plan.files)
            revision = int(record["revision"]) + 1
            JJ(out).run(
                "commit", "-m",
                _render_subject(str(data["project_id"]), layer, revision, plan.source_digest),
            )
            next_render = JJ(out).commit_id("@-")
            if JJ(out).commit_id(f"{next_render}-") != old_render:
                raise LocalError("new render has the wrong parent")
            if JJ(out).merge_base(active_head, next_render) != old_render:
                raise LocalError("project and render have the wrong merge base")
            JJ(out).run("new", active_head, next_render, "-m", "copyroom:preview")
            conflict_paths = JJ(out).conflicts()
            new_snapshot = _snapshot_for_plan(source, project, out, plan)
            if new_snapshot:
                # The source snapshot becomes part of the reviewed tree and is replayable.
                JJ(out).run("commit", "-m", f"copyroom:source snapshot {plan.source_digest}")
            preview_tree = working_digest(out)
            if jj.commit_id("@") != active_head or working_digest(project) != active_tree:
                raise LocalError("active project changed during preview", 1)
            state = {
                "schema": 1,
                "project": str(project),
                "project_id": data["project_id"],
                "layer": layer,
                "workspace": workspace_name,
                "path": str(out),
                "active_head": active_head,
                "active_tree": active_tree,
                "marker_digest": digest_bytes((project / MARKER).read_bytes()),
                "old_render": old_render,
                "next_render": next_render,
                "preview_head": JJ(out).commit_id("@"),
                "preview_tree": preview_tree,
                "revision": revision,
                "source": str(source),
                "source_digest": plan.source_digest,
                "manifest_digest": plan.manifest_digest,
                "templateer_version": plan.templateer_version,
                "templateer_digest": plan.templateer_digest,
                "composer_digest": plan.composer_digest,
                "answers": plan.answers,
                "owners": plan.owners,
                "render_digest": plan.render_digest,
                "conflicts": conflict_paths,
                "record_metadata": record_metadata,
            }
            _store_preview_state(project, out, state)
        except Exception:
            if added:
                jj.run("workspace", "forget", workspace_name)
            if out.exists():
                shutil.rmtree(out)
            _preview_sidecar(out).unlink(missing_ok=True)
            _state_path(project, workspace_name).unlink(missing_ok=True)
            raise
    return state


def _load_preview(out: Path) -> dict[str, Any]:
    """Load and validate a preview sidecar."""

    out = normalize_path(out)
    if not out.is_dir() or not (out / ".jj").exists():
        raise LocalError(f"preview workspace is missing: {out}")
    state = read_json(_preview_sidecar(out))
    required = {
        "schema", "project", "project_id", "layer", "workspace", "path", "active_head", "active_tree",
        "marker_digest", "old_render", "next_render", "preview_head", "preview_tree", "revision",
        "source", "source_digest", "manifest_digest", "templateer_version", "templateer_digest",
        "composer_digest", "answers", "owners", "render_digest", "conflicts",
        "record_metadata",
    }
    if (
        state.get("schema") != 1 or not required <= state.keys()
        or not str(state["workspace"]).startswith(WORKSPACE_PREFIX)
        or normalize_path(Path(str(state["path"]))) != out
    ):
        raise LocalError("unsupported preview state")
    return state


def _discard(project: Path, out: Path, state: dict[str, Any]) -> None:
    """Forget and remove a preview workspace."""

    JJ(project).run("workspace", "forget", str(state["workspace"]))
    shutil.rmtree(out)
    _remove_preview_state(project, out, str(state["workspace"]))


def apply(project: Path, out: Path) -> dict[str, str]:
    """Apply the reviewed preview tree and record its source state."""

    project = normalize_path(project)
    out = normalize_path(out)
    state = _load_preview(out)
    if normalize_path(Path(str(state["project"]))) != project:
        raise LocalError("preview belongs to another project", 1)
    jj = JJ(project)
    with project_lock(project):
        # Backfill the ignore rules before any JSON write. An older project lacks them.
        exclude_local_state(project)
        data = marker(project)
        if state["project_id"] != data["project_id"]:
            raise LocalError("preview belongs to another project", 1)
        layer = str(state["layer"])
        record = _layer_record(data, layer)
        if jj.commit_id("@") != state["active_head"] or working_digest(project) != state["active_tree"]:
            raise LocalError("active project changed after preview", 1)
        if digest_bytes((project / MARKER).read_bytes()) != state["marker_digest"]:
            raise LocalError("project marker changed after preview", 1)
        if jj.render_head(str(data["project_id"]), layer) != state["old_render"]:
            raise LocalError("render head changed after preview", 1)
        if jj.commit_id(f"{state['next_render']}-") != state["old_render"]:
            raise LocalError("preview render has the wrong parent", 1)

        preview_jj = JJ(out)
        current_conflicts = preview_jj.conflicts()
        if current_conflicts:
            raise LocalError(
                "preview has unresolved conflicts: " + ", ".join(current_conflicts), 1,
            )
        preview_head = preview_jj.commit_id("@")
        preview_tree = working_digest(out)
        if state["conflicts"]:
            if (
                preview_jj.merge_base(preview_head, str(state["active_head"]))
                != state["active_head"]
                or preview_jj.merge_base(preview_head, str(state["next_render"]))
                != state["next_render"]
            ):
                raise LocalError("resolved preview no longer has the reviewed parents", 1)
        elif preview_head != state["preview_head"] or preview_tree != state["preview_tree"]:
            raise LocalError("preview workspace changed after preview", 1)
        preview_marker = out / MARKER
        if not preview_marker.is_file() or digest_bytes(preview_marker.read_bytes()) != state["marker_digest"]:
            raise LocalError("preview changed a protected project marker", 1)

        operation = jj.operation_id()
        _check_active_state(
            jj, project, str(state["active_head"]), str(state["active_tree"]), operation,
            "apply",
        )
        last_operation = operation
        try:
            jj.run("new", preview_head, "-m", "copyroom:update")
            applied_head = jj.commit_id("@")
            last_operation = _check_operation_parent(jj, operation, "apply")
            if jj.commit_id(f"{applied_head}-") != preview_head:
                raise LocalError("apply did not use its reviewed preview head", 1)
            applied_tree = working_digest(project)
            if jj.conflicts() or applied_tree != preview_tree:
                expected_files = working_files(out)
                applied_files = working_files(project)
                different = sorted(
                    name for name in set(expected_files) | set(applied_files)
                    if expected_files.get(name) != applied_files.get(name)
                )
                detail = {
                    name: {
                        "preview": expected_files.get(name),
                        "project": applied_files.get(name),
                    }
                    for name in different
                }
                raise LocalError(
                    "applied tree differs from the reviewed preview "
                    f"(expected {preview_tree}, got {applied_tree}; paths: {detail})",
                    1,
                )
            updated_record = {
                **record,
                "source": state["source"],
                "source_digest": state["source_digest"],
                "manifest_digest": state["manifest_digest"],
                "templateer_version": state["templateer_version"],
                "templateer_digest": state["templateer_digest"],
                "composer_digest": state["composer_digest"],
                "answers": state["answers"],
                "owners": state["owners"],
                "revision": state["revision"],
                "render_digest": state["render_digest"],
            }
            if state.get("record_metadata"):
                updated_record["generation"] = state["record_metadata"]
                updated_record["kind"] = "generated"
            records = data.get("layers", {"base": data})
            if not isinstance(records, dict):
                raise LocalError("invalid layer records in project marker")
            next_data = {**data, "layers": {**records, layer: updated_record}}
            if layer == "base":
                next_data.update(updated_record)
            write_json(project / MARKER, next_data)
            jj.run("commit", "-m", "copyroom:project inputs")
            last_operation = jj.operation_id()
            if jj.render_head(str(data["project_id"]), layer) != state["next_render"]:
                raise LocalError("applied render head is wrong", 1)
        except Exception as exc:
            current_operation = jj.operation_id()
            if current_operation == last_operation:
                jj.run("op", "restore", operation)
            elif isinstance(exc, LocalError):
                raise LocalError(
                    f"{exc}; repository advanced during apply (saved operation {operation}, "
                    f"current operation {current_operation}); preview kept for review",
                    exc.code,
                ) from exc
            else:
                raise LocalError(
                    f"apply failed; repository advanced (saved operation {operation}, "
                    f"current operation {current_operation}); preview kept for review",
                ) from exc
            raise
        _discard(project, out, state)
    return {"project": str(project), "render": str(state["next_render"])}


def update(project: Path, out: Path) -> dict[str, str]:
    """Compatibility name for apply."""

    return apply(project, out)


def discard(out: Path) -> dict[str, str]:
    """Discard a preview workspace without changing the project."""

    out = normalize_path(out)
    state = _load_preview(out)
    project = normalize_path(Path(str(state["project"])))
    with project_lock(project):
        current = marker(project)
        if current["project_id"] != state["project_id"]:
            raise LocalError("preview belongs to another project", 1)
        _discard(project, out, state)
    return {"result": "discarded", "preview": str(out)}


def list_previews(project: Path) -> list[dict[str, Any]]:
    """List saved preview workspaces for one project."""

    project = normalize_path(project)
    marker_data = marker(project)
    states: list[dict[str, Any]] = []
    directory = project / PREVIEW_DIR
    if not directory.is_dir():
        return states
    for path in sorted(directory.glob("*.json")):
        state = read_json(path)
        if state.get("project_id") != marker_data["project_id"]:
            continue
        states.append({
            "workspace": state.get("workspace"),
            "path": state.get("path"),
            "conflicts": state.get("conflicts", []),
            "source_digest": state.get("source_digest"),
        })
    return states


def inspect(project: Path) -> dict[str, Any]:
    """Return full project state for structured output."""

    project = normalize_path(project)
    data = marker(project)
    records = data.get("layers", {"base": data})
    if not isinstance(records, dict):
        raise LocalError("invalid layer records in project marker")
    jj = JJ(project)
    layers: dict[str, Any] = {}
    for name, record in records.items():
        source = Path(str(record["source"]))
        source_ok = source.is_dir() and not source.is_symlink()
        if source_ok:
            try:
                source_ok = digest_source(source) == record["source_digest"]
            except LocalError:
                source_ok = False
        snapshot = snapshot_path(project, str(record["source_digest"]))
        snapshot_ok = snapshot.is_dir() and digest_source(snapshot) == record["source_digest"]
        layers[str(name)] = {
            "source": record["source"],
            "source_digest": record["source_digest"],
            "source_reachable": source_ok,
            "snapshot_reachable": snapshot_ok,
            "revision": record["revision"],
            "render_head": jj.render_head(str(data["project_id"]), str(name)),
            "owners": record["owners"],
        }
    return {
        "project": str(project),
        "project_id": data["project_id"],
        "revision": data["revision"],
        "source": data["source"],
        "source_digest": data["source_digest"],
        "source_reachable": layers["base"]["source_reachable"],
        "snapshot_reachable": layers["base"]["snapshot_reachable"],
        "render_head": layers["base"]["render_head"],
        "layers": layers,
        "working_tree_digest": working_digest(project),
        "pending_previews": list_previews(project),
        "conflicts": jj.conflicts(),
        "owners": _owner_map(data),
        "answers": data["answers"],
    }


def status(project: Path) -> dict[str, Any]:
    """Return a concise project status report."""

    report = inspect(project)
    report["ok"] = all(
        item["source_reachable"] or item["snapshot_reachable"]
        for item in report["layers"].values()
    )
    report["has_conflicts"] = bool(report["conflicts"])
    return report


def doctor() -> dict[str, Any]:
    """Check local workflow dependencies."""

    import importlib.metadata
    import shutil

    try:
        templateer_version = importlib.metadata.version("templateer")
        templateer_ok = True
    except importlib.metadata.PackageNotFoundError:
        templateer_version = None
        templateer_ok = False
    jj_path = shutil.which("jj")
    return {
        "ok": templateer_ok and jj_path is not None,
        "templateer": templateer_version,
        "jj": jj_path,
    }


__all__ = [
    "add_layer", "apply", "discard", "doctor", "inspect", "list_layers", "list_previews",
    "new", "preview", "status", "update", "working_digest", "working_files",
]
