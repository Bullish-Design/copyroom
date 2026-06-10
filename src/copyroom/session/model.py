"""Domain types for CLI session lifecycle and mode detection.

Maps directly to the Allium spec at .scratch/specs/copyroom-session.allium.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .._compat.state_machine import StateMachine


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

PROJECT_COMMANDS: frozenset[str] = frozenset(
    {"update", "inspect", "status",
     "template-checkout", "template-test", "template-preview"},
)

# Bootstrap commands run in an *unmanaged* repo (no workshop/project markers),
# so they bypass mode detection entirely — they resolve their own context from
# the repo and arguments. Kept out of COMMAND_MODE_MAP for that reason. `new`
# belongs here: it is run to *create* a project, so the project markers it would
# be gated on don't exist yet (its real guard is the empty-target check).
BOOTSTRAP_COMMANDS: frozenset[str] = frozenset({"adopt", "templatize", "new"})

_session_sm = StateMachine(VALID_SESSION_TRANSITIONS, entity_name="CLISession")


@dataclass
class CLISession:
    """Represents a CLI session with status and optional mode.

    The ``mode`` field is state-dependent: only present when status has
    advanced past ``mode_detecting`` and is not ``unknown_mode``.
    """

    status: SessionStatus = SessionStatus.mode_detecting
    mode: CLIMode | None = None

    def advance(self, target: SessionStatus) -> None:
        """Move to *target*, validating it against ``VALID_SESSION_TRANSITIONS``.

        Raises ``InvalidTransitionError`` (from ``_compat.state_machine``) when
        the transition is not declared, keeping the session lifecycle honest
        rather than decorative.
        """
        self.status = _session_sm.transition(self.status, target)
