#!/usr/bin/env python3
"""Exercise explicit generation, replay, refresh, and path ownership."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic_ai.usage import RunUsage
from templateer.api import TemplateRegistry

ROOT = Path(__file__).resolve().parents[3]
TEMPLATEER = ROOT.parent / "templateer_v2"
PROTOTYPE = ROOT / ".scratch/projects/13-local-jj-prototype/prototype.py"
EVIDENCE = Path(__file__).with_name("evidence.json")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fake_agent(model_data: dict[str, object], calls: list[str]) -> MagicMock:
    agent = MagicMock()

    async def run(prompt: str) -> MagicMock:
        calls.append(prompt)
        output_type = agent.output_type
        result = MagicMock()
        result.output = output_type.model_validate(model_data)
        result.usage.return_value = RunUsage(input_tokens=11, output_tokens=7)
        return result

    agent.run = AsyncMock(side_effect=run)
    return agent


def main() -> None:
    records: dict[str, object] = {}
    with tempfile.TemporaryDirectory(prefix="templateer-generation-") as temporary:
        work = Path(temporary)
        catalog = work / "templates"
        shutil.copytree(TEMPLATEER / "templates/pyproject-uv", catalog / "pyproject-uv")
        registry = TemplateRegistry.from_paths([catalog])
        first_data = {"project_name": "first-app", "python_version": "3.13"}
        second_data = {"project_name": "second-app", "python_version": "3.13"}
        calls: list[str] = []
        agent = fake_agent(first_data, calls)

        def construct(_model_name: str, *, output_type: type, **_kwargs: object) -> MagicMock:
            agent.output_type = output_type
            return agent

        with patch("templateer.generator.Agent", side_effect=construct):
            first = registry.generate("pyproject-uv", "Generate first-app", model_name="test:fake")
        assert first.succeeded, first.error_detail
        assert first.model is not None and first.artifact is not None
        assert first.output_path == "pyproject.toml"
        assert len(calls) == 1
        assert first.usage is not None and first.usage.get("input_tokens") == 11
        errors, warnings = registry.validate_artifact(
            "pyproject-uv", first.artifact, model_data=first.model
        )
        assert not errors and not warnings, (errors, warnings)
        frozen = {
            "model": first.model,
            "artifact": first.artifact,
            "output_path": first.output_path,
            "template_sha256": digest(b"".join(
                (catalog / "pyproject-uv" / name).read_bytes()
                for name in ("schema.py", "template.j2", "metadata.yml", "prompt.md")
            )),
        }
        snapshot = work / "frozen.json"
        snapshot.write_text(json.dumps(frozen, indent=2, sort_keys=True), encoding="utf-8")
        restored = json.loads(snapshot.read_text(encoding="utf-8"))
        with patch("templateer.generator.Agent", side_effect=AssertionError("model called on replay")):
            replay = registry.render_from_model("pyproject-uv", restored["model"])
        assert replay == restored["artifact"]
        records["generate_replay"] = {
            "model_calls": len(calls),
            "output_path": first.output_path,
            "artifact_sha256": digest(first.artifact.encode()),
            "model_keys": sorted(first.model),
            "usage": first.usage,
        }

        agent2 = fake_agent(second_data, calls)

        def construct_second(_model_name: str, *, output_type: type, **_kwargs: object) -> MagicMock:
            agent2.output_type = output_type
            return agent2

        with patch("templateer.generator.Agent", side_effect=construct_second):
            refreshed = registry.generate("pyproject-uv", "Generate second-app", model_name="test:fake")
        assert refreshed.succeeded, refreshed.error_detail
        assert refreshed.model is not None and refreshed.artifact is not None
        assert len(calls) == 2
        assert refreshed.artifact != first.artifact
        assert registry.render_from_model("pyproject-uv", restored["model"]) == first.artifact
        records["explicit_refresh"] = {
            "model_calls_after_refresh": len(calls),
            "refreshed_sha256": digest(refreshed.artifact.encode()),
            "old_snapshot_unchanged": True,
        }

        renderer = catalog / "pyproject-uv/template.j2"
        renderer.write_text(renderer.read_text(encoding="utf-8") + "\n# changed renderer\n", encoding="utf-8")
        changed = TemplateRegistry.from_paths([catalog]).render_from_model("pyproject-uv", restored["model"])
        assert changed != first.artifact
        assert snapshot.exists() and json.loads(snapshot.read_text())["artifact"] == first.artifact
        records["renderer_drift"] = {
            "same_model_changed_bytes": True,
            "frozen_artifact_stable": True,
            "result_has_template_digest": "template_sha256" in type(first).model_fields,
            "result_has_renderer_version": "renderer_version" in type(first).model_fields,
        }

        spec = importlib.util.spec_from_file_location("prototype13", PROTOTYPE)
        assert spec is not None and spec.loader is not None
        prototype = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(prototype)
        source = work / "source"
        generated = work / "generated"
        output = work / "output"
        source.mkdir()
        generated.mkdir()
        output.mkdir()
        (source / "pyproject.toml").write_text("owner = 'template'\n", encoding="utf-8")
        (generated / "pyproject.toml").write_text("owner = 'generated'\n", encoding="utf-8")
        owned = prototype.render(source, {}, output)
        produced = prototype.overlay_generated(generated, output)
        assert owned == set(produced) == {"pyproject.toml"}
        assert (output / "pyproject.toml").read_text() == "owner = 'generated'\n"
        records["path_collision"] = {
            "path": "pyproject.toml",
            "template_paths": sorted(owned),
            "generated_paths": produced,
            "actual_owner": "generated",
            "rejected": False,
        }

    EVIDENCE.write_text(json.dumps(records, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for name in records:
        print(f"PASS {name}")


if __name__ == "__main__":
    main()
