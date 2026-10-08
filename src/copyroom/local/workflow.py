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
from collections.abc import Callable
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
    JOURNAL_DIR,
    LOCK_FILE,
    MARKER,
    PREVIEW_DIR,
    SOURCE_DIR,
    TEMP_PREFIX,
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
        if relative.parts[:2] == (".copyroom-local", "journal"):
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


def tracked_tree_digest(root: Path, jj: JJ | None = None, rev: str = "@") -> str:
    """Digest only files in one jj revision's tracked tree."""

    jj = jj or JJ(root)
    tracked = jj.tracked_paths(rev)
    digest = hashlib.sha256()
    for name in sorted(tracked):
        path = root / name
        if path.is_symlink():
            kind, content, mode = "symlink", os.readlink(path).encode(), 0
        elif path.is_file():
            kind = "file"
            content = path.read_bytes()
            mode = stat.S_IMODE(path.stat().st_mode)
        elif path.is_dir():
            kind, content = "directory", b""
            mode = stat.S_IMODE(path.stat().st_mode)
        else:
            raise LocalError(f"jj-tracked path is missing from the working copy: {name}", 1)
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
    tracked_paths: set[str] | None = None,
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
    if tracked_paths is not None:
        for name in new_owners:
            path = project / name
            if (path.exists() or path.is_symlink()) and name not in tracked_paths:
                raise LocalError(f"render-owned path is not tracked by jj: {name}", 1)
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
    current_tree = tracked_tree_digest(project, jj)
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


def _verify_published(
    project: Path,
    jj: JJ,
    expected_head: str,
    expected_tree: str,
    expected_marker: str,
    project_id: str,
    layer: str,
    expected_render: str,
) -> list[str]:
    """List every way the published result differs from the prepared result."""

    problems: list[str] = []

    def check(label: str, action: Callable[[], None]) -> None:
        try:
            action()
        except Exception as exc:
            problems.append(f"could not verify {label}: {exc}")

    def check_parent() -> None:
        applied_head = jj.commit_id("@")
        applied_parent = jj.commit_id(f"{applied_head}-")
        if applied_parent != expected_head:
            problems.append(
                f"active head parent is {applied_parent}, expected {expected_head}",
            )

    def check_conflicts() -> None:
        conflicts = jj.conflicts()
        if conflicts:
            problems.append("active project has conflicts: " + ", ".join(conflicts))

    def check_tree() -> None:
        actual_tree = tracked_tree_digest(project, jj)
        if actual_tree != expected_tree:
            problems.append(
                f"active tree is {actual_tree}, expected {expected_tree}",
            )

    def check_marker() -> None:
        marker_path = project / MARKER
        if not marker_path.is_file():
            problems.append("active marker is missing")
            return
        actual_marker = digest_bytes(marker_path.read_bytes())
        if actual_marker != expected_marker:
            problems.append(
                f"active marker digest is {actual_marker}, expected {expected_marker}",
            )

    def check_render() -> None:
        actual_render = jj.render_head(project_id, layer)
        if actual_render != expected_render:
            problems.append(
                f"render head is {actual_render}, expected {expected_render}",
            )

    check("active head parent", check_parent)
    check("active conflicts", check_conflicts)
    check("active tree", check_tree)
    check("active marker", check_marker)
    check("render head", check_render)
    return problems


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


def _journal_path(project: Path, workspace: str) -> Path:
    return project / JOURNAL_DIR / f"{workspace}.json"


def _write_journal(project: Path, journal: dict[str, Any]) -> Path:
    path = _journal_path(project, str(journal["workspace"]))
    write_json(path, journal)
    return path


def _set_journal_phase(
    project: Path,
    journal: dict[str, Any],
    phase: str,
    state: dict[str, Any] | None = None,
    **changes: Any,
) -> dict[str, Any]:
    """Persist a transaction phase before syncing its preview state."""

    journal.update(changes)
    journal["journal_state"] = phase
    if state is not None:
        state["journal_state"] = phase
        journal["preview_state"] = state
    _write_journal(project, journal)
    if state is not None:
        _store_preview_state(project, Path(str(state["path"])), state)
    return journal


def _cleanup_transaction(project: Path, journal: dict[str, Any]) -> None:
    """Finish cleanup for one published or discarded transaction."""

    if normalize_path(Path(str(journal.get("project", "")))) != project:
        raise LocalError("transaction journal names another project")
    jj = JJ(project)
    workspace = str(journal["workspace"])
    if not workspace.startswith(WORKSPACE_PREFIX):
        raise LocalError("transaction journal has an invalid workspace name")
    workspace_path = normalize_path(Path(str(journal["workspace_path"])))
    kind = journal.get("kind")
    temporary_path: Path | None = None
    if kind == "layer_add":
        temporary_path = normalize_path(Path(str(journal.get("temporary_path", ""))))
        if (
            temporary_path.parent != Path(tempfile.gettempdir()).resolve()
            or not temporary_path.name.startswith("copyroom-layer-")
            or workspace_path != temporary_path / "workspace"
            or workspace_path.is_symlink()
        ):
            raise LocalError("transaction journal has an unsafe layer path")
    elif kind == "update":
        if (
            project in workspace_path.parents
            or workspace_path == project
            or workspace_path in project.parents
            or workspace_path.is_symlink()
        ):
            raise LocalError("transaction journal has an unsafe preview path")
    else:
        raise LocalError("transaction journal has an unknown kind")

    registered = {row["name"] for row in jj.workspaces()}
    if workspace in registered:
        jj.run("workspace", "forget", workspace)

    if temporary_path is not None:
        if temporary_path.is_dir():
            shutil.rmtree(temporary_path)
    else:
        if workspace_path.is_dir():
            shutil.rmtree(workspace_path)
        _state_path(project, workspace).unlink(missing_ok=True)
        _preview_sidecar(workspace_path).unlink(missing_ok=True)

    _journal_path(project, workspace).unlink(missing_ok=True)


def _snapshot_for_plan(source: Path, project: Path, out: Path, plan: RenderPlan) -> bool:
    """Put the source snapshot in the reviewed workspace when it is new."""

    target = snapshot_path(out, plan.source_digest)
    if target.exists():
        if digest_source(target) != plan.source_digest:
            raise LocalError(f"saved source snapshot has a digest mismatch: {target}")
        return False
    snapshot_source(source, out, plan.source_digest)
    return True


def _next_marker(
    data: dict[str, Any],
    record: dict[str, Any],
    layer: str,
    source: Path,
    plan: RenderPlan,
    revision: int,
    record_metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build the marker for a prepared render."""

    updated_record = {
        **record,
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
    if record_metadata:
        updated_record["generation"] = record_metadata
        updated_record["kind"] = "generated"
    records = data.get("layers", {"base": data})
    if not isinstance(records, dict):
        raise LocalError("invalid layer records in project marker")
    next_data = {**data, "layers": {**records, layer: updated_record}}
    if layer == "base":
        next_data.update(updated_record)
    return next_data


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
    temporary_root = Path(tempfile.gettempdir()) / f"copyroom-layer-{uuid.uuid4().hex}"
    workspace_path = temporary_root / "workspace"
    workspace_name = WORKSPACE_PREFIX + uuid.uuid4().hex[:12]
    with project_lock(project):
        # Backfill the ignore rules before any JSON write. An older project lacks them.
        exclude_local_state(project)
        data = marker(project)
        records = data.get("layers", {"base": data})
        if not isinstance(records, dict):
            raise LocalError("invalid layer records in project marker")
        if layer in records:
            raise LocalError(f"layer already exists: {layer}", 3)
        _preflight_paths(
            project, data, layer, plan.owners, tracked_paths=jj.tracked_paths("@"),
        )
        if digest_source(source) != plan.source_digest:
            raise LocalError("source changed after render", 1)
        active_head = jj.commit_id("@")
        active_tree = tracked_tree_digest(project, jj)
        journal = {
            "schema": 1,
            "kind": "layer_add",
            "journal_state": "prepared",
            "project": str(project),
            "project_id": data["project_id"],
            "layer": layer,
            "workspace": workspace_name,
            "workspace_path": str(workspace_path),
            "temporary_path": str(temporary_root),
            "active_head": active_head,
            "active_tree": active_tree,
            "marker_digest": digest_bytes((project / MARKER).read_bytes()),
            "old_render": None,
            "next_render": None,
            "prepared_head": None,
            "prepared_tree": None,
            "prepared_marker_digest": None,
        }
        _write_journal(project, journal)
        workspace_added = False
        publication_returned = False
        publication_error_handled = False
        try:
            temporary_root.mkdir()
            root = jj.commit_id("root()")
            jj.run("workspace", "add", "--name", workspace_name, "-r", root, str(workspace_path))
            workspace_added = True
            clear_workspace(workspace_path)
            write_tree(workspace_path, plan.files)
            JJ(workspace_path).run(
                "commit", "-m", _render_subject(str(data["project_id"]), layer, 0, plan.source_digest),
            )
            render = JJ(workspace_path).commit_id("@-")
            journal["old_render"] = jj.render_head(str(data["project_id"]), layer) if layer in records else None
            JJ(workspace_path).run("new", active_head, render, "-m", f"copyroom:layer {layer}")
            conflicts = JJ(workspace_path).conflicts()
            if conflicts:
                raise LocalError("layer add has conflicts: " + ", ".join(conflicts), 1)
            has_snapshot = snapshot_path(workspace_path, plan.source_digest).exists()
            snapshot_source(source, workspace_path, plan.source_digest)
            if not has_snapshot:
                JJ(workspace_path).run("commit", "-m", f"copyroom:source snapshot {plan.source_digest}")

            next_data = _next_marker(
                data, {}, layer, source, plan, 0, record_metadata,
            )
            next_records = next_data["layers"]
            if not record_metadata:
                next_records[layer]["kind"] = "template"
            write_json(workspace_path / MARKER, next_data)
            preview_jj = JJ(workspace_path)
            preview_jj.run("commit", "-m", "copyroom:project inputs")
            prepared_head = preview_jj.commit_id("@")
            prepared_tree = tracked_tree_digest(workspace_path, preview_jj)
            prepared_marker_digest = digest_bytes((workspace_path / MARKER).read_bytes())

            active_operation = jj.operation_id()
            _check_active_state(
                jj, project, active_head, active_tree, active_operation, "layer add",
            )
            _set_journal_phase(
                project,
                journal,
                "prepared",
                next_render=render,
                prepared_head=prepared_head,
                prepared_tree=prepared_tree,
                prepared_marker_digest=prepared_marker_digest,
            )
            _set_journal_phase(project, journal, "publishing")
            try:
                jj.run("new", prepared_head, "-m", f"copyroom:layer add {layer}")
            except Exception as exc:
                publication_error_handled = True
                try:
                    row = _reconcile_journal(project, jj, journal)
                except Exception as recovery_error:
                    raise LocalError(
                        f"layer add outcome is uncertain; run copyroom recover: {recovery_error}", 1,
                    ) from exc
                if row.get("journal_state") == "published":
                    return {"project": str(project), "layer": layer, "render": render}
                if isinstance(exc, LocalError):
                    raise LocalError(
                        f"{exc}; {row['action']}; run copyroom recover",
                        exc.code,
                    ) from exc
                raise LocalError(
                    f"layer add failed; {row['action']}; run copyroom recover",
                ) from exc
            publication_returned = True
            problems = _verify_published(
                project,
                jj,
                prepared_head,
                prepared_tree,
                prepared_marker_digest,
                str(data["project_id"]),
                layer,
                render,
            )
            if problems:
                _set_journal_phase(
                    project, journal, "publishing", verification=problems,
                )
                raise LocalError(
                    "published result does not match the prepared layer; run copyroom recover: "
                    + "; ".join(problems),
                    1,
                )
            _set_journal_phase(project, journal, "published")
            _cleanup_transaction(project, journal)
        except Exception:
            if publication_returned or publication_error_handled:
                raise
            if workspace_added and workspace_name in {row["name"] for row in jj.workspaces()}:
                jj.run("workspace", "forget", workspace_name)
            shutil.rmtree(temporary_root, ignore_errors=True)
            _journal_path(project, workspace_name).unlink(missing_ok=True)
            raise
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
    jj = JJ(project)
    _preflight_paths(
        project, data, layer, plan.owners, tracked_paths=jj.tracked_paths("@"),
    )
    if (
        plan.render_digest == record["render_digest"]
        and plan.source_digest == record["source_digest"]
        and plan.answers == record["answers"]
        and plan.templateer_digest == record["templateer_digest"]
        and plan.composer_digest == record["composer_digest"]
        and (record_metadata is None or record_metadata == record.get("generation"))
    ):
        return {"result": "no-change", "project": str(project)}

    with project_lock(project):
        # Backfill the ignore rules before any JSON write. An older project lacks them.
        exclude_local_state(project)
        # Read all active state after taking the lock.
        data = marker(project)
        record = _layer_record(data, layer)
        current_source = normalize_path(resolve_source(project, data, source_override, record))
        if current_source != source:
            raise LocalError("project source locator changed during render", 1)
        _preflight_paths(
            project, data, layer, plan.owners, tracked_paths=jj.tracked_paths("@"),
        )
        old_render = jj.render_head(str(data["project_id"]), layer)
        active_head = jj.commit_id("@")
        active_tree = tracked_tree_digest(project, jj)
        workspace_name = WORKSPACE_PREFIX + uuid.uuid4().hex[:12]
        journal = {
            "schema": 1,
            "kind": "update",
            "journal_state": "prepared",
            "project": str(project),
            "project_id": data["project_id"],
            "layer": layer,
            "workspace": workspace_name,
            "workspace_path": str(out),
            "temporary_path": None,
            "active_head": active_head,
            "active_tree": active_tree,
            "marker_digest": digest_bytes((project / MARKER).read_bytes()),
            "old_render": old_render,
            "next_render": None,
            "prepared_head": None,
            "prepared_tree": None,
            "prepared_marker_digest": None,
        }
        journal_file = _write_journal(project, journal)
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
            next_data = _next_marker(
                data, record, layer, source, plan, revision, record_metadata,
            )
            write_json(out / MARKER, next_data)
            preview_jj = JJ(out)
            preview_jj.run("commit", "-m", "copyroom:project inputs")
            preview_head = preview_jj.commit_id("@")
            preview_tree = tracked_tree_digest(out, preview_jj)
            prepared_marker_digest = digest_bytes((out / MARKER).read_bytes())
            if jj.commit_id("@") != active_head or tracked_tree_digest(project, jj) != active_tree:
                raise LocalError("active project changed during preview", 1)
            state = {
                "schema": 2,
                "project": str(project),
                "project_id": data["project_id"],
                "layer": layer,
                "workspace": workspace_name,
                "path": str(out),
                "active_head": active_head,
                "active_tree": active_tree,
                "marker_digest": digest_bytes((project / MARKER).read_bytes()),
                "prepared_marker_digest": prepared_marker_digest,
                "old_render": old_render,
                "next_render": next_render,
                "preview_head": preview_head,
                "prepared_head": preview_head,
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
                "journal_state": "prepared",
            }
            _set_journal_phase(
                project,
                journal,
                "prepared",
                state,
                next_render=next_render,
                prepared_head=preview_head,
                prepared_tree=preview_tree,
                prepared_marker_digest=prepared_marker_digest,
            )
        except Exception:
            if added:
                jj.run("workspace", "forget", workspace_name)
            if out.exists():
                shutil.rmtree(out)
            _preview_sidecar(out).unlink(missing_ok=True)
            _state_path(project, workspace_name).unlink(missing_ok=True)
            journal_file.unlink(missing_ok=True)
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
        "marker_digest", "prepared_marker_digest", "old_render", "next_render", "preview_head",
        "prepared_head", "preview_tree", "revision",
        "source", "source_digest", "manifest_digest", "templateer_version", "templateer_digest",
        "composer_digest", "answers", "owners", "render_digest", "conflicts",
        "record_metadata",
    }
    if (
        state.get("schema") != 2 or not required <= state.keys()
        or not str(state["workspace"]).startswith(WORKSPACE_PREFIX)
        or normalize_path(Path(str(state["path"]))) != out
    ):
        raise LocalError("unsupported preview state")
    return state


def _discard(project: Path, out: Path, state: dict[str, Any]) -> None:
    """Forget and remove a preview workspace."""

    journal_file = _journal_path(project, str(state["workspace"]))
    if journal_file.is_file():
        _cleanup_transaction(project, read_json(journal_file))
        return
    JJ(project).run("workspace", "forget", str(state["workspace"]))
    if out.is_dir():
        shutil.rmtree(out)
    _remove_preview_state(project, out, str(state["workspace"]))


def _journal_from_preview_state(project: Path, state: dict[str, Any]) -> dict[str, Any]:
    """Build a prepared journal for a preview made by an earlier CopyRoom version."""

    return {
        "schema": 1,
        "kind": "update",
        "journal_state": "prepared",
        "project": str(project),
        "project_id": state["project_id"],
        "layer": state["layer"],
        "workspace": state["workspace"],
        "workspace_path": state["path"],
        "temporary_path": None,
        "active_head": state["active_head"],
        "active_tree": state["active_tree"],
        "marker_digest": state["marker_digest"],
        "old_render": state["old_render"],
        "next_render": state["next_render"],
        "prepared_head": state["prepared_head"],
        "prepared_tree": state["preview_tree"],
        "prepared_marker_digest": state["prepared_marker_digest"],
        "preview_state": state,
    }


def _ensure_preview_journal(project: Path, state: dict[str, Any]) -> dict[str, Any]:
    """Load a preview journal or add one to a saved preview from Step 1."""

    path = _journal_path(project, str(state["workspace"]))
    if path.is_file():
        return read_json(path)
    journal = _journal_from_preview_state(project, state)
    _write_journal(project, journal)
    return journal


def _is_ancestor(jj: JJ, ancestor: str, descendant: str) -> bool:
    return jj.merge_base(descendant, ancestor) == ancestor


def _journal_state(project: Path, journal: dict[str, Any]) -> dict[str, Any] | None:
    embedded = journal.get("preview_state")
    if isinstance(embedded, dict):
        return dict(embedded)
    workspace = str(journal["workspace"])
    for path in (
        _state_path(project, workspace),
        _preview_sidecar(Path(str(journal["workspace_path"]))),
    ):
        if path.is_file():
            try:
                return read_json(path)
            except LocalError:
                continue
    return None


def _journal_row(journal: dict[str, Any], action: str) -> dict[str, Any]:
    return {
        "workspace": journal.get("workspace"),
        "kind": journal.get("kind"),
        "layer": journal.get("layer"),
        "journal_state": journal.get("journal_state"),
        "prepared_head": journal.get("prepared_head"),
        "action": action,
    }


def _publish_layer_transaction(
    project: Path,
    jj: JJ,
    journal: dict[str, Any],
) -> dict[str, Any]:
    """Publish a prepared layer when its active head is still current."""

    active_head = jj.commit_id("@")
    if (
        active_head != journal.get("active_head")
        or tracked_tree_digest(project, jj) != journal.get("active_tree")
        or digest_bytes((project / MARKER).read_bytes()) != journal.get("marker_digest")
    ):
        return _journal_row(journal, "project-moved; retry layer add")
    prepared_head = str(journal["prepared_head"])
    state = _journal_state(project, journal)
    workspace_path = Path(str(journal["workspace_path"]))
    if not workspace_path.is_dir():
        return _journal_row(journal, "prepared workspace missing; retry layer add")
    prepared_jj = JJ(workspace_path)
    if (
        prepared_jj.commit_id("@") != prepared_head
        or tracked_tree_digest(workspace_path, prepared_jj) != journal.get("prepared_tree")
        or digest_bytes((workspace_path / MARKER).read_bytes())
        != journal.get("prepared_marker_digest")
    ):
        return _journal_row(journal, "prepared layer changed; retry layer add")
    _set_journal_phase(project, journal, "publishing", state)
    try:
        jj.run("new", prepared_head, "-m", f"copyroom:layer add {journal['layer']}")
    except Exception:
        try:
            current_head = jj.commit_id("@")
            published = _is_ancestor(jj, prepared_head, current_head)
            if published and journal.get("next_render"):
                current_render = jj.render_head(str(journal["project_id"]), str(journal["layer"]))
                published = _is_ancestor(jj, str(journal["next_render"]), current_render)
        except LocalError:
            return _journal_row(journal, "publication-uncertain; run recover again")
        if published:
            problems = _verify_published(
                project,
                jj,
                prepared_head,
                str(journal["prepared_tree"]),
                str(journal["prepared_marker_digest"]),
                str(journal["project_id"]),
                str(journal["layer"]),
                str(journal["next_render"]),
            )
            if problems:
                _set_journal_phase(
                    project, journal, "publishing", state, verification=problems,
                )
                return _journal_row(
                    journal,
                    "published but unverified; inspect the project: " + "; ".join(problems),
                )
            _set_journal_phase(project, journal, "published", state)
            _cleanup_transaction(project, journal)
            return _journal_row(journal, "published and cleaned after command error")
        _set_journal_phase(project, journal, "prepared", state)
        return _journal_row(journal, "publication did not complete; retry layer add")

    problems = _verify_published(
        project,
        jj,
        prepared_head,
        str(journal["prepared_tree"]),
        str(journal["prepared_marker_digest"]),
        str(journal["project_id"]),
        str(journal["layer"]),
        str(journal["next_render"]),
    )
    if problems:
        _set_journal_phase(project, journal, "publishing", state, verification=problems)
        return _journal_row(
            journal,
            "published but unverified; inspect the project: " + "; ".join(problems),
        )
    _set_journal_phase(project, journal, "published", state)
    _cleanup_transaction(project, journal)
    return _journal_row(journal, "published and cleaned")


def _reconcile_journal(project: Path, jj: JJ, journal: dict[str, Any]) -> dict[str, Any]:
    """Reconcile one journal with the active jj history."""

    journal_file = _journal_path(project, str(journal.get("workspace", "")))
    if (
        journal.get("schema") != 1
        or normalize_path(Path(str(journal.get("project", "")))) != project
        or not str(journal.get("workspace", "")).startswith(WORKSPACE_PREFIX)
        or journal_file.name != f"{journal.get('workspace')}.json"
    ):
        raise LocalError(f"invalid transaction journal: {journal_file}")

    phase = str(journal.get("journal_state"))
    state = _journal_state(project, journal)
    if phase == "published":
        _cleanup_transaction(project, journal)
        return _journal_row(journal, "published cleanup completed")

    if phase not in {"prepared", "publishing"}:
        raise LocalError(f"invalid journal state in {journal_file}: {phase}")

    prepared_head = journal.get("prepared_head")
    if prepared_head:
        current_head = jj.commit_id("@")
        published = _is_ancestor(jj, str(prepared_head), current_head)
        if published and journal.get("next_render"):
            try:
                current_render = jj.render_head(str(journal["project_id"]), str(journal["layer"]))
                published = _is_ancestor(jj, str(journal["next_render"]), current_render)
            except LocalError:
                published = False
        if published:
            problems = _verify_published(
                project,
                jj,
                str(prepared_head),
                str(journal["prepared_tree"]),
                str(journal["prepared_marker_digest"]),
                str(journal["project_id"]),
                str(journal["layer"]),
                str(journal["next_render"]),
            )
            if problems:
                _set_journal_phase(
                    project, journal, "publishing", state, verification=problems,
                )
                return _journal_row(
                    journal,
                    "published but unverified; inspect the project: " + "; ".join(problems),
                )
            _set_journal_phase(project, journal, "published", state)
            _cleanup_transaction(project, journal)
            return _journal_row(journal, "published and cleaned")

    if phase == "publishing":
        _set_journal_phase(project, journal, "prepared", state)

    if not journal.get("prepared_head"):
        # Preparation did not produce a complete result. Remove only its staging workspace.
        _cleanup_transaction(project, journal)
        row = _journal_row(journal, "incomplete preparation removed; retry command")
        row["journal_state"] = "prepared"
        return row

    current_head = jj.commit_id("@")
    if current_head != journal.get("active_head"):
        return _journal_row(journal, "project moved; keep prepared result")

    if journal.get("kind") == "layer_add":
        return _publish_layer_transaction(project, jj, journal)

    if state is not None:
        state["journal_state"] = "prepared"
        _store_preview_state(project, Path(str(journal["workspace_path"])), state)
    return _journal_row(journal, "prepared; retry update --apply or discard")


def _workspace_repo(path: Path) -> Path | None:
    """Resolve the shared repository path recorded by one jj workspace."""

    pointer = path / ".jj" / "repo"
    try:
        if pointer.is_symlink():
            return pointer.resolve()
        if pointer.is_dir():
            return pointer.resolve()
        if pointer.is_file():
            target = pointer.read_text(encoding="utf-8").strip()
            return (pointer.parent / target).resolve()
    except OSError:
        return None
    return None


def _orphan_temporaries(
    roots: list[Path],
    direct_roots: list[Path] | None = None,
) -> list[dict[str, str]]:
    """Find ignored JSON write temporaries below the supplied roots."""

    excluded = STATE_EXCLUDES | {".git", ".jj"}
    found: dict[str, dict[str, str]] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for current, directories, files in os.walk(root):
            current_path = Path(current)
            directories[:] = sorted(name for name in directories if name not in excluded)
            for name in files:
                if name.startswith(TEMP_PREFIX):
                    path = current_path / name
                    found[str(path)] = {"path": str(path), "ignored": "true"}
    for root in direct_roots or []:
        if not root.is_dir():
            continue
        for path in root.iterdir():
            if path.name.startswith(TEMP_PREFIX) and path.is_file():
                found[str(path)] = {"path": str(path), "ignored": "true"}
    return [found[name] for name in sorted(found)]


def recover(project: Path, prune: bool = False) -> dict[str, Any]:
    """Report and reconcile interrupted local transactions."""

    project = normalize_path(project)
    jj = JJ(project)
    with project_lock(project):
        exclude_local_state(project)
        transactions: list[dict[str, Any]] = []
        directory = project / JOURNAL_DIR
        journal_files = sorted(directory.glob("*.json")) if directory.is_dir() else []
        preview_sidecar_roots: list[Path] = []
        for path in journal_files:
            journal = read_json(path)
            if journal.get("kind") == "update":
                preview_sidecar_roots.append(
                    Path(str(journal.get("workspace_path", ""))).parent,
                )
            transactions.append(_reconcile_journal(project, jj, journal))

        journals = {
            str(row.get("workspace")): row
            for row in (
                read_json(path) for path in sorted(directory.glob("*.json"))
            )
        } if directory.is_dir() else {}
        workspace_rows = jj.workspaces()
        journal_names = set(journals)
        orphan_workspaces = [
            row for row in workspace_rows
            if row["name"].startswith(WORKSPACE_PREFIX) and row["name"] not in journal_names
        ]
        referenced_layer_dirs = {
            str(Path(str(journal.get("temporary_path"))).resolve())
            for journal in journals.values()
            if journal.get("kind") == "layer_add" and journal.get("temporary_path")
        }
        repo_path = (project / ".jj" / "repo").resolve()
        orphan_layer_dirs: list[dict[str, str]] = []
        temporary_root = Path(tempfile.gettempdir())
        for path in sorted(temporary_root.glob("copyroom-layer-*")):
            if str(path.resolve()) in referenced_layer_dirs:
                continue
            workspace_repo = _workspace_repo(path / "workspace")
            if workspace_repo == repo_path:
                orphan_layer_dirs.append({"path": str(path), "repository": str(repo_path)})

        scan_roots = [project]
        for row in workspace_rows:
            workspace_path = Path(row["path"])
            scan_roots.append(workspace_path)
        scan_roots.extend(Path(row["path"]) for row in orphan_layer_dirs)
        scan_roots = list(dict.fromkeys(scan_roots))
        direct_roots = [
            root for root in dict.fromkeys(
                [*preview_sidecar_roots, *(Path(row["path"]).parent for row in orphan_workspaces)],
            )
            if root != project and project not in root.parents
        ]
        write_temporaries = _orphan_temporaries(scan_roots, direct_roots)

        pruned: list[dict[str, str]] = []
        if prune:
            for row in orphan_workspaces:
                path = Path(row["path"])
                jj.run("workspace", "forget", row["name"])
                if path.is_dir():
                    shutil.rmtree(path)
                _state_path(project, row["name"]).unlink(missing_ok=True)
                _preview_sidecar(path).unlink(missing_ok=True)
                pruned.append({"kind": "workspace", "path": row["path"]})
            for row in orphan_layer_dirs:
                shutil.rmtree(row["path"])
                pruned.append({"kind": "layer_directory", "path": row["path"]})
            for row in write_temporaries:
                path = Path(row["path"])
                path.unlink(missing_ok=True)
                pruned.append({"kind": "write_temporary", "path": str(path)})

        pending = any(
            row["journal_state"] != "published"
            or "published" not in str(row["action"])
            for row in transactions
        )
        has_orphans = bool(orphan_workspaces or orphan_layer_dirs or write_temporaries)
        return {
            "project": str(project),
            "ok": not pending and (prune or not has_orphans),
            "transactions": transactions,
            "orphans": {
                "workspaces": orphan_workspaces,
                "layer_directories": orphan_layer_dirs,
                "write_temporaries": write_temporaries,
            },
            "pruned": pruned,
        }


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
        journal = _ensure_preview_journal(project, state)
        if journal.get("journal_state") in {"publishing", "published"}:
            row = _reconcile_journal(project, jj, journal)
            if row.get("journal_state") == "published":
                return {"project": str(project), "render": str(state["next_render"])}
            journal = read_json(_journal_path(project, str(state["workspace"])))
        data = marker(project)
        if state["project_id"] != data["project_id"]:
            raise LocalError("preview belongs to another project", 1)
        layer = str(state["layer"])
        _layer_record(data, layer)
        if (
            jj.commit_id("@") != state["active_head"]
            or tracked_tree_digest(project, jj) != state["active_tree"]
        ):
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
        preview_tree = tracked_tree_digest(out, preview_jj)
        if state["conflicts"]:
            if (
                preview_jj.merge_base(preview_head, str(state["active_head"]))
                != state["active_head"]
                or preview_jj.merge_base(preview_head, str(state["next_render"]))
                != state["next_render"]
            ):
                raise LocalError("resolved preview no longer has the reviewed parents", 1)
        elif (
            preview_head != journal.get("prepared_head")
            or preview_head != state["preview_head"]
            or preview_tree != journal.get("prepared_tree")
        ):
            raise LocalError("preview workspace changed after preview", 1)
        preview_marker = out / MARKER
        if (
            not preview_marker.is_file()
            or digest_bytes(preview_marker.read_bytes()) != state["prepared_marker_digest"]
        ):
            raise LocalError("preview changed a protected project marker", 1)

        operation = jj.operation_id()
        _check_active_state(
            jj, project, str(state["active_head"]), str(state["active_tree"]), operation,
            "apply",
        )
        state["prepared_head"] = preview_head
        state["preview_head"] = preview_head
        state["preview_tree"] = preview_tree
        journal["prepared_head"] = preview_head
        journal["prepared_tree"] = preview_tree
        journal["prepared_marker_digest"] = state["prepared_marker_digest"]
        _set_journal_phase(project, journal, "prepared", state)
        _set_journal_phase(project, journal, "publishing", state)
        try:
            jj.run("new", preview_head, "-m", "copyroom:update")
        except Exception as exc:
            try:
                row = _reconcile_journal(project, jj, journal)
            except Exception as recovery_error:
                raise LocalError(
                    f"apply outcome is uncertain; run copyroom recover: {recovery_error}", 1,
                ) from exc
            if row.get("journal_state") == "published":
                return {"project": str(project), "render": str(state["next_render"])}
            detail = str(exc)
            if isinstance(exc, LocalError):
                raise LocalError(
                    f"{detail}; publication did not complete; preview kept for review",
                    exc.code,
                ) from exc
            raise LocalError(
                f"apply failed; publication did not complete; preview kept for review: {detail}",
                1,
            ) from exc
        problems = _verify_published(
            project,
            jj,
            preview_head,
            preview_tree,
            str(state["prepared_marker_digest"]),
            str(data["project_id"]),
            layer,
            str(state["next_render"]),
        )
        if problems:
            _set_journal_phase(
                project, journal, "publishing", state, verification=problems,
            )
            raise LocalError(
                "published result does not match the reviewed preview; run copyroom recover: "
                + "; ".join(problems),
                1,
            )
        _set_journal_phase(project, journal, "published", state)
        _cleanup_transaction(project, journal)
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
        journal_path = _journal_path(project, str(state.get("workspace", "")))
        journal_state = (
            read_json(journal_path).get("journal_state")
            if journal_path.is_file()
            else state.get("journal_state")
        )
        states.append({
            "workspace": state.get("workspace"),
            "path": state.get("path"),
            "conflicts": state.get("conflicts", []),
            "source_digest": state.get("source_digest"),
            "journal_state": journal_state,
        })
    return states


def _marker_render_mismatches(
    data: dict[str, Any],
    records: dict[str, Any],
    jj: JJ,
) -> tuple[list[dict[str, Any]], dict[str, str | None]]:
    """Compare marker revisions with the render heads visible from active @."""

    project_id = str(data["project_id"])
    expected = {
        str(name): _render_subject(
            project_id,
            str(name),
            int(record["revision"]),
            str(record["source_digest"]),
        )
        for name, record in records.items()
        if isinstance(record, dict)
    }
    active_heads = jj.render_heads(project_id)
    actual: dict[str, list[tuple[str, str]]] = {}
    for commit_id, subject in active_heads:
        fields = subject.split(" ", 4)
        if len(fields) == 5 and fields[0] == "copyroom:render" and fields[1] == project_id:
            actual.setdefault(fields[2], []).append((commit_id, subject))

    mismatches: list[dict[str, Any]] = []
    render_ids: dict[str, str | None] = {}
    for layer, subject in expected.items():
        heads = actual.get(layer, [])
        render_ids[layer] = heads[0][0] if len(heads) == 1 else None
        if len(heads) != 1 or heads[0][1] != subject:
            mismatches.append({
                "layer": layer,
                "marker_render": subject,
                "render_heads": [
                    {"commit": commit_id, "subject": head_subject}
                    for commit_id, head_subject in heads
                ],
            })
    for layer, heads in actual.items():
        if layer not in expected:
            mismatches.append({
                "layer": layer,
                "marker_render": None,
                "render_heads": [
                    {"commit": commit_id, "subject": head_subject}
                    for commit_id, head_subject in heads
                ],
            })
    return mismatches, render_ids


def _transaction_summaries(project: Path) -> list[dict[str, Any]]:
    """List saved publication phases for the active project."""

    directory = project / JOURNAL_DIR
    if not directory.is_dir():
        return []
    return [
        {
            "workspace": journal.get("workspace"),
            "kind": journal.get("kind"),
            "layer": journal.get("layer"),
            "journal_state": journal.get("journal_state"),
            "prepared_head": journal.get("prepared_head"),
        }
        for path in sorted(directory.glob("*.json"))
        for journal in [read_json(path)]
    ]


def inspect(project: Path) -> dict[str, Any]:
    """Return full project state for structured output."""

    project = normalize_path(project)
    data = marker(project)
    records = data.get("layers", {"base": data})
    if not isinstance(records, dict):
        raise LocalError("invalid layer records in project marker")
    jj = JJ(project)
    marker_render_mismatches, render_ids = _marker_render_mismatches(data, records, jj)
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
            "render_head": render_ids[str(name)],
            "marker_render_mismatch": any(
                item["layer"] == str(name) for item in marker_render_mismatches
            ),
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
        "marker_render_mismatches": marker_render_mismatches,
        "has_marker_render_mismatch": bool(marker_render_mismatches),
        "working_tree_digest": working_digest(project),
        "pending_previews": list_previews(project),
        "pending_transactions": _transaction_summaries(project),
        "conflicts": jj.conflicts(),
        "owners": _owner_map(data),
        "answers": data["answers"],
    }


def status(project: Path) -> dict[str, Any]:
    """Return a concise project status report."""

    report = inspect(project)
    report["has_pending_publication"] = any(
        transaction["kind"] == "layer_add"
        or transaction["journal_state"] in {"publishing", "published"}
        for transaction in report["pending_transactions"]
    )
    report["ok"] = all(
        item["source_reachable"] or item["snapshot_reachable"]
        for item in report["layers"].values()
    ) and not report["has_marker_render_mismatch"] and not report["has_pending_publication"]
    report["has_conflicts"] = bool(report["conflicts"])
    report["has_marker_render_mismatch"] = bool(report["marker_render_mismatches"])
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
    "add_layer", "apply", "discard", "doctor", "inspect", "list_layers", "list_previews", "recover",
    "new", "preview", "status", "update", "working_digest", "working_files",
]
