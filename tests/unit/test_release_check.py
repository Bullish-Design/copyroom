"""Unit tests for the release check module — copyroom/release/check.py."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from copyroom.release.check import (
    VALID_RELEASE_TRANSITIONS,
    CopyRoomError,
    ReleaseCheck,
    ReleaseStatus,
    create_check,
    evaluate,
    format_release_report,
    resolve,
    run_release_check,
    _discover_scenarios,
    _check_worktree_clean,
)
from copyroom.workshop.registry import resolve_template_source as _resolve_template_source


# ===========================================================================
# State machine tests
# ===========================================================================


class TestReleaseTransitions:
    """Verify the ReleaseCheck state machine matches the spec."""

    def test_initiated_to_matrix_run_valid(self) -> None:
        assert ReleaseStatus.matrix_run in VALID_RELEASE_TRANSITIONS[ReleaseStatus.initiated]

    def test_initiated_to_failed_valid(self) -> None:
        assert ReleaseStatus.failed in VALID_RELEASE_TRANSITIONS[ReleaseStatus.initiated]

    def test_matrix_run_to_checked_valid(self) -> None:
        assert ReleaseStatus.checked in VALID_RELEASE_TRANSITIONS[ReleaseStatus.matrix_run]

    def test_matrix_run_to_failed_valid(self) -> None:
        assert ReleaseStatus.failed in VALID_RELEASE_TRANSITIONS[ReleaseStatus.matrix_run]

    def test_checked_to_passed_valid(self) -> None:
        assert ReleaseStatus.passed in VALID_RELEASE_TRANSITIONS[ReleaseStatus.checked]

    def test_checked_to_failed_valid(self) -> None:
        assert ReleaseStatus.failed in VALID_RELEASE_TRANSITIONS[ReleaseStatus.checked]

    def test_passed_is_terminal(self) -> None:
        assert VALID_RELEASE_TRANSITIONS[ReleaseStatus.passed] == set()

    def test_failed_is_terminal(self) -> None:
        assert VALID_RELEASE_TRANSITIONS[ReleaseStatus.failed] == set()


# ===========================================================================
# create_check tests
# ===========================================================================


class TestCreateCheck:
    """Rule RunReleaseCheck (spec L29-L37)."""

    def test_creates_entity_in_initiated(self) -> None:
        check = create_check("my-template")
        assert check.template_id == "my-template"
        assert check.status == ReleaseStatus.initiated
        assert check.matrix_passed is False
        assert check.worktree_clean is False
        assert check.golden_ok is False

    def test_rejects_empty_template_id(self) -> None:
        with pytest.raises(CopyRoomError, match="Template ID is required"):
            create_check("")


# ===========================================================================
# resolve tests — all 8 boolean condition combinations
# ===========================================================================


class TestResolvePassed:
    """Rule ReleaseCheckPassed (spec L49-L54)."""

    def test_all_three_true_passes(self) -> None:
        check = ReleaseCheck(template_id="t", matrix_passed=True,
                             worktree_clean=True, golden_ok=True)
        check.status = ReleaseStatus.checked
        result = resolve(check)
        assert result == ReleaseStatus.passed
        assert check.status == ReleaseStatus.passed


class TestResolveFailed:
    """Rule ReleaseCheckFailed (spec L56-L62)."""

    CONDITION_COMBINATIONS = [
        (False, True,  True),
        (True,  False, True),
        (True,  True,  False),
        (False, False, True),
        (False, True,  False),
        (True,  False, False),
        (False, False, False),
    ]

    @pytest.mark.parametrize("matrix_passed,worktree_clean,golden_ok", CONDITION_COMBINATIONS)
    def test_any_false_fails(self, matrix_passed, worktree_clean, golden_ok) -> None:
        check = ReleaseCheck(
            template_id="t",
            matrix_passed=matrix_passed,
            worktree_clean=worktree_clean,
            golden_ok=golden_ok,
        )
        check.status = ReleaseStatus.checked
        result = resolve(check)
        assert result == ReleaseStatus.failed
        assert check.status == ReleaseStatus.failed

    def test_all_false_fails(self) -> None:
        check = ReleaseCheck(template_id="t")
        check.status = ReleaseStatus.checked
        result = resolve(check)
        assert result == ReleaseStatus.failed
        assert check.status == ReleaseStatus.failed


# ===========================================================================
# evaluate tests
# ===========================================================================


class TestEvaluateReleaseReadiness:
    """Rule EvaluateReleaseReadiness (spec L45-L47)."""

    def test_matrix_run_to_checked(self) -> None:
        check = ReleaseCheck(template_id="t")
        check.status = ReleaseStatus.matrix_run
        result = evaluate(check)
        assert result == ReleaseStatus.checked
        assert check.status == ReleaseStatus.checked

    def test_evaluate_preserves_booleans(self) -> None:
        check = ReleaseCheck(
            template_id="t",
            matrix_passed=True,
            worktree_clean=False,
            golden_ok=True,
        )
        check.status = ReleaseStatus.matrix_run
        evaluate(check)
        assert check.matrix_passed is True
        assert check.worktree_clean is False
        assert check.golden_ok is True


# ===========================================================================
# format_release_report tests
# ===========================================================================


class TestFormatReleaseReport:
    """Output formatting matches spec §7.3."""

    def test_passed_report_format(self) -> None:
        check = ReleaseCheck(
            template_id="my-template",
            matrix_passed=True,
            worktree_clean=True,
            golden_ok=True,
            status=ReleaseStatus.passed,
            scenario_total=5,
            scenario_passed=5,
            golden_total=3,
            golden_passed=3,
        )
        report = format_release_report(check)
        assert "Release Check: my-template" in report
        assert "✅ PASSED" in report
        assert "5/5 scenarios" in report
        assert "✅ CLEAN" in report
        assert "✅ OK" in report
        assert "3/3 scenarios match golden" in report
        assert "🟢 PASSED" in report
        assert "Release checks are advisory" in report

    def test_failed_report_format(self) -> None:
        check = ReleaseCheck(
            template_id="bad-template",
            matrix_passed=False,
            worktree_clean=True,
            golden_ok=False,
            status=ReleaseStatus.failed,
            scenario_total=3,
            scenario_passed=1,
            golden_total=3,
            golden_passed=0,
            render_failures=["scenario-a"],
            golden_failures=["scenario-b", "scenario-c"],
        )
        report = format_release_report(check)
        assert "Release Check: bad-template" in report
        assert "❌ FAILED" in report
        assert "1/3 scenarios" in report
        assert "failures: scenario-a" in report
        assert "✅ CLEAN" in report
        assert "❌ DIFFS" in report
        assert "diffs: scenario-b, scenario-c" in report
        assert "🔴 FAILED" in report

    def test_dirty_worktree_report(self) -> None:
        check = ReleaseCheck(
            template_id="t",
            matrix_passed=True,
            worktree_clean=False,
            golden_ok=True,
            status=ReleaseStatus.failed,
        )
        report = format_release_report(check)
        assert "DIRTY" in report


# ===========================================================================
# _discover_scenarios tests
# ===========================================================================


class TestDiscoverScenarios:
    """Scenario discovery from scenarios/<template_id>/."""

    def test_no_scenarios_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = _discover_scenarios(root, "my-template")
            assert result == []

    def test_empty_scenarios_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scenarios" / "my-template").mkdir(parents=True)
            result = _discover_scenarios(root, "my-template")
            assert result == []

    def test_discovers_yml_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sd = root / "scenarios" / "my-template"
            sd.mkdir(parents=True)
            (sd / "default.yml").write_text("answers:\n  project_name: test\n")
            (sd / "custom.yml").write_text("answers:\n  project_name: custom\n")
            result = _discover_scenarios(root, "my-template")
            assert result == ["custom", "default"]

    def test_excludes_edits_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sd = root / "scenarios" / "my-template"
            sd.mkdir(parents=True)
            (sd / "default.yml").write_text("answers:\n  project_name: test\n")
            (sd / "default-edits.yml").write_text("edits:\n  - file: README.md\n")
            result = _discover_scenarios(root, "my-template")
            assert result == ["default"]
            assert "default-edits" not in result

    def test_excludes_non_yml_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sd = root / "scenarios" / "my-template"
            sd.mkdir(parents=True)
            (sd / "default.yml").write_text("answers:\n  project_name: test\n")
            (sd / "notes.txt").write_text("some notes\n")
            (sd / "subdir").mkdir()
            result = _discover_scenarios(root, "my-template")
            assert result == ["default"]


# ===========================================================================
# _check_worktree_clean tests
# ===========================================================================


class TestWorktreeClean:
    """Git worktree cleanliness check."""

    def test_clean_worktree(self) -> None:
        """Mocked git status --porcelain returning empty output."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = ""
            result = _check_worktree_clean(Path("/fake"))
            assert result is True

    def test_dirty_worktree(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = " M modified_file.py\n"
            result = _check_worktree_clean(Path("/fake"))
            assert result is False

    def test_git_not_available(self) -> None:
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = _check_worktree_clean(Path("/fake"))
            assert result is True

    def test_not_a_git_repo(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 128
            mock_run.return_value.stderr = "fatal: not a git repository"
            result = _check_worktree_clean(Path("/fake"))
            assert result is True


# ===========================================================================
# _resolve_template_source tests
# ===========================================================================


class TestResolveTemplateSource:
    """Template source resolution from workshop registry."""

    def test_no_config_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = _resolve_template_source(root, "my-template")
            assert result is None

    def test_resolves_from_copyroom_yml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "copyroom.yml").write_text(
                "templates:\n  my-template:\n    source: /path/to/template\n"
            )
            result = _resolve_template_source(root, "my-template")
            assert result == "/path/to/template"

    def test_resolves_from_registry_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "registry").mkdir()
            (root / "registry" / "my-template.yml").write_text(
                "source: /path/to/registry-template\n"
            )
            result = _resolve_template_source(root, "my-template")
            assert result == "/path/to/registry-template"

    def test_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "copyroom.yml").write_text(
                "templates:\n  other-template:\n    source: /other\n"
            )
            result = _resolve_template_source(root, "my-template")
            assert result is None


# ===========================================================================
# Full workflow (happy path) tests with mocks
# ===========================================================================


class TestReleaseCheckWorkflow:
    """Integration tests for the full release check workflow."""

    def test_run_release_check_no_scenarios(self) -> None:
        """When no scenarios exist, the check passes trivially."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Create workshop markers
            (root / "copyroom.yml").write_text(
                "templates:\n  t1:\n    source: /fake/template\n"
            )
            (root / "registry").mkdir()
            (root / "scenarios").mkdir()

            check = run_release_check("t1", workshop_root=root,
                                       template_source="/fake/template")
            assert check.status == ReleaseStatus.passed
            assert check.matrix_passed is True
            assert check.golden_ok is True

    def test_run_release_check_template_not_found(self) -> None:
        """When template is not in registry, returns failed."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "copyroom.yml").write_text("templates: {}\n")
            (root / "registry").mkdir()
            (root / "scenarios").mkdir()

            check = run_release_check("nonexistent", workshop_root=root)
            assert check.status == ReleaseStatus.failed

    def test_run_release_check_with_scenarios(self) -> None:
        """Full integration test with mocked render and golden.

        Renders all scenarios successfully, golden all clean — should pass.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "copyroom.yml").write_text(
                "templates:\n  t1:\n    source: /fake/template\n"
            )
            (root / "registry").mkdir()
            sd = root / "scenarios" / "t1"
            sd.mkdir(parents=True)
            (sd / "default.yml").write_text("answers:\n  name: test\n")
            (sd / "custom.yml").write_text("answers:\n  name: custom\n")

            with (
                patch("copyroom.release.check.render_scenario") as mock_render,
                patch("copyroom.release.check._golden_diff") as mock_golden,
                patch("copyroom.release.check._check_worktree_clean", return_value=True),
            ):
                # Mock render returns complete
                from copyroom.workshop.model import ScenarioRender, RenderStatus, GoldenDiff, GoldenStatus
                mock_render.return_value = ScenarioRender(
                    template_id="t1", scenario_id="default",
                    status=RenderStatus.complete,
                )
                mock_golden.return_value = GoldenDiff(
                    template_id="t1", scenario_id="default",
                    status=GoldenStatus.no_diffs,
                )

                check = run_release_check("t1", workshop_root=root,
                                           template_source="/fake/template")

                assert check.status == ReleaseStatus.passed
                assert check.matrix_passed is True
                assert check.worktree_clean is True
                assert check.golden_ok is True
                assert check.scenario_total == 2
                assert check.scenario_passed == 2

    def test_run_release_check_render_failure(self) -> None:
        """If any scenario render fails, matrix_passed is False."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "copyroom.yml").write_text(
                "templates:\n  t1:\n    source: /fake/template\n"
            )
            (root / "registry").mkdir()
            sd = root / "scenarios" / "t1"
            sd.mkdir(parents=True)
            (sd / "broken.yml").write_text("answers:\n  name: broken\n")

            with (
                patch("copyroom.release.check.render_scenario") as mock_render,
                patch("copyroom.release.check._golden_diff") as mock_golden,
                patch("copyroom.release.check._check_worktree_clean", return_value=True),
            ):
                from copyroom.workshop.model import ScenarioRender, RenderStatus, GoldenDiff, GoldenStatus
                mock_render.return_value = ScenarioRender(
                    template_id="t1", scenario_id="broken",
                    status=RenderStatus.failed,
                )
                mock_golden.return_value = GoldenDiff(
                    template_id="t1", scenario_id="broken",
                    status=GoldenStatus.has_diffs,
                )

                check = run_release_check("t1", workshop_root=root,
                                           template_source="/fake/template")

                assert check.status == ReleaseStatus.failed
                assert check.matrix_passed is False
                assert check.golden_ok is False
                assert check.scenario_passed == 0

    def test_run_release_check_golden_dirty(self) -> None:
        """If golden has diffs, golden_ok is False."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "copyroom.yml").write_text(
                "templates:\n  t1:\n    source: /fake/template\n"
            )
            (root / "registry").mkdir()
            sd = root / "scenarios" / "t1"
            sd.mkdir(parents=True)
            (sd / "default.yml").write_text("answers:\n  name: test\n")

            with (
                patch("copyroom.release.check.render_scenario") as mock_render,
                patch("copyroom.release.check._golden_diff") as mock_golden,
                patch("copyroom.release.check._check_worktree_clean", return_value=True),
            ):
                from copyroom.workshop.model import ScenarioRender, RenderStatus, GoldenDiff, GoldenStatus
                mock_render.return_value = ScenarioRender(
                    template_id="t1", scenario_id="default",
                    status=RenderStatus.complete,
                )
                mock_golden.return_value = GoldenDiff(
                    template_id="t1", scenario_id="default",
                    status=GoldenStatus.has_diffs,
                )

                check = run_release_check("t1", workshop_root=root,
                                           template_source="/fake/template")

                assert check.status == ReleaseStatus.failed
                assert check.matrix_passed is True
                assert check.golden_ok is False
