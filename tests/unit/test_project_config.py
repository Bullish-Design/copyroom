"""Unit tests for the validated copyroom.project.yml loader (project/config.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from copyroom.project.config import (
    CopyRoomError,
    CopyRoomProjectConfig,
    load_hook_commands,
    load_project_config,
)

FULL_CONFIG = """\
copyroom:
  version: 1
project:
  kind: generated-project
  name: demo-cli
  template_id: python-cli-template
  template_source: git@github.com:example/python-cli-template.git
  template_ref_policy: tagged
  answers_file: .copier-answers.yml
git:
  default_branch: main
  require_clean_worktree: false
context:
  docs:
    - README.md
    - docs/
  source:
    - src/
devenv:
  enabled: true
commands:
  check:
    - uv run pytest
  post_project_create:
    - uv run pytest
    - uv run ruff check
  post_template_update:
    - uv run pytest
"""


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "copyroom.project.yml"
    p.write_text(text)
    return p


def test_full_config_loads(tmp_path: Path) -> None:
    cfg = load_project_config(_write(tmp_path, FULL_CONFIG))
    assert cfg.version == 1
    assert cfg.project.name == "demo-cli"
    assert cfg.project.kind == "generated-project"
    assert cfg.project.template_ref_policy == "tagged"
    assert cfg.git.require_clean_worktree is False
    assert cfg.git.default_branch == "main"
    assert cfg.devenv.enabled is True
    assert Path("README.md") in cfg.context.docs
    assert cfg.commands["post_project_create"] == ["uv run pytest", "uv run ruff check"]
    assert cfg.commands["post_template_update"] == ["uv run pytest"]


def test_missing_file_returns_defaults(tmp_path: Path) -> None:
    cfg = load_project_config(tmp_path / "nope.yml")
    assert isinstance(cfg, CopyRoomProjectConfig)
    assert cfg.version == 1
    assert cfg.project.kind == "generated-project"  # defaulted
    assert cfg.commands == {}
    assert cfg.git.require_clean_worktree is True


def test_minimal_config_all_defaults(tmp_path: Path) -> None:
    cfg = load_project_config(_write(tmp_path, "copyroom:\n  version: 1\n"))
    assert cfg.commands == {}
    assert cfg.project.kind == "generated-project"


def test_commands_only(tmp_path: Path) -> None:
    cfg = load_project_config(
        _write(tmp_path, "commands:\n  post_project_create:\n    - echo hi\n")
    )
    assert cfg.commands["post_project_create"] == ["echo hi"]


def test_bare_string_hook_is_accepted(tmp_path: Path) -> None:
    """A lone string hook value is coerced to a single-element list."""
    cfg = load_project_config(
        _write(tmp_path, "commands:\n  post_project_create: echo single\n")
    )
    assert cfg.commands["post_project_create"] == ["echo single"]


def test_unknown_fields_tolerated(tmp_path: Path) -> None:
    """Unknown top-level and nested keys are ignored (additive evolution)."""
    cfg = load_project_config(
        _write(
            tmp_path,
            "future_top_level: 42\n"
            "project:\n"
            "  kind: generated-project\n"
            "  future_field: yes\n",
        )
    )
    assert cfg.project.kind == "generated-project"


def test_malformed_yaml_raises(tmp_path: Path) -> None:
    with pytest.raises(CopyRoomError):
        load_project_config(_write(tmp_path, "commands: [unclosed\n"))


def test_non_mapping_raises(tmp_path: Path) -> None:
    with pytest.raises(CopyRoomError):
        load_project_config(_write(tmp_path, "- just\n- a\n- list\n"))


def test_future_kind_value_loads(tmp_path: Path) -> None:
    """#P1-1: a forward-compat-sensitive field carrying a value this CLI doesn't
    know (a newer template's `kind`) must LOAD, not abort generation."""
    cfg = load_project_config(_write(tmp_path, "project:\n  kind: library\n"))
    assert cfg.project.kind == "library"


def test_future_ref_policy_value_loads(tmp_path: Path) -> None:
    """#P1-1: an unknown template_ref_policy value loads (additive evolution)."""
    cfg = load_project_config(
        _write(tmp_path, "project:\n  template_ref_policy: pinned\n")
    )
    assert cfg.project.template_ref_policy == "pinned"


# ---------------------------------------------------------------------------
# load_hook_commands — resilient hook accessor (P1-1 / P2-7)
# ---------------------------------------------------------------------------


def test_hook_commands_missing_file_is_empty(tmp_path: Path) -> None:
    assert load_hook_commands(tmp_path / "nope.yml", "post_project_create") == []


def test_hook_commands_reads_normal_config(tmp_path: Path) -> None:
    p = _write(tmp_path, "commands:\n  post_template_update:\n    - uv run pytest\n")
    assert load_hook_commands(p, "post_template_update") == ["uv run pytest"]


def test_hook_commands_survive_invalid_unrelated_field(tmp_path: Path) -> None:
    """#P1-1/P2-7: a schema problem unrelated to hooks must not drop the hooks.

    A type slip on a known field (here, version as a non-int) makes full
    validation raise, but the configured hooks must still be returned so
    new/update don't silently skip them.
    """
    p = _write(
        tmp_path,
        "git:\n"
        "  require_clean_worktree: maybe\n"
        "commands:\n"
        "  post_template_update:\n"
        "    - uv run pytest\n",
    )
    # Full validation rejects it...
    with pytest.raises(CopyRoomError):
        load_project_config(p)
    # ...but the resilient accessor still surfaces the hook.
    assert load_hook_commands(p, "post_template_update") == ["uv run pytest"]


def test_hook_commands_bare_string_in_fallback(tmp_path: Path) -> None:
    """A bare-string hook is coerced to a list even on the fallback path."""
    p = _write(
        tmp_path,
        "git:\n  require_clean_worktree: maybe\ncommands:\n  post_project_create: echo hi\n",
    )
    assert load_hook_commands(p, "post_project_create") == ["echo hi"]


def test_hook_commands_truly_broken_yaml_raises(tmp_path: Path) -> None:
    with pytest.raises(CopyRoomError):
        load_hook_commands(_write(tmp_path, "commands: [unclosed\n"), "post_project_create")


def test_hook_commands_non_mapping_raises(tmp_path: Path) -> None:
    with pytest.raises(CopyRoomError):
        load_hook_commands(_write(tmp_path, "- a\n- b\n"), "post_project_create")
