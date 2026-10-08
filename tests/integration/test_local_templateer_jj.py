"""Exercise the local Templateer and jj workflows in disposable projects."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from copyroom.local import workflow as workflow_module
from copyroom.local.composer import compose
from copyroom.local.errors import LocalError
from copyroom.local.generation import generate, refresh
from copyroom.local.jj import JJ
from copyroom.local.manage import adopt, templatize
from copyroom.local.source import LOCK_FILE, MARKER, TEMP_EXCLUDE, TEMP_PREFIX, marker, snapshot_path
from copyroom.local.workflow import (
    add_layer,
    apply,
    discard,
    inspect,
    list_layers,
    list_previews,
    new,
    preview,
    recover,
    status,
    tracked_tree_digest,
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
        self.layer_temporary_baseline = set(
            Path(tempfile.gettempdir()).glob("copyroom-layer-*")
        )

    def leaked_layer_directories(self) -> list[Path]:
        """List new copyroom-layer-* directories whose workspace uses this project's repository."""

        project_repo = (self.project / ".jj" / "repo").resolve()
        created = set(Path(tempfile.gettempdir()).glob("copyroom-layer-*")) - self.layer_temporary_baseline
        return sorted(
            path for path in created
            if workflow_module._workspace_repo(path / "workspace") == project_repo
        )

    def tearDown(self) -> None:
        self.assertEqual([], self.leaked_layer_directories(), "test left a copyroom-layer-* directory")

    def test_cleanup_guard_finds_an_owned_layer_directory(self) -> None:
        self.create()
        leaked = Path(tempfile.gettempdir()) / f"copyroom-layer-{uuid.uuid4().hex}"
        leaked.mkdir()
        jj = JJ(self.project)
        jj.run("workspace", "add", "--name", "guard-probe", str(leaked / "workspace"))
        try:
            self.assertEqual([leaked], self.leaked_layer_directories())
        finally:
            jj.run("workspace", "forget", "guard-probe")
            shutil.rmtree(leaked, ignore_errors=True)
        self.assertEqual([], self.leaked_layer_directories())

    def create(self) -> None:
        new(self.source, self.project, self.answers)

    def change_template(self, name: str, content: str) -> None:
        path = self.source / "templates" / name / "template.j2"
        path.write_text(content, encoding="utf-8")

    def make_overlay(self, name: str = "overlay-source") -> Path:
        overlay = self.root / name
        shutil.copytree(self.source, overlay)
        manifest_path = overlay / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["templates"] = ["settings"]
        manifest["executable"] = []
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        metadata = overlay / "templates/settings/metadata.yml"
        metadata.write_text(
            metadata.read_text(encoding="utf-8").replace(
                "config/project.yml", "docs/guide.md",
            ),
            encoding="utf-8",
        )
        return overlay

    def interrupt_layer_add(self, overlay: Path) -> dict[str, object]:
        original = JJ.run

        class SimulatedCrash(BaseException):
            pass

        def stop_before_publish(jj: JJ, *args: str, **kwargs: object) -> str:
            if (
                jj.cwd == self.project
                and args[:1] == ("new",)
                and "copyroom:layer add docs" in args
            ):
                raise SimulatedCrash
            return original(jj, *args, **kwargs)

        with patch.object(JJ, "run", stop_before_publish):
            with self.assertRaises(SimulatedCrash):
                add_layer(self.project, overlay, overlay / "answers.json", "docs")

        journals = list((self.project / ".copyroom-local/journal").glob("*.json"))
        self.assertEqual(1, len(journals))
        return json.loads(journals[0].read_text(encoding="utf-8"))

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

    def test_exclude_rules_keep_preview_state_out_of_the_colocated_tree(self) -> None:
        self.create()
        self.change_template(
            "settings",
            (self.source / "templates/settings/template.j2").read_text(encoding="utf-8")
            + '\nrevision: "v2"\n',
        )

        preview(self.project, self.root / "ignored-preview")

        tracked = JJ(self.project).tracked_paths("@")
        self.assertFalse(
            [
                path for path in tracked
                if path.startswith((".copyroom-local/previews/", ".copyroom-local/journal/"))
                or path == LOCK_FILE
                or Path(path).name.startswith(TEMP_PREFIX)
            ],
        )
        self.assertIn(TEMP_EXCLUDE, (self.project / ".git/info/exclude").read_text())

    def test_preview_and_apply_refuse_tracked_local_state(self) -> None:
        self.create()
        self.change_template(
            "settings",
            (self.source / "templates/settings/template.j2").read_text(encoding="utf-8")
            + '\nrevision: "v2"\n',
        )
        out = self.root / "tracked-state-preview"
        preview(self.project, out)
        local_lock = self.project / LOCK_FILE
        local_lock.write_text("tracked by mistake\n", encoding="utf-8")
        JJ(self.project).run("file", "track", "--include-ignored", LOCK_FILE)
        JJ(self.project).run("commit", "-m", "test: track CopyRoom lock")

        for operation in (
            lambda: preview(self.project, self.root / "blocked-preview"),
            lambda: apply(self.project, out),
        ):
            with self.subTest(operation=operation):
                with self.assertRaisesRegex(LocalError, "recover --prune") as caught:
                    operation()
                self.assertEqual(2, caught.exception.code)
        self.assertTrue(out.exists())

    def test_prepared_tree_equals_applied_tree_including_marker(self) -> None:
        self.create()
        self.change_template(
            "settings",
            (self.source / "templates/settings/template.j2").read_text(encoding="utf-8")
            + '\nrevision: "v2"\n',
        )
        out = self.root / "prepared"
        state = preview(self.project, out)
        prepared_tree = tracked_tree_digest(out)
        prepared_marker = (out / ".copyroom-local.json").read_bytes()

        apply(self.project, out)

        self.assertEqual(prepared_tree, tracked_tree_digest(self.project))
        self.assertEqual(prepared_marker, (self.project / ".copyroom-local.json").read_bytes())
        self.assertEqual(state["prepared_head"], state["preview_head"])

    def test_apply_performs_one_active_head_mutation_plus_cleanup_forget(self) -> None:
        self.create()
        self.change_template(
            "settings",
            (self.source / "templates/settings/template.j2").read_text(encoding="utf-8")
            + '\nrevision: "v2"\n',
        )
        out = self.root / "single-mutation"
        state = preview(self.project, out)
        original = JJ.run
        active_mutations: list[tuple[str, ...]] = []
        mediated_calls: list[tuple[tuple[str, ...], Path]] = []
        subprocess_calls: list[tuple[tuple[str, ...], Path]] = []
        original_subprocess_run = subprocess.run
        old_marker = (self.project / MARKER).read_bytes()

        def read_only(args: tuple[str, ...]) -> bool:
            return (
                args[0] in {"log", "status", "show", "diff"}
                or args[:2] in {
                    ("file", "list"), ("op", "log"), ("workspace", "list"),
                    ("resolve", "--list"),
                }
            )

        def record(jj: JJ, *args: str, **kwargs: object) -> str:
            if jj.cwd == self.project and args and not read_only(args):
                active_mutations.append(args)
            if jj.cwd == self.project and args[:1] == ("new",) and "copyroom:update" in args:
                self.assertEqual(old_marker, (self.project / MARKER).read_bytes())
                self.assertEqual(state["active_tree"], tracked_tree_digest(self.project))
            result = original(jj, *args, **kwargs)
            mediated_calls.append((args, jj.cwd))
            return result

        def record_subprocess(command: object, *args: object, **kwargs: object):
            command_cwd = Path(str(kwargs.get("cwd", self.project)))
            if isinstance(command, (list, tuple)) and command:
                if Path(str(command[0])).name == "jj":
                    subprocess_calls.append((tuple(str(item) for item in command[1:]), command_cwd))
                elif str(command[0]) in {"bash", "sh", "zsh"}:
                    script = command[-1] if len(command) > 1 else ""
                    if "jj" in shlex.split(str(script)):
                        subprocess_calls.append((("shell", str(script)), command_cwd))
            elif isinstance(command, str):
                tokens = shlex.split(command)
                if tokens and Path(tokens[0]).name == "jj":
                    subprocess_calls.append((tuple(tokens[1:]), command_cwd))
                elif "jj" in tokens:
                    subprocess_calls.append((("shell", command), command_cwd))
            return original_subprocess_run(command, *args, **kwargs)

        with (
            patch.object(JJ, "run", record),
            patch.object(subprocess, "run", record_subprocess),
        ):
            apply(self.project, out)

        self.assertEqual(["new", "workspace"], [args[0] for args in active_mutations])
        self.assertEqual("forget", active_mutations[1][1])
        self.assertEqual(mediated_calls, subprocess_calls)

    def test_apply_does_not_write_the_marker_before_publication(self) -> None:
        self.create()
        self.change_template(
            "settings",
            (self.source / "templates/settings/template.j2").read_text(encoding="utf-8")
            + '\nrevision: "v2"\n',
        )
        out = self.root / "publication-boundary-preview"
        state = preview(self.project, out)
        old_marker = (self.project / MARKER).read_bytes()
        original = JJ.run

        def check_before_publish(jj: JJ, *args: str, **kwargs: object) -> str:
            if jj.cwd == self.project and args[:1] == ("new",) and "copyroom:update" in args:
                self.assertEqual(old_marker, (self.project / MARKER).read_bytes())
                self.assertEqual(state["active_tree"], tracked_tree_digest(self.project))
            return original(jj, *args, **kwargs)

        with patch.object(JJ, "run", check_before_publish):
            apply(self.project, out)

    def test_apply_reports_a_cleanup_failure_after_publication(self) -> None:
        self.create()
        self.change_template(
            "settings",
            (self.source / "templates/settings/template.j2").read_text(encoding="utf-8")
            + '\nrevision: "v2"\n',
        )
        out = self.root / "cleanup-failure-preview"
        preview(self.project, out)

        with (
            patch.object(
                workflow_module, "_cleanup_transaction", side_effect=OSError("cleanup failed"),
            ),
            self.assertRaises(LocalError) as raised,
        ):
            apply(self.project, out)

        self.assertEqual(1, raised.exception.code)
        self.assertIn("published; cleanup pending: cleanup failed", str(raised.exception))
        journal = next((self.project / ".copyroom-local/journal").glob("*.json"))
        self.assertEqual("published", json.loads(journal.read_text())["journal_state"])
        self.assertTrue(out.is_dir())
        recover(self.project)
        self.assertFalse(out.exists())

    def test_layer_add_reports_a_cleanup_failure_after_publication(self) -> None:
        self.create()
        overlay = self.make_overlay()

        with (
            patch.object(
                workflow_module, "_cleanup_transaction", side_effect=OSError("cleanup failed"),
            ),
            self.assertRaises(LocalError) as raised,
        ):
            add_layer(self.project, overlay, overlay / "answers.json", "docs")

        self.assertEqual(1, raised.exception.code)
        self.assertIn("published; cleanup pending: cleanup failed", str(raised.exception))
        journal_path = next((self.project / ".copyroom-local/journal").glob("*.json"))
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        temporary_path = Path(str(journal["temporary_path"]))
        self.addCleanup(lambda: shutil.rmtree(temporary_path, ignore_errors=True))
        self.assertEqual("published", journal["journal_state"])
        self.assertTrue(temporary_path.exists())
        recover(self.project)
        self.assertFalse(temporary_path.exists())

    def test_apply_reports_a_published_tree_mismatch(self) -> None:
        self.create()
        self.change_template(
            "settings",
            (self.source / "templates/settings/template.j2").read_text(encoding="utf-8")
            + '\nrevision: "v2"\n',
        )
        out = self.root / "tree-mismatch-preview"
        preview(self.project, out)
        original_run = JJ.run
        original_digest = workflow_module.tracked_tree_digest
        published = False

        def record_publish(jj: JJ, *args: str, **kwargs: object) -> str:
            nonlocal published
            result = original_run(jj, *args, **kwargs)
            if jj.cwd == self.project and args[:1] == ("new",) and "copyroom:update" in args:
                published = True
            return result

        def wrong_tree(path: Path, jj: JJ | None = None) -> str:
            digest = original_digest(path, jj)
            if published and path == self.project:
                return "wrong-tree"
            return digest

        with (
            patch.object(JJ, "run", record_publish),
            patch.object(workflow_module, "tracked_tree_digest", wrong_tree),
            self.assertRaises(LocalError) as raised,
        ):
            apply(self.project, out)

        self.assertEqual(1, raised.exception.code)
        self.assertIn("published result does not match the reviewed preview", str(raised.exception))
        journal_path = next((self.project / ".copyroom-local/journal").glob("*.json"))
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        self.assertEqual("publishing", journal["journal_state"])
        self.assertTrue(journal["verification"])
        self.assertTrue(out.is_dir())
        self.assertFalse(status(self.project)["ok"])

    def test_apply_reports_a_published_conflict(self) -> None:
        self.create()
        self.change_template(
            "settings",
            (self.source / "templates/settings/template.j2").read_text(encoding="utf-8")
            + '\nrevision: "v2"\n',
        )
        out = self.root / "conflict-mismatch-preview"
        preview(self.project, out)
        original_run = JJ.run
        original_conflicts = JJ.conflicts
        published = False
        injected = False

        def record_publish(jj: JJ, *args: str, **kwargs: object) -> str:
            nonlocal published
            result = original_run(jj, *args, **kwargs)
            if jj.cwd == self.project and args[:1] == ("new",) and "copyroom:update" in args:
                published = True
            return result

        def report_conflict(jj: JJ) -> list[str]:
            nonlocal injected
            if published and jj.cwd == self.project and not injected:
                injected = True
                return ["README.md"]
            return original_conflicts(jj)

        with (
            patch.object(JJ, "run", record_publish),
            patch.object(JJ, "conflicts", report_conflict),
            self.assertRaises(LocalError) as raised,
        ):
            apply(self.project, out)

        self.assertEqual(1, raised.exception.code)
        journal_path = next((self.project / ".copyroom-local/journal").glob("*.json"))
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        self.assertEqual("publishing", journal["journal_state"])
        self.assertIn("active project has conflicts: README.md", journal["verification"])
        self.assertTrue(out.is_dir())

    def test_apply_reports_a_published_marker_mismatch(self) -> None:
        self.create()
        self.change_template(
            "settings",
            (self.source / "templates/settings/template.j2").read_text(encoding="utf-8")
            + '\nrevision: "v2"\n',
        )
        out = self.root / "marker-mismatch-preview"
        preview(self.project, out)
        original_run = JJ.run
        original_digest = workflow_module.digest_bytes
        published = False

        def record_publish(jj: JJ, *args: str, **kwargs: object) -> str:
            nonlocal published
            result = original_run(jj, *args, **kwargs)
            if jj.cwd == self.project and args[:1] == ("new",) and "copyroom:update" in args:
                published = True
            return result

        def wrong_marker(content: bytes) -> str:
            digest = original_digest(content)
            if published and content == (self.project / ".copyroom-local.json").read_bytes():
                return "wrong-marker"
            return digest

        with (
            patch.object(JJ, "run", record_publish),
            patch.object(workflow_module, "digest_bytes", wrong_marker),
            self.assertRaises(LocalError) as raised,
        ):
            apply(self.project, out)

        self.assertEqual(1, raised.exception.code)
        journal_path = next((self.project / ".copyroom-local/journal").glob("*.json"))
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        self.assertEqual("publishing", journal["journal_state"])
        self.assertTrue(any("active marker digest" in item for item in journal["verification"]))
        self.assertTrue(out.is_dir())

    def test_layer_add_reports_a_published_tree_mismatch(self) -> None:
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
        original_run = JJ.run
        original_digest = workflow_module.tracked_tree_digest
        published = False

        def record_publish(jj: JJ, *args: str, **kwargs: object) -> str:
            nonlocal published
            result = original_run(jj, *args, **kwargs)
            if jj.cwd == self.project and args[:1] == ("new",) and "copyroom:layer add docs" in args:
                published = True
            return result

        def wrong_tree(path: Path, jj: JJ | None = None) -> str:
            digest = original_digest(path, jj)
            if published and path == self.project:
                return "wrong-tree"
            return digest

        with (
            patch.object(JJ, "run", record_publish),
            patch.object(workflow_module, "tracked_tree_digest", wrong_tree),
            self.assertRaises(LocalError) as raised,
        ):
            add_layer(self.project, overlay, overlay / "answers.json", "docs")

        self.assertEqual(1, raised.exception.code)
        self.assertIn("published result does not match the prepared layer", str(raised.exception))
        journal_path = next((self.project / ".copyroom-local/journal").glob("*.json"))
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        temporary_path = Path(str(journal["temporary_path"]))
        self.addCleanup(lambda: shutil.rmtree(temporary_path, ignore_errors=True))
        self.assertEqual("publishing", journal["journal_state"])
        self.assertTrue(journal["verification"])
        self.assertFalse(status(self.project)["ok"])
        shutil.rmtree(temporary_path)

    def test_apply_wraps_unexpected_publication_failure_as_code_two(self) -> None:
        self.create()
        self.change_template(
            "settings",
            (self.source / "templates/settings/template.j2").read_text(encoding="utf-8")
            + '\nrevision: "v2"\n',
        )
        out = self.root / "publication-error-preview"
        preview(self.project, out)
        original = JJ.run

        def fail_publish(jj: JJ, *args: str, **kwargs: object) -> str:
            if jj.cwd == self.project and args[:1] == ("new",) and "copyroom:update" in args:
                raise OSError("jj could not start")
            return original(jj, *args, **kwargs)

        with (
            patch.object(JJ, "run", fail_publish),
            self.assertRaises(LocalError) as raised,
        ):
            apply(self.project, out)

        self.assertEqual(2, raised.exception.code)
        self.assertIn("jj could not start", str(raised.exception))

    def test_status_includes_conflicts_in_ok(self) -> None:
        self.create()
        with patch.object(JJ, "conflicts", return_value=["README.md"]):
            report = status(self.project)
        self.assertTrue(report["has_conflicts"])
        self.assertFalse(report["ok"])

    def test_inspect_reports_orphan_render_layer(self) -> None:
        self.create()
        data = marker(self.project)
        base_subject = workflow_module._render_subject(
            data["project_id"], "base", data["revision"], data["source_digest"],
        )
        base_head = JJ(self.project).render_head(data["project_id"], "base")
        orphan_subject = workflow_module._render_subject(
            data["project_id"], "orphan", 0, data["source_digest"],
        )
        with patch.object(
            JJ,
            "render_heads",
            return_value=[(base_head, base_subject), ("f" * 40, orphan_subject)],
        ):
            report = inspect(self.project)
        self.assertTrue(report["layers"]["orphan"]["marker_render_mismatch"])
        self.assertIsNone(report["layers"]["orphan"]["source"])

    def test_inspect_reports_two_render_heads_for_one_layer(self) -> None:
        self.create()
        data = marker(self.project)
        base_subject = workflow_module._render_subject(
            data["project_id"], "base", data["revision"], data["source_digest"],
        )
        base_head = JJ(self.project).render_head(data["project_id"], "base")
        with patch.object(
            JJ,
            "render_heads",
            return_value=[(base_head, base_subject), ("f" * 40, base_subject)],
        ):
            report = inspect(self.project)
        self.assertTrue(report["layers"]["base"]["marker_render_mismatch"])
        self.assertEqual(2, len(report["marker_render_mismatches"][0]["render_heads"]))

    def test_tracked_paths_preserves_newline_filenames(self) -> None:
        self.create()
        name = "line\nbreak.txt"
        (self.project / name).write_text("tracked path\n", encoding="utf-8")
        JJ(self.project).run("commit", "-m", "test: track newline path")
        self.assertIn(name, JJ(self.project).tracked_paths())

    def test_recover_does_not_publish_an_unverified_result(self) -> None:
        self.create()
        self.change_template(
            "settings",
            (self.source / "templates/settings/template.j2").read_text(encoding="utf-8")
            + '\nrevision: "v2"\n',
        )
        out = self.root / "unverified-recovery-preview"
        preview(self.project, out)
        original_run = JJ.run

        class SimulatedCrash(BaseException):
            pass

        def crash_after_publish(jj: JJ, *args: str, **kwargs: object) -> str:
            result = original_run(jj, *args, **kwargs)
            if jj.cwd == self.project and args[:1] == ("new",) and "copyroom:update" in args:
                raise SimulatedCrash
            return result

        with patch.object(JJ, "run", crash_after_publish):
            with self.assertRaises(SimulatedCrash):
                apply(self.project, out)

        original_digest = workflow_module.tracked_tree_digest

        def wrong_tree(path: Path, jj: JJ | None = None) -> str:
            digest = original_digest(path, jj)
            if path == self.project:
                return "wrong-tree"
            return digest

        with patch.object(workflow_module, "tracked_tree_digest", wrong_tree):
            report = recover(self.project)

        self.assertFalse(report["ok"])
        self.assertEqual("publishing", report["transactions"][0]["journal_state"])
        self.assertIn("published but unverified", report["transactions"][0]["action"])
        self.assertTrue(out.is_dir())

    def test_ignored_project_artifact_does_not_block_apply(self) -> None:
        self.create()
        self.change_template(
            "settings",
            (self.source / "templates/settings/template.j2").read_text(encoding="utf-8")
            + '\nrevision: "v2"\n',
        )
        out = self.root / "ignored-artifact"
        preview(self.project, out)
        exclude = self.project / ".git" / "info" / "exclude"
        exclude.write_text(exclude.read_text(encoding="utf-8") + "dist/\n", encoding="utf-8")
        artifact = self.project / "dist" / "x.whl"
        artifact.parent.mkdir()
        artifact.write_bytes(b"ignored artifact")

        apply(self.project, out)

        self.assertEqual(b"ignored artifact", artifact.read_bytes())

    def test_ignored_render_owned_path_is_refused_before_preview_workspace(self) -> None:
        self.create()
        metadata = self.source / "templates/settings/metadata.yml"
        metadata.write_text(
            metadata.read_text(encoding="utf-8").replace("config/project.yml", "dist/x.whl"),
            encoding="utf-8",
        )
        exclude = self.project / ".git" / "info" / "exclude"
        exclude.write_text(exclude.read_text(encoding="utf-8") + "dist/\n", encoding="utf-8")
        ignored_path = self.project / "dist" / "x.whl"
        ignored_path.parent.mkdir()
        ignored_path.write_bytes(b"untracked ignored artifact")
        out = self.root / "ignored-render"
        workspaces_before = JJ(self.project).workspaces()
        operation_before = JJ(self.project).operation_id()
        journal_dir = self.project / ".copyroom-local" / "journal"
        journals_before = sorted(path.name for path in journal_dir.glob("*.json"))

        with self.assertRaisesRegex(LocalError, "render-owned path is not tracked by jj"):
            preview(self.project, out)

        self.assertFalse(out.exists())
        self.assertFalse(out.with_name(out.name + ".copyroom-preview.json").exists())
        self.assertEqual(workspaces_before, JJ(self.project).workspaces())
        self.assertEqual(operation_before, JJ(self.project).operation_id())
        self.assertEqual(journals_before, sorted(path.name for path in journal_dir.glob("*.json")))

    def test_preview_refuses_ignored_render_path_that_does_not_exist(self) -> None:
        self.create()
        metadata = self.source / "templates/settings/metadata.yml"
        metadata.write_text(
            metadata.read_text(encoding="utf-8").replace("config/project.yml", "dist/x.txt"),
            encoding="utf-8",
        )
        exclude = self.project / ".git" / "info" / "exclude"
        exclude.write_text(exclude.read_text(encoding="utf-8") + "dist/\n", encoding="utf-8")
        out = self.root / "ignored-absent-render"

        with self.assertRaisesRegex(LocalError, "render-owned path is ignored by this repository"):
            preview(self.project, out)

        self.assertFalse((self.project / "dist/x.txt").exists())
        self.assertFalse(out.exists())
        self.assertFalse(out.with_name(out.name + ".copyroom-preview.json").exists())
        self.assertEqual([], list_previews(self.project))

    def test_apply_refuses_ignored_render_path_created_after_preview(self) -> None:
        self.create()
        metadata = self.source / "templates/settings/metadata.yml"
        metadata.write_text(
            metadata.read_text(encoding="utf-8").replace("config/project.yml", "dist/new.txt"),
            encoding="utf-8",
        )
        out = self.root / "ignored-path-created-after-preview"
        preview(self.project, out)
        exclude = self.project / ".git" / "info" / "exclude"
        exclude.write_text(exclude.read_text(encoding="utf-8") + "dist/\n", encoding="utf-8")
        owned_path = self.project / "dist/new.txt"
        owned_path.parent.mkdir()
        owned_path.write_bytes(b"user bytes")
        operation_before = JJ(self.project).operation_id()

        with self.assertRaisesRegex(LocalError, "render-owned path is not tracked by jj") as raised:
            apply(self.project, out)

        self.assertEqual(1, raised.exception.code)
        self.assertEqual(b"user bytes", owned_path.read_bytes())
        self.assertEqual(operation_before, JJ(self.project).operation_id())
        self.assertTrue(out.is_dir())

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

    def test_mutating_commands_backfill_the_write_temporary_ignore_rule(self) -> None:
        self.create()
        exclude = self.project / ".git" / "info" / "exclude"

        def strip_rule() -> None:
            """Return the project to the state of one created before the rule existed."""

            kept = [
                line
                for line in exclude.read_text(encoding="utf-8").splitlines()
                if line != TEMP_EXCLUDE
            ]
            exclude.write_text("\n".join(kept) + "\n", encoding="utf-8")

        def rules() -> list[str]:
            return exclude.read_text(encoding="utf-8").splitlines()

        self.assertIn(TEMP_EXCLUDE, rules())

        template = self.source / "templates/settings/template.j2"
        template.write_text(
            template.read_text(encoding="utf-8") + '\nrevision: "v2"\n', encoding="utf-8",
        )
        out = self.root / "backfill"
        strip_rule()
        self.assertNotIn(TEMP_EXCLUDE, rules())
        preview(self.project, out)
        self.assertIn(TEMP_EXCLUDE, rules())

        strip_rule()
        apply(self.project, out)
        self.assertIn(TEMP_EXCLUDE, rules())

        overlay = self.root / "backfill-overlay"
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
        strip_rule()
        add_layer(self.project, overlay, overlay / "answers.json", "docs")
        self.assertIn(TEMP_EXCLUDE, rules())
        self.assertIn("docs", {str(record["layer"]) for record in list_layers(self.project)})

    def make_docs_overlay(self) -> Path:
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
        return overlay

    def race_before_publication(self, subject: str) -> dict[str, str]:
        """Return a patch target that commits foreign work just before CopyRoom runs jj new."""

        original = JJ.run
        foreign: dict[str, str] = {}

        def concurrent_run(jj: JJ, *args: str, **kwargs: object) -> str:
            if (
                jj.cwd == self.project
                and args[:1] == ("new",)
                and subject in args
                and not foreign
            ):
                (self.project / "concurrent.txt").write_text("concurrent work\n", encoding="utf-8")
                original(jj, "commit", "-m", "external concurrent commit")
                foreign["head"] = jj.commit_id("@-")
            return original(jj, *args, **kwargs)

        self.patch_run = patch.object(JJ, "run", concurrent_run)
        return foreign

    def assert_race_is_a_finding(self, foreign: dict[str, str], raised: LocalError) -> None:
        jj = JJ(self.project)
        self.assertEqual(1, raised.code)
        self.assertIn("overlapped", str(raised))
        self.assertEqual(
            "concurrent work\n",
            jj.run("file", "show", "-r", foreign["head"], "concurrent.txt"),
        )
        # CopyRoom must not report success. The foreign commit is off the active line.
        self.assertEqual("", jj.run("log", "--no-graph", "-r", f"{foreign['head']} & ::@", "-T", "commit_id"))
        journals = list((self.project / ".copyroom-local/journal").glob("*.json"))
        self.assertEqual(1, len(journals))
        journal = json.loads(journals[0].read_text(encoding="utf-8"))
        self.assertEqual("publishing", journal["journal_state"])
        self.assertTrue(journal["verification"])
        for _ in range(2):
            self.assertFalse(status(self.project)["ok"])
            self.assertTrue(status(self.project)["has_pending_publication"])
            report = recover(self.project)
            self.assertFalse(report["ok"])
            self.assertEqual(1, len(report["pending_recovery"]))
            self.assertIn("unverified", report["pending_recovery"][0]["action"])
            self.assertTrue(journals[0].is_file())

    def test_apply_refuses_success_after_a_competing_writer(self) -> None:
        self.create()
        template = self.source / "templates/settings/template.j2"
        template.write_text(
            template.read_text(encoding="utf-8") + '\nrevision: "concurrent-check"\n',
            encoding="utf-8",
        )
        out = self.root / "concurrent-preview"
        preview(self.project, out)
        foreign = self.race_before_publication("copyroom:update")

        with self.patch_run, self.assertRaises(LocalError) as raised:
            apply(self.project, out)

        self.assert_race_is_a_finding(foreign, raised.exception)
        self.assertTrue(out.is_dir())

    def test_layer_add_refuses_success_after_a_competing_writer(self) -> None:
        self.create()
        overlay = self.make_docs_overlay()
        foreign = self.race_before_publication("copyroom:layer add docs")

        with self.patch_run, self.assertRaises(LocalError) as raised:
            add_layer(self.project, overlay, overlay / "answers.json", "docs")

        # The journal keeps the staging directory as recovery state. Remove it after the checks.
        journal_path = next((self.project / ".copyroom-local/journal").glob("*.json"))
        staging = Path(str(json.loads(journal_path.read_text(encoding="utf-8"))["temporary_path"]))
        try:
            self.assert_race_is_a_finding(foreign, raised.exception)
            self.assertTrue(staging.is_dir())
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def prepare_update_preview(self, name: str) -> Path:
        self.create()
        template = self.source / "templates/settings/template.j2"
        template.write_text(
            template.read_text(encoding="utf-8") + f'\nrevision: "{name}"\n', encoding="utf-8",
        )
        out = self.root / f"{name}-preview"
        preview(self.project, out)
        return out

    def test_apply_command_error_after_a_competing_writer_stays_a_finding(self) -> None:
        out = self.prepare_update_preview("error-after-race")
        foreign = self.race_before_publication("copyroom:update")

        with self.patch_run:
            racing_run = JJ.run

            def run_then_fail(jj: JJ, *args: str, **kwargs: object) -> str:
                result = racing_run(jj, *args, **kwargs)
                if jj.cwd == self.project and args[:1] == ("new",) and "copyroom:update" in args:
                    raise LocalError("jj lost its connection")
                return result

            with patch.object(JJ, "run", run_then_fail), self.assertRaises(LocalError) as raised:
                apply(self.project, out)

        self.assertEqual(1, raised.exception.code)
        self.assertIn("unverified", str(raised.exception))
        self.assertEqual(
            "concurrent work\n",
            JJ(self.project).run("file", "show", "-r", foreign["head"], "concurrent.txt"),
        )
        self.assertFalse(recover(self.project)["ok"])
        self.assertTrue(out.is_dir())

    def test_journal_without_a_pre_publication_operation_is_unverified(self) -> None:
        out = self.prepare_update_preview("old-journal")
        original = JJ.run

        def run_then_crash(jj: JJ, *args: str, **kwargs: object) -> str:
            result = original(jj, *args, **kwargs)
            if jj.cwd == self.project and args[:1] == ("new",) and "copyroom:update" in args:
                raise KeyboardInterrupt
            return result

        with patch.object(JJ, "run", run_then_crash), self.assertRaises(KeyboardInterrupt):
            apply(self.project, out)
        # Remove the new field to mimic a journal from an earlier Step 2.5 lane.
        journal_path = next((self.project / ".copyroom-local/journal").glob("*.json"))
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        del journal["publish_from_operation"]
        journal_path.write_text(json.dumps(journal), encoding="utf-8")

        for _ in range(2):
            report = recover(self.project)
            self.assertFalse(report["ok"])
            self.assertIn("no pre-publication operation", report["pending_recovery"][0]["action"])
            self.assertTrue(journal_path.is_file())
            self.assertTrue(out.is_dir())

    def test_recover_finishes_after_a_later_foreign_commit(self) -> None:
        self.create()
        template = self.source / "templates/settings/template.j2"
        template.write_text(
            template.read_text(encoding="utf-8") + '\nrevision: "later-writer"\n',
            encoding="utf-8",
        )
        out = self.root / "later-writer-preview"
        preview(self.project, out)
        apply(self.project, out)
        (self.project / "later.txt").write_text("later work\n", encoding="utf-8")
        JJ(self.project).run("commit", "-m", "later foreign commit")

        self.assertTrue(recover(self.project)["ok"])
        self.assertTrue(status(self.project)["ok"])

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
        self.assertEqual("prepared", report["pending_previews"][0]["journal_state"])
        discard(out)
        self.assertEqual([], status(self.project)["pending_previews"])

    def test_status_and_inspect_report_marker_render_mismatch(self) -> None:
        self.create()
        old_marker = (self.project / MARKER).read_bytes()
        self.change_template(
            "settings",
            (self.source / "templates/settings/template.j2").read_text(encoding="utf-8")
            + '\nrevision: "v2"\n',
        )
        out = self.root / "mismatch-preview"
        preview(self.project, out)
        apply(self.project, out)
        (self.project / MARKER).write_bytes(old_marker)

        inspected = inspect(self.project)
        reported = status(self.project)
        self.assertTrue(inspected["has_marker_render_mismatch"])
        self.assertTrue(inspected["marker_render_mismatches"])
        self.assertTrue(reported["has_marker_render_mismatch"])
        self.assertFalse(reported["ok"])

    def test_recover_reports_prepared_update_and_keeps_preview(self) -> None:
        self.create()
        self.change_template(
            "settings",
            (self.source / "templates/settings/template.j2").read_text(encoding="utf-8")
            + '\nrevision: "v2"\n',
        )
        out = self.root / "recover-preview"
        preview(self.project, out)

        report = recover(self.project)

        self.assertTrue(report["ok"])
        self.assertEqual("prepared", report["transactions"][0]["journal_state"])
        self.assertIn("retry update --apply", report["transactions"][0]["action"])
        self.assertEqual(
            [report["transactions"][0]],
            report["pending_review"],
        )
        self.assertEqual([], report["pending_recovery"])
        self.assertTrue(out.is_dir())
        self.assertEqual(1, len(list_previews(self.project)))
        self.assertFalse(status(self.project)["has_pending_publication"])

    def test_recover_prune_backfills_a_journal_less_preview(self) -> None:
        self.create()
        self.change_template(
            "settings",
            (self.source / "templates/settings/template.j2").read_text(encoding="utf-8")
            + '\nrevision: "v2"\n',
        )
        out = self.root / "journal-less-preview"
        state = preview(self.project, out)
        journal = workflow_module._journal_path(self.project, state["workspace"])
        journal.unlink()

        report = recover(self.project, prune=True)

        self.assertTrue(report["ok"])
        self.assertTrue(journal.is_file())
        self.assertTrue(out.is_dir())
        self.assertEqual([state["workspace"]], [row["workspace"] for row in report["pending_review"]])

    def test_recover_prune_keeps_a_workshop_workspace(self) -> None:
        self.create()
        workspace = self.root / "workshop-workspace"
        JJ(self.project).run(
            "workspace", "add", "--name", "copyroom-walkthrough", "-r", "root()",
            str(workspace),
        )

        report = recover(self.project, prune=True)

        self.assertTrue(report["ok"])
        self.assertTrue(workspace.is_dir())
        self.assertIn(
            "copyroom-walkthrough", {row["name"] for row in JJ(self.project).workspaces()},
        )

    def test_recover_clears_a_dead_layer_journal_after_retry(self) -> None:
        self.create()
        overlay = self.make_overlay()
        journal = self.interrupt_layer_add(overlay)
        (self.project / "writer.txt").write_text("writer commit\n", encoding="utf-8")
        JJ(self.project).run("commit", "-m", "test: move project head")

        interrupted = recover(self.project)
        self.assertIn("retry layer add", interrupted["pending_recovery"][0]["action"])
        self.assertTrue(status(self.project)["has_pending_publication"])

        add_layer(self.project, overlay, overlay / "answers.json", "docs")
        dead_temporary = Path(str(journal["temporary_path"]))
        dead_workspace = str(journal["workspace"])
        self.assertTrue(dead_temporary.exists())
        self.assertIn(dead_workspace, {row["name"] for row in JJ(self.project).workspaces()})

        pruned = recover(self.project, prune=True)

        self.assertTrue(pruned["ok"])
        self.assertFalse(dead_temporary.exists())
        self.assertNotIn(dead_workspace, {row["name"] for row in JJ(self.project).workspaces()})
        self.assertTrue(status(self.project)["ok"])
        self.assertFalse(status(self.project)["has_pending_publication"])

    def test_recover_unlinks_a_missing_preview_workspace(self) -> None:
        self.create()
        self.change_template(
            "settings",
            (self.source / "templates/settings/template.j2").read_text(encoding="utf-8")
            + '\nrevision: "v2"\n',
        )
        out = self.root / "missing-preview"
        state = preview(self.project, out)
        shutil.rmtree(out)

        report = recover(self.project)
        self.assertFalse(report["ok"])
        self.assertIn("discard this transaction", report["pending_recovery"][0]["action"])
        self.assertEqual([state["workspace"]], [row["workspace"] for row in list_previews(self.project)])

        pruned = recover(self.project, prune=True)

        self.assertTrue(pruned["ok"])
        self.assertEqual([], list_previews(self.project))
        self.assertNotIn(state["workspace"], {row["name"] for row in JJ(self.project).workspaces()})

    def test_discard_clears_a_missing_preview_workspace(self) -> None:
        self.create()
        self.change_template(
            "settings",
            (self.source / "templates/settings/template.j2").read_text(encoding="utf-8")
            + '\nrevision: "v2"\n',
        )
        out = self.root / "discard-missing-preview"
        state = preview(self.project, out)
        shutil.rmtree(out)

        result = discard(out)

        self.assertEqual("discarded", result["result"])
        self.assertEqual([], list_previews(self.project))
        self.assertNotIn(state["workspace"], {row["name"] for row in JJ(self.project).workspaces()})

    def test_recover_reports_one_damaged_journal_and_continues(self) -> None:
        self.create()
        self.change_template(
            "settings",
            (self.source / "templates/settings/template.j2").read_text(encoding="utf-8")
            + '\nrevision: "v2"\n',
        )
        good = preview(self.project, self.root / "good-preview")
        bad = preview(self.project, self.root / "bad-preview")
        bad_path = workflow_module._journal_path(self.project, bad["workspace"])
        broken = json.loads(bad_path.read_text(encoding="utf-8"))
        broken["prepared_head"] = "f" * 40
        bad_path.write_text(json.dumps(broken), encoding="utf-8")
        orphan = self.root / "orphan-preview"
        JJ(self.project).run(
            "workspace", "add", "--name", "copyroom-000000000003", "-r", "root()",
            str(orphan),
        )

        report = recover(self.project)

        self.assertFalse(report["ok"])
        self.assertEqual(good["workspace"], report["pending_review"][0]["workspace"])
        self.assertEqual(str(bad_path), report["damaged"][0]["path"])
        self.assertEqual(str(orphan), report["orphans"]["workspaces"][0]["path"])
        self.assertTrue(bad_path.exists())
        self.assertTrue((self.root / "good-preview").is_dir())

        pruned = recover(self.project, prune=True)

        self.assertFalse(pruned["ok"])
        self.assertTrue(bad_path.exists())
        self.assertTrue((self.root / "bad-preview").is_dir())
        self.assertIn(
            bad["workspace"], {row["name"] for row in JJ(self.project).workspaces()},
        )

    def test_recover_does_not_prune_a_shared_preview_temporary(self) -> None:
        self.create()
        shared = self.root / "shared-previews"
        shared.mkdir()
        temporary = shared / ".copyroom-tmp-active-writer"
        temporary.write_text("writer has not renamed this file\n", encoding="utf-8")

        report = recover(self.project, prune=True)

        self.assertTrue(report["ok"])
        self.assertTrue(temporary.exists())
        self.assertNotIn(
            str(temporary),
            [row["path"] for row in report["orphans"]["write_temporaries"]],
        )

    def test_recover_uses_the_layer_journal_after_tmpdir_changes(self) -> None:
        self.create()
        overlay = self.make_overlay()
        journal = self.interrupt_layer_add(overlay)
        temporary_path = Path(str(journal["temporary_path"]))
        new_tmpdir = self.root / "new-tmpdir"
        new_tmpdir.mkdir()
        old_tempdir = tempfile.tempdir
        with patch.dict(os.environ, {"TMPDIR": str(new_tmpdir)}):
            tempfile.tempdir = None
            try:
                report = recover(self.project)
            finally:
                tempfile.tempdir = old_tempdir

        self.assertTrue(report["ok"])
        self.assertFalse(temporary_path.exists())

    def test_status_reports_interrupted_publication_after_prepared_head_lands(self) -> None:
        self.create()
        self.change_template(
            "settings",
            (self.source / "templates/settings/template.j2").read_text(encoding="utf-8")
            + '\nrevision: "v2"\n',
        )
        out = self.root / "crashed-apply-preview"
        preview(self.project, out)
        original = JJ.run

        class SimulatedCrash(BaseException):
            pass

        def crash_after_publish(jj: JJ, *args: str, **kwargs: object) -> str:
            result = original(jj, *args, **kwargs)
            if jj.cwd == self.project and args[:1] == ("new",) and "copyroom:update" in args:
                raise SimulatedCrash
            return result

        with patch.object(JJ, "run", crash_after_publish):
            with self.assertRaises(SimulatedCrash):
                apply(self.project, out)

        inspected = inspect(self.project)
        reported = status(self.project)
        self.assertEqual("publishing", inspected["pending_transactions"][0]["journal_state"])
        self.assertFalse(reported["has_marker_render_mismatch"])
        self.assertTrue(reported["has_pending_publication"])
        self.assertFalse(reported["ok"])

        recovered = recover(self.project)
        self.assertEqual("published", recovered["transactions"][0]["journal_state"])

    def test_recover_prunes_orphan_workspace_and_layer_directory(self) -> None:
        self.create()
        layer_root = Path(tempfile.gettempdir()) / f"copyroom-layer-{uuid.uuid4().hex}"
        workspace = layer_root / "workspace"
        workspace.mkdir(parents=True)
        JJ(self.project).run(
            "workspace", "add", "--name", "copyroom-000000000001", "-r", "root()", str(workspace),
        )

        report = recover(self.project)
        self.assertFalse(report["ok"])
        self.assertEqual("copyroom-000000000001", report["orphans"]["workspaces"][0]["name"])
        self.assertEqual(str(layer_root), report["orphans"]["layer_directories"][0]["path"])

        pruned = recover(self.project, prune=True)
        self.assertTrue(pruned["ok"])
        self.assertFalse(layer_root.exists())
        self.assertNotIn(
            "copyroom-000000000001", {row["name"] for row in JJ(self.project).workspaces()},
        )

    def test_recover_prunes_orphan_preview_workspace(self) -> None:
        self.create()
        orphan = self.root / "orphan-preview"
        JJ(self.project).run(
            "workspace", "add", "--name", "copyroom-000000000002", "-r", "root()",
            str(orphan),
        )

        report = recover(self.project)
        self.assertFalse(report["ok"])
        self.assertEqual(
            str(orphan), report["orphans"]["workspaces"][0]["path"],
        )

        pruned = recover(self.project, prune=True)
        self.assertTrue(pruned["ok"])
        self.assertFalse(orphan.exists())

    def test_recover_lists_and_prunes_ignored_json_temporaries(self) -> None:
        self.create()
        temporary = self.project / ".copyroom-tmp-interrupted-write"
        temporary.write_bytes(b"partial JSON")

        report = recover(self.project)
        self.assertFalse(report["ok"])
        self.assertEqual(str(temporary), report["orphans"]["write_temporaries"][0]["path"])
        self.assertEqual("true", report["orphans"]["write_temporaries"][0]["ignored"])
        self.assertNotIn(".copyroom-tmp-interrupted-write", JJ(self.project).tracked_paths("@"))

        pruned = recover(self.project, prune=True)
        self.assertTrue(pruned["ok"])
        self.assertFalse(temporary.exists())

    def test_recover_reports_a_negated_write_temporary_as_not_ignored(self) -> None:
        self.create()
        temporary = self.project / ".copyroom-tmp-not-ignored"
        exclude = self.project / ".git" / "info" / "exclude"
        with exclude.open("a", encoding="utf-8") as stream:
            stream.write("!/.copyroom-tmp-not-ignored\n")
        temporary.write_bytes(b"partial JSON")

        report = recover(self.project)

        self.assertIn(".copyroom-tmp-not-ignored", report["tracked_local_state"])
        self.assertEqual(
            "false", report["orphans"]["write_temporaries"][0]["ignored"],
        )

    def test_layer_add_refuses_ignored_render_path_that_does_not_exist(self) -> None:
        self.create()
        overlay = self.root / "ignored-overlay"
        shutil.copytree(self.source, overlay)
        manifest_path = overlay / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["templates"] = ["settings"]
        manifest["executable"] = []
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        metadata = overlay / "templates/settings/metadata.yml"
        metadata.write_text(
            metadata.read_text(encoding="utf-8").replace("config/project.yml", "dist/x.txt"),
            encoding="utf-8",
        )
        exclude = self.project / ".git" / "info" / "exclude"
        exclude.write_text(exclude.read_text(encoding="utf-8") + "dist/\n", encoding="utf-8")

        with self.assertRaisesRegex(LocalError, "render-owned path is ignored by this repository"):
            add_layer(self.project, overlay, overlay / "answers.json", "ignored")

        self.assertEqual(["base"], [item["layer"] for item in list_layers(self.project)])
        self.assertFalse((self.project / "dist/x.txt").exists())
        journal_dir = self.project / ".copyroom-local" / "journal"
        self.assertEqual([], list(journal_dir.glob("*.json")))

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

    def test_adopt_refuses_a_non_colocated_project(self) -> None:
        target = self.root / "non-colocated"
        target.mkdir()
        JJ(target).run("git", "init", "--no-colocate")

        with self.assertRaises(LocalError) as caught:
            adopt(
                target, self.source, self.answers, write=True,
                template_only_choice="keep",
            )

        self.assertEqual(2, caught.exception.code)
        self.assertIn("jj git init --colocate", str(caught.exception))
        self.assertFalse((target / ".git").exists())
        self.assertFalse((target / ".copyroom-local").exists())

    def test_recover_reports_and_untracks_local_state(self) -> None:
        self.create()
        local_lock = self.project / LOCK_FILE
        local_lock.parent.mkdir(parents=True, exist_ok=True)
        local_lock.write_text("tracked by mistake\n", encoding="utf-8")
        JJ(self.project).run("file", "track", "--include-ignored", LOCK_FILE)
        JJ(self.project).run("commit", "-m", "test: track CopyRoom lock")
        self.assertIn(LOCK_FILE, JJ(self.project).tracked_paths("@"))

        report = recover(self.project)
        self.assertFalse(report["ok"])
        self.assertIn(LOCK_FILE, report["tracked_local_state"])
        self.assertEqual([], report["repaired"])

        repaired = recover(self.project, prune=True)
        self.assertTrue(repaired["ok"])
        self.assertEqual(
            [{"kind": "tracked_local_state", "path": LOCK_FILE}],
            repaired["repaired"],
        )
        self.assertNotIn(LOCK_FILE, JJ(self.project).tracked_paths("@"))

    def test_exclude_local_state_uses_non_colocated_jj_store(self) -> None:
        from copyroom.local.source import exclude_local_state

        project = self.root / "non-colocated-excludes"
        project.mkdir()
        JJ(project).run("git", "init", "--no-colocate")

        exclude_local_state(project)

        self.assertFalse((project / ".git").exists())
        self.assertIn(
            TEMP_EXCLUDE,
            (project / ".jj/repo/store/git/info/exclude").read_text(encoding="utf-8"),
        )

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

    def make_workshop(self) -> Path:
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
        return workshop

    def test_update_test_reports_no_change_when_candidate_matches_source(self) -> None:
        workshop = self.make_workshop()
        template_checkout("demo", workshop)

        real_run = subprocess.run

        def fail_devenv(command: list[str], *args: object, **kwargs: object) -> object:
            if command == ["devenv", "test"]:
                raise AssertionError("devenv test must not run without a change")
            return real_run(command, *args, **kwargs)

        before = set(Path(tempfile.gettempdir()).glob("copyroom-update-demo-basic-*"))
        with patch("copyroom.local.workshop.subprocess.run", side_effect=fail_devenv):
            report = update_test("demo", "basic", workshop)
        after = set(Path(tempfile.gettempdir()).glob("copyroom-update-demo-basic-*"))

        self.assertEqual(
            {"result": "no-change", "template": "demo", "scenario": "basic"}, report,
        )
        self.assertEqual(before, after)
        template_discard(workshop)


if __name__ == "__main__":
    unittest.main()
