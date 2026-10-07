"""End-to-end checks for the local render-commit prototype."""

from __future__ import annotations

import json
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
CLI = HERE / "prototype.py"
FIXTURES = HERE.parent / "12-jj-render-merge" / "fixtures"


class PrototypeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="copyroom-prototype-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.answers = self.root / "answers.json"
        self.answers.write_text(
            json.dumps({"project_name": "demo-app", "module": "demo_app", "python_version": "3.13"}),
            encoding="utf-8",
        )

    def cli(self, *args: str, expected: int = 0) -> str:
        result = subprocess.run(
            [sys.executable, str(CLI), *args], capture_output=True, text=True, check=False
        )
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result.stdout + result.stderr

    def jj(self, *args: str) -> str:
        result = subprocess.run(
            ["jj", *args], cwd=self.project, capture_output=True, text=True, check=False
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def create(self, source: Path, generated: Path | None = None) -> None:
        args = [
            "new", "--template", str(source), "--target", str(self.project),
            "--answers", str(self.answers),
        ]
        if generated:
            args.extend(["--generated", str(generated)])
        self.cli(*args)

    def update(self, source: Path, generated: Path | None = None, expected: int = 0) -> str:
        args = ["update", "--project", str(self.project), "--template", str(source)]
        if generated:
            args.extend(["--generated", str(generated)])
        return self.cli(*args, expected=expected)

    def project_state(self) -> tuple[str, dict[str, tuple[bytes, int]]]:
        head = self.jj("log", "--no-graph", "--ignore-working-copy", "-r", "@", "-T", "commit_id").strip()
        tree = {
            path.relative_to(self.project).as_posix(): (
                path.read_bytes(), stat.S_IMODE(path.stat().st_mode)
            )
            for path in self.project.rglob("*")
            if path.is_file() and not {".jj", ".git"} & set(path.relative_to(self.project).parts)
        }
        return head, tree

    def test_two_updates_preserve_project_edits(self) -> None:
        self.create(FIXTURES / "base-v1")
        with (self.project / "README.md").open("a", encoding="utf-8") as stream:
            stream.write("\nProject note one.\n")
        self.jj("commit", "-m", "project: first edit")
        self.update(FIXTURES / "base-v2")
        with (self.project / "README.md").open("a", encoding="utf-8") as stream:
            stream.write("\nProject note two.\n")
        (self.project / "local.txt").write_text("local\n", encoding="utf-8")
        self.jj("commit", "-m", "project: second edit")

        v3 = self.root / "base-v3"
        shutil.copytree(FIXTURES / "base-v2", v3)
        config = v3 / "pyproject.toml"
        config.write_text(
            config.read_text(encoding="utf-8").replace("line-length = 120", "line-length = 140"),
            encoding="utf-8",
        )
        self.update(v3)

        readme = (self.project / "README.md").read_text(encoding="utf-8")
        self.assertIn("Project note one.", readme)
        self.assertIn("Project note two.", readme)
        self.assertEqual((self.project / "local.txt").read_text(encoding="utf-8"), "local\n")
        self.assertIn(
            "line-length = 140", (self.project / "pyproject.toml").read_text(encoding="utf-8")
        )
        status = self.cli("status", "--project", str(self.project))
        self.assertIn("revision 2", status)
        self.assertIn("conflicts 0", status)

    def test_generated_snapshot_is_explicit_and_persistent(self) -> None:
        v1 = self.root / "v1"
        v2 = self.root / "v2"
        v3 = self.root / "v3"
        for index, source in enumerate((v1, v2, v3), start=1):
            source.mkdir()
            (source / "template.txt").write_text(f"version {index}\n", encoding="utf-8")
        first = self.root / "generated-one"
        second = self.root / "generated-two"
        first.mkdir()
        second.mkdir()
        (first / "llm.txt").write_text("model output one\n", encoding="utf-8")
        (second / "llm.txt").write_text("model output two\n", encoding="utf-8")
        (first / "run.sh").write_text("#!/bin/sh\necho first\n", encoding="utf-8")
        (first / "run.sh").chmod(0o755)

        self.create(v1, first)
        self.update(v2)
        self.assertEqual((self.project / "llm.txt").read_text(encoding="utf-8"), "model output one\n")
        self.assertTrue((self.project / "run.sh").stat().st_mode & 0o111)
        self.update(v3, second)
        self.assertEqual((self.project / "llm.txt").read_text(encoding="utf-8"), "model output two\n")
        self.assertFalse((self.project / "run.sh").exists())
        marker = json.loads((self.project / ".copyroom-local.json").read_text(encoding="utf-8"))
        self.assertTrue(marker["generation"]["enabled"])
        self.assertEqual(marker["generation"]["paths"], ["llm.txt"])

    def test_new_rejects_generated_exact_and_prefix_collisions_before_init(self) -> None:
        source = self.root / "template"
        (source / "docs").mkdir(parents=True)
        (source / "README.md").write_text("template\n", encoding="utf-8")
        (source / "docs" / "guide.md").write_text("guide\n", encoding="utf-8")
        for label, generated_path, expected in (
            ("exact", "README.md", "exact output path collision"),
            ("child", "README.md/child.txt", "file-directory output path collision"),
            ("parent", "docs", "file-directory output path collision"),
        ):
            with self.subTest(label=label):
                generated = self.root / f"generated-{label}"
                target = generated / generated_path
                target.parent.mkdir(parents=True)
                target.write_text("generated\n", encoding="utf-8")
                report = self.cli(
                    "new", "--template", str(source), "--target", str(self.project),
                    "--answers", str(self.answers), "--generated", str(generated),
                    expected=2,
                )
                self.assertIn(expected, report)
                self.assertFalse(self.project.exists())

    def test_generated_refresh_collision_preserves_project_state(self) -> None:
        source = self.root / "template"
        source.mkdir()
        (source / "base.txt").write_text("template\n", encoding="utf-8")
        original = self.root / "generated-original"
        original.mkdir()
        (original / "frozen.txt").write_text("frozen\n", encoding="utf-8")
        self.create(source, original)
        before = self.project_state()
        for label, generated_path, expected in (
            ("exact", "base.txt", "exact output path collision"),
            ("child", "base.txt/child.txt", "file-directory output path collision"),
        ):
            with self.subTest(label=label):
                generated = self.root / f"refresh-{label}"
                target = generated / generated_path
                target.parent.mkdir(parents=True)
                target.write_text("refresh\n", encoding="utf-8")
                report = self.update(source, generated, expected=2)
                self.assertIn(expected, report)
                self.assertEqual(self.project_state(), before)

    def test_reused_generated_path_collision_preserves_project_state(self) -> None:
        source = self.root / "template-v1"
        source.mkdir()
        (source / "base.txt").write_text("template\n", encoding="utf-8")
        original = self.root / "generated"
        original.mkdir()
        (original / "frozen.txt").write_text("frozen\n", encoding="utf-8")
        self.create(source, original)
        before = self.project_state()
        for label, template_path, expected in (
            ("exact", "frozen.txt", "exact output path collision"),
            ("child", "frozen.txt/child.txt", "file-directory output path collision"),
        ):
            with self.subTest(label=label):
                next_source = self.root / f"template-{label}"
                target = next_source / template_path
                target.parent.mkdir(parents=True)
                target.write_text("template now owns this\n", encoding="utf-8")
                report = self.update(next_source, expected=2)
                self.assertIn(expected, report)
                self.assertEqual(self.project_state(), before)

    def test_same_output_is_no_change(self) -> None:
        source = FIXTURES / "base-v1"
        self.create(source)
        before = self.cli("status", "--project", str(self.project))
        self.assertIn("result no-change", self.update(source))
        after = self.cli("status", "--project", str(self.project))
        self.assertEqual(before, after)

    def test_conflict_is_reported_and_preserved(self) -> None:
        v1 = self.root / "v1"
        v2 = self.root / "v2"
        v1.mkdir()
        v2.mkdir()
        (v1 / "config.txt").write_text("value=old\n", encoding="utf-8")
        (v2 / "config.txt").write_text("value=template\n", encoding="utf-8")
        self.create(v1)
        (self.project / "config.txt").write_text("value=project\n", encoding="utf-8")
        self.jj("commit", "-m", "project: edit config")
        report = self.update(v2, expected=1)
        self.assertIn("conflicts 1", report)
        self.assertIn("conflict config.txt", report)
        self.assertIn("conflicts 1", self.cli("status", "--project", str(self.project), expected=1))

    def test_path_escape_and_collision_fail_before_init(self) -> None:
        source = self.root / "unsafe"
        (source / "{{ module }}").mkdir(parents=True)
        (source / "{{ module }}" / "x.txt").write_text("x\n", encoding="utf-8")
        self.answers.write_text(json.dumps({"module": "../outside"}), encoding="utf-8")
        report = self.cli(
            "new", "--template", str(source), "--target", str(self.project),
            "--answers", str(self.answers), expected=2,
        )
        self.assertIn("unsafe output path", report)
        self.assertFalse(self.project.exists())

        self.answers.write_text(json.dumps({"module": "demo"}), encoding="utf-8")
        (source / "demo").mkdir()
        (source / "demo" / "x.txt").write_text("other\n", encoding="utf-8")
        report = self.cli(
            "new", "--template", str(source), "--target", str(self.project),
            "--answers", str(self.answers), expected=2,
        )
        self.assertIn("two template files render to", report)
        self.assertFalse(self.project.exists())

    def test_usage_exit_code(self) -> None:
        self.cli("new", expected=3)


if __name__ == "__main__":
    unittest.main()
