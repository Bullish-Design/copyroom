"""Domain types for CLI session lifecycle and mode detection.

Maps directly to the Allium spec at .scratch/specs/copyroom-session.allium.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CLIMode(StrEnum):
    """Dispatchable modes for CopyRoom.

    v0.x defines exactly two dispatchable modes: workshop and project.
    ``template_repo`` and ``standalone`` are held in reserve for future
    feature gates (v0.5.0). See §10.4 and §13 of the implementation plan.
    """

    workshop = "workshop"
    project = "project"
    # template_repo and standalone — held in reserve


class SessionStatus(StrEnum):
    """States in the CLISession lifecycle (copyroom-session.allium L16-L17)."""

    mode_detecting = "mode_detecting"
    mode_detected = "mode_detected"
    command_running = "command_running"
    command_complete = "command_complete"
    command_failed = "command_failed"
    unknown_mode = "unknown_mode"


# Copyroom-session.allium L22-L33
VALID_SESSION_TRANSITIONS: dict[SessionStatus, set[SessionStatus]] = {
    SessionStatus.mode_detecting: {
        SessionStatus.mode_detected,
        SessionStatus.unknown_mode,
    },
    SessionStatus.mode_detected: {
        SessionStatus.command_running,
        SessionStatus.command_failed,
    },
    SessionStatus.command_running: {
        SessionStatus.command_complete,
        SessionStatus.command_failed,
    },
    SessionStatus.command_complete: set(),  # terminal
    SessionStatus.command_failed: set(),  # terminal
    SessionStatus.unknown_mode: set(),  # terminal
}

# Copyroom-session.allium L88-92, L94-98
WORKSHOP_COMMANDS: frozenset[str] = frozenset(
    {"registry", "render", "test", "golden", "release-check", "update-test"},
)

PROJECT_COMMANDS: frozenset[str] = frozenset({"new", "update"})


@dataclass
class CLISession:
    """Represents a CLI session with status and optional mode.

    The ``mode`` field is state-dependent: only present when status has
    advanced past ``mode_detecting`` and is not ``unknown_mode``.
    """

    status: SessionStatus = SessionStatus.mode_detecting
    mode: CLIMode | None = None


class InvalidTransitionError(Exception):
    """Raised when an entity attempts an invalid state transition."""

    def __init__(self, status: SessionStatus, target: SessionStatus) -> None:
        self.status = status
        self.target = target
        super().__init__(f"Invalid transition: {status.value} -> {target.value}")
