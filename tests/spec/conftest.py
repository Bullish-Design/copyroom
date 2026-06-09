"""
Shared fixtures and helpers for CopyRoom spec-derived tests.

All tests in this directory are derived from the Allium specifications at
.scratch/specs/ following the test-generation guide at
.agents/skills/allium/references/test-generation.md.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from enum import StrEnum
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Path resolution helpers
# ---------------------------------------------------------------------------

def _project_root() -> Path:
    """Return the project root (parent of tests/)."""
    return Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# CLI invocation helper
# ---------------------------------------------------------------------------

class CopyRoomCLI:
    """Wraps copyroom CLI invocation for black-box behavioural tests."""

    def __init__(self, cwd: Path | None = None) -> None:
        self.cwd = Path(cwd) if cwd else Path.cwd()
        self._last_result: subprocess.CompletedProcess[str] | None = None

    def run(self, *args: str, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.update(kwargs.pop("env", {}))
        result = subprocess.run(
            ["copyroom", *args],
            cwd=str(self.cwd),
            capture_output=True,
            text=True,
            env=env,
            **kwargs,
        )
        self._last_result = result
        return result

    @property
    def last_result(self) -> subprocess.CompletedProcess[str] | None:
        return self._last_result


# ---------------------------------------------------------------------------
# Temp workspace fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_dir() -> Iterator[Path]:
    """A clean temporary directory that is removed after the test."""
    d = tempfile.mkdtemp(prefix="copyroom_test_")
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def cli(temp_dir: Path) -> CopyRoomCLI:
    """A CopyRoom CLI wrapper rooted in a clean temp directory."""
    return CopyRoomCLI(cwd=temp_dir)


# ---------------------------------------------------------------------------
# Spec entity builder helpers
# ---------------------------------------------------------------------------
# These are lightweight Python dataclasses that mirror the Allium entity
# definitions and are used solely for test assertions — they are NOT
# coupled to the implementation's internal representation.


class CLIMode(StrEnum):
    workshop = "workshop"
    project = "project"
    template_repo = "template_repo"
    standalone = "standalone"


class SessionStatus(StrEnum):
    mode_detecting = "mode_detecting"
    mode_detected = "mode_detected"
    command_running = "command_running"
    command_complete = "command_complete"
    command_failed = "command_failed"
    unknown_mode = "unknown_mode"


VALID_SESSION_TRANSITIONS: dict[SessionStatus, set[SessionStatus]] = {
    SessionStatus.mode_detecting: {SessionStatus.mode_detected, SessionStatus.unknown_mode},
    SessionStatus.mode_detected: {SessionStatus.command_running, SessionStatus.command_failed},
    SessionStatus.command_running: {SessionStatus.command_complete, SessionStatus.command_failed},
    SessionStatus.command_complete: set(),   # terminal
    SessionStatus.command_failed: set(),     # terminal
    SessionStatus.unknown_mode: set(),       # terminal
}


class CreationStatus(StrEnum):
    initiated = "initiated"
    target_verified = "target_verified"
    prompts_collected = "prompts_collected"
    copy_executed = "copy_executed"
    post_create_run = "post_create_run"
    complete = "complete"
    failed = "failed"


VALID_CREATION_TRANSITIONS: dict[CreationStatus, set[CreationStatus]] = {
    CreationStatus.initiated: {CreationStatus.target_verified, CreationStatus.failed},
    CreationStatus.target_verified: {CreationStatus.prompts_collected, CreationStatus.failed},
    CreationStatus.prompts_collected: {CreationStatus.copy_executed, CreationStatus.failed},
    CreationStatus.copy_executed: {CreationStatus.post_create_run, CreationStatus.complete, CreationStatus.failed},
    CreationStatus.post_create_run: {CreationStatus.complete, CreationStatus.failed},
    CreationStatus.complete: set(),   # terminal
    CreationStatus.failed: set(),     # terminal
}


class UpdateStatus(StrEnum):
    initiated = "initiated"
    config_loaded = "config_loaded"
    worktree_verified = "worktree_verified"
    branch_created = "branch_created"
    update_executed = "update_executed"
    post_update_run = "post_update_run"
    complete = "complete"
    failed = "failed"


VALID_UPDATE_TRANSITIONS: dict[UpdateStatus, set[UpdateStatus]] = {
    UpdateStatus.initiated: {UpdateStatus.config_loaded, UpdateStatus.failed},
    UpdateStatus.config_loaded: {UpdateStatus.worktree_verified, UpdateStatus.failed},
    UpdateStatus.worktree_verified: {UpdateStatus.branch_created, UpdateStatus.update_executed, UpdateStatus.failed},
    UpdateStatus.branch_created: {UpdateStatus.update_executed, UpdateStatus.failed},
    UpdateStatus.update_executed: {UpdateStatus.post_update_run, UpdateStatus.complete, UpdateStatus.failed},
    UpdateStatus.post_update_run: {UpdateStatus.complete, UpdateStatus.failed},
    UpdateStatus.complete: set(),    # terminal
    UpdateStatus.failed: set(),      # terminal
}


class ReleaseStatus(StrEnum):
    initiated = "initiated"
    matrix_run = "matrix_run"
    checked = "checked"
    passed = "passed"
    failed = "failed"


VALID_RELEASE_TRANSITIONS: dict[ReleaseStatus, set[ReleaseStatus]] = {
    ReleaseStatus.initiated: {ReleaseStatus.matrix_run, ReleaseStatus.failed},
    ReleaseStatus.matrix_run: {ReleaseStatus.checked, ReleaseStatus.failed},
    ReleaseStatus.checked: {ReleaseStatus.passed, ReleaseStatus.failed},
    ReleaseStatus.passed: set(),   # terminal
    ReleaseStatus.failed: set(),   # terminal
}


class RenderStatus(StrEnum):
    initiated = "initiated"
    rendered = "rendered"
    tested = "tested"
    complete = "complete"
    failed = "failed"


VALID_RENDER_TRANSITIONS: dict[RenderStatus, set[RenderStatus]] = {
    RenderStatus.initiated: {RenderStatus.rendered, RenderStatus.failed},
    RenderStatus.rendered: {RenderStatus.tested, RenderStatus.complete, RenderStatus.failed},
    RenderStatus.tested: {RenderStatus.complete, RenderStatus.failed},
    RenderStatus.complete: set(),   # terminal
    RenderStatus.failed: set(),     # terminal
}


class GoldenStatus(StrEnum):
    initiated = "initiated"
    rendered = "rendered"
    compared = "compared"
    has_diffs = "has_diffs"
    no_diffs = "no_diffs"
    failed = "failed"


VALID_GOLDEN_TRANSITIONS: dict[GoldenStatus, set[GoldenStatus]] = {
    GoldenStatus.initiated: {GoldenStatus.rendered, GoldenStatus.failed},
    GoldenStatus.rendered: {GoldenStatus.compared, GoldenStatus.failed},
    GoldenStatus.compared: {GoldenStatus.has_diffs, GoldenStatus.no_diffs},
    GoldenStatus.has_diffs: set(),   # terminal (prose spec says terminal: has_diffs, no_diffs)
    GoldenStatus.no_diffs: set(),    # terminal
}


class SimStatus(StrEnum):
    initiated = "initiated"
    old_rendered = "old_rendered"
    user_edited = "user_edited"
    update_applied = "update_applied"
    checks_run = "checks_run"
    complete = "complete"
    failed = "failed"


VALID_SIM_TRANSITIONS: dict[SimStatus, set[SimStatus]] = {
    SimStatus.initiated: {SimStatus.old_rendered, SimStatus.failed},
    SimStatus.old_rendered: {SimStatus.user_edited, SimStatus.failed},
    SimStatus.user_edited: {SimStatus.update_applied, SimStatus.failed},
    SimStatus.update_applied: {SimStatus.checks_run, SimStatus.failed},
    SimStatus.checks_run: {SimStatus.complete, SimStatus.failed},
    SimStatus.complete: set(),   # terminal
    SimStatus.failed: set(),     # terminal
}
