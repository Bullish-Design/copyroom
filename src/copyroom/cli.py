"""CLI frontend for CopyRoom.

Entry point::

    copyroom [--no-detect] <command> [args...]

Modes are auto-detected unless ``--no-detect`` is passed.
If neither workshop nor project markers are found, exits with a clear error.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence

from .project.create import CopyRoomError as CreateError
from .project.create import create_project
from .project.model import CreationStatus, UpdateStatus
from .project.update import CopyRoomError as UpdateError
from .project.update import update_project
from .session.detector import detect_mode
from .session.dispatcher import COMMAND_MODE_MAP, dispatch
from .session.model import (
    PROJECT_COMMANDS,
    WORKSHOP_COMMANDS,
    CLIMode,
    CLISession,
    SessionStatus,
)
from .release.check import CopyRoomError as ReleaseError
from .release.check import ReleaseStatus, run_release_check as _run_release_check
from .workshop.golden import CopyRoomError as GoldenError
from .workshop.golden import golden_diff, refresh_golden
from .workshop.model import GoldenStatus, RenderStatus, SimStatus
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
  new       <source> [target] [--answers FILE]
                               Create a new project from a template
  update    [target_ref] [--branch]
                               Update an existing project

Workshop commands (in a workshop directory):
  registry      <action> [args...]
                               Manage template registry
  render        <template_id> <scenario_id>
                               Render a template scenario
  test          <template_id> <scenario_id>
                               Test rendered output
  golden        <template_id> <scenario_id>
                               Golden test a scenario
  release-check <template_id>  Run release readiness checks
  update-test   <template_id> <scenario_id> <old> <new>
                               Simulate a template update

Deferred (v0.3.0): inspect, status
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


def _detect_and_report(no_detect: bool) -> CLISession:
    """Detect mode and return a session. Prints status and may exit."""
    session = CLISession()

    if no_detect:
        # --no-detect: skip detection; caller must specify mode explicitly
        # (currently just echoes the mode)
        return session

    mode = detect_mode()
    if mode is None:
        session.status = SessionStatus.unknown_mode
        print(NO_MODE_FOUND_MESSAGE, file=sys.stderr)
        sys.exit(1)
        # unreachable

    session.mode = mode
    session.status = SessionStatus.mode_detected
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
# Subcommand stubs (Phases 2-4 will fill these in)
# ---------------------------------------------------------------------------


def _cmd_new(args: argparse.Namespace) -> None:
    """``copyroom new <source> [target] [--answers FILE]`` — Phase 2."""
    try:
        creation = create_project(
            source=args.source,
            target_dir=args.target or ".",
            answers_file=args.answers_file,
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
        )
    except UpdateError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    if update.status == UpdateStatus.failed:
        if update.previous_ref == update.target_ref:
            print(f"Already at version {update.target_ref}; nothing to update.", file=sys.stderr)
        else:
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


def _cmd_registry(args: argparse.Namespace) -> None:
    """``copyroom registry <action> [args...]`` — deferred to Phase 3."""
    print(f"[copyroom registry] action={args.action} args={args.args}")
    # TODO Phase 3: implement registry operations


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
        "--no-detect",
        action="store_true",
        help="Skip mode auto-detection",
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

    p_update = subparsers.add_parser("update", help="Update an existing project")
    p_update.add_argument("target_ref", nargs="?", default=None,
                          help="Target version ref (tag or branch)")
    p_update.add_argument("--branch", action="store_true",
                          help="Create an isolation branch for the update")

    # --- Workshop commands ---
    p_registry = subparsers.add_parser("registry", help="Manage template registry")
    p_registry.add_argument("action", help="Registry action (list, add, remove, etc.)")
    p_registry.add_argument("args", nargs="*", help="Additional arguments")

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
    "new": _cmd_new,
    "update": _cmd_update,
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

    # --- Mode detection ---
    session = _detect_and_report(no_detect=args.no_detect)

    # --- Dispatch ---
    cmd = args.command
    result = dispatch(cmd, session)

    if result == SessionStatus.command_failed:
        if session.status == SessionStatus.unknown_mode:
            # Already printed the message and exited in _detect_and_report
            sys.exit(1)
        elif session.mode and cmd in COMMAND_MODE_MAP:
            _print_out_of_mode_error(cmd, session)
        else:
            _print_unknown_command_error(cmd)
        # unreachable

    # --- Run the command ---
    session.status = SessionStatus.command_running
    handler = COMMAND_FN.get(cmd)
    if handler is not None:
        handler(args)
    session.status = SessionStatus.command_complete


if __name__ == "__main__":
    main()
