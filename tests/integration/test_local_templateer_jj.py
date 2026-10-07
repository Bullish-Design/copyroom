"""Exercise the local Templateer and jj workflows in disposable projects."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from copyroom.local.composer import compose
from copyroom.local.errors import LocalError
from copyroom.local.generation import generate, refresh
from copyroom.local.jj import JJ
from copyroom.local.manage import adopt, templatize
from copyroom.local.source import marker, snapshot_path
from copyroom.local.workflow import (
    add_layer,
    apply,
    discard,
    list_layers,
    list_previews,
    new,
    preview,
    status,
    working_digest,
    working_files,
)
from copyroom.local.workshop import (
    golden_diff,
    render_scenario,
    template_checkout,
    template_discard,
    template_test,
    update_test,
)

ROOT = Path(__file__).resolve().parents[2]
SLICE = ROOT / ".scratch" / "projects" / "26-templateer-jj-slice"


class LocalTemplateerJJTests(unittest.TestCase):
    """Run local rendering and merge behavior against real temporary jj repos."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="copyroom-local-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        shutil.copytree(SLICE / "example", self.source)
        self.answers = self.source / "answers.json"
        self.project = self.root / "project"

    def create(self) -> None:
        new(self.source, self.project, self.answers)

    def change_template(self, name: str, content: str) -> None:
        path = self.source / "templates" / name / "template.j2"
        path.write_text(content, encoding="utf-8")

    def test_new_saves_source_snapshot_modes_and_answers(self) -> None:
        self.create()
        data = marker(self.project)
        self.assertEqual(5, len(data["owners"]))
        self.assertTrue((self.project / "scripts/about.py").stat().st_mode & 0o111)
        snapshot = snapshot_path(self.project, data["source_digest"])
        self.assertTrue(snapshot.is_dir())
        self.assertEqual(data["source_digest"], marker(self.project)["source_digest"])

    def test_preview_apply_preserves_local_edits_and_snapshots_new_source(self) -> None:
        self.create()
        readme = self.project / "README.md"
        readme.write_text(readme.read_text(encoding="utf-8") + "\nLocal note.\n", encoding="utf-8")
        old_head = JJ(self.project).commit_id("@")
        self.change_template(
            "settings",
            (self.source / "templates/settings/template.j2").read_text(encoding="utf-8")
            + '\nrevision: "v2"\n',
        )
        before = working_digest(self.project)
        out = self.root / "preview"
        state = preview(self.project, out)
        self.assertEqual(before, working_digest(self.project))
        self.assertEqual(old_head, state["active_head"])
        self.assertTrue((out / ".copyroom-local/sources" / state["source_digest"]).is_dir())
        self.assertEqual(1, len(list_previews(self.project)))
        apply(self.project, out)
        self.assertFalse(out.exists())
        self.assertIn("Local note.", readme.read_text(encoding="utf-8"))
        self.assertIn('revision: "v2"', (self.project / "config/project.yml").read_text(encoding="utf-8"))
        self.assertTrue(snapshot_path(self.project, state["source_digest"]).is_dir())
        self.assertEqual(1, marker(self.project)["revision"])

    def test_conflict_can_be_resolved_in_preview_and_applied_exactly(self) -> None:
        self.create()
        readme = self.project / "README.md"
        readme.write_text("# Project edit\n", encoding="utf-8")
        template = self.source / "templates/readme/template.j2"
        template.write_text("# Template edit\n", encoding="utf-8")
        before = working_digest(self.project)
        out = self.root / "conflict"
        state = preview(self.project, out)
        self.assertEqual(["README.md"], state["conflicts"])
        self.assertEqual(before, working_digest(self.project))
        self.assertTrue(JJ(out).conflicts())
        (out / "README.md").write_text("# Resolved in preview\n", encoding="utf-8")
        self.assertEqual([], JJ(out).conflicts())
        preview_files = {
            name: value for name, value in working_files(out).items()
            if name != ".copyroom-local.json"
        }
        apply(self.project, out)
        self.assertEqual("# Resolved in preview\n", readme.read_text(encoding="utf-8"))
        project_files = {
            name: value for name, value in working_files(self.project).items()
            if name != ".copyroom-local.json"
        }
        self.assertEqual(preview_files, project_files)

    def test_stale_preview_and_project_owned_path_collision_are_rejected(self) -> None:
        self.create()
        template = self.source / "templates/settings/template.j2"
        template.write_text(template.read_text(encoding="utf-8") + '\nrevision: "v2"\n', encoding="utf-8")
        out = self.root / "stale"
        preview(self.project, out)
        (self.project / "notes.txt").write_text("Project-owned\n", encoding="utf-8")
        before = working_digest(self.project)
        with self.assertRaisesRegex(LocalError, "active project changed"):
            apply(self.project, out)
        self.assertEqual(before, working_digest(self.project))
        discard(out)

        (self.project / "claimed.txt").write_text("Project-owned\n", encoding="utf-8")
        metadata = self.source / "templates/settings/metadata.yml"
        metadata.write_text(
            metadata.read_text(encoding="utf-8").replace("config/project.yml", "claimed.txt"),
            encoding="utf-8",
        )
        before = working_digest(self.project)
        with self.assertRaisesRegex(LocalError, "output path collision"):
            preview(self.project, self.root / "collision")
        self.assertEqual(before, working_digest(self.project))
        self.assertFalse((self.root / "collision").exists())

    def test_apply_reports_a_foreign_jj_operation_and_keeps_preview(self) -> None:
        self.create()
        template = self.source / "templates/settings/template.j2"
        template.write_text(
            template.read_text(encoding="utf-8") + '\nrevision: "concurrent-check"\n',
            encoding="utf-8",
        )
        out = self.root / "concurrent-preview"
        preview(self.project, out)

        original = JJ.run
        foreign: dict[str, str] = {}

        def concurrent_run(jj: JJ, *args: str, **kwargs: object) -> str:
            if jj.cwd == self.project and args[:1] == ("new",) and not foreign:
                (self.project / "concurrent.txt").write_text("concurrent work\n", encoding="utf-8")
                original(jj, "commit", "-m", "external concurrent commit")
                foreign["head"] = jj.commit_id("@")
                foreign["operation"] = jj.operation_id()
            return original(jj, *args, **kwargs)

        with patch.object(JJ, "run", concurrent_run):
            with self.assertRaisesRegex(LocalError, "overlapped a jj operation") as raised:
                apply(self.project, out)

        self.assertIn(foreign["operation"], str(raised.exception))
        self.assertIn("Inspect jj op log", str(raised.exception))
        self.assertTrue(out.exists())
        self.assertEqual(foreign["head"], JJ(self.project).commit_id(foreign["head"]))

    def test_layer_add_reports_a_foreign_jj_operation(self) -> None:
        self.create()
        overlay = self.root / "overlay-source"
        shutil.copytree(self.source, overlay)
        manifest_path = overlay / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["templates"] = ["settings"]
        manifest["executable"] = []
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        metadata = overlay / "templates/settings/metadata.yml"
        metadata.write_text(
            metadata.read_text(encoding="utf-8").replace("config/project.yml", "docs/guide.md"),
            encoding="utf-8",
        )

        original = JJ.run
        foreign: dict[str, str] = {}

        def concurrent_run(jj: JJ, *args: str, **kwargs: object) -> str:
            if jj.cwd == self.project and args[:1] == ("new",) and not foreign:
                (self.project / "concurrent.txt").write_text("concurrent work\n", encoding="utf-8")
                original(jj, "commit", "-m", "external concurrent commit")
                foreign["head"] = jj.commit_id("@")
                foreign["operation"] = jj.operation_id()
            return original(jj, *args, **kwargs)

        with patch.object(JJ, "run", concurrent_run):
            with self.assertRaisesRegex(LocalError, "overlapped a jj operation") as raised:
                add_layer(self.project, overlay, overlay / "answers.json", "docs")

        self.assertIn(foreign["operation"], str(raised.exception))
        self.assertIn("Inspect jj op log", str(raised.exception))
        self.assertEqual(foreign["head"], JJ(self.project).commit_id(foreign["head"]))

    def test_source_snapshot_replays_after_locator_disappears(self) -> None:
        self.create()
        self.source.rename(self.root / "moved-source")
        result = preview(self.project, self.root / "no-change")
        self.assertEqual("no-change", result["result"])
        self.assertFalse((self.root / "no-change").exists())
        self.assertEqual(0, len(list_previews(self.project)))

    def test_static_bytes_and_safe_relative_symlink_are_composed(self) -> None:
        (self.source / "assets").mkdir()
        (self.source / "assets/payload.bin").write_bytes(b"\x00\xfftemplateer\n")
        manifest_path = self.source / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["static"] = [{
            "path": "assets/payload.bin", "source": "assets/payload.bin", "executable": True,
        }]
        manifest["symlinks"] = [{"path": "docs/current", "target": "../README.md"}]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        self.create()
        binary = self.project / "assets/payload.bin"
        self.assertEqual(b"\x00\xfftemplateer\n", binary.read_bytes())
        self.assertTrue(binary.stat().st_mode & 0o111)
        self.assertTrue((self.project / "docs/current").is_symlink())
        self.assertEqual("../README.md", (self.project / "docs/current").readlink().as_posix())

    def test_unsafe_symlink_and_schema_mismatch_leave_no_project(self) -> None:
        manifest_path = self.source / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["symlinks"] = [{"path": "docs/current", "target": "../../outside"}]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(LocalError, "escapes"):
            new(self.source, self.project, self.answers)
        self.assertFalse(self.project.exists())

        manifest.pop("symlinks")
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        schema = self.source / "templates/about/schema.py"
        schema.write_text(
            schema.read_text(encoding="utf-8").replace(
                "class ProjectModel(BaseModel):\n",
                "class ProjectModel(BaseModel):\n    extra_field: str = 'x'\n",
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(LocalError, "schema differs"):
            new(self.source, self.project, self.answers)
        self.assertFalse(self.project.exists())

    def test_symlink_cycle_is_rejected_before_project_creation(self) -> None:
        manifest_path = self.source / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["symlinks"] = [
            {"path": "docs/a", "target": "b"},
            {"path": "docs/b", "target": "a"},
        ]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        with self.assertRaisesRegex(LocalError, "symlink cycle"):
            new(self.source, self.project, self.answers)

        self.assertFalse(self.project.exists())

    def test_status_reports_render_head_and_pending_preview(self) -> None:
        self.create()
        template = self.source / "templates/settings/template.j2"
        template.write_text(template.read_text(encoding="utf-8") + '\nrevision: "v2"\n', encoding="utf-8")
        out = self.root / "pending"
        preview(self.project, out)
        report = status(self.project)
        self.assertTrue(report["ok"])
        self.assertTrue(report["render_head"])
        self.assertEqual(1, len(report["pending_previews"]))
        discard(out)
        self.assertEqual([], status(self.project)["pending_previews"])

    def test_layer_add_and_update_keep_render_heads_independent(self) -> None:
        self.create()
        overlay = self.root / "overlay-source"
        shutil.copytree(self.source, overlay)
        manifest_path = overlay / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["templates"] = ["settings"]
        manifest["executable"] = []
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        metadata = overlay / "templates/settings/metadata.yml"
        metadata.write_text(
            metadata.read_text(encoding="utf-8").replace("config/project.yml", "docs/guide.md"),
            encoding="utf-8",
        )
        base_head = JJ(self.project).render_head(marker(self.project)["project_id"], "base")
        add_layer(self.project, overlay, overlay / "answers.json", "docs")
        self.assertEqual(["base", "docs"], [item["layer"] for item in list_layers(self.project)])
        self.assertTrue((self.project / "docs/guide.md").is_file())
        self.assertEqual(base_head, JJ(self.project).render_head(marker(self.project)["project_id"], "base"))
        docs_head = JJ(self.project).render_head(marker(self.project)["project_id"], "docs")
        template = overlay / "templates/settings/template.j2"
        template.write_text(
            template.read_text(encoding="utf-8") + '\nrevision: "overlay-v2"\n',
            encoding="utf-8",
        )
        out = self.root / "docs-preview"
        preview(self.project, out, layer="docs")
        apply(self.project, out)
        self.assertEqual(base_head, JJ(self.project).render_head(marker(self.project)["project_id"], "base"))
        self.assertNotEqual(docs_head, JJ(self.project).render_head(marker(self.project)["project_id"], "docs"))

    def test_generation_is_explicit_and_refresh_freezes_a_new_artifact(self) -> None:
        generated_source = self.root / "generated-source"
        shutil.copytree(self.source, generated_source)
        template_dir = generated_source / "templates/generated"
        shutil.copytree(generated_source / "templates/settings", template_dir)
        metadata = template_dir / "metadata.yml"
        metadata.write_text(
            metadata.read_text(encoding="utf-8")
            .replace("name: settings", "name: generated")
            .replace("config/project.yml", "generated/config.yml"),
            encoding="utf-8",
        )
        self.create()
        calls: list[str] = []

        def fake_agent(model_data: dict[str, str]) -> MagicMock:
            agent = MagicMock()

            async def run(prompt: str) -> MagicMock:
                calls.append(prompt)
                result = MagicMock()
                result.output = agent.output_type.model_validate(model_data)
                result.usage.return_value = SimpleNamespace(input_tokens=11, output_tokens=7)
                return result

            agent.run = AsyncMock(side_effect=run)
            return agent

        first_agent = fake_agent({
            "project_name": "cedar-lab", "module": "cedar_lab",
            "description": "First generated description", "python_version": "3.13",
        })

        def first_agent_factory(_model: str, *, output_type: type, **_kwargs: object) -> MagicMock:
            first_agent.output_type = output_type
            return first_agent

        with patch("templateer.generator.Agent", side_effect=first_agent_factory):
            generate(self.project, generated_source, "generated", "Write the initial config", "test:fake")
        state = marker(self.project)
        owner = state["layers"]["gen-generated"]
        frozen = owner["generation"]["artifact_base64"]
        old_bytes = (self.project / "generated/config.yml").read_bytes()
        self.assertEqual(1, len(calls))
        self.assertEqual("unknown", owner["generation"]["provider_revision"])
        self.assertEqual("First generated description", owner["generation"]["model"]["description"])

        replay = preview(self.project, self.root / "frozen-replay", layer="gen-generated")
        self.assertEqual("no-change", replay["result"])
        self.assertEqual(1, len(calls))

        second_agent = fake_agent({
            "project_name": "cedar-lab", "module": "cedar_lab",
            "description": "Refreshed generated description", "python_version": "3.13",
        })

        def second_agent_factory(_model: str, *, output_type: type, **_kwargs: object) -> MagicMock:
            second_agent.output_type = output_type
            return second_agent

        preview_path = self.root / "refresh-preview"
        with patch("templateer.generator.Agent", side_effect=second_agent_factory):
            pending = refresh(
                self.project, "gen-generated", preview_path, "Refresh the config", model_name="test:fake",
            )
        self.assertEqual(2, len(calls))
        self.assertEqual("Refreshed generated description", pending["answers"]["description"])
        self.assertEqual(old_bytes, (self.project / "generated/config.yml").read_bytes())
        apply(self.project, preview_path)
        updated = marker(self.project)["layers"]["gen-generated"]["generation"]
        self.assertNotEqual(frozen, updated["artifact_base64"])
        self.assertIn(
            "Refreshed generated description",
            (self.project / "generated/config.yml").read_text(encoding="utf-8"),
        )

    def test_adopt_reports_then_records_marker_without_changing_project_files(self) -> None:
        source = self.root / "adopt-source"
        shutil.copytree(SLICE / "example", source)
        target = self.root / "existing"
        target.mkdir()
        plan = compose(source, json.loads((source / "answers.json").read_text(encoding="utf-8")))
        from copyroom.local.workflow import write_tree

        write_tree(target, plan.files)
        (target / "notes.txt").write_text("Project-owned note\n", encoding="utf-8")
        before = {
            name: value for name, value in working_files(target).items()
            if name != ".copyroom-local.json" and not name.startswith(".copyroom-local/")
        }
        report = adopt(target, source, source / "answers.json")
        self.assertEqual("report", report["result"])
        self.assertEqual(["notes.txt"], report["project_only"])
        self.assertFalse((target / ".jj").exists())
        adopted = adopt(target, source, source / "answers.json", write=True)
        self.assertTrue(adopted["project_tree_preserved"])
        after = {
            name: value for name, value in working_files(target).items()
            if name != ".copyroom-local.json" and not name.startswith(".copyroom-local/")
        }
        self.assertEqual(before, after)
        self.assertEqual(plan.source_digest, marker(target)["source_digest"])
        self.assertTrue(JJ(target).render_head(marker(target)["project_id"], "base"))

    def test_adopt_requires_template_only_choice_and_saves_omissions(self) -> None:
        source = self.root / "adopt-source"
        shutil.copytree(SLICE / "example", source)
        target = self.root / "empty-project"
        target.mkdir()
        with self.assertRaisesRegex(LocalError, "choose --template-only keep"):
            adopt(target, source, source / "answers.json", write=True)
        result = adopt(target, source, source / "answers.json", write=True, template_only_choice="keep")
        self.assertTrue(result["project_tree_preserved"])
        self.assertEqual(
            sorted(result["template_only"]),
            sorted(marker(target)["layers"]["base"]["omissions"]),
        )
        preview_result = preview(target, self.root / "omitted-preview")
        self.assertEqual("no-change", preview_result["result"])

    def test_templatize_reproduces_text_binary_modes_and_links(self) -> None:
        project = self.root / "legacy"
        project.mkdir()
        (project / "README.md").write_text(
            "# legacy\n\nLiteral marker: {{ keep this }}\n", encoding="utf-8",
        )
        (project / "scripts").mkdir()
        script = project / "scripts/hello.sh"
        script.write_text("#!/bin/sh\necho legacy\n", encoding="utf-8")
        script.chmod(0o755)
        (project / "assets").mkdir()
        (project / "assets/pixel.bin").write_bytes(b"\x00\xff\x01")
        (project / "docs").mkdir()
        (project / "docs/current").symlink_to("../README.md")
        source = self.root / "legacy-template"
        report = templatize(project, source, parameterize=["README.md"])
        self.assertTrue(report["golden_exact"])
        answers = json.loads((source / "answers.json").read_text(encoding="utf-8"))
        original = compose(source, answers)
        self.assertEqual(
            {name: value for name, value in working_files(project).items()},
            {
                name: (entry.kind, entry.content, entry.mode)
                for name, entry in original.files.items()
            },
        )
        probe = compose(source, {"project_name": "probe-app"})
        self.assertIn(b"# probe-app", probe.files["README.md"].content)
        self.assertIn(b"{{ keep this }}", probe.files["README.md"].content)
        self.assertEqual(b"\x00\xff\x01", probe.files["assets/pixel.bin"].content)

    def test_templatize_preserves_crlf_bytes_in_exact_and_parameterized_renders(self) -> None:
        project = self.root / "alpha"
        project.mkdir()
        original = b"alpha\r\nsecond line\r\nthird line"
        (project / "README.md").write_bytes(original)
        source = self.root / "alpha-template"

        templatize(project, source, parameterize=["README.md"])

        answers = json.loads((source / "answers.json").read_text(encoding="utf-8"))
        exact = compose(source, answers)
        probe = compose(source, {"project_name": "beta"})
        self.assertEqual(original, exact.files["README.md"].content)
        self.assertEqual(b"beta\r\nsecond line\r\nthird line", probe.files["README.md"].content)

    def test_workshop_golden_compares_full_tree_and_candidate_is_isolated(self) -> None:
        workshop = self.root / "workshop"
        (workshop / "registry").mkdir(parents=True)
        (workshop / "scenarios/demo").mkdir(parents=True)
        shutil.copytree(self.source, workshop / "source")
        (workshop / "copyroom.yml").write_text(
            "templates:\n  demo:\n    source: source\n", encoding="utf-8",
        )
        (workshop / "scenarios/demo/basic.yml").write_text(
            self.answers.read_text(encoding="utf-8"), encoding="utf-8",
        )
        rendered = render_scenario("demo", "basic", workshop)
        golden = workshop / "goldens/demo/basic"
        golden.parent.mkdir(parents=True)
        shutil.copytree(rendered["output"], golden)
        self.assertEqual("match", golden_diff("demo", "basic", workshop)["result"])

        candidate_state = template_checkout("demo", workshop)
        candidate = Path(candidate_state["candidate"])
        template_test("demo", workshop)
        settings = candidate / "templates/settings/template.j2"
        settings.write_text(
            settings.read_text(encoding="utf-8") + "\n# Candidate update\n",
            encoding="utf-8",
        )
        real_run = subprocess.run

        def fake_devenv(command: list[str], *args: object, **kwargs: object) -> object:
            if command == ["devenv", "test"]:
                return SimpleNamespace(returncode=0, stdout="tests passed\n", stderr="")
            return real_run(command, *args, **kwargs)

        with patch("copyroom.local.workshop.subprocess.run", side_effect=fake_devenv):
            update_report = update_test("demo", "basic", workshop)
        self.assertEqual("passed", update_report["result"])
        active_readme = (workshop / "source/templates/readme/template.j2").read_bytes()
        candidate_readme = candidate / "templates/readme/template.j2"
        candidate_readme.write_bytes(candidate_readme.read_bytes() + b"Candidate line.\n")
        with self.assertRaisesRegex(LocalError, "candidate golden differs"):
            template_test("demo", workshop)
        self.assertEqual(active_readme, (workshop / "source/templates/readme/template.j2").read_bytes())
        template_discard(workshop)
        self.assertFalse(candidate.exists())


if __name__ == "__main__":
    unittest.main()
