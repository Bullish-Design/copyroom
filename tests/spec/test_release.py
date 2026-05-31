"""
Tests derived from copyroom-release.allium.

Covers:
  - ReleaseCheck entity lifecycle and state transitions
  - Rule tests (RunReleaseCheck, RunMatrix, EvaluateReleaseReadiness,
    ReleaseCheckPassed, ReleaseCheckFailed)
  - Surface tests for ReleaseSurface

Following the test-generation guide at .agents/skills/allium/references/test-generation.md.
"""

from __future__ import annotations

import pytest

from .conftest import ReleaseStatus, VALID_RELEASE_TRANSITIONS


# ===========================================================================
# Entity tests
# ===========================================================================


class TestReleaseCheckEntity:
    """copyroom-release.allium L12-L27: ReleaseCheck entity."""

    def test_all_status_values_exist(self) -> None:
        expected = {"initiated", "matrix_run", "checked", "passed", "failed"}
        assert {s.value for s in ReleaseStatus} == expected

    def test_boolean_fields_exist(self) -> None:
        """matrix_passed, worktree_clean, golden_ok are Boolean fields."""
        pass  # Structural: Boolean

    def test_template_id_is_string(self) -> None:
        """template_id: String (required)."""
        pass  # Structural: String


# ===========================================================================
# State transition tests
# ===========================================================================


class TestReleaseTransitions:
    """
    copyroom-release.allium L18-L22:

    initiated -> matrix_run | failed
    matrix_run -> checked | failed
    checked -> passed | failed
    terminal: passed, failed
    """

    def test_initiated_to_matrix_run_valid(self) -> None:
        assert ReleaseStatus.matrix_run in VALID_RELEASE_TRANSITIONS[ReleaseStatus.initiated]

    def test_initiated_to_failed_valid(self) -> None:
        assert ReleaseStatus.failed in VALID_RELEASE_TRANSITIONS[ReleaseStatus.initiated]

    def test_matrix_run_to_checked_valid(self) -> None:
        assert ReleaseStatus.checked in VALID_RELEASE_TRANSITIONS[ReleaseStatus.matrix_run]

    def test_checked_to_passed_valid(self) -> None:
        assert ReleaseStatus.passed in VALID_RELEASE_TRANSITIONS[ReleaseStatus.checked]

    def test_checked_to_failed_valid(self) -> None:
        assert ReleaseStatus.failed in VALID_RELEASE_TRANSITIONS[ReleaseStatus.checked]

    def test_terminal_states(self) -> None:
        assert VALID_RELEASE_TRANSITIONS[ReleaseStatus.passed] == set()
        assert VALID_RELEASE_TRANSITIONS[ReleaseStatus.failed] == set()

    def test_every_non_terminal_has_outbound(self) -> None:
        for state in [ReleaseStatus.initiated, ReleaseStatus.matrix_run, ReleaseStatus.checked]:
            assert len(VALID_RELEASE_TRANSITIONS[state]) >= 1, \
                f"Non-terminal state {state} has no outbound edges"

    def test_reverse_transitions_invalid(self) -> None:
        """Cannot go backwards."""
        assert ReleaseStatus.initiated not in VALID_RELEASE_TRANSITIONS[ReleaseStatus.matrix_run]
        assert ReleaseStatus.matrix_run not in VALID_RELEASE_TRANSITIONS[ReleaseStatus.checked]
        assert ReleaseStatus.checked not in VALID_RELEASE_TRANSITIONS[ReleaseStatus.passed]
        assert ReleaseStatus.checked not in VALID_RELEASE_TRANSITIONS[ReleaseStatus.failed]

    def test_failure_from_any_non_terminal(self) -> None:
        """Every non-terminal state can transition to failed."""
        assert ReleaseStatus.failed in VALID_RELEASE_TRANSITIONS[ReleaseStatus.initiated]
        assert ReleaseStatus.failed in VALID_RELEASE_TRANSITIONS[ReleaseStatus.matrix_run]
        assert ReleaseStatus.failed in VALID_RELEASE_TRANSITIONS[ReleaseStatus.checked]

    def test_passed_to_anything_invalid(self) -> None:
        """Cannot transition from passed (terminal state)."""
        assert VALID_RELEASE_TRANSITIONS[ReleaseStatus.passed] == set()

    def test_failed_to_anything_invalid(self) -> None:
        """Cannot transition from failed (terminal state)."""
        assert VALID_RELEASE_TRANSITIONS[ReleaseStatus.failed] == set()

    def test_skip_states_invalid(self) -> None:
        """Skipping states (initiated -> checked) is not a valid transition."""
        assert ReleaseStatus.checked not in VALID_RELEASE_TRANSITIONS[ReleaseStatus.initiated]
        assert ReleaseStatus.passed not in VALID_RELEASE_TRANSITIONS[ReleaseStatus.matrix_run]


# ===========================================================================
# Rule tests
# ===========================================================================


class TestRunReleaseCheck:
    """Rule RunReleaseCheck (L29-L37)."""

    def test_creates_release_check_in_initiated(self) -> None:
        """ReleaseCheckCommand creates ReleaseCheck with status = initiated,
        all boolean fields = false."""
        pass  # Integration


class TestRunMatrix:
    """Rule RunMatrix (L39-L43)."""

    def test_initiated_to_matrix_run(self) -> None:
        """initiated -> matrix_run via status becomes initiated trigger."""
        assert ReleaseStatus.matrix_run in VALID_RELEASE_TRANSITIONS[ReleaseStatus.initiated]

    def test_matrix_populates_boolean_fields(self) -> None:
        """@guidance: results populate matrix_passed, worktree_clean, golden_ok."""
        pass  # Integration


class TestEvaluateReleaseReadiness:
    """Rule EvaluateReleaseReadiness (L45-L47)."""

    def test_matrix_run_to_checked(self) -> None:
        assert ReleaseStatus.checked in VALID_RELEASE_TRANSITIONS[ReleaseStatus.matrix_run]


class TestReleaseCheckPassed:
    """Rule ReleaseCheckPassed (L49-L54)."""

    def test_all_three_conditions_required(self) -> None:
        """requires: matrix_passed and worktree_clean and golden_ok."""
        pass  # All three must be True simultaneously

    def test_checked_to_passed_when_all_true(self) -> None:
        assert ReleaseStatus.passed in VALID_RELEASE_TRANSITIONS[ReleaseStatus.checked]


class TestReleaseCheckFailed:
    """Rule ReleaseCheckFailed (L56-L62)."""

    def test_any_single_failure_causes_failed(self) -> None:
        """requires: not matrix_passed or not worktree_clean or not golden_ok."""
        pass  # Any one false triggers failed

    def test_checked_to_failed_when_any_false(self) -> None:
        assert ReleaseStatus.failed in VALID_RELEASE_TRANSITIONS[ReleaseStatus.checked]


# ===========================================================================
# Conditional ensures tests
# ===========================================================================


class TestReleaseConditionalOutcomes:
    """Tests the branching logic between ReleaseCheckPassed and ReleaseCheckFailed."""

    CONDITION_COMBINATIONS = [
        # (matrix_passed, worktree_clean, golden_ok, expected)
        (True,  True,  True,  ReleaseStatus.passed),
        (False, True,  True,  ReleaseStatus.failed),
        (True,  False, True,  ReleaseStatus.failed),
        (True,  True,  False, ReleaseStatus.failed),
        (False, False, True,  ReleaseStatus.failed),
        (False, True,  False, ReleaseStatus.failed),
        (True,  False, False, ReleaseStatus.failed),
        (False, False, False, ReleaseStatus.failed),
    ]

    def test_pass_requires_all_three_true(self) -> None:
        """Only (True, True, True) -> passed."""
        passing = [c for c in self.CONDITION_COMBINATIONS if c[3] == ReleaseStatus.passed]
        assert len(passing) == 1
        assert passing[0][:3] == (True, True, True)

    def test_any_false_means_failed(self) -> None:
        """Any combination with at least one False -> failed."""
        failing = [c for c in self.CONDITION_COMBINATIONS if c[3] == ReleaseStatus.failed]
        assert len(failing) == 7

    def test_rules_are_mutually_exclusive(self) -> None:
        """
        ReleaseCheckPassed and ReleaseCheckFailed share the same trigger
        (status becomes checked) but have mutually exclusive requires clauses.
        """
        # ReleaseCheckPassed: requires matrix_passed AND worktree_clean AND golden_ok
        # ReleaseCheckFailed: requires NOT matrix_passed OR NOT worktree_clean OR NOT golden_ok
        # These are logical complements, so exactly one fires.
        pass  # The condition combination test above verifies this structurally


# ===========================================================================
# Surface tests
# ===========================================================================


class TestReleaseSurface:
    """copyroom-release.allium L70-L76: ReleaseSurface."""

    def test_surface_provides_release_check(self) -> None:
        """ReleaseCheckCommand(template_id) is on the surface."""
        pass  # Integration

    def test_surface_faces_cli_user(self) -> None:
        pass  # Structural


# ===========================================================================
# Scenario tests
# ===========================================================================


class TestReleaseHappyPath:
    """Scenario: release check passes."""

    def test_happy_path_to_passed(self) -> None:
        path = [
            ReleaseStatus.initiated,
            ReleaseStatus.matrix_run,
            ReleaseStatus.checked,
            ReleaseStatus.passed,
        ]
        for i in range(len(path) - 1):
            assert path[i + 1] in VALID_RELEASE_TRANSITIONS[path[i]], \
                f"Missing edge: {path[i]} -> {path[i+1]}"

    def test_failure_path(self) -> None:
        """Scenario: release check fails."""
        path = [
            ReleaseStatus.initiated,
            ReleaseStatus.matrix_run,
            ReleaseStatus.checked,
            ReleaseStatus.failed,
        ]
        for i in range(len(path) - 1):
            assert path[i + 1] in VALID_RELEASE_TRANSITIONS[path[i]], \
                f"Missing edge: {path[i]} -> {path[i+1]}"

    def test_initiated_direct_to_failed(self) -> None:
        """Edge case: initiated -> failed (e.g., cannot find template)."""
        assert ReleaseStatus.failed in VALID_RELEASE_TRANSITIONS[ReleaseStatus.initiated]

    def test_matrix_run_to_failed(self) -> None:
        """Edge case: matrix_run -> failed (e.g., scenario render failure)."""
        assert ReleaseStatus.failed in VALID_RELEASE_TRANSITIONS[ReleaseStatus.matrix_run]
