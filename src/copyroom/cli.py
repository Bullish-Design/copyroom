"""CLI frontend for CopyRoom.

Entry point::

    copyroom [--no-detect] <command> [args...]

Modes are auto-detected unless ``--no-detect`` is passed.
If neither workshop nor project markers are found, exits with a clear error.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from .session.detector import detect_mode
from .session.dispatcher import COMMAND_MODE_MAP, dispatch
from .session.model import (
    CLIMode,
    CLISession,
    PROJECT_COMMANDS,
    SessionStatus,
    WORKSHOP_COMMANDS,
)

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
    """``copyroom new <source> [target] [--answers FILE]`` — deferred to Phase 2."""
    print(f"[copyroom new] source={args.source} target={args.target} "
          f"answers_file={args.answers_file}")
    # TODO Phase 2: implement ProjectCreation workflow


def _cmd_update(args: argparse.Namespace) -> None:
    """``copyroom update [target_ref] [--branch]`` — deferred to Phase 2."""
    print(f"[copyroom update] target_ref={args.target_ref} branch={args.branch}")
    # TODO Phase 2: implement TemplateUpdate workflow


def _cmd_registry(args: argparse.Namespace) -> None:
    """``copyroom registry <action> [args...]`` — deferred to Phase 3."""
    print(f"[copyroom registry] action={args.action} args={args.args}")
    # TODO Phase 3: implement registry operations


def _cmd_render(args: argparse.Namespace) -> None:
    """``copyroom render <template_id> <scenario_id>`` — deferred to Phase 3."""
    print(f"[copyroom render] template_id={args.template_id} scenario_id={args.scenario_id}")
    # TODO Phase 3: implement scenario rendering


def _cmd_test(args: argparse.Namespace) -> None:
    """``copyroom test <template_id> <scenario_id>`` — deferred to Phase 3."""
    print(f"[copyroom test] template_id={args.template_id} scenario_id={args.scenario_id}")
    # TODO Phase 3: implement test scenario


def _cmd_golden(args: argparse.Namespace) -> None:
    """``copyroom golden <template_id> <scenario_id>`` — deferred to Phase 3."""
    print(f"[copyroom golden] template_id={args.template_id} scenario_id={args.scenario_id}")
    # TODO Phase 3: implement golden diff


def _cmd_release_check(args: argparse.Namespace) -> None:
    """``copyroom release-check <template_id>`` — deferred to Phase 4."""
    print(f"[copyroom release-check] template_id={args.template_id}")
    # TODO Phase 4: implement release checks


def _cmd_update_test(args: argparse.Namespace) -> None:
    """``copyroom update-test <template_id> <scenario_id> <old> <new>`` — deferred to Phase 3."""
    print(f"[copyroom update-test] template_id={args.template_id} "
          f"scenario_id={args.scenario_id} old={args.old_version} new={args.new_version}")
    # TODO Phase 3: implement update simulation


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

COMMAND_FN: dict[str, callable] = {
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
