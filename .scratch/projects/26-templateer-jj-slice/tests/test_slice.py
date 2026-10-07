"""Exercise the local Templateer and jj command flow in disposable repos."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from slice import (  # noqa: E402
    MARKER,
    SliceError,
    commit_id,
    render_head,
    update,
    working_digest,
    working_files,
)


class SliceFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="copyroom-slice-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        shutil.copytree(ROOT / "example", self.source)
        self.project = self.root / "project"
        self.answers = self.source / "answers.json"

    def command(self, *args: str, code: int = 0) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [sys.executable, str(ROOT / "slice.py"), *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(code, result.returncode, f"{result.stdout}\n{result.stderr}")
        return result

    def create(self) -> None:
        self.command(
            "new", "--source", str(self.source), "--target", str(self.project),
            "--answers", str(self.answers),
        )

    def change_template(self, relative: str, addition: str) -> None:
        path = self.source / "templates" / relative / "template.j2"
        path.write_text(path.read_text(encoding="utf-8") + addition, encoding="utf-8")

    def test_new_preview_update_and_second_update(self) -> None:
        self.create()
        initial = json.loads((self.project / MARKER).read_text())
        old_render = render_head(self.project, initial["project_id"])
        self.assertEqual(5, len(initial["owners"]))
        self.assertTrue((self.project / "scripts/about.py").stat().st_mode & 0o111)

        pyproject = self.project / "pyproject.toml"
        pyproject.write_text(
            pyproject.read_text().replace('version = "0.1.0"', 'version = "0.1.1"')
        )
        (self.project / "notes.txt").write_text("owned by project\n")
        self.change_template("pyproject", '\nclassifiers = ["Private :: Local"]\n')
        self.change_template("settings", 'revision: "v2"\n')
        active_before = working_digest(self.project)
        head_before = commit_id(self.project, "@")
        preview = self.root / "preview-one"
        result = self.command("preview", "--project", str(self.project), "--out", str(preview))
        self.assertIn("classifiers", result.stdout)
        self.assertEqual(active_before, working_digest(self.project))
        self.assertEqual(head_before, commit_id(self.project, "@"))
        expected = working_files(preview)
        self.assertIn(b'version = "0.1.1"', expected["pyproject.toml"][1])
        self.assertIn(b"classifiers", expected["pyproject.toml"][1])
        self.assertIn(b"revision: \"v2\"", expected["config/project.yml"][1])
        self.command("update", "--project", str(self.project), "--preview", str(preview))
        self.assertFalse(preview.exists())
        self.assertEqual(
            {name: value for name, value in expected.items() if name != MARKER},
            {name: value for name, value in working_files(self.project).items() if name != MARKER},
        )
        self.assertEqual(1, json.loads((self.project / MARKER).read_text())["revision"])
        first_render = render_head(self.project, initial["project_id"])
        self.assertEqual(old_render, commit_id(self.project, f"{first_render}-"))

        readme = self.project / "README.md"
        readme.write_text(readme.read_text() + "\nLocal note.\n")
        self.change_template("settings", 'phase: "v3"\n')
        second = self.root / "preview-two"
        self.command("preview", "--project", str(self.project), "--out", str(second))
        self.command("update", "--project", str(self.project), "--preview", str(second))
        second_render = render_head(self.project, initial["project_id"])
        self.assertEqual(first_render, commit_id(self.project, f"{second_render}-"))
        self.assertIn("Local note.", readme.read_text())
        self.assertIn('phase: "v3"', (self.project / "config/project.yml").read_text())
        self.assertEqual("owned by project\n", (self.project / "notes.txt").read_text())
        self.assertEqual(2, json.loads((self.project / MARKER).read_text())["revision"])
        self.command("status", "--project", str(self.project))

        no_change = self.root / "no-change"
        result = self.command("preview", "--project", str(self.project), "--out", str(no_change))
        self.assertIn("result no-change", result.stdout)
        self.assertFalse(no_change.exists())

    def test_conflict_stays_in_preview(self) -> None:
        self.create()
        readme = self.project / "README.md"
        readme.write_text(readme.read_text().replace("# cedar-lab", "# Local cedar-lab"))
        path = self.source / "templates/readme/template.j2"
        path.write_text(
            path.read_text().replace("# {{ project_name }}", "# New {{ project_name }}")
        )
        active_before = working_digest(self.project)
        preview = self.root / "conflict"
        result = self.command(
            "preview", "--project", str(self.project), "--out", str(preview), code=1
        )
        self.assertIn("conflict README.md", result.stdout)
        self.assertEqual(active_before, working_digest(self.project))
        self.command("update", "--project", str(self.project), "--preview", str(preview), code=1)
        self.assertEqual(active_before, working_digest(self.project))
        self.command("discard", "--preview", str(preview))
        self.assertFalse(preview.exists())

    def test_stale_preview_and_new_path_ownership(self) -> None:
        self.create()
        self.change_template("settings", 'revision: "v2"\n')
        preview = self.root / "stale"
        self.command("preview", "--project", str(self.project), "--out", str(preview))
        (self.project / "notes.txt").write_text("new project work\n")
        before = working_digest(self.project)
        result = self.command(
            "update", "--project", str(self.project), "--preview", str(preview), code=1
        )
        self.assertIn("active project changed", result.stderr)
        self.assertEqual(before, working_digest(self.project))
        self.command("discard", "--preview", str(preview))

        (self.project / "claimed.txt").write_text("project owns this\n")
        metadata = self.source / "templates/settings/metadata.yml"
        metadata.write_text(metadata.read_text().replace("config/project.yml", "claimed.txt"))
        before = working_digest(self.project)
        result = self.command(
            "preview", "--project", str(self.project), "--out", str(self.root / "collision"),
            code=2,
        )
        self.assertIn("output path collision", result.stderr)
        self.assertEqual(before, working_digest(self.project))
        self.assertFalse((self.root / "collision").exists())

    def test_apply_uses_the_previewed_render_after_source_changes(self) -> None:
        self.create()
        self.change_template("settings", 'revision: "previewed"\n')
        preview = self.root / "frozen"
        self.command("preview", "--project", str(self.project), "--out", str(preview))
        state = json.loads((self.root / "frozen.copyroom-preview.json").read_text())
        self.change_template("settings", 'revision: "later"\n')
        self.command("update", "--project", str(self.project), "--preview", str(preview))
        settings = (self.project / "config/project.yml").read_text()
        self.assertIn('revision: "previewed"', settings)
        self.assertNotIn('revision: "later"', settings)
        saved = json.loads((self.project / MARKER).read_text())
        self.assertEqual(state["source_digest"], saved["source_digest"])
        self.assertEqual(state["next_render"], render_head(self.project, saved["project_id"]))

        later = self.root / "later"
        self.command("preview", "--project", str(self.project), "--out", str(later))
        self.command("discard", "--preview", str(later))

    def test_new_rejects_two_templates_with_one_output_path(self) -> None:
        metadata = self.source / "templates/settings/metadata.yml"
        metadata.write_text(metadata.read_text().replace("config/project.yml", "README.md"))
        result = self.command(
            "new", "--source", str(self.source), "--target", str(self.project),
            "--answers", str(self.answers), code=2,
        )
        self.assertIn("output path collision", result.stderr)
        self.assertFalse(self.project.exists())

    def test_controlled_apply_failure_restores_the_active_project(self) -> None:
        self.create()
        self.change_template("settings", 'revision: "v2"\n')
        preview = self.root / "rollback"
        self.command("preview", "--project", str(self.project), "--out", str(preview))
        before_head = commit_id(self.project, "@")
        before_tree = working_digest(self.project)
        with patch("slice.conflicts", side_effect=SliceError("injected check failure")):
            with self.assertRaisesRegex(SliceError, "injected check failure"):
                update(argparse.Namespace(project=self.project, preview=preview))
        self.assertEqual(before_head, commit_id(self.project, "@"))
        self.assertEqual(before_tree, working_digest(self.project))
        self.assertTrue(preview.exists())
        self.command("discard", "--preview", str(preview))

    def test_source_change_without_output_change_records_a_render(self) -> None:
        self.create()
        before = json.loads((self.project / MARKER).read_text())
        prompt = self.source / "templates/settings/prompt.md"
        prompt.write_text(prompt.read_text() + "\nAuthor note.\n")
        preview = self.root / "source-only"
        self.command("preview", "--project", str(self.project), "--out", str(preview))
        self.command("update", "--project", str(self.project), "--preview", str(preview))
        after = json.loads((self.project / MARKER).read_text())
        self.assertNotEqual(before["source_digest"], after["source_digest"])
        self.assertEqual(before["render_digest"], after["render_digest"])
        self.assertEqual(1, after["revision"])

    def test_source_override_and_new_answers(self) -> None:
        self.create()
        moved = self.root / "moved-source"
        self.source.rename(moved)
        answers = json.loads((moved / "answers.json").read_text())
        answers["description"] = "Changed after source move"
        new_answers = self.root / "new-answers.json"
        new_answers.write_text(json.dumps(answers))
        preview = self.root / "moved-preview"
        self.command(
            "preview", "--project", str(self.project), "--out", str(preview), code=2
        )
        self.assertFalse(preview.exists())
        self.command(
            "preview", "--project", str(self.project), "--out", str(preview),
            "--source", str(moved), "--answers", str(new_answers),
        )
        self.command("update", "--project", str(self.project), "--preview", str(preview))
        saved = json.loads((self.project / MARKER).read_text())
        self.assertEqual(str(moved), saved["source"])
        self.assertEqual("Changed after source move", saved["answers"]["description"])
        self.assertIn("Changed after source move", (self.project / "README.md").read_text())

    def test_source_templates_symlink_is_rejected_before_new(self) -> None:
        external = self.root / "external-templates"
        (self.source / "templates").rename(external)
        (self.source / "templates").symlink_to(external, target_is_directory=True)
        self.command(
            "new", "--source", str(self.source), "--target", str(self.project),
            "--answers", str(self.answers), code=2,
        )
        self.assertFalse(self.project.exists())


if __name__ == "__main__":
    unittest.main()
