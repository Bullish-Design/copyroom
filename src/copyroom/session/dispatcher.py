"""Command dispatch — routes commands based on session mode.

Maps to DispatchWorkshopCommand, DispatchProjectCommand, and
RejectCommandOutOfMode rules in copyroom-session.allium (L88-L117).
"""

from __future__ import annotations

from .model import (
    PROJECT_COMMANDS,
    WORKSHOP_COMMANDS,
    CLIMode,
    CLISession,
    SessionStatus,
)

# Map commands to their expected mode (derived from the command sets, so new
# project/workshop commands are gated automatically).
COMMAND_MODE_MAP: dict[str, CLIMode] = {}
for cmd in WORKSHOP_COMMANDS:
    COMMAND_MODE_MAP[cmd] = CLIMode.workshop
for cmd in PROJECT_COMMANDS:
    COMMAND_MODE_MAP[cmd] = CLIMode.project


def dispatch(command: str, session: CLISession) -> SessionStatus:
    """Route *command* based on *session* mode.

    Returns the resulting status:

    * ``command_running`` — valid dispatch
    * ``command_failed`` — out-of-mode, unknown mode, or unknown command

    The caller is responsible for printing error messages and exiting.
    """
    # --- unknown_mode: reject everything ---
    if session.status == SessionStatus.unknown_mode:
        return SessionStatus.command_failed

    # --- must be in mode_detected to accept commands ---
    if session.status != SessionStatus.mode_detected:
        return SessionStatus.command_failed

    # --- look up the expected mode ---
    expected = COMMAND_MODE_MAP.get(command)
    if expected is None:
        # unknown command
        return SessionStatus.command_failed

    # --- mode check ---
    if session.mode != expected:
        return SessionStatus.command_failed

    return SessionStatus.command_running
