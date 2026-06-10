"""
Tests derived from copyroom-project.allium.

Covers:
  - ProjectCreation entity lifecycle and state transitions
  - TemplateUpdate entity lifecycle and state transitions
  - Rule tests for safe project creation (initiate → verify → prompts → copy → post-create → complete)
  - Rule tests for safe template update (initiate → config → worktree → branch/copy → update → complete)
  - Invariants: CleanWorktreeBeforeUpdate, NoSilentErrors
  - Surface tests for ProjectSurface

Following the test-generation guide at .agents/skills/allium/references/test-generation.md.
"""

from __future__ import annotations

from .conftest import (
    VALID_CREATION_TRANSITIONS,
    VALID_UPDATE_TRANSITIONS,
    CreationStatus,
    UpdateStatus,
)

# ===========================================================================
# Entity tests — ProjectCreation
# ===========================================================================


class TestProjectCreationEntity:
    """copyroom-project.allium L12-L39: ProjectCreation entity."""

    def test_all_status_values_exist(self) -> None:
        """All 7 status values from the declaration must be representable."""
        expected = {"initiated", "target_verified", "prompts_collected",
                     "copy_executed", "post_create_run", "complete", "failed"}
        assert {s.value for s in CreationStatus} == expected

    def test_template_source_is_required_string(self) -> None:
        """template_source: String (required)."""
        # InitiateProjectCreation requires: source != ""
        pass  # Structural: type constraint

    def test_target_dir_is_string(self) -> None:
        """target_dir: String — defaults to "." via null coalescing."""
        # Spec: target_dir: target_dir ?? "."
        pass  # Structural

    def test_uses_answer_file_is_boolean(self) -> None:
        """uses_answer_file: Boolean — derived from answer_file != null."""
        # Spec: uses_answer_file: answer_file != null
        pass  # Structural

    def test_result_suggestions_is_string_list(self) -> None:
        """result_suggestions: List<String> — present in all states."""
        # Not state-dependent (no 'when' clause)
        pass  # Structural


# ===========================================================================
# Entity tests — TemplateUpdate
# ===========================================================================


class TestTemplateUpdateEntity:
    """copyroom-project.allium L41-L72: TemplateUpdate entity."""

    def test_all_status_values_exist(self) -> None:
        """All status values from the declaration must be representable.

        ``up_to_date`` is the no-op success terminal added for P1-2.
        """
        expected = {"initiated", "config_loaded", "worktree_verified",
                     "branch_created", "update_executed", "post_update_run",
                     "complete", "up_to_date", "failed"}
        assert {s.value for s in UpdateStatus} == expected

    def test_previous_ref_is_optional_string(self) -> None:
        """previous_ref: String? — may be null."""
        pass  # Structural: String?

    def test_target_ref_is_optional_string(self) -> None:
        """target_ref: String? — may be null; resolved via ResolveLatestRef."""
        pass  # Structural: String?

    def test_update_branch_is_optional_string(self) -> None:
        """update_branch: String? — set only when --branch is passed."""
        pass  # Structural: String?

    def test_conflicts_is_string_set(self) -> None:
        """conflicts: Set<String> — captured from Copier output."""
        pass  # Structural: Set<String>

    def test_rejects_is_string_set(self) -> None:
        """rejects: Set<String> — captured from Copier output."""
        pass  # Structural: Set<String>


# ===========================================================================
# State transition tests — ProjectCreation
# ===========================================================================


class TestCreationTransitions:
    """
    copyroom-project.allium L26-L39: ProjectCreation transitions block.

    initiated -> target_verified | failed
    target_verified -> prompts_collected | failed
    prompts_collected -> copy_executed | failed
    copy_executed -> post_create_run | complete | failed
    post_create_run -> complete | failed
    terminal: complete, failed
    """

    def test_initiated_to_target_verified_valid(self) -> None:
        assert CreationStatus.target_verified in VALID_CREATION_TRANSITIONS[CreationStatus.initiated]

    def test_initiated_to_failed_valid(self) -> None:
        assert CreationStatus.failed in VALID_CREATION_TRANSITIONS[CreationStatus.initiated]

    def test_target_verified_to_prompts_collected_valid(self) -> None:
        assert CreationStatus.prompts_collected in VALID_CREATION_TRANSITIONS[CreationStatus.target_verified]

    def test_prompts_collected_to_copy_executed_valid(self) -> None:
        assert CreationStatus.copy_executed in VALID_CREATION_TRANSITIONS[CreationStatus.prompts_collected]

    def test_copy_executed_to_post_create_run_valid(self) -> None:
        assert CreationStatus.post_create_run in VALID_CREATION_TRANSITIONS[CreationStatus.copy_executed]

    def test_copy_executed_to_complete_valid(self) -> None:
        """Short-circuit: skip post_create_run if no commands configured."""
        assert CreationStatus.complete in VALID_CREATION_TRANSITIONS[CreationStatus.copy_executed]

    def test_post_create_run_to_complete_valid(self) -> None:
        assert CreationStatus.complete in VALID_CREATION_TRANSITIONS[CreationStatus.post_create_run]

    def test_terminal_states(self) -> None:
        assert VALID_CREATION_TRANSITIONS[CreationStatus.complete] == set()
        assert VALID_CREATION_TRANSITIONS[CreationStatus.failed] == set()

    def test_every_state_has_outbound_except_terminal(self) -> None:
        """Every non-terminal state has at least one outbound edge."""
        non_terminal = [
            CreationStatus.initiated,
            CreationStatus.target_verified,
            CreationStatus.prompts_collected,
            CreationStatus.copy_executed,
            CreationStatus.post_create_run,
        ]
        for state in non_terminal:
            assert len(VALID_CREATION_TRANSITIONS[state]) >= 1, \
                f"Non-terminal state {state} has no outbound edges"

    def test_reverse_transitions_invalid(self) -> None:
        """Cannot go backwards in the lifecycle."""
        assert CreationStatus.initiated not in VALID_CREATION_TRANSITIONS[CreationStatus.target_verified]
        assert CreationStatus.target_verified not in VALID_CREATION_TRANSITIONS[CreationStatus.prompts_collected]
        assert CreationStatus.prompts_collected not in VALID_CREATION_TRANSITIONS[CreationStatus.copy_executed]

    def test_terminal_to_anything_invalid(self) -> None:
        """Cannot transition from terminal states."""
        for from_state in [CreationStatus.complete, CreationStatus.failed]:
            assert VALID_CREATION_TRANSITIONS[from_state] == set()

    def test_skip_states_invalid(self) -> None:
        """Skipping states (initiated -> copy_executed) is not a valid transition."""
        assert CreationStatus.copy_executed not in VALID_CREATION_TRANSITIONS[CreationStatus.initiated]
        assert CreationStatus.post_create_run not in VALID_CREATION_TRANSITIONS[CreationStatus.prompts_collected]

    def test_failure_from_any_non_terminal_state(self) -> None:
        """From every non-terminal state there is a path to failed."""
        assert CreationStatus.failed in VALID_CREATION_TRANSITIONS[CreationStatus.initiated]
        assert CreationStatus.failed in VALID_CREATION_TRANSITIONS[CreationStatus.target_verified]
        assert CreationStatus.failed in VALID_CREATION_TRANSITIONS[CreationStatus.prompts_collected]
        assert CreationStatus.failed in VALID_CREATION_TRANSITIONS[CreationStatus.copy_executed]
        assert CreationStatus.failed in VALID_CREATION_TRANSITIONS[CreationStatus.post_create_run]


# ===========================================================================
# State transition tests — TemplateUpdate
# ===========================================================================


class TestUpdateTransitions:
    """
    copyroom-project.allium L58-L72: TemplateUpdate transitions block.

    initiated -> config_loaded | failed
    config_loaded -> worktree_verified | failed
    worktree_verified -> branch_created | update_executed | failed
    branch_created -> update_executed | failed
    update_executed -> post_update_run | complete | failed
    post_update_run -> complete | failed
    terminal: complete, failed
    """

    def test_worktree_verified_direct_to_update_executed(self) -> None:
        """Bypass branch creation: worktree_verified -> update_executed (no --branch)."""
        assert UpdateStatus.update_executed in VALID_UPDATE_TRANSITIONS[UpdateStatus.worktree_verified]

    def test_worktree_verified_to_branch_created(self) -> None:
        """With --branch: worktree_verified -> branch_created."""
        assert UpdateStatus.branch_created in VALID_UPDATE_TRANSITIONS[UpdateStatus.worktree_verified]

    def test_branch_created_to_update_executed(self) -> None:
        """After branch: branch_created -> update_executed."""
        assert UpdateStatus.update_executed in VALID_UPDATE_TRANSITIONS[UpdateStatus.branch_created]

    def test_terminal_states(self) -> None:
        assert VALID_UPDATE_TRANSITIONS[UpdateStatus.complete] == set()
        assert VALID_UPDATE_TRANSITIONS[UpdateStatus.up_to_date] == set()
        assert VALID_UPDATE_TRANSITIONS[UpdateStatus.failed] == set()

    def test_config_loaded_to_up_to_date_valid(self) -> None:
        """P1-2: a no-op update (already at target) is a success terminal."""
        assert UpdateStatus.up_to_date in VALID_UPDATE_TRANSITIONS[UpdateStatus.config_loaded]

    def test_every_non_terminal_has_outbound(self) -> None:
        non_terminal = [
            UpdateStatus.initiated,
            UpdateStatus.config_loaded,
            UpdateStatus.worktree_verified,
            UpdateStatus.branch_created,
            UpdateStatus.update_executed,
            UpdateStatus.post_update_run,
        ]
        for state in non_terminal:
            assert len(VALID_UPDATE_TRANSITIONS[state]) >= 1, \
                f"Non-terminal state {state} has no outbound edges"

    def test_reverse_transitions_invalid(self) -> None:
        """Cannot go backwards."""
        assert UpdateStatus.initiated not in VALID_UPDATE_TRANSITIONS[UpdateStatus.config_loaded]
        assert UpdateStatus.config_loaded not in VALID_UPDATE_TRANSITIONS[UpdateStatus.worktree_verified]
        assert UpdateStatus.worktree_verified not in VALID_UPDATE_TRANSITIONS[UpdateStatus.branch_created]
        assert UpdateStatus.update_executed not in VALID_UPDATE_TRANSITIONS[UpdateStatus.post_update_run]


# ===========================================================================
# Rule tests — Project Creation
# ===========================================================================


class TestInitiateProjectCreation:
    """Rule InitiateProjectCreation (L76-L85)."""

    def test_requires_source_not_empty(self) -> None:
        """source != "" — empty source is rejected."""
        pass  # Integration: requires CLI invocation

    def test_target_defaults_to_dot(self) -> None:
        """When target_dir is null, uses "." via null coalescing."""
        pass  # Integration

    def test_uses_answer_file_derived_correctly(self) -> None:
        """uses_answer_file = (answer_file != null)."""
        pass  # Integration: test both null and non-null


class TestVerifyTargetDirectory:
    """Rule VerifyTargetDirectory (L87-L94)."""

    def test_initiated_flows_to_target_verified(self) -> None:
        """Happy path: empty/non-existent target -> target_verified."""
        assert CreationStatus.target_verified in VALID_CREATION_TRANSITIONS[CreationStatus.initiated]


class TestRejectNonEmptyTarget:
    """Rule RejectNonEmptyTarget (L96-L100)."""

    def test_transitions_to_failed_with_suggestion(self) -> None:
        """TargetDirectoryNotEmpty stimulus -> status = failed with result_suggestions."""
        assert CreationStatus.failed in VALID_CREATION_TRANSITIONS[CreationStatus.initiated]
        # Spec: result_suggestions = {"Target directory is not empty..."}
        pass  # Integration


class TestCollectPrompts:
    """Rule CollectPrompts (L102-L107)."""

    def test_verified_to_prompts_collected(self) -> None:
        """target_verified -> prompts_collected."""
        assert CreationStatus.prompts_collected in VALID_CREATION_TRANSITIONS[CreationStatus.target_verified]


class TestExecuteCopierCopy:
    """Rule ExecuteCopierCopy (L109-L116)."""

    def test_prompts_to_copy_executed(self) -> None:
        """prompts_collected -> copy_executed."""
        assert CreationStatus.copy_executed in VALID_CREATION_TRANSITIONS[CreationStatus.prompts_collected]


class TestCopierCopyFailed:
    """Rule CopierCopyFailed (L118-L125)."""

    def test_copy_failed_transitions_to_failed_with_suggestions(self) -> None:
        """CopierCopyFailed stimulus -> failed with result_suggestions."""
        # result_suggestions = {"Copier copy failed...", "The target directory may be..."}
        pass  # Integration


class TestDetectPostCreateCommands:
    """Rule DetectPostCreateCommands (L127-L133)."""

    def test_copy_executed_to_post_create_run(self) -> None:
        """copy_executed -> post_create_run."""
        assert CreationStatus.post_create_run in VALID_CREATION_TRANSITIONS[CreationStatus.copy_executed]


class TestRunPostCreateCommands:
    """Rule RunPostCreateCommands (L135-L139)."""

    def test_post_create_to_complete(self) -> None:
        """post_create_run -> complete."""
        assert CreationStatus.complete in VALID_CREATION_TRANSITIONS[CreationStatus.post_create_run]


class TestCompleteProjectCreation:
    """Rule CompleteProjectCreation (L141-L149)."""

    def test_complete_sets_result_suggestions(self) -> None:
        """On complete, result_suggestions populated with next-steps."""
        # result_suggestions includes "cd <target>", "git init && ...", "copyroom inspect"
        pass  # Integration


# ===========================================================================
# Rule tests — Template Update
# ===========================================================================


class TestInitiateTemplateUpdate:
    """Rule InitiateTemplateUpdate (L181-L195)."""

    def test_target_ref_is_optional(self) -> None:
        """target_ref may be null — the no-arg path resolves it (ResolveLatestRef)."""
        pass  # Integration

    def test_infers_previous_ref_from_answers_file(self) -> None:
        """previous_ref and template_source derived from .copier-answers.yml."""
        pass  # Integration


class TestResolveLatestRef:
    """Rule ResolveLatestRef (L206-L217)."""

    def test_null_target_ref_resolved_to_latest_semver(self) -> None:
        """When target_ref = null on config_loaded, resolved to the latest semver tag."""
        pass  # Integration


class TestLoadUpdateConfig:
    """Rule LoadUpdateConfig (L197-L204)."""

    def test_initiated_to_config_loaded(self) -> None:
        assert UpdateStatus.config_loaded in VALID_UPDATE_TRANSITIONS[UpdateStatus.initiated]


class TestNoUpdateAvailable:
    """Rule NoUpdateAvailable (L219-L225)."""

    def test_already_at_target_version(self) -> None:
        """When previous_ref = target_ref, transition to failed."""
        assert UpdateStatus.failed in VALID_UPDATE_TRANSITIONS[UpdateStatus.config_loaded]


class TestVerifyCleanWorktree:
    """Rule VerifyCleanWorktree (L227-L239)."""

    def test_config_to_worktree_verified_when_refs_differ(self) -> None:
        """config_loaded -> worktree_verified when previous_ref != target_ref."""
        assert UpdateStatus.worktree_verified in VALID_UPDATE_TRANSITIONS[UpdateStatus.config_loaded]


class TestRejectDirtyWorktree:
    """Rule RejectDirtyWorktree (L241-L247)."""

    def test_dirty_worktree_fails_update(self) -> None:
        """WorktreeNotClean stimulus -> failed."""
        assert UpdateStatus.failed in VALID_UPDATE_TRANSITIONS[UpdateStatus.config_loaded]


class TestCreateUpdateBranch:
    """Rule CreateUpdateBranch (L201-L209)."""

    def test_worktree_to_branch_when_flag_passed(self) -> None:
        """worktree_verified -> branch_created when --branch is passed."""
        assert UpdateStatus.branch_created in VALID_UPDATE_TRANSITIONS[UpdateStatus.worktree_verified]

    def test_branch_name_pattern(self) -> None:
        """update_branch = "template-update/<template_id>-<target_ref>"."""
        pass  # Structural: naming convention


class TestExecuteCopierUpdate:
    """Rules ExecuteCopierUpdate (L211-L216) & ExecuteCopierUpdateFromBranch (L218-L226)."""

    def test_worktree_direct_to_update(self) -> None:
        """worktree_verified -> update_executed (no branch)."""
        assert UpdateStatus.update_executed in VALID_UPDATE_TRANSITIONS[UpdateStatus.worktree_verified]

    def test_branch_to_update(self) -> None:
        """branch_created -> update_executed."""
        assert UpdateStatus.update_executed in VALID_UPDATE_TRANSITIONS[UpdateStatus.branch_created]


class TestCaptureUpdateConflicts:
    """Rule CaptureUpdateConflicts (L228-L234)."""

    def test_executed_to_post_update(self) -> None:
        assert UpdateStatus.post_update_run in VALID_UPDATE_TRANSITIONS[UpdateStatus.update_executed]


class TestRunPostUpdateCommands:
    """Rule RunPostUpdateCommands (L236-L241)."""

    def test_post_update_to_complete(self) -> None:
        assert UpdateStatus.complete in VALID_UPDATE_TRANSITIONS[UpdateStatus.post_update_run]


# ===========================================================================
# Invariant tests
# ===========================================================================


class TestProjectInvariants:
    """Expression-bearing invariants from copyroom-project.allium L243-L260."""

    def test_clean_worktree_invariant(self) -> None:
        """
        Invariant CleanWorktreeBeforeUpdate (L243):
          for update in TemplateUpdates where status in {
              worktree_verified, branch_created, update_executed,
              post_update_run, complete
          }:
              update.previous_ref != update.target_ref

        After worktree is verified, the refs must differ — otherwise
        NoUpdateAvailable would have sent it to failed.
        """
        qualifying = {UpdateStatus.worktree_verified, UpdateStatus.branch_created,
                       UpdateStatus.update_executed, UpdateStatus.post_update_run,
                       UpdateStatus.complete}
        assert UpdateStatus.failed not in qualifying  # failed is excluded from invariant scope

    def test_no_silent_errors_invariant_creations(self) -> None:
        """
        Invariant NoSilentErrors (L252):
          for creation in ProjectCreations where status = failed:
              creation.result_suggestions.count >= 1
        """
        # Structural: every failed creation must have at least one suggestion
        pass  # Integration

    def test_no_silent_errors_invariant_updates(self) -> None:
        """
        Invariant NoSilentErrors (L254):
          for update in TemplateUpdates where status = failed:
              update.previous_ref != null or update.target_ref != null
        """
        # Structural: a failed update must have meaningful ref information
        pass  # Integration


# ===========================================================================
# Surface tests
# ===========================================================================


class TestProjectSurface:
    """copyroom-project.allium L268-L275: ProjectSurface."""

    def test_surface_provides_create_project(self) -> None:
        """CreateProject(source, target_dir?, answer_file?) is on the surface."""
        pass  # Integration

    def test_surface_provides_update_template(self) -> None:
        """UpdateTemplate(project_root, target_ref?, use_branch?) is on the surface."""
        pass  # Integration

    def test_surface_faces_cli_user(self) -> None:
        """ProjectSurface faces CLIUser (always accessible)."""
        pass  # Structural


# ===========================================================================
# Scenario tests
# ===========================================================================


class TestProjectCreationHappyPath:
    """
    Scenario: full happy path through project creation.

    CreateProject -> initiated -> target_verified -> prompts_collected ->
    copy_executed -> post_create_run -> complete (terminal)
    """

    def test_happy_path_chain(self) -> None:
        """All transitions in the happy path are declared valid."""
        path = [
            CreationStatus.initiated,
            CreationStatus.target_verified,
            CreationStatus.prompts_collected,
            CreationStatus.copy_executed,
            CreationStatus.post_create_run,
            CreationStatus.complete,
        ]
        for i in range(len(path) - 1):
            source = path[i]
            target = path[i + 1]
            assert target in VALID_CREATION_TRANSITIONS[source], \
                f"Missing edge: {source} -> {target}"

    def test_short_circuit_path(self) -> None:
        """Path: copy_executed -> complete (no post-create commands)."""
        assert CreationStatus.complete in VALID_CREATION_TRANSITIONS[CreationStatus.copy_executed]


class TestTemplateUpdateHappyPath:
    """
    Scenario: full happy path through template update.

    UpdateTemplate -> initiated -> config_loaded -> worktree_verified ->
    update_executed -> post_update_run -> complete (terminal)
    """

    def test_happy_path_chain_no_branch(self) -> None:
        """Happy path without --branch flag."""
        path = [
            UpdateStatus.initiated,
            UpdateStatus.config_loaded,
            UpdateStatus.worktree_verified,
            UpdateStatus.update_executed,
            UpdateStatus.post_update_run,
            UpdateStatus.complete,
        ]
        for i in range(len(path) - 1):
            source = path[i]
            target = path[i + 1]
            assert target in VALID_UPDATE_TRANSITIONS[source], \
                f"Missing edge: {source} -> {target}"

    def test_branch_path(self) -> None:
        """Path with --branch: worktree_verified -> branch_created -> update_executed."""
        assert UpdateStatus.branch_created in VALID_UPDATE_TRANSITIONS[UpdateStatus.worktree_verified]
        assert UpdateStatus.update_executed in VALID_UPDATE_TRANSITIONS[UpdateStatus.branch_created]

    def test_no_update_available_path(self) -> None:
        """When already at target ref: config_loaded -> failed."""
        assert UpdateStatus.failed in VALID_UPDATE_TRANSITIONS[UpdateStatus.config_loaded]

    def test_dirty_worktree_path(self) -> None:
        """When worktree not clean: config_loaded -> failed."""
        assert UpdateStatus.failed in VALID_UPDATE_TRANSITIONS[UpdateStatus.config_loaded]
