"""Unit tests for template-edit domain types and answers parsing."""

from __future__ import annotations

from pathlib import Path

import pytest

from copyroom._compat.state_machine import InvalidTransitionError, StateMachine
from copyroom.template.model import (
    VALID_CHECKOUT_TRANSITIONS,
    VALID_PREVIEW_TRANSITIONS,
    CheckoutStatus,
    PreviewResult,
    PreviewStatus,
)
from copyroom.template.workspace import CopyRoomError, read_answers


class TestPreviewResult:
    def test_has_changes_false_when_empty(self) -> None:
        assert PreviewResult().has_changes is False

    @pytest.mark.parametrize("field", ["added", "modified", "removed"])
    def test_has_changes_true_for_any_file_set(self, field: str) -> None:
        result = PreviewResult(**{field: {"x"}})
        assert result.has_changes is True

    def test_conflicts_alone_are_not_file_changes(self) -> None:
        # Conflicts/rejects are reported separately and don't flip has_changes.
        assert PreviewResult(conflicts={"c"}, rejects={"r"}).has_changes is False


class TestTransitions:
    def test_checkout_terminal_states_have_no_exits(self) -> None:
        for terminal in (CheckoutStatus.worktree_ready, CheckoutStatus.failed):
            assert VALID_CHECKOUT_TRANSITIONS[terminal] == set()

    def test_preview_illegal_transition_raises(self) -> None:
        sm = StateMachine(VALID_PREVIEW_TRANSITIONS, entity_name="TemplatePreview")
        # complete is terminal; cannot roll back to initiated.
        with pytest.raises(InvalidTransitionError):
            sm.transition(PreviewStatus.complete, PreviewStatus.initiated)

    def test_preview_happy_path_is_legal(self) -> None:
        sm = StateMachine(VALID_PREVIEW_TRANSITIONS, entity_name="TemplatePreview")
        state = PreviewStatus.initiated
        for nxt in (
            PreviewStatus.sandbox_prepared,
            PreviewStatus.update_simulated,
            PreviewStatus.diffed,
            PreviewStatus.complete,
        ):
            state = sm.transition(state, nxt)
        assert state == PreviewStatus.complete


class TestReadAnswers:
    def test_missing_answers_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(CopyRoomError, match="copier-answers"):
            read_answers(tmp_path)

    def test_reads_mapping(self, tmp_path: Path) -> None:
        (tmp_path / ".copier-answers.yml").write_text(
            "_src_path: /tmp/t\n_commit: v1.0.0\nname: demo\n"
        )
        data = read_answers(tmp_path)
        assert data["_src_path"] == "/tmp/t"
        assert data["_commit"] == "v1.0.0"

    def test_non_mapping_raises(self, tmp_path: Path) -> None:
        (tmp_path / ".copier-answers.yml").write_text("- just\n- a\n- list\n")
        with pytest.raises(CopyRoomError, match="not a mapping"):
            read_answers(tmp_path)
