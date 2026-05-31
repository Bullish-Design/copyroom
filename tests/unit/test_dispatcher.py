"""Unit tests for command dispatch logic.

Covers the ``dispatch`` function from ``copyroom.session.dispatcher``.
"""

from __future__ import annotations

import pytest

from copyroom.session.dispatcher import COMMAND_MODE_MAP, dispatch
from copyroom.session.model import (
    PROJECT_COMMANDS,
    WORKSHOP_COMMANDS,
    CLIMode,
    CLISession,
    SessionStatus,
)

# ===========================================================================
# COMMAND_MODE_MAP tests
# ===========================================================================


class TestCommandModeMap:
    def test_all_workshop_commands_mapped(self) -> None:
        for cmd in WORKSHOP_COMMANDS:
            assert COMMAND_MODE_MAP[cmd] == CLIMode.workshop, f"{cmd} should map to workshop"

    def test_all_project_commands_mapped(self) -> None:
        for cmd in PROJECT_COMMANDS:
            assert COMMAND_MODE_MAP[cmd] == CLIMode.project, f"{cmd} should map to project"

    def test_command_sets_are_disjoint(self) -> None:
        """Workshop and project command sets must be disjoint (invariant)."""
        assert WORKSHOP_COMMANDS.isdisjoint(PROJECT_COMMANDS)

    def test_no_unexpected_commands_in_map(self) -> None:
        """Every key in COMMAND_MODE_MAP must be in one of the command sets."""
        all_known = WORKSHOP_COMMANDS | PROJECT_COMMANDS
        for cmd in COMMAND_MODE_MAP:
            assert cmd in all_known, f"{cmd} is not in any command set"


# ===========================================================================
# dispatch tests
# ===========================================================================


class BaseDispatchMixin:
    """Shared helpers for dispatch tests."""

    @staticmethod
    def _make_session(mode: CLIMode | None = None) -> CLISession:
        if mode is None:
            return CLISession(status=SessionStatus.mode_detecting)
        return CLISession(status=SessionStatus.mode_detected, mode=mode)


class TestDispatchWorkshop(BaseDispatchMixin):
    """Workshop commands should dispatch in workshop mode."""

    @pytest.mark.parametrize("cmd", sorted(WORKSHOP_COMMANDS))
    def test_workshop_cmd_in_workshop_mode(self, cmd: str) -> None:
        session = self._make_session(CLIMode.workshop)
        assert dispatch(cmd, session) == SessionStatus.command_running

    @pytest.mark.parametrize("cmd", sorted(WORKSHOP_COMMANDS))
    def test_workshop_cmd_in_project_mode_fails(self, cmd: str) -> None:
        session = self._make_session(CLIMode.project)
        assert dispatch(cmd, session) == SessionStatus.command_failed


class TestDispatchProject(BaseDispatchMixin):
    """Project commands should dispatch in project mode."""

    @pytest.mark.parametrize("cmd", sorted(PROJECT_COMMANDS))
    def test_project_cmd_in_project_mode(self, cmd: str) -> None:
        session = self._make_session(CLIMode.project)
        assert dispatch(cmd, session) == SessionStatus.command_running

    @pytest.mark.parametrize("cmd", sorted(PROJECT_COMMANDS))
    def test_project_cmd_in_workshop_mode_fails(self, cmd: str) -> None:
        session = self._make_session(CLIMode.workshop)
        assert dispatch(cmd, session) == SessionStatus.command_failed


class TestDispatchUnknownMode(BaseDispatchMixin):
    """In unknown_mode, every command should fail."""

    @pytest.mark.parametrize("cmd", sorted(WORKSHOP_COMMANDS | PROJECT_COMMANDS))
    def test_any_command_in_unknown_mode_fails(self, cmd: str) -> None:
        session = CLISession(status=SessionStatus.unknown_mode)
        assert dispatch(cmd, session) == SessionStatus.command_failed


class TestDispatchNotYetDetected(BaseDispatchMixin):
    """If mode hasn't been detected yet, dispatch should fail."""

    def test_command_before_detection_fails(self) -> None:
        session = CLISession(status=SessionStatus.mode_detecting)
        assert dispatch("new", session) == SessionStatus.command_failed

    def test_command_after_completion_fails(self) -> None:
        session = CLISession(
            status=SessionStatus.command_complete,
            mode=CLIMode.project,
        )
        assert dispatch("new", session) == SessionStatus.command_failed


class TestDispatchUnknownCommand(BaseDispatchMixin):
    """Unknown commands should be rejected."""

    def test_unknown_command_returns_failed(self) -> None:
        session = self._make_session(CLIMode.workshop)
        assert dispatch("nonexistent", session) == SessionStatus.command_failed

    def test_empty_string_returns_failed(self) -> None:
        session = self._make_session(CLIMode.workshop)
        assert dispatch("", session) == SessionStatus.command_failed

    def test_deferred_command_returns_failed(self) -> None:
        """inspect and status are deferred to v0.3.0 — should fail dispatch."""
        session = self._make_session(CLIMode.project)
        assert dispatch("inspect", session) == SessionStatus.command_failed
        assert dispatch("status", session) == SessionStatus.command_failed


class TestDispatchInvalidSession(BaseDispatchMixin):
    """Edge cases with invalid/malformed sessions."""

    def test_mode_detected_no_mode_set(self) -> None:
        """Should not normally happen, but guard against it."""
        session = CLISession(status=SessionStatus.mode_detected, mode=None)
        # No mode -> cannot determine if command is valid
        result = dispatch("new", session)
        assert result == SessionStatus.command_failed
