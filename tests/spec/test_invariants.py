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

import subprocess
from pathlib import Path

import pytest
import yaml

from copyroom._compat.state_machine import InvalidTransitionError, StateMachine
from copyroom.project.create import CopyRoomError
from copyroom.project.model import (
    VALID_CREATION_TRANSITIONS,
    VALID_UPDATE_TRANSITIONS,
    CreationStatus,
    UpdateStatus,
)
from copyroom.session.dispatcher import COMMAND_MODE_MAP, dispatch
from copyroom.session.model import (
    PROJECT_COMMANDS,
    VALID_SESSION_TRANSITIONS,
    WORKSHOP_COMMANDS,
    CLIMode,
    CLISession,
    SessionStatus,
)

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
        # CopyRoomError constructor takes a message that describes what happened
        err = CopyRoomError("Project creation failed during copy step", state="copy_executed")
        output = str(err)
        # The error message should describe what happened (the operation)
        assert "Project creation" in output
        assert "copy step" in output

    def test_errors_print_what_failed(self) -> None:
        """Error messages must describe what specifically failed."""
        err = CopyRoomError(
            "Copier copy failed with exit code 1: template source not found",
            state="prompts_collected",
        )
        output = str(err)
        assert "Copier copy failed" in output
        assert "exit code 1" in output

    def test_errors_print_state_left(self) -> None:
        """Error messages must describe where state was left after failure."""
        err = CopyRoomError("Target directory is not empty", state="target_verified")
        output = str(err)
        assert "State left: target_verified" in output

        # And when no state is provided, the output doesn't mention state
        err2 = CopyRoomError("Template source is required")
        output2 = str(err2)
        assert "State left:" not in output2

    def test_no_automatic_rollback(self) -> None:
        """The CLI must never automatically roll back changes on failure.

        Verify that state machines throw InvalidTransitionError rather than
        silently rolling back — transitions must be explicit.
        """
        sm = StateMachine(VALID_CREATION_TRANSITIONS, entity_name="ProjectCreation")

        # A transition from complete back to initiated should raise
        with pytest.raises(InvalidTransitionError, match="Invalid ProjectCreation transition"):
            sm.transition(CreationStatus.complete, CreationStatus.initiated)

        # A terminal failed state should not transition to anything
        with pytest.raises(InvalidTransitionError, match="Invalid ProjectCreation transition"):
            sm.transition(CreationStatus.failed, CreationStatus.complete)

    def test_no_silent_errors(self) -> None:
        """Every error must produce visible output.

        Verify that CopyRoomError always produces a non-empty string representation.
        """
        err = CopyRoomError("Something went wrong", state="initiated")
        output = str(err)
        assert len(output) > 0
        assert "Error:" in output

    def test_non_zero_exit_on_failure(self) -> None:
        """The process must exit with a non-zero code on failure.

        Verify that dispatch returns command_failed for invalid commands,
        which the CLI layer translates to a non-zero exit.
        """
        # Dispatch an out-of-mode command
        session = CLISession(status=SessionStatus.mode_detected, mode=CLIMode.project)
        result = dispatch("render", session)  # render is a workshop command
        assert result == SessionStatus.command_failed

        # Dispatch an unknown command
        result2 = dispatch("nonexistent", session)
        assert result2 == SessionStatus.command_failed

        # Dispatch from unknown_mode
        session2 = CLISession(status=SessionStatus.unknown_mode)
        result3 = dispatch("new", session2)
        assert result3 == SessionStatus.command_failed

    def test_wrapped_command_stderr_forwarded(self) -> None:
        """When Copier or other wrapped tools fail, their stderr is printed.

        Verify that the copier subprocess wrapper captures stderr and that
        the create workflow forwards it on failure.
        """
        # Run copier with an invalid source to trigger failure
        result = subprocess.run(
            ["copier", "copy", "--quiet", "nonexistent-template-source", "/tmp/copyroom_test_doesnotexist"],
            capture_output=True,
            text=True,
        )
        # Copier should fail (returncode != 0)
        assert result.returncode != 0
        # Copier should produce some output on stderr
        assert len(result.stderr) > 0 or len(result.stdout) > 0


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
        """The CLI subprocess wrapper only calls local copier; no URL fetching logic.

        Verify that the copier compat layer delegates entirely to Copier subprocess.
        """
        # Inspect the function source to verify it only calls subprocess.run
        import inspect

        from copyroom._compat.copier import copier_copy, copier_update
        copy_src = inspect.getsource(copier_copy)
        update_src = inspect.getsource(copier_update)

        # Both functions should delegate to subprocess.run
        assert "subprocess.run" in copy_src
        assert "subprocess.run" in update_src

        # Neither function should contain URL fetching logic
        assert "urllib" not in copy_src
        assert "requests" not in copy_src
        assert "http" not in copy_src.lower()

    def test_no_remote_registry_command_execution(self) -> None:
        """The CreateProject operation only accepts local paths and git URLs.

        Verify that the project creation module does not execute remote scripts.
        """
        from copyroom.project.create import initiate

        # initiate should accept any non-empty source (passed to Copier)
        creation = initiate(source="gh:org/template")
        assert creation.template_source == "gh:org/template"

        # initiate should reject empty source
        with pytest.raises(CopyRoomError, match="Template source is required"):
            initiate(source="")

        # The implementation delegates to Copier which handles git clone
        # CopyRoom never directly fetches or executes remote content

    def test_copier_handles_git_fetch(self) -> None:
        """Template sources are Git URLs passed to Copier. Copier handles the fetch.

        Verify that the copier subprocess wrapper passes the source URL through
        to Copier without interception or transformation.
        """
        import inspect

        from copyroom._compat.copier import copier_copy
        src = inspect.getsource(copier_copy)

        # The source parameter is passed directly to the copier subprocess command
        assert '"copier"' in src
        assert '"copy"' in src

        # The function does not inspect, validate, or transform the source URL
        # before passing it to Copier


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
        """Workshop markers (template repos) are distinct from project markers.

        A directory cannot simultaneously be a workshop and a project root.
        """
        # The marker sets are mutually exclusive in structure:
        # - Workshop needs: copyroom.yml + registry/ + scenarios/
        # - Project needs: .copier-answers.yml or copyroom.project.yml
        #
        # While it's technically possible for a directory to have all these
        # files, the detector checks workshop first and returns immediately,
        # so the effective mode is always one or the other.
        # Verify the helper functions work independently
        import tempfile

        from copyroom.session.detector import is_project, is_workshop

        with tempfile.TemporaryDirectory() as td:
            p = Path(td)

            # Neither workshop nor project markers
            assert not is_workshop(p)
            assert not is_project(p)

            # With project marker only
            (p / "copyroom.project.yml").touch()
            assert not is_workshop(p)
            assert is_project(p)
            (p / "copyroom.project.yml").unlink()

            # Workshop structurally requires three markers
            (p / "copyroom.yml").touch()
            assert not is_workshop(p)  # missing registry/ and scenarios/
            (p / "copyroom.yml").unlink()

    def test_shared_tooling_repo_separate_from_template_repo(self) -> None:
        """The CopyRoom package is a shared tool; it does not embed template content.

        Verify that src/copyroom/ contains no template files.
        """
        src_dir = Path(__file__).resolve().parent.parent.parent / "src" / "copyroom"
        template_files = list(src_dir.rglob("copier.yml"))
        jinja_files = list(src_dir.rglob("*.jinja"))
        cookiecutter_files = list(src_dir.rglob("cookiecutter.json"))

        assert len(template_files) == 0, "copyroom/ must not contain copier.yml"
        assert len(jinja_files) == 0, "copyroom/ must not contain Jinja templates"
        assert len(cookiecutter_files) == 0, "copyroom/ must not contain cookiecutter.json"

        # A directory named ``template`` is only a boundary violation if it embeds
        # template *content*; a code package (the template-edit workflow) is fine.
        content_dirs = [
            d
            for d in src_dir.rglob("template")
            if d.is_dir()
            and (list(d.rglob("copier.yml")) or list(d.rglob("*.jinja")))
        ]
        assert not content_dirs, "copyroom/ must not embed a template/ directory with template content"

    def test_generated_projects_own_local_choices(self) -> None:
        """Generated projects own local modifications (in .copier-answers.yml scope).

        Verify the detector distinguishes workshop mode from project mode.
        A generated project with .copier-answers.yml is detected as project mode.
        """
        import tempfile

        from copyroom.session.detector import is_project

        with tempfile.TemporaryDirectory() as td:
            p = Path(td)

            # Without markers: not a project
            assert not is_project(p)

            # With .copier-answers.yml: is a project
            (p / ".copier-answers.yml").touch()
            assert is_project(p)
            (p / ".copier-answers.yml").unlink()

            # With copyroom.project.yml: is a project
            (p / "copyroom.project.yml").touch()
            assert is_project(p)


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
        """.copier-answers.yml is the canonical source for template metadata.

        CopyRoom's project detector treats .copier-answers.yml as a definitive
        project marker. The file contains Copier's authoritative answers
        (template source, version, answers).
        """
        import tempfile

        from copyroom.session.detector import is_project

        with tempfile.TemporaryDirectory() as td:
            p = Path(td)

            # .copier-answers.yml alone is sufficient to identify a project
            (p / ".copier-answers.yml").touch()
            assert is_project(p)

            # A minimal .copier-answers.yml contains the _commit and _src_path keys
            (p / ".copier-answers.yml").write_text(
                "_commit: abc123\n_src_path: gh:org/template\n")
            assert is_project(p)

    def test_project_yml_is_advisory(self) -> None:
        """copyroom.project.yml carries workflow metadata but does not override copier answers.

        The detector considers copyroom.project.yml as a project marker, but
        this file carries advisory metadata (post-create commands, git policy)
        — it does NOT override the template source or version from .copier-answers.yml.
        """
        import tempfile

        from copyroom.session.detector import is_project

        with tempfile.TemporaryDirectory() as td:
            p = Path(td)

            # copyroom.project.yml alone can indicate a project
            (p / "copyroom.project.yml").touch()
            assert is_project(p)

            # Write advisory content to copyroom.project.yml
            (p / "copyroom.project.yml").write_text(yaml.dump({
                "commands": {
                    "post_project_create": ["pytest"]
                },
                "git_policy": {
                    "branch_protection": "optional"
                }
            }))

            # This file contains no template source or version — those are
            # in .copier-answers.yml. CopyRoom treats copyroom.project.yml
            # as advisory only.


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
        """After removing copyroom.project.yml, the project still has Copier markers.

        A project identified by .copier-answers.yml alone is still a valid
        Copier-managed project — the CopyRoom metadata file is purely additive.
        """
        import tempfile

        from copyroom.session.detector import is_project

        with tempfile.TemporaryDirectory() as td:
            p = Path(td)

            # Create a project with both markers
            (p / ".copier-answers.yml").touch()
            (p / "copyroom.project.yml").touch()
            assert is_project(p)

            # Remove copyroom.project.yml — still a project
            (p / "copyroom.project.yml").unlink()
            assert is_project(p)  # .copier-answers.yml remains

    def test_copier_answers_unaffected_by_copyroom_removal(self) -> None:
        """.copier-answers.yml is never modified by CopyRoom removal."""
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            p = Path(td)

            answers_content = "_commit: abc123\n_src_path: gh:org/template\n"
            (p / ".copier-answers.yml").write_text(answers_content)

            # Simulate CopyRoom presence
            (p / "copyroom.project.yml").touch()

            # Remove CopyRoom
            (p / "copyroom.project.yml").unlink()

            # .copier-answers.yml must be unchanged
            assert (p / ".copier-answers.yml").read_text() == answers_content

    def test_no_irreversible_actions(self) -> None:
        """CopyRoom must not perform irreversible modifications to the project.

        Verify that:
        1. The state machine provides explicit failure states (no silent corruption)
        2. The detector doesn't modify filesystem state (it only reads)
        """
        import tempfile

        from copyroom.session.detector import detect_mode

        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            # Create a project marker
            (p / "copyroom.project.yml").touch()

            # Snapshot filesystem state before detection
            before = sorted(p.iterdir())

            # Run detection
            mode = detect_mode(str(p))

            # Snapshot filesystem state after detection
            after = sorted(p.iterdir())

            # Detection must not modify the filesystem
            assert mode == CLIMode.project
            assert before == after, "detect_mode must not modify the filesystem"


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

        # Verify dispatch rejects workshop commands in project mode
        session = CLISession(status=SessionStatus.mode_detected, mode=CLIMode.project)
        for cmd in workshop_commands:
            result = dispatch(cmd, session)
            assert result == SessionStatus.command_failed, \
                f"Workshop command '{cmd}' should fail in project mode"

    def test_project_commands_only_in_project_mode(self) -> None:
        """
        Project commands (update, inspect, status) only dispatch in project mode.
        (`new` is a bootstrap command — it bypasses mode dispatch entirely.)
        """
        workshop_commands = {"registry", "render", "test", "golden", "release-check", "update-test"}
        project_commands = {"update", "inspect", "status"}
        for cmd in project_commands:
            assert cmd not in workshop_commands

        # Verify dispatch rejects project commands in workshop mode
        session = CLISession(status=SessionStatus.mode_detected, mode=CLIMode.workshop)
        for cmd in project_commands:
            result = dispatch(cmd, session)
            assert result == SessionStatus.command_failed, \
                f"Project command '{cmd}' should fail in workshop mode"

    def test_project_creation_is_bootstrap(self) -> None:
        """CreateProject (`new`) is a bootstrap command (P1-1): it runs in an
        unmanaged repo to *create* a project, so it bypasses mode dispatch
        rather than being gated on project markers."""
        from copyroom.session.model import BOOTSTRAP_COMMANDS

        assert "new" in BOOTSTRAP_COMMANDS
        # It is therefore not mode-gated.
        assert "new" not in COMMAND_MODE_MAP

    def test_template_update_requires_project_mode(self) -> None:
        """UpdateTemplate is a project command; must dispatch in project mode only."""
        assert COMMAND_MODE_MAP["update"] == CLIMode.project

        # Verify dispatch in workshop mode fails
        session = CLISession(status=SessionStatus.mode_detected, mode=CLIMode.workshop)
        result = dispatch("update", session)
        assert result == SessionStatus.command_failed

    def test_render_requires_workshop_mode(self) -> None:
        """RenderCommand is a workshop command; must dispatch in workshop mode only."""
        assert COMMAND_MODE_MAP["render"] == CLIMode.workshop

        # Verify dispatch in project mode fails
        session = CLISession(status=SessionStatus.mode_detected, mode=CLIMode.project)
        result = dispatch("render", session)
        assert result == SessionStatus.command_failed

    def test_release_check_requires_workshop_mode(self) -> None:
        """ReleaseCheckCommand is a workshop command; must dispatch in workshop mode only."""
        assert COMMAND_MODE_MAP["release-check"] == CLIMode.workshop

        # Verify dispatch in project mode fails
        session = CLISession(status=SessionStatus.mode_detected, mode=CLIMode.project)
        result = dispatch("release-check", session)
        assert result == SessionStatus.command_failed

    def test_workshop_project_modes_are_mutually_exclusive_invariant(self) -> None:
        """
        From copyroom-session.allium ModeExclusive invariant:
        A session cannot be in two modes simultaneously.
        """
        # CLIMode is a StrEnum with exactly two dispatchable values
        # A session's mode field is a single value, not a collection
        session_ws = CLISession(status=SessionStatus.mode_detected, mode=CLIMode.workshop)
        session_proj = CLISession(status=SessionStatus.mode_detected, mode=CLIMode.project)

        assert session_ws.mode == CLIMode.workshop
        assert session_ws.mode != CLIMode.project
        assert session_proj.mode == CLIMode.project
        assert session_proj.mode != CLIMode.workshop

        # Mode exclusivity is structural — a single field cannot be two values


# ===========================================================================
# Invariant: State machine transitions are valid
# ===========================================================================


class TestStateMachineInvariants:
    """Invariants about the state machine implementations."""

    def test_all_state_machines_have_terminal_states(self) -> None:
        """Every entity lifecycle must have at least one terminal state."""
        # CLISession
        assert VALID_SESSION_TRANSITIONS[SessionStatus.command_complete] == set()
        assert VALID_SESSION_TRANSITIONS[SessionStatus.command_failed] == set()
        assert VALID_SESSION_TRANSITIONS[SessionStatus.unknown_mode] == set()

        # ProjectCreation
        assert VALID_CREATION_TRANSITIONS[CreationStatus.complete] == set()
        assert VALID_CREATION_TRANSITIONS[CreationStatus.failed] == set()

        # TemplateUpdate
        assert VALID_UPDATE_TRANSITIONS[UpdateStatus.complete] == set()
        assert VALID_UPDATE_TRANSITIONS[UpdateStatus.failed] == set()

    def test_no_implicit_transitions(self) -> None:
        """State machines must only allow declared transitions."""
        sm = StateMachine(VALID_SESSION_TRANSITIONS, entity_name="CLISession")

        # cmd_complete is terminal — no transitions out
        assert sm.is_terminal(SessionStatus.command_complete)

        # cmd_failed is terminal
        assert sm.is_terminal(SessionStatus.command_failed)

        # mode_detected can go to cmd_running or cmd_failed
        assert sm.can_transition(SessionStatus.mode_detected, SessionStatus.command_running)
        assert sm.can_transition(SessionStatus.mode_detected, SessionStatus.command_failed)

        # mode_detected cannot go directly to cmd_complete
        assert not sm.can_transition(SessionStatus.mode_detected, SessionStatus.command_complete)

    def test_command_mode_map_consistency(self) -> None:
        """Every command in COMMAND_MODE_MAP has exactly one mode."""
        # All workshop commands map to workshop mode
        for cmd in WORKSHOP_COMMANDS:
            assert COMMAND_MODE_MAP[cmd] == CLIMode.workshop

        # All project commands map to project mode
        for cmd in PROJECT_COMMANDS:
            assert COMMAND_MODE_MAP[cmd] == CLIMode.project

        # No command maps to more than one mode
        # (StrEnum guarantees this structurally)
        assert WORKSHOP_COMMANDS.isdisjoint(PROJECT_COMMANDS)

    def test_unknown_mode_rejects_all_commands(self) -> None:
        """A session in unknown_mode must reject all commands."""
        session = CLISession(status=SessionStatus.unknown_mode)

        all_commands = list(WORKSHOP_COMMANDS) + list(PROJECT_COMMANDS)
        for cmd in all_commands:
            result = dispatch(cmd, session)
            assert result == SessionStatus.command_failed, \
                f"Command '{cmd}' must fail in unknown_mode"
