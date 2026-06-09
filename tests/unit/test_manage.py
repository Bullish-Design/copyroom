"""Unit tests for the repo-adoption domain types and the shared tree diff."""

from __future__ import annotations

from pathlib import Path

import pytest

from copyroom._compat.state_machine import InvalidTransitionError, StateMachine
from copyroom._compat.treediff import collect_files, tree_diff
from copyroom.manage.model import (
    VALID_ADOPTION_TRANSITIONS,
    VALID_TEMPLATIZATION_TRANSITIONS,
    AdoptionStatus,
    DriftResult,
    TemplatizationStatus,
)
from copyroom.manage.templatize import _slugify


class TestDriftResult:
    def test_has_drift_false_when_empty(self) -> None:
        assert DriftResult().has_drift is False

    @pytest.mark.parametrize("field", ["added", "modified", "removed"])
    def test_has_drift_true_for_any_file_set(self, field: str) -> None:
        assert DriftResult(**{field: {"x"}}).has_drift is True


class TestTransitions:
    def test_adoption_terminal_states_have_no_exits(self) -> None:
        for terminal in (AdoptionStatus.complete, AdoptionStatus.failed):
            assert VALID_ADOPTION_TRANSITIONS[terminal] == set()

    def test_templatization_terminal_states_have_no_exits(self) -> None:
        for terminal in (TemplatizationStatus.complete, TemplatizationStatus.failed):
            assert VALID_TEMPLATIZATION_TRANSITIONS[terminal] == set()

    def test_adoption_illegal_transition_raises(self) -> None:
        sm = StateMachine(VALID_ADOPTION_TRANSITIONS, entity_name="Adoption")
        with pytest.raises(InvalidTransitionError):
            # Cannot skip straight from initiated to complete.
            sm.transition(AdoptionStatus.initiated, AdoptionStatus.complete)

    def test_templatization_happy_path_is_legal(self) -> None:
        sm = StateMachine(VALID_TEMPLATIZATION_TRANSITIONS, entity_name="Templatization")
        s = TemplatizationStatus.initiated
        for nxt in (
            TemplatizationStatus.scaffolded,
            TemplatizationStatus.golden_captured,
            TemplatizationStatus.complete,
        ):
            s = sm.transition(s, nxt)
        assert s == TemplatizationStatus.complete


class TestSlugify:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("MyRepo", "myrepo"),
            ("my cool repo", "my-cool-repo"),
            ("weird__Name!!", "weird__name"),
            ("--", "template"),
            ("", "template"),
        ],
    )
    def test_slugify(self, name: str, expected: str) -> None:
        assert _slugify(name) == expected


class TestTreeDiff:
    def _write(self, root: Path, rel: str, content: str) -> None:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)

    def test_added_modified_removed(self, tmp_path: Path) -> None:
        a = tmp_path / "a"
        b = tmp_path / "b"
        # common-same, common-diff, only-in-a (removed), only-in-b (added)
        self._write(a, "same.txt", "x")
        self._write(b, "same.txt", "x")
        self._write(a, "diff.txt", "one")
        self._write(b, "diff.txt", "two")
        self._write(a, "gone.txt", "bye")
        self._write(b, "new.txt", "hi")

        added, modified, removed = tree_diff(a, b)

        assert added == {"new.txt"}
        assert modified == {"diff.txt"}
        assert removed == {"gone.txt"}

    def test_copier_answers_excluded(self, tmp_path: Path) -> None:
        a = tmp_path / "a"
        b = tmp_path / "b"
        self._write(a, "keep.txt", "x")
        self._write(b, "keep.txt", "x")
        # Differing answers files must not surface as drift.
        self._write(a, ".copier-answers.yml", "_commit: 1\n")
        self._write(b, ".copier-answers.yml", "_commit: 2\n")

        added, modified, removed = tree_diff(a, b)

        assert not (added or modified or removed)

    def test_ignore_dirs_skips_subtree(self, tmp_path: Path) -> None:
        a = tmp_path / "a"
        b = tmp_path / "b"
        self._write(a, "src/main.py", "x")
        self._write(b, "src/main.py", "x")
        # Only present in a, but inside an ignored dir → not "removed".
        self._write(a, ".git/HEAD", "ref: x")

        added, modified, removed = tree_diff(a, b, ignore_dirs=frozenset({".git"}))

        assert not (added or modified or removed)

    def test_collect_files_relative_paths(self, tmp_path: Path) -> None:
        self._write(tmp_path, "a.txt", "1")
        self._write(tmp_path, "sub/b.txt", "2")
        assert collect_files(tmp_path) == {"a.txt", "sub/b.txt"}
