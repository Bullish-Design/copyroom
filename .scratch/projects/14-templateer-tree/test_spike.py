"""Evidence for composing Templateer outputs into a local project tree."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError
from spike import ROOT, CompositionError, fingerprint, output_path, plan, write_tree

ANSWERS = json.loads((ROOT / "answers.json").read_text(encoding="utf-8"))
MANIFEST = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))


def test_five_artifacts_share_saved_typed_model(tmp_path: Path) -> None:
    files = plan(ROOT / "fixtures", MANIFEST, ANSWERS)
    assert set(files) == {
        "README.md", "config/project.yml", "pyproject.toml",
        "scripts/about.py", "src/cedar_lab/__init__.py",
    }
    write_tree(files, tmp_path / "out")
    out = tmp_path / "out"
    assert "Local example" in (out / "README.md").read_text()
    assert stat.S_IMODE((out / "scripts/about.py").stat().st_mode) == 0o755
    assert all(
        stat.S_IMODE((out / name).stat().st_mode) == 0o644
        for name in files if name != "scripts/about.py"
    )


@pytest.mark.parametrize(
    "value",
    ["../outside", "/absolute", "a//b", "a/./b", "a/../b", "a/.jj/x", "a\\b", ""],
)
def test_unsafe_paths_fail(value: str) -> None:
    with pytest.raises(CompositionError, match="unsafe output path"):
        output_path(value, ANSWERS)


def test_path_answer_cannot_escape() -> None:
    with pytest.raises(CompositionError, match="unsafe output path"):
        output_path("src/{{ module }}/__init__.py", {**ANSWERS, "module": "../outside"})


def test_two_templates_cannot_own_one_path(tmp_path: Path) -> None:
    fixtures = tmp_path / "fixtures"
    shutil.copytree(ROOT / "fixtures", fixtures)
    metadata = fixtures / "settings" / "metadata.yml"
    metadata.write_text(metadata.read_text().replace("config/project.yml", "README.md"))
    with pytest.raises(CompositionError, match="two templates own README.md"):
        plan(fixtures, MANIFEST, ANSWERS)


def test_file_and_directory_cannot_collide(tmp_path: Path) -> None:
    fixtures = tmp_path / "fixtures"
    shutil.copytree(ROOT / "fixtures", fixtures)
    metadata = fixtures / "settings" / "metadata.yml"
    metadata.write_text(metadata.read_text().replace("config/project.yml", "README.md/settings.yml"))
    with pytest.raises(CompositionError, match="file and directory collide"):
        plan(fixtures, MANIFEST, ANSWERS)


def test_validator_rejects_invalid_toml(tmp_path: Path) -> None:
    fixtures = tmp_path / "fixtures"
    shutil.copytree(ROOT / "fixtures", fixtures)
    (fixtures / "pyproject" / "template.j2").write_text("[project\nname = 12\n")
    with pytest.raises(CompositionError, match="toml parse failed"):
        plan(fixtures, MANIFEST, ANSWERS)


def test_command_validator_rejects_readme_without_heading(tmp_path: Path) -> None:
    fixtures = tmp_path / "fixtures"
    shutil.copytree(ROOT / "fixtures", fixtures)
    (fixtures / "readme" / "template.j2").write_text("Missing heading\n")
    with pytest.raises(CompositionError, match="Command .* failed"):
        plan(fixtures, MANIFEST, ANSWERS)


def test_structured_artifacts_keep_injected_text_as_data() -> None:
    malicious = {**ANSWERS, "description": '"\nINJECTED = "yes'}
    files = plan(ROOT / "fixtures", MANIFEST, malicious)
    toml_data = tomllib.loads(files["pyproject.toml"][0].decode("utf-8"))
    yaml_data = yaml.safe_load(files["config/project.yml"][0])
    assert toml_data["project"]["description"] == malicious["description"]
    assert "INJECTED" not in toml_data
    assert yaml_data["description"] == malicious["description"]
    assert "INJECTED" not in yaml_data


def test_missing_executable_artifact_fails() -> None:
    manifest = {**MANIFEST, "executable": ["not-generated.py"]}
    with pytest.raises(CompositionError, match="executable path has no artifact"):
        plan(ROOT / "fixtures", manifest, ANSWERS)


def test_changed_required_schema_rejects_saved_model(tmp_path: Path) -> None:
    fixtures = tmp_path / "fixtures"
    shutil.copytree(ROOT / "fixtures", fixtures)
    schema = fixtures / "readme" / "schema.py"
    schema.write_text(schema.read_text() + "\n    license: str\n")
    with pytest.raises(ValidationError, match="license"):
        plan(fixtures, {"templates": ["readme"], "executable": []}, ANSWERS)


def test_changed_default_schema_accepts_saved_model_and_changes_bytes(tmp_path: Path) -> None:
    fixtures = tmp_path / "fixtures"
    shutil.copytree(ROOT / "fixtures", fixtures)
    schema = fixtures / "readme" / "schema.py"
    schema.write_text(schema.read_text() + '\n    license: str = "MIT"\n')
    template = fixtures / "readme" / "template.j2"
    template.write_text(template.read_text() + "\nLicense: {{ license }}\n")
    single = {"templates": ["readme"], "executable": []}
    original = plan(ROOT / "fixtures", single, ANSWERS)["README.md"][0]
    modified = plan(fixtures, single, ANSWERS)["README.md"][0]
    assert modified != original
    assert b"License: MIT" in modified
    with pytest.raises(CompositionError, match="model schema differs"):
        plan(fixtures, MANIFEST, ANSWERS)


def test_fresh_process_tree_bytes_stable_with_changed_environment(tmp_path: Path) -> None:
    fingerprints: list[str] = []
    bytes_by_run: list[dict[str, tuple[bytes, int]]] = []
    for index, (seed, zone, locale) in enumerate(
        [("1", "UTC", "C"), ("2147483647", "Pacific/Honolulu", "C.UTF-8"), ("random", "Asia/Tokyo", "C")]
    ):
        out = tmp_path / f"run-{index}"
        env = {
            **os.environ,
            "PYTHONHASHSEED": seed,
            "TZ": zone,
            "LC_ALL": locale,
            "SOURCE_DATE_EPOCH": str(1_700_000_000 + index),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        process = subprocess.run(
            [sys.executable, str(ROOT / "spike.py"), "--out", str(out)],
            env=env, capture_output=True, text=True, check=True,
        )
        assert process.stdout.startswith("sha256 ")
        fingerprints.append(fingerprint(out))
        bytes_by_run.append({
            p.relative_to(out).as_posix(): (p.read_bytes(), stat.S_IMODE(p.stat().st_mode))
            for p in out.rglob("*") if p.is_file()
        })
    assert len(set(fingerprints)) == 1
    assert bytes_by_run[0] == bytes_by_run[1] == bytes_by_run[2]
