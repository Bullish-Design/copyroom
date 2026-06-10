"""Per-action unit tests for the edits DSL (`workshop/edits.py`).

The edits DSL feeds the `update-test` simulation, so a botched edit must fail
loudly rather than silently mis-simulate (P2-2). These cover every action plus
the loader's validation errors — the module was the least-tested in the repo.
"""

from __future__ import annotations

import shutil
import stat
from pathlib import Path

import pytest

from copyroom.workshop.edits import (
    EditsParseError,
    apply_edits,
    load_edits,
)

# ---------------------------------------------------------------------------
# load_edits — validation
# ---------------------------------------------------------------------------


def test_load_edits_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_edits(tmp_path / "nope.yml") == []


def test_load_edits_empty_doc_returns_empty(tmp_path: Path) -> None:
    p = tmp_path / "e.yml"
    p.write_text("")
    assert load_edits(p) == []


def test_load_edits_non_mapping_raises(tmp_path: Path) -> None:
    p = tmp_path / "e.yml"
    p.write_text("- just\n- a\n- list\n")
    with pytest.raises(EditsParseError, match="expected a mapping"):
        load_edits(p)


def test_load_edits_missing_edits_key_raises(tmp_path: Path) -> None:
    p = tmp_path / "e.yml"
    p.write_text("other: 1\n")
    with pytest.raises(EditsParseError, match="missing 'edits' key"):
        load_edits(p)


def test_load_edits_edits_not_a_list_raises(tmp_path: Path) -> None:
    p = tmp_path / "e.yml"
    p.write_text("edits:\n  not: a-list\n")
    with pytest.raises(EditsParseError, match="must be a list"):
        load_edits(p)


def test_load_edits_missing_file_field_raises(tmp_path: Path) -> None:
    p = tmp_path / "e.yml"
    p.write_text("edits:\n  - action: append\n    content: x\n")
    with pytest.raises(EditsParseError, match="missing required 'file' key"):
        load_edits(p)


def test_load_edits_missing_action_raises(tmp_path: Path) -> None:
    p = tmp_path / "e.yml"
    p.write_text("edits:\n  - file: a.txt\n")
    with pytest.raises(EditsParseError, match="missing required 'action' key"):
        load_edits(p)


def test_load_edits_unknown_action_raises(tmp_path: Path) -> None:
    p = tmp_path / "e.yml"
    p.write_text("edits:\n  - file: a.txt\n    action: frobnicate\n")
    with pytest.raises(EditsParseError, match="unknown action"):
        load_edits(p)


def test_load_edits_non_mapping_edit_raises(tmp_path: Path) -> None:
    p = tmp_path / "e.yml"
    p.write_text("edits:\n  - just-a-string\n")
    with pytest.raises(EditsParseError, match="must be a mapping"):
        load_edits(p)


# ---------------------------------------------------------------------------
# append
# ---------------------------------------------------------------------------


def test_append_to_existing_file(tmp_path: Path) -> None:
    (tmp_path / "f.txt").write_text("line1\n")
    apply_edits([{"file": "f.txt", "action": "append", "content": "line2"}], tmp_path)
    assert (tmp_path / "f.txt").read_text() == "line1\nline2\n"


def test_append_to_missing_file_creates_it(tmp_path: Path) -> None:
    apply_edits([{"file": "new.txt", "action": "append", "content": "hi"}], tmp_path)
    assert (tmp_path / "new.txt").read_text() == "hi\n"


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


def test_create_writes_content(tmp_path: Path) -> None:
    apply_edits([{"file": "sub/a.txt", "action": "create", "content": "body"}], tmp_path)
    assert (tmp_path / "sub" / "a.txt").read_text() == "body\n"


def test_create_with_executable_mode(tmp_path: Path) -> None:
    apply_edits(
        [{"file": "run.sh", "action": "create", "content": "#!/bin/sh", "mode": "x"}],
        tmp_path,
    )
    mode = (tmp_path / "run.sh").stat().st_mode
    assert mode & stat.S_IXUSR  # 0o755 — owner-executable


# ---------------------------------------------------------------------------
# set-field (YAML)
# ---------------------------------------------------------------------------


def test_set_field_yaml_nested(tmp_path: Path) -> None:
    import yaml

    p = tmp_path / "c.yml"
    p.write_text("tool:\n  name: old\n")
    apply_edits(
        [{"file": "c.yml", "action": "set-field", "path": ["tool", "name"], "value": "new"}],
        tmp_path,
    )
    assert yaml.safe_load(p.read_text())["tool"]["name"] == "new"


def test_set_field_yaml_list_index(tmp_path: Path) -> None:
    import yaml

    p = tmp_path / "c.yml"
    p.write_text("items:\n  - a\n  - b\n")
    apply_edits(
        [{"file": "c.yml", "action": "set-field", "path": ["items", "1"], "value": "B"}],
        tmp_path,
    )
    assert yaml.safe_load(p.read_text())["items"] == ["a", "B"]


def test_set_field_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(EditsParseError, match="does not exist"):
        apply_edits(
            [{"file": "gone.yml", "action": "set-field", "path": ["x"], "value": 1}],
            tmp_path,
        )


def test_set_field_unsupported_suffix_raises(tmp_path: Path) -> None:
    (tmp_path / "c.ini").write_text("[x]\n")
    with pytest.raises(EditsParseError, match="unsupported file type"):
        apply_edits(
            [{"file": "c.ini", "action": "set-field", "path": ["x"], "value": 1}],
            tmp_path,
        )


# ---------------------------------------------------------------------------
# set-field (TOML, via tomlkit)
# ---------------------------------------------------------------------------


def test_set_field_toml_nested_preserves_comments(tmp_path: Path) -> None:
    import tomlkit

    p = tmp_path / "pyproject.toml"
    p.write_text(
        "[tool.demo]\n"
        "name = \"old\"  # keep me\n"
        "version = \"1.0\"\n"
    )
    apply_edits(
        [{"file": "pyproject.toml", "action": "set-field",
          "path": ["tool", "demo", "name"], "value": "new"}],
        tmp_path,
    )
    text = p.read_text()
    assert tomlkit.parse(text)["tool"]["demo"]["name"] == "new"
    assert "# keep me" in text  # comment survived (tomlkit round-trip)
    assert tomlkit.parse(text)["tool"]["demo"]["version"] == "1.0"


def test_set_field_toml_creates_missing_table(tmp_path: Path) -> None:
    import tomlkit

    p = tmp_path / "c.toml"
    p.write_text("[existing]\na = 1\n")
    apply_edits(
        [{"file": "c.toml", "action": "set-field",
          "path": ["new", "key"], "value": True}],
        tmp_path,
    )
    doc = tomlkit.parse(p.read_text())
    assert doc["new"]["key"] is True
    assert doc["existing"]["a"] == 1


def test_set_field_toml_malformed_raises(tmp_path: Path) -> None:
    p = tmp_path / "bad.toml"
    p.write_text("this is = = not valid toml\n")
    with pytest.raises(EditsParseError, match="failed to parse"):
        apply_edits(
            [{"file": "bad.toml", "action": "set-field", "path": ["x"], "value": 1}],
            tmp_path,
        )


# ---------------------------------------------------------------------------
# patch
# ---------------------------------------------------------------------------

_HAS_PATCH = shutil.which("patch") is not None


def _unified_patch(rel: str, old: str, new: str) -> str:
    return (
        f"--- a/{rel}\n"
        f"+++ b/{rel}\n"
        "@@ -1 +1 @@\n"
        f"-{old}\n"
        f"+{new}\n"
    )


@pytest.mark.skipif(not _HAS_PATCH, reason="'patch' binary not available")
def test_patch_success(tmp_path: Path) -> None:
    (tmp_path / "f.txt").write_text("old line\n")
    apply_edits(
        [{"file": "f.txt", "action": "patch",
          "patch": _unified_patch("f.txt", "old line", "new line")}],
        tmp_path,
    )
    assert (tmp_path / "f.txt").read_text() == "new line\n"


@pytest.mark.skipif(not _HAS_PATCH, reason="'patch' binary not available")
def test_patch_failure_raises(tmp_path: Path) -> None:
    # File content doesn't match the patch context → patch fails → must raise.
    (tmp_path / "f.txt").write_text("totally different\n")
    with pytest.raises(EditsParseError, match="patch failed"):
        apply_edits(
            [{"file": "f.txt", "action": "patch",
              "patch": _unified_patch("f.txt", "old line", "new line")}],
            tmp_path,
        )


def test_patch_missing_binary_raises(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)
    (tmp_path / "f.txt").write_text("old line\n")
    with pytest.raises(EditsParseError, match="'patch' binary is required"):
        apply_edits(
            [{"file": "f.txt", "action": "patch",
              "patch": _unified_patch("f.txt", "old line", "new line")}],
            tmp_path,
        )


def test_empty_patch_is_noop(tmp_path: Path) -> None:
    (tmp_path / "f.txt").write_text("unchanged\n")
    apply_edits([{"file": "f.txt", "action": "patch", "patch": ""}], tmp_path)
    assert (tmp_path / "f.txt").read_text() == "unchanged\n"
