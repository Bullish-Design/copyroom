"""CLI frontend for CopyRoom.

Entry point::

    copyroom [--mode {workshop,project}] <command> [args...]

Modes are auto-detected from directory markers unless ``--mode`` forces one.
If neither workshop nor project markers are found, exits with a clear error.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence

from .manage import CopyRoomError as ManageError
from .manage import adopt as _adopt
from .manage import templatize as _templatize
from .project.create import CopyRoomError as CreateError
from .project.create import create_project
from .project.inspect import CopyRoomError as InspectError
from .project.inspect import inspect_project, project_status
from .project.model import CreationStatus, UpdateStatus
from .project.update import CopyRoomError as UpdateError
from .project.update import update_project
from .release.check import CopyRoomError as ReleaseError
from .release.check import ReleaseStatus
from .release.check import run_release_check as _run_release_check
from .session.detector import detect_mode
from .session.dispatcher import COMMAND_MODE_MAP, dispatch
from .session.model import (
    BOOTSTRAP_COMMANDS,
    PROJECT_COMMANDS,
    WORKSHOP_COMMANDS,
    CLIMode,
    CLISession,
    SessionStatus,
)
from .template.model import PreviewStatus
from .template.preview import CopyRoomError as TemplateError
from .template.preview import run_preview
from .template.validate import validate_template
from .template.workspace import checkout_template
from .workshop.golden import CopyRoomError as GoldenError
from .workshop.golden import golden_diff, refresh_golden
from .workshop.model import GoldenStatus, RenderStatus, SimStatus
from .workshop.registry import CopyRoomError as RegistryError
from .workshop.registry import (
    add_template,
    list_templates,
    load_entry,
    require_workshop_root,
    validate_registry,
)
from .workshop.render import CopyRoomError as RenderError
from .workshop.render import render_scenario
from .workshop.simulate import CopyRoomError as SimError
from .workshop.simulate import run_update_simulation

# ---------------------------------------------------------------------------
# Help text
# ---------------------------------------------------------------------------

COPYROOM_DESCRIPTION = """\
CopyRoom coordinates template-driven project workflows using Copier.

Modes are auto-detected from directory markers. The command set adapts
to the detected mode.

Project commands (in a project directory):
  update    [target_ref] [--branch]
                               Update an existing project (latest tag if no ref)
  inspect   [--json]           Full report on this project + its template link
  status    [--json]           Terse status: mode, ref, worktree, update available
  template-checkout [--from REF]
                               Resolve this project's template into an editable worktree
  template-test     [--from REF] [--check CMD]
                               Render-test the edited template with this project's answers
  template-preview  [--from REF]
                               Preview the update this project would receive from the edit

Bootstrap commands (in an unmanaged repo — no markers needed):
  new       <source> [target] [--answers FILE]
                               Create a new project from a template (runs anywhere)
  templatize    [--into PATH] [--name NAME] [--id ID]
                               Scaffold a template repo from this repo
  adopt         <template> [--ref REF] --answers FILE [--write] [--force]
                               Link this repo to a template and report drift

Workshop commands (in a workshop directory):
  registry      list | show <id> | validate | add <id> --source <src> [--scaffold]
                               Inspect the template registry (add is create-only)
  render        <template_id> <scenario_id>
                               Render a template scenario
  test          <template_id> <scenario_id>
                               Test rendered output
  golden        <template_id> <scenario_id>
                               Golden test a scenario
  release-check <template_id>  Run release readiness checks
  update-test   <template_id> <scenario_id> <old> <new>
                               Simulate a template update
"""

NO_MODE_FOUND_MESSAGE = """\
Error: No CopyRoom project or workshop found here.

CopyRoom looks for these markers in the current directory and its ancestors:

  Workshop markers (template author's workbench):
    - copyroom.yml  +  registry/  +  scenarios/

  Project markers (generated project):
    - .copier-answers.yml  or  copyroom.project.yml

Run 'copyroom --help' for more information.
"""


# ---------------------------------------------------------------------------
# Mode detection helper
# ---------------------------------------------------------------------------


def _detect_and_report(mode_override: str | None) -> CLISession:
    """Resolve the session mode and return a session. Prints status and may exit.

    When *mode_override* is given (via ``--mode``), detection is skipped and the
    forced mode is used. Otherwise the mode is auto-detected from directory
    markers; an unknown mode prints a diagnostic and exits.
    """
    session = CLISession()

    if mode_override is not None:
        session.mode = CLIMode(mode_override)
        session.advance(SessionStatus.mode_detected)
        return session

    mode = detect_mode()
    if mode is None:
        session.advance(SessionStatus.unknown_mode)
        print(NO_MODE_FOUND_MESSAGE, file=sys.stderr)
        sys.exit(1)
        # unreachable

    session.mode = mode
    session.advance(SessionStatus.mode_detected)
    return session


# ---------------------------------------------------------------------------
# Error formatters
# ---------------------------------------------------------------------------


def _print_out_of_mode_error(command: str, session: CLISession) -> None:
    """Print a clear error when a command doesn't belong in the current mode."""
    expected = COMMAND_MODE_MAP.get(command)
    mode_label = session.mode.value if session.mode else "unknown"
    expected_label = expected.value if expected else "unknown"
    print(
        f"Error: '{command}' is a {expected_label} command, "
        f"but the current mode is {mode_label}.",
        file=sys.stderr,
    )
    print(f"Available commands in {mode_label} mode:", file=sys.stderr)
    if session.mode == CLIMode.workshop:
        for c in sorted(WORKSHOP_COMMANDS):
            print(f"  {c}", file=sys.stderr)
    elif session.mode == CLIMode.project:
        for c in sorted(PROJECT_COMMANDS):
            print(f"  {c}", file=sys.stderr)
    sys.exit(1)


def _print_unknown_command_error(command: str) -> None:
    """Print a clear error for an unknown command."""
    print(
        f"Error: Unknown command '{command}'. "
        f"Run 'copyroom --help' for available commands.",
        file=sys.stderr,
    )
    sys.exit(1)


# ---------------------------------------------------------------------------
# Subcommand handlers (one thin _cmd_* per command)
# ---------------------------------------------------------------------------


def _cmd_new(args: argparse.Namespace) -> None:
    """``copyroom new <source> [target] [--answers FILE]`` — Phase 2."""
    try:
        creation = create_project(
            source=args.source,
            target_dir=args.target or ".",
            answers_file=args.answers_file,
            trust=args.trust,
        )
    except CreateError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    if creation.status == CreationStatus.failed:
        for suggestion in creation.result_suggestions:
            print(suggestion, file=sys.stderr)
        sys.exit(1)

    print(f"Project created in {creation.target_dir}")
    for suggestion in creation.result_suggestions:
        print(f"  Next: {suggestion}")


def _cmd_update(args: argparse.Namespace) -> None:
    """``copyroom update [target_ref] [--branch]`` — Phase 2."""
    try:
        update = update_project(
            project_root=None,  # defaults to cwd
            target_ref=args.target_ref,
            use_branch=args.branch,
            trust=args.trust,
        )
    except UpdateError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    # A no-op (already at the target version) is a success, not a failure (P1-2).
    if update.status == UpdateStatus.up_to_date:
        if update.resolved_latest:
            print(f"Already at the latest version ({update.target_ref}); nothing to update.")
        else:
            print(f"Already at version {update.target_ref}; nothing to update.")
        return  # exit 0

    if update.status == UpdateStatus.failed:
        print(f"Update failed at state: {update.status.value}", file=sys.stderr)
        if update.conflicts:
            print("Conflicts:", file=sys.stderr)
            for c in update.conflicts:
                print(f"  {c}", file=sys.stderr)
        if update.rejects:
            print("Rejects:", file=sys.stderr)
            for r in update.rejects:
                print(f"  {r}", file=sys.stderr)
        sys.exit(1)

    print(f"Project updated to {update.target_ref}")
    if update.update_branch:
        print(f"  Isolation branch: {update.update_branch}")
    if update.conflicts:
        print("  Conflicts captured:", file=sys.stderr)
        for c in update.conflicts:
            print(f"    {c}", file=sys.stderr)
    if update.rejects:
        print("  Rejects captured:", file=sys.stderr)
        for r in update.rejects:
            print(f"    {r}", file=sys.stderr)


def _cmd_inspect(args: argparse.Namespace) -> None:
    """``copyroom inspect [--json]`` — full read-only project report."""
    try:
        report = inspect_project(project_root=None)
    except InspectError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
        return

    print(f"Project: {report.project_root}")
    print(f"  Template id:     {report.template_id or '(none)'}")
    print(f"  Template source: {report.template_source or '(none)'}")
    print(f"  Recorded commit: {report.commit or '(none)'}")
    print(f"  Answers file:    {report.answers_file}")
    print(f"  Project config:  {'present' if report.has_project_config else 'absent'}")
    if report.hooks:
        print("  Configured commands:")
        for name, cmds in report.hooks.items():
            print(f"    {name}:")
            for cmd in cmds:
                print(f"      - {cmd}")
    else:
        print("  Configured commands: (none)")


def _cmd_status(args: argparse.Namespace) -> None:
    """``copyroom status [--json]`` — terse "where am I" project status."""
    try:
        report = project_status(project_root=None)
    except InspectError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
        return

    if report.worktree_clean is None:
        worktree = "N/A (not a git repository)"
    else:
        worktree = "clean" if report.worktree_clean else "dirty"

    print(f"Mode:             {report.mode or 'unknown'}")
    print(f"Template:         {report.template_id or report.template_source or '(none)'}")
    print(f"Current ref:      {report.current_ref or '(none)'}")
    print(f"Latest ref:       {report.latest_ref or 'unknown'}")
    print(f"Update available: {'yes' if report.update_available else 'no'}")
    print(f"Worktree:         {worktree}")


def _cmd_template_checkout(args: argparse.Namespace) -> None:
    """``copyroom template-checkout [--from REF]`` — editable template worktree."""
    try:
        checkout = checkout_template(project_root=None, from_ref=args.from_ref)
    except TemplateError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    print("Template checked out for editing:")
    print(f"  Worktree: {checkout.worktree_dir}")
    print(f"  Branch:   {checkout.branch}")
    print(f"  Source:   {checkout.template_source}")
    print()
    print("Edit files under the worktree, then run:")
    print("  copyroom template-test       # confirm it still renders")
    print("  copyroom template-preview    # see what your project would receive")


def _cmd_template_test(args: argparse.Namespace) -> None:
    """``copyroom template-test [--from REF] [--check CMD]`` — render-test the edit."""
    try:
        result = validate_template(
            project_root=None, from_ref=args.from_ref, check_cmd=args.check,
        )
    except TemplateError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    if not result.ok:
        print("Template test failed:", file=sys.stderr)
        for msg in result.messages:
            print(f"  {msg}", file=sys.stderr)
        sys.exit(1)

    for msg in result.messages:
        print(f"  ✅ {msg}")
    print(f"  Rendered into: {result.output_dir}")


def _cmd_template_preview(args: argparse.Namespace) -> None:
    """``copyroom template-preview [--from REF]`` — preview the project's update."""
    try:
        preview = run_preview(project_root=None, from_ref=args.from_ref)
    except TemplateError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    if preview.status != PreviewStatus.complete or preview.result is None:
        print("Template preview failed.", file=sys.stderr)
        sys.exit(1)

    result = preview.result
    print(f"Update preview (project ← edited template on {preview.branch}):")
    if not result.has_changes and not result.conflicts and not result.rejects:
        print("  No changes — your project already matches the edited template.")
    else:
        if result.added:
            print(f"  Added:    {sorted(result.added)}")
        if result.modified:
            print(f"  Modified: {sorted(result.modified)}")
        if result.removed:
            print(f"  Removed:  {sorted(result.removed)}")
        if result.conflicts:
            print(f"  ⚠️  Conflicts: {sorted(result.conflicts)}")
        if result.rejects:
            print(f"  ⚠️  Rejects:   {sorted(result.rejects)}")
    print(f"  Patch: {result.patch_path}")
    print()
    print("Nothing was applied to your project. Review the patch, then once the")
    print("template change is committed/tagged, apply it with: copyroom update <ref>")


def _cmd_templatize(args: argparse.Namespace) -> None:
    """``copyroom templatize [--into PATH] [--name NAME] [--id ID]``.

    Scaffold a self-contained template repo (Home A) from the current repo.
    """
    try:
        tz = _templatize(
            repo_root=None, into=args.into, name=args.name, template_id=args.id,
        )
    except ManageError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    print(f"Template repo scaffolded at {tz.home_dir}")
    print(f"  Template id: {tz.template_id}")
    print(f"  Default project_name: {tz.project_name}")
    print()
    print("Next — parameterize, then converge the golden loop (from the template repo):")
    print(f"  cd {tz.home_dir}")
    print(f"  copyroom golden {tz.template_id} default      # → no diffs when faithful")
    print("  # rename files under template/ to *.jinja and insert {{ project_name }}")
    print(f"  copyroom render {tz.template_id} probe         # sanity-check parameterization")
    print()
    print("When the golden loop is clean, finalize and adopt:")
    print("  git init -q && git add -A && git commit -qm 'template v0.1.0' && git tag v0.1.0")
    print(f"  cd {tz.repo_root}")
    print(f"  copyroom adopt {tz.home_dir} --ref v0.1.0 --answers <answers.yml> --write")


def _cmd_adopt(args: argparse.Namespace) -> None:
    """``copyroom adopt <template> [--ref REF] --answers FILE [--write] [--force]``.

    Link this repo to a template and report drift (report-only unless --write).
    """
    try:
        adoption = _adopt(
            template=args.template,
            repo_root=None,
            ref=args.ref,
            answers_file=args.answers_file,
            write=args.write,
            force=args.force,
        )
    except ManageError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    result = adoption.result
    print(f"Adoption drift (repo vs {args.template} rendered with your answers):")
    if result is None or not result.has_drift:
        print("  No drift — the template reproduces this repo exactly.")
    else:
        if result.added:
            print(f"  Template adds (absent in repo): {sorted(result.added)}")
        if result.modified:
            print(f"  Differs:                        {sorted(result.modified)}")
        if result.removed:
            print(f"  Repo-only (not in template):    {sorted(result.removed)}")
    if result and result.patch_path:
        print(f"  Patch: {result.patch_path}")
    print()
    if adoption.wrote_answers:
        print("  Recorded .copier-answers.yml — this repo is now CopyRoom-managed.")
        print("  No other repo file was modified. Verify with: git status")
    else:
        print("  Report-only: nothing was written. Re-run with --write to record")
        print("  the link (.copier-answers.yml) once the answers look right.")


_REGISTRY_ACTIONS = ("list", "show", "validate", "add")


def _cmd_registry(args: argparse.Namespace) -> None:
    """``copyroom registry <list|show|validate|add> ...``.

    Read-only (``list``/``show``/``validate``) plus a create-only ``add`` that
    writes a new ``registry/<id>.yml`` — ``copyroom.yml`` is never rewritten.
    """
    action = args.action
    try:
        root = require_workshop_root(None)

        if action == "list":
            entries = list_templates(root)
            if not entries:
                print("No templates registered.")
                return
            for entry in entries:
                print(f"{entry.template_id}")
                print(f"  source: {entry.source or '(unresolved)'}")
                if entry.checks:
                    print(f"  checks: {len(entry.checks)} configured")
            return

        if action == "show":
            if not args.args:
                print("Usage: copyroom registry show <template_id>", file=sys.stderr)
                sys.exit(1)
            entry = load_entry(root, args.args[0])
            print(f"{entry.template_id}")
            print(f"  source: {entry.source or '(unresolved)'}")
            print(f"  checks: {entry.checks or '(none)'}")
            return

        if action == "validate":
            report = validate_registry(root)
            if not report.problems:
                print("No templates registered — nothing to validate.")
                return
            for template_id, problems in report.problems.items():
                if problems:
                    print(f"✗ {template_id}", file=sys.stderr)
                    for problem in problems:
                        print(f"    - {problem}", file=sys.stderr)
                else:
                    print(f"✓ {template_id}")
            if not report.ok:
                sys.exit(1)
            return

        if action == "add":
            if not args.args:
                print(
                    "Usage: copyroom registry add <template_id> --source <src> [--scaffold]",
                    file=sys.stderr,
                )
                sys.exit(1)
            if not args.source:
                print("registry add requires --source <path-or-url>", file=sys.stderr)
                sys.exit(1)
            path = add_template(root, args.args[0], args.source, scaffold=args.scaffold)
            print(f"Created registry entry: {path.relative_to(root)}")
            if args.scaffold:
                print(f"Scaffolded scenarios/{args.args[0]}/default.yml")
            return

        supported = ", ".join(_REGISTRY_ACTIONS)
        print(
            f"Error: unknown registry action '{action}'. Supported: {supported}.",
            file=sys.stderr,
        )
        sys.exit(1)
    except RegistryError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)


def _cmd_render(args: argparse.Namespace) -> None:
    """``copyroom render <template_id> <scenario_id>`` — Phase 3."""
    try:
        render = render_scenario(
            template_id=args.template_id,
            scenario_id=args.scenario_id,
        )
    except RenderError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    if render.status == RenderStatus.failed:
        print(f"Render failed: {render.template_id}/{render.scenario_id}", file=sys.stderr)
        sys.exit(1)

    print(f"Rendered {render.template_id}/{render.scenario_id} → generated/{render.template_id}/{render.scenario_id}/")
    if render.status == RenderStatus.tested:
        print("  Tests: passed")
    print(f"  Status: {render.status.value}")


def _cmd_test(args: argparse.Namespace) -> None:
    """``copyroom test <template_id> <scenario_id>`` — Phase 3.

    Delegates to ``render`` with a focus on testing. The render workflow
    already runs tests when checks are configured.
    """
    _cmd_render(args)


def _cmd_golden(args: argparse.Namespace) -> None:
    """``copyroom golden <template_id> <scenario_id>`` — Phase 3.

    Supports ``--refresh`` to overwrite the golden snapshot.
    """
    if args.refresh:
        try:
            refresh_golden(
                template_id=args.template_id,
                scenario_id=args.scenario_id,
                workshop_root=None,
            )
        except GoldenError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(1)
        print(f"Golden snapshot refreshed: {args.template_id}/{args.scenario_id}")
        return

    try:
        diff = golden_diff(
            template_id=args.template_id,
            scenario_id=args.scenario_id,
        )
    except GoldenError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    if diff.status == GoldenStatus.failed:
        print(f"Golden diff failed: {diff.template_id}/{diff.scenario_id}", file=sys.stderr)
        sys.exit(1)

    if diff.status == GoldenStatus.no_diffs:
        print(f"Golden: {diff.template_id}/{diff.scenario_id} — ✅ OK (no diffs)")
    elif diff.status == GoldenStatus.has_diffs:
        print(f"Golden: {diff.template_id}/{diff.scenario_id} — ⚠️  DIFFS FOUND")
        if diff.result:
            print(f"  {diff.result}")
            if diff.result.modified:
                print(f"  Modified: {sorted(diff.result.modified)}")
            if diff.result.added:
                print(f"  Added:    {sorted(diff.result.added)}")
            if diff.result.removed:
                print(f"  Removed:  {sorted(diff.result.removed)}")
        print("  Review changes, then run: copyroom golden --refresh <template_id> <scenario_id>")
        sys.exit(1)


def _cmd_release_check(args: argparse.Namespace) -> None:
    """``copyroom release-check <template_id>`` — Phase 4."""
    try:
        check = _run_release_check(template_id=args.template_id)
    except ReleaseError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    # Format and print the report
    from .release.check import format_release_report
    print(format_release_report(check))

    if check.status == ReleaseStatus.failed:
        sys.exit(1)


def _cmd_update_test(args: argparse.Namespace) -> None:
    """``copyroom update-test <template_id> <scenario_id> <old> <new>`` — Phase 3."""
    try:
        sim = run_update_simulation(
            template_id=args.template_id,
            scenario_id=args.scenario_id,
            old_version=args.old_version,
            new_version=args.new_version,
        )
    except SimError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    if sim.status == SimStatus.failed:
        print(
            f"Update simulation failed: {sim.template_id}/{sim.scenario_id} "
            f"({sim.old_version} → {sim.new_version})",
            file=sys.stderr,
        )
        sys.exit(1)

    if sim.status == SimStatus.complete:
        print(
            f"Update simulation: {sim.template_id}/{sim.scenario_id} "
            f"({sim.old_version} → {sim.new_version})"
        )
        result = sim.result
        if result and result.check_passed:
            print("  ✅ Update applied cleanly — no conflicts")
        elif result:
            print("  ⚠️  Update had issues:")
            if result.conflicts:
                print(f"  Conflicts: {sorted(result.conflicts)}")
            if result.rejects:
                print(f"  Rejects:   {sorted(result.rejects)}")
        print(f"  Status: {sim.status.value}")


# ---------------------------------------------------------------------------
# Argument parser setup
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="copyroom",
        description=COPYROOM_DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--mode",
        choices=["workshop", "project"],
        default=None,
        help="Force a mode instead of auto-detecting from directory markers",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print version and exit",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # --- Project commands ---
    p_new = subparsers.add_parser("new", help="Create a new project from a template")
    p_new.add_argument("source", help="Template source (local path or git URL)")
    p_new.add_argument("target", nargs="?", default=".", help="Target directory")
    p_new.add_argument("--answers", dest="answers_file", default=None,
                       help="Path to YAML answers file")
    p_new.add_argument("--trust", action="store_true",
                       help="Execute the template's post-create hook commands")

    p_update = subparsers.add_parser("update", help="Update an existing project")
    p_update.add_argument("target_ref", nargs="?", default=None,
                          help="Target version ref (tag or branch)")
    p_update.add_argument("--branch", action="store_true",
                          help="Create an isolation branch for the update")
    p_update.add_argument("--trust", action="store_true",
                          help="Execute the template's post-update hook commands")

    p_inspect = subparsers.add_parser(
        "inspect", help="Full read-only report on this project and its template link",
    )
    p_inspect.add_argument("--json", action="store_true",
                           help="Emit the report as JSON")

    p_status = subparsers.add_parser(
        "status", help="Terse project status (mode, ref, worktree, update available)",
    )
    p_status.add_argument("--json", action="store_true",
                          help="Emit the status as JSON")

    # --- Template-edit commands (project mode) ---
    p_tco = subparsers.add_parser(
        "template-checkout",
        help="Resolve this project's template into an editable worktree",
    )
    p_tco.add_argument("--from", dest="from_ref", default=None,
                       help="Base ref for the edit branch (default: template's default branch)")

    p_ttest = subparsers.add_parser(
        "template-test",
        help="Render-test the edited template with this project's answers",
    )
    p_ttest.add_argument("--from", dest="from_ref", default=None,
                         help="Base ref for the edit branch")
    p_ttest.add_argument("--check", default=None,
                         help="Shell command to run against the rendered output")

    p_tprev = subparsers.add_parser(
        "template-preview",
        help="Preview the update this project would receive from the edited template",
    )
    p_tprev.add_argument("--from", dest="from_ref", default=None,
                         help="Base ref for the edit branch")

    # --- Bootstrap commands (unmanaged repo) ---
    p_templatize = subparsers.add_parser(
        "templatize",
        help="Scaffold a template repo from the current (unmanaged) repo",
    )
    p_templatize.add_argument(
        "--into", default=None,
        help="Where to create the template repo (default: <repo>-template sibling)",
    )
    p_templatize.add_argument(
        "--name", default=None,
        help="Project name to record as the template default (default: repo name)",
    )
    p_templatize.add_argument(
        "--id", default=None,
        help="Workshop/registry template id (default: slug of --name)",
    )

    p_adopt = subparsers.add_parser(
        "adopt",
        help="Link this repo to a template and report drift",
    )
    p_adopt.add_argument("template", help="Template source (local path or git URL)")
    p_adopt.add_argument(
        "--ref", default=None,
        help="Template VCS ref to render (tag/branch/commit)",
    )
    p_adopt.add_argument(
        "--answers", dest="answers_file", default=None,
        help="Path to the YAML answers file inferred for this repo",
    )
    p_adopt.add_argument(
        "--write", action="store_true",
        help="Write .copier-answers.yml into the repo (otherwise report-only)",
    )
    p_adopt.add_argument(
        "--force", action="store_true",
        help="Re-adopt even if the repo already has .copier-answers.yml",
    )

    # --- Workshop commands ---
    p_registry = subparsers.add_parser(
        "registry", help="Inspect the template registry (list/show/validate/add)",
    )
    p_registry.add_argument("action", help="Registry action: list, show, validate, add")
    p_registry.add_argument("args", nargs="*", help="Template id (for show/add)")
    p_registry.add_argument("--source", default=None,
                            help="Template source for 'add' (local path or git URL)")
    p_registry.add_argument("--scaffold", action="store_true",
                            help="With 'add', also scaffold a scenarios/<id>/ skeleton")

    p_render = subparsers.add_parser("render", help="Render a template scenario")
    p_render.add_argument("template_id", help="Template identifier")
    p_render.add_argument("scenario_id", help="Scenario identifier")

    p_test = subparsers.add_parser("test", help="Test rendered output")
    p_test.add_argument("template_id", help="Template identifier")
    p_test.add_argument("scenario_id", help="Scenario identifier")

    p_golden = subparsers.add_parser("golden", help="Golden test a scenario")
    p_golden.add_argument("template_id", help="Template identifier")
    p_golden.add_argument("scenario_id", help="Scenario identifier")
    p_golden.add_argument(
        "--refresh", action="store_true",
        help="Refresh (overwrite) the golden snapshot with current output",
    )

    p_release = subparsers.add_parser(
        "release-check", help="Run release readiness checks",
    )
    p_release.add_argument("template_id", help="Template identifier")

    p_update_test = subparsers.add_parser(
        "update-test", help="Simulate a template update",
    )
    p_update_test.add_argument("template_id", help="Template identifier")
    p_update_test.add_argument("scenario_id", help="Scenario identifier")
    p_update_test.add_argument("old_version", help="Old template version")
    p_update_test.add_argument("new_version", help="New template version")

    return parser


# ---------------------------------------------------------------------------
# Command dispatch map
# ---------------------------------------------------------------------------

COMMAND_FN: dict[str, Callable[..., None]] = {
    "templatize": _cmd_templatize,
    "adopt": _cmd_adopt,
    "new": _cmd_new,
    "update": _cmd_update,
    "inspect": _cmd_inspect,
    "status": _cmd_status,
    "template-checkout": _cmd_template_checkout,
    "template-test": _cmd_template_test,
    "template-preview": _cmd_template_preview,
    "registry": _cmd_registry,
    "render": _cmd_render,
    "test": _cmd_test,
    "golden": _cmd_golden,
    "release-check": _cmd_release_check,
    "update-test": _cmd_update_test,
}


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> None:
    """Main entry point for the CopyRoom CLI.

    Parameters
    ----------
    argv:
        Command-line arguments. Defaults to ``sys.argv[1:]``.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    # --version handling
    if args.version:
        from . import __version__
        print(f"copyroom {__version__}")
        sys.exit(0)

    # No command given → show help
    if args.command is None:
        parser.print_help()
        sys.exit(0)

    cmd = args.command

    # --- Bootstrap commands run in an unmanaged repo: skip mode detection and
    # dispatch entirely; they resolve their own context from the repo/args. ---
    if cmd in BOOTSTRAP_COMMANDS:
        COMMAND_FN[cmd](args)
        return

    # --- Mode detection ---
    session = _detect_and_report(mode_override=args.mode)

    # --- Dispatch ---
    result = dispatch(cmd, session)

    if result == SessionStatus.command_failed:
        if session.status == SessionStatus.unknown_mode:
            # Already printed the message and exited in _detect_and_report
            sys.exit(1)
        session.advance(SessionStatus.command_failed)
        if session.mode and cmd in COMMAND_MODE_MAP:
            _print_out_of_mode_error(cmd, session)
        else:
            _print_unknown_command_error(cmd)
        # unreachable

    # --- Run the command ---
    session.advance(SessionStatus.command_running)
    handler = COMMAND_FN.get(cmd)
    if handler is not None:
        handler(args)
    session.advance(SessionStatus.command_complete)


if __name__ == "__main__":
    main()
