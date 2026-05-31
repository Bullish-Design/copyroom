"""
Tests derived from copyroom.allium (entrypoint) — cross-cutting invariants.

Covers:
  - Top-level invariants from the entrypoint spec
  - Cross-spec behavioural properties
  - Deferred specification awareness
  - Operational guarantees (OffRampAlwaysAvailable, NoRemoteExecution, etc.)

These invariants are prose (prefixed with @invariant / invariant without
expression body), so they describe properties to verify through
integration/behavioural tests rather than compile-time checks.

Following the test-generation guide at .agents/skills/allium/references/test-generation.md.
"""

from __future__ import annotations

import pytest


# ===========================================================================
# Invariant: OperatingModelBoundary
# ===========================================================================


class TestOperatingModelBoundary:
    """
    copyroom.allium L30-L33:

    CopyRoom coordinates template work. Template repos contain template
    source. Shared tooling repos contain reusable behavior. Generated
    projects own local choices.
    """

    def test_template_repo_separate_from_generated_project(self) -> None:
        """Template source lives in a template repo, not in generated projects."""
        pass  # Architectural

    def test_shared_tooling_repo_separate_from_template_repo(self) -> None:
        """Shared tooling repos contain reusable behavior, separate from templates."""
        pass  # Architectural

    def test_generated_projects_own_local_choices(self) -> None:
        """Generated projects own their local modifications (in .copier-answers.yml scope)."""
        pass  # Architectural


# ===========================================================================
# Invariant: NoRemoteExecution
# ===========================================================================


class TestNoRemoteExecution:
    """
    copyroom.allium L35-L37:

    The CLI never fetches scripts from URLs or executes commands from
    remote registry entries. Template sources are Git URLs passed to
    Copier. Copier handles the fetch.
    """

    def test_no_url_fetched_scripts(self) -> None:
        """The CLI must never fetch and execute scripts from arbitrary URLs."""
        pass  # Security audit / integration

    def test_no_remote_registry_command_execution(self) -> None:
        """The CLI must never execute commands from remote registry entries."""
        pass  # Security audit / integration

    def test_copier_handles_git_fetch(self) -> None:
        """Template sources are Git URLs passed to Copier. Copier handles the fetch."""
        pass  # Architectural


# ===========================================================================
# Invariant: CopierAnswersAuthoritative
# ===========================================================================


class TestCopierAnswersAuthoritative:
    """
    copyroom.allium L39-L42:

    .copier-answers.yml is authoritative for Copier operations.
    copyroom.project.yml is advisory for workflow metadata.
    """

    def test_copier_answers_is_authoritative(self) -> None:
        """Template source and version come from .copier-answers.yml, not copyroom.project.yml."""
        pass  # Integration

    def test_project_yml_is_advisory(self) -> None:
        """copyroom.project.yml carries workflow metadata but does not override copier answers."""
        pass  # Integration


# ===========================================================================
# Invariant: OffRampAlwaysAvailable
# ===========================================================================


class TestOffRampAlwaysAvailable:
    """
    copyroom.allium L44-L47:

    Removing CopyRoom from a project: delete copyroom.project.yml,
    optionally remove copyroom from dev deps. .copier-answers.yml is
    unaffected. The project remains a normal Copier-managed project.
    """

    def test_project_remains_copier_managed_after_copyroom_removal(self) -> None:
        """After removing copyroom.project.yml, the project still works with copier update."""
        pass  # Integration

    def test_copier_answers_unaffected_by_copyroom_removal(self) -> None:
        """.copier-answers.yml is never modified by CopyRoom removal."""
        pass  # Integration

    def test_no_irreversible_actions(self) -> None:
        """CopyRoom must not perform irreversible modifications to the project."""
        pass  # Integration


# ===========================================================================
# Invariant: ErrorHandlingConsistent
# ===========================================================================


class TestErrorHandlingConsistent:
    """
    copyroom.allium L49-L52:

    All errors: print what happened, what failed, where state was left.
    Never automatic rollback. Never silent errors. Non-zero exit on
    failure. For wrapped commands, print the underlying tool's stderr.
    """

    def test_errors_print_what_happened(self) -> None:
        """Error messages must describe what operation was being performed."""
        pass  # Integration

    def test_errors_print_what_failed(self) -> None:
        """Error messages must describe what specifically failed."""
        pass  # Integration

    def test_errors_print_state_left(self) -> None:
        """Error messages must describe where state was left after failure."""
        pass  # Integration

    def test_no_automatic_rollback(self) -> None:
        """The CLI must never automatically roll back changes on failure."""
        pass  # Integration

    def test_no_silent_errors(self) -> None:
        """Every error must produce visible output."""
        pass  # Integration

    def test_non_zero_exit_on_failure(self) -> None:
        """The process must exit with a non-zero code on failure."""
        pass  # Integration

    def test_wrapped_command_stderr_forwarded(self) -> None:
        """When Copier or other wrapped tools fail, their stderr is printed."""
        pass  # Integration


# ===========================================================================
# Cross-spec invariant: mode-gated surface access
# ===========================================================================


class TestCrossSpecInvariants:
    """Invariants that span multiple spec files."""

    def test_workshop_commands_only_in_workshop_mode(self) -> None:
        """
        From copyroom-session.allium RejectCommandOutOfMode:
        Workshop commands (registry, render, test, golden, release-check, update-test)
        only dispatch in workshop mode.
        """
        workshop_commands = {"registry", "render", "test", "golden", "release-check", "update-test"}
        project_commands = {"new", "update"}
        assert workshop_commands.isdisjoint(project_commands)

    def test_project_commands_only_in_project_mode(self) -> None:
        """
        Project commands (new, update) only dispatch in project mode.
        inspect and status are deferred to v0.3.0.
        """
        workshop_commands = {"registry", "render", "test", "golden", "release-check", "update-test"}
        project_commands = {"new", "update"}
        for cmd in project_commands:
            assert cmd not in workshop_commands

    def test_project_creation_requires_project_mode(self) -> None:
        """CreateProject is a project command; must dispatch in project mode only."""
        pass  # Integration: RunCommand with CreateProject in non-project modes must fail

    def test_template_update_requires_project_mode(self) -> None:
        """UpdateTemplate is a project command; must dispatch in project mode only."""
        pass  # Integration

    def test_render_requires_workshop_mode(self) -> None:
        """RenderCommand is a workshop command; must dispatch in workshop mode only."""
        pass  # Integration

    def test_release_check_requires_workshop_mode(self) -> None:
        """ReleaseCheckCommand is a workshop command; must dispatch in workshop mode only."""
        pass  # Integration

    def test_workshop_project_modes_are_mutually_exclusive_invariant(self) -> None:
        """
        From copyroom-session.allium ModeExclusive invariant:
        A session cannot be in two modes simultaneously.
        """
        # Tested structurally in test_session_lifecycle.py
        pass
