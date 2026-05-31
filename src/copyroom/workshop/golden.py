"""Golden testing workflow — ``copyroom golden`` and ``copyroom golden --refresh``.

Implements the GoldenDiff state machine from copyroom-workshop.allium:

    initiated -> rendered -> compared -> has_diffs | no_diffs

Golden targets: ``tree.txt`` (file listing) and ``important-files/``
(pyproject.toml, README, CI config, etc.).
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from .._compat.state_machine import StateMachine
from .model import (
    VALID_GOLDEN_TRANSITIONS,
    GoldenDiff,
    GoldenDiffResult,
    GoldenStatus,
)
from .render import execute_render, initiate as render_initiate

# ---------------------------------------------------------------------------
# State machine instance
# ---------------------------------------------------------------------------

_golden_sm = StateMachine(
    VALID_GOLDEN_TRANSITIONS,
    entity_name="GoldenDiff",
)


class CopyRoomError(Exception):
    """Base error with structured message."""

    def __init__(self, message: str, state: str | None = None) -> None:
        self.message = message
        self.state = state
        super().__init__(self._format())

    def _format(self) -> str:
        parts = [f"Error: {self.message}"]
        if self.state:
            parts.append(f"State left: {self.state}")
        return "\n".join(parts)


# ===================================================================
# Rule: DiffGolden                     (spec L110-L116)
# ===================================================================


def initiate(template_id: str, scenario_id: str) -> GoldenDiff:
    """Create a GoldenDiff entity in ``initiated`` state."""
    if not template_id:
        raise CopyRoomError(
            "Template ID is required. Usage: copyroom golden <template_id> <scenario_id>",
            state="not_started",
        )
    if not scenario_id:
        raise CopyRoomError(
            "Scenario ID is required. Usage: copyroom golden <template_id> <scenario_id>",
            state="not_started",
        )

    return GoldenDiff(template_id=template_id, scenario_id=scenario_id)


# ===================================================================
# Rule: RenderForGoldenDiff            (spec L118-L124)
# ===================================================================


def render_for_golden(
    diff: GoldenDiff,
    workshop_root: Path,
    template_source: str,
) -> GoldenStatus:
    """Render the template with the scenario to get current output.

    Reuses the same rendering logic as ``copyroom render`` but stores
    state in the GoldenDiff entity.
    """
    # Reuse ScenarioRender for the rendering step
    render = render_initiate(diff.template_id, diff.scenario_id)
    status = execute_render(render, workshop_root, template_source)

    if status.value == "failed":
        diff.status = _golden_sm.transition(
            GoldenStatus.initiated,
            GoldenStatus.failed,
        )
        return diff.status

    diff.status = _golden_sm.transition(
        GoldenStatus.initiated,
        GoldenStatus.rendered,
    )
    return diff.status


# ===================================================================
# Rule: CompareToGolden                (spec L126-L132)
# Rule: GoldenHasDiffs                 (spec L134-L139)
# Rule: GoldenNoDiffs                  (spec L141-L146)
# ===================================================================


def compare_to_golden(
    diff: GoldenDiff,
    workshop_root: Path,
) -> GoldenStatus:
    """Compare generated output to golden snapshot.

    Golden targets:
      * ``tree.txt`` — file listing of the golden directory
      * ``important-files/`` — pyproject.toml, README, CI config, etc.

    Produces lists of added, removed, and modified files in ``diff.result``.
    """
    generated_dir = workshop_root / "generated" / diff.template_id / diff.scenario_id
    golden_dir = workshop_root / "golden" / diff.template_id / diff.scenario_id

    if not generated_dir.is_dir():
        diff.status = _golden_sm.transition(
            GoldenStatus.rendered,
            GoldenStatus.failed,
        )
        print(
            f"Error: Generated directory not found: {generated_dir}",
            file=sys.stderr,
        )
        return diff.status

    if not golden_dir.is_dir():
        # No golden snapshot exists — everything is "added"
        all_files = _collect_important_files(generated_dir)
        diff.result = GoldenDiffResult(added=all_files)
    else:
        gen_files = _collect_important_files(generated_dir, relative_to=generated_dir)
        gold_files = _collect_important_files(golden_dir, relative_to=golden_dir)

        added = gen_files - gold_files
        removed = gold_files - gen_files
        modified: set[str] = set()

        # Compare common files for content differences
        for file in gen_files & gold_files:
            gen_path = generated_dir / file
            gold_path = golden_dir / file
            if gen_path.is_file() and gold_path.is_file():
                if _file_content_differs(gen_path, gold_path):
                    modified.add(file)
            elif gen_path.is_dir() != gold_path.is_dir():
                modified.add(file)

        diff.result = GoldenDiffResult(
            added=added, removed=removed, modified=modified,
        )

    # Transition to compared
    diff.status = _golden_sm.transition(
        GoldenStatus.rendered,
        GoldenStatus.compared,
    )

    # Branch on has_changes
    if diff.result.has_changes:
        diff.status = _golden_sm.transition(
            GoldenStatus.compared,
            GoldenStatus.has_diffs,
        )
    else:
        diff.status = _golden_sm.transition(
            GoldenStatus.compared,
            GoldenStatus.no_diffs,
        )

    return diff.status


# ===================================================================
# Rule: RefreshGolden                  (spec L148-L152)
# ===================================================================


def refresh_golden(
    template_id: str,
    scenario_id: str,
    workshop_root: Path,
) -> None:
    """Overwrite the golden snapshot with the current generated output.

    Copies ``generated/<template_id>/<scenario_id>/`` to
    ``golden/<template_id>/<scenario_id>/``.
    """
    generated_dir = workshop_root / "generated" / template_id / scenario_id
    golden_dir = workshop_root / "golden" / template_id / scenario_id

    if not generated_dir.is_dir():
        raise CopyRoomError(
            f"Generated directory not found: {generated_dir}\n"
            f"Run 'copyroom render {template_id} {scenario_id}' first.",
            state="refresh_failed",
        )

    # Remove old golden if it exists
    if golden_dir.exists():
        shutil.rmtree(golden_dir)

    # Copy generated output to golden
    shutil.copytree(generated_dir, golden_dir)


# ===================================================================
# High-level workflow
# ===================================================================


def golden_diff(
    template_id: str,
    scenario_id: str,
    workshop_root: Path | None = None,
    template_source: str | None = None,
) -> GoldenDiff:
    """Run the full golden diff workflow.

    This is the top-level entry point called from the CLI for
    ``copyroom golden <template_id> <scenario_id>``.

    Returns the ``GoldenDiff`` entity in its final state
    (``has_diffs``, ``no_diffs``, or ``failed``).
    """
    if workshop_root is None:
        workshop_root = Path.cwd()

    # Resolve template source from registry if not provided
    if template_source is None:
        template_source = _resolve_template_source(workshop_root, template_id)
        if template_source is None:
            diff = initiate(template_id, scenario_id)
            diff.status = _golden_sm.transition(
                GoldenStatus.initiated,
                GoldenStatus.failed,
            )
            print(
                f"Error: Template '{template_id}' not found in workshop registry.",
                file=sys.stderr,
            )
            return diff

    # 1. DiffGolden — create entity
    diff = initiate(template_id, scenario_id)

    # 2. RenderForGoldenDiff
    status = render_for_golden(diff, workshop_root, template_source)
    if status in (GoldenStatus.failed,):
        return diff

    # 3. CompareToGolden → GoldenHasDiffs | GoldenNoDiffs
    status = compare_to_golden(diff, workshop_root)
    return diff


# ===================================================================
# Internal helpers
# ===================================================================


def _resolve_template_source(workshop_root: Path, template_id: str) -> str | None:
    """Resolve a template ID to its source path/URL from the workshop registry."""
    import yaml

    config_path = workshop_root / "copyroom.yml"
    if config_path.is_file():
        try:
            with open(config_path) as f:
                config = yaml.safe_load(f)
            if isinstance(config, dict):
                templates = config.get("templates", config.get("registry", None))
                if isinstance(templates, dict):
                    source = templates.get(template_id)
                    if isinstance(source, str):
                        return source
                    if isinstance(source, dict):
                        return source.get("source", source.get("url", str(source)))
        except yaml.YAMLError:
            pass

    # Also check registry/ directory
    registry_dir = workshop_root / "registry"
    template_yml = registry_dir / f"{template_id}.yml"
    if template_yml.is_file():
        try:
            import yaml as _yaml
            with open(template_yml) as f:
                template = _yaml.safe_load(f)
            if isinstance(template, dict):
                source = template.get("source", template.get("url"))
                if isinstance(source, str):
                    return source
        except yaml.YAMLError:
            pass

    return None


def _collect_important_files(
    directory: Path,
    relative_to: Path | None = None,
) -> set[str]:
    """Collect the set of important files from a directory.

    "Important files" are those that constitute the golden snapshot:
    everything in the directory, represented as relative paths.

    Parameters
    ----------
    directory:
        The directory to scan.
    relative_to:
        If provided, paths are relative to this directory.
    """
    if relative_to is None:
        relative_to = directory

    files: set[str] = set()
    for item in sorted(directory.rglob("*")):
        if item.is_file():
            rel = item.relative_to(relative_to)
            files.add(str(rel))
    return files


def _file_content_differs(path_a: Path, path_b: Path) -> bool:
    """Return True if the two files have different content."""
    try:
        return path_a.read_bytes() != path_b.read_bytes()
    except OSError:
        return True
