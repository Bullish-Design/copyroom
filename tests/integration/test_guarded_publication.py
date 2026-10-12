"""Check publication through the pyjutsu guard in disposable projects."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from typer.testing import CliRunner

from copyroom.cli import app
from copyroom.local import workflow as workflow_module
from copyroom.local.errors import LocalError
from copyroom.local.guard import GUARD_ENV, UNGUARDED_ENV, Guard, resolve_guard
from copyroom.local.jj import JJ, resolve_jj
from copyroom.local.workflow import add_layer, apply, preview, recover, status

from . import test_local_templateer_jj as base

GUARD_MISSING = resolve_guard() is None
OLD_GUARD = Guard("/opt/pyjutsu", "0.23.0", "0.44.0")


def known_defect_while_jj_lib_is_old(test: Any) -> Any:
    """Expect failure while the installed pyjutsu embeds a jj-lib older than 0.45.

    A fixed build makes the test run as a plain check, so the expectation lifts by itself.
    """

    guard = resolve_guard()
    return unittest.expectedFailure(test) if guard and not guard.keeps_child_git_head() else test


class GuardedPublicationTests(unittest.TestCase):
    """Publish through `pyjutsu publish-if` and check each rejection."""

    setUp = base.LocalTemplateerJJTests.setUp
    tearDown = base.LocalTemplateerJJTests.tearDown
    leaked_layer_directories = base.LocalTemplateerJJTests.leaked_layer_directories
    create = base.LocalTemplateerJJTests.create
    change_template = base.LocalTemplateerJJTests.change_template
    make_docs_overlay = base.LocalTemplateerJJTests.make_docs_overlay
    prepare_update_preview = base.LocalTemplateerJJTests.prepare_update_preview

    def run_with_writer(self, writer: Any) -> None:
        """Run `writer` just before the guard call, once."""

        original = workflow_module.guard_module.publish_if
        fired: list[bool] = []

        def publish_after_writer(*args: Any, **kwargs: Any) -> Any:
            if not fired:
                fired.append(True)
                writer()
            return original(*args, **kwargs)

        self.guard_patch = patch.object(
            workflow_module.guard_module, "publish_if", publish_after_writer,
        )

    def commit_foreign_work(self, foreign: dict[str, str]) -> None:
        jj = JJ(self.project)
        (self.project / "concurrent.txt").write_text("concurrent work\n", encoding="utf-8")
        jj.run("commit", "-m", "external concurrent commit")
        foreign["commit"] = jj.commit_id("@-")
        foreign["wc"] = jj.commit_id("@")
        foreign["operation"] = jj.operation_id()

    def assert_nothing_published(self, foreign: dict[str, str]) -> None:
        jj = JJ(self.project)
        self.assertEqual(foreign["wc"], jj.commit_id("@"))
        self.assertEqual(foreign["operation"], jj.operation_id())
        self.assertEqual(
            "concurrent work\n",
            jj.run("file", "show", "-r", foreign["commit"], "concurrent.txt"),
        )
        self.assertEqual(
            foreign["commit"], jj.commit_id("::@ & " + foreign["commit"]),
        )

    @unittest.skipIf(GUARD_MISSING, "pyjutsu guard not installed")
    def test_apply_publishes_with_one_guard_call_and_no_jj_new(self) -> None:
        out = self.prepare_update_preview("guarded-happy")
        original_run = JJ.run
        new_calls: list[tuple[str, ...]] = []
        journals: list[dict[str, Any]] = []
        original_cleanup = workflow_module._cleanup_transaction

        def watch_run(jj: JJ, *args: str, **kwargs: object) -> str:
            if jj.cwd == self.project and args[:1] == ("new",):
                new_calls.append(args)
            return original_run(jj, *args, **kwargs)

        def watch_cleanup(project: Path, journal: dict[str, Any]) -> None:
            journals.append(dict(journal))
            original_cleanup(project, journal)

        with (
            patch.object(JJ, "run", watch_run),
            patch.object(workflow_module, "_cleanup_transaction", watch_cleanup),
        ):
            apply(self.project, out)

        self.assertEqual([], new_calls)
        mode = journals[0]["publish_mode"]
        self.assertTrue(mode["guard"])
        self.assertTrue(Path(mode["path"]).is_absolute())
        jj = JJ(self.project)
        self.assertEqual("", jj.run("diff", "-r", "@", "--summary"))
        self.assertEqual(journals[0]["prepared_head"], jj.commit_id("@-"))
        self.assertTrue(status(self.project)["ok"])
        self.assertFalse(out.exists())

    @unittest.skipIf(GUARD_MISSING, "pyjutsu guard not installed")
    def test_apply_rejects_before_at_moves_after_a_committed_writer(self) -> None:
        out = self.prepare_update_preview("guarded-committed")
        foreign: dict[str, str] = {}
        self.run_with_writer(lambda: self.commit_foreign_work(foreign))

        with self.guard_patch, self.assertRaises(LocalError) as raised:
            apply(self.project, out)

        self.assertEqual(1, raised.exception.code)
        self.assertIn("commit-moved", str(raised.exception))
        self.assertIn("nothing was published", str(raised.exception))
        self.assert_nothing_published(foreign)
        self.assertTrue(out.is_dir())
        journal = json.loads(
            next((self.project / ".copyroom-local/journal").glob("*.json")).read_text("utf-8"),
        )
        self.assertEqual("prepared", journal["journal_state"])
        with self.assertRaises(LocalError) as stale:
            apply(self.project, out)
        self.assertEqual(1, stale.exception.code)
        self.assertIn("active project changed after preview", str(stale.exception))
        self.assert_nothing_published(foreign)

    @unittest.skipIf(GUARD_MISSING, "pyjutsu guard not installed")
    def test_apply_rejects_before_at_moves_after_a_direct_file_edit(self) -> None:
        out = self.prepare_update_preview("guarded-direct")
        operation = JJ(self.project).operation_id()
        head = JJ(self.project).commit_id("@")
        self.run_with_writer(
            lambda: (self.project / "direct.txt").write_text("direct bytes\n", encoding="utf-8"),
        )

        with self.guard_patch, self.assertRaises(LocalError) as raised:
            apply(self.project, out)

        self.assertEqual(1, raised.exception.code)
        self.assertIn("dirty-working-copy", str(raised.exception))
        self.assertEqual("direct bytes\n", (self.project / "direct.txt").read_text("utf-8"))
        jj = JJ(self.project)
        self.assertEqual(operation, jj.operation_id())
        recorded = jj.run(
            "log", "--ignore-working-copy", "--no-graph", "-r", "@", "-T", "commit_id",
        ).strip()
        self.assertEqual(head, recorded)
        self.assertTrue(out.is_dir())

    @unittest.skipIf(GUARD_MISSING, "pyjutsu guard not installed")
    def test_layer_add_rejects_before_at_moves_after_a_committed_writer(self) -> None:
        self.create()
        overlay = self.make_docs_overlay()
        foreign: dict[str, str] = {}
        self.run_with_writer(lambda: self.commit_foreign_work(foreign))

        with self.guard_patch, self.assertRaises(LocalError) as raised:
            add_layer(self.project, overlay, overlay / "answers.json", "docs")

        journal_path = next((self.project / ".copyroom-local/journal").glob("*.json"))
        staging = Path(str(json.loads(journal_path.read_text("utf-8"))["temporary_path"]))
        try:
            self.assertEqual(1, raised.exception.code)
            self.assertIn("commit-moved", str(raised.exception))
            self.assert_nothing_published(foreign)
            report = recover(self.project)
            self.assertFalse(report["ok"])
            self.assertEqual(1, len(report["pending_recovery"]))
            self.assert_nothing_published(foreign)
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def test_apply_refuses_without_the_guard(self) -> None:
        out = self.prepare_update_preview("no-guard")
        journals_before = sorted((self.project / ".copyroom-local/journal").glob("*"))
        jj = JJ(self.project)
        operation, head = jj.operation_id(), jj.commit_id("@")

        with (
            patch.dict(os.environ, {GUARD_ENV: "/nonexistent/pyjutsu"}),
            self.assertRaises(LocalError) as raised,
        ):
            os.environ.pop(UNGUARDED_ENV, None)
            apply(self.project, out)

        self.assertEqual(2, raised.exception.code)
        self.assertIn("publication guard not found", str(raised.exception))
        self.assertIn("--publish-unguarded", str(raised.exception))
        self.assertEqual(operation, jj.operation_id())
        self.assertEqual(head, jj.commit_id("@"))
        self.assertTrue(out.is_dir())
        self.assertEqual(journals_before, sorted((self.project / ".copyroom-local/journal").glob("*")))

    def test_layer_add_refuses_without_the_guard(self) -> None:
        self.create()
        overlay = self.make_docs_overlay()
        with (
            patch.dict(os.environ, {GUARD_ENV: "/nonexistent/pyjutsu"}),
            self.assertRaises(LocalError) as raised,
        ):
            os.environ.pop(UNGUARDED_ENV, None)
            add_layer(self.project, overlay, overlay / "answers.json", "docs")

        self.assertEqual(2, raised.exception.code)
        self.assertEqual([], self.leaked_layer_directories())
        self.assertEqual([], list((self.project / ".copyroom-local/journal").glob("*.json")))

    def test_publish_unguarded_records_that_no_guard_ran(self) -> None:
        out = self.prepare_update_preview("unguarded")
        journals: list[dict[str, Any]] = []
        original_cleanup = workflow_module._cleanup_transaction

        def watch_cleanup(project: Path, journal: dict[str, Any]) -> None:
            journals.append(dict(journal))
            original_cleanup(project, journal)

        with (
            patch.dict(os.environ, {GUARD_ENV: "/nonexistent/pyjutsu"}),
            patch.object(workflow_module, "_cleanup_transaction", watch_cleanup),
        ):
            os.environ.pop(UNGUARDED_ENV, None)
            apply(self.project, out, publish_unguarded=True)

        self.assertEqual({"guard": False}, journals[0]["publish_mode"])
        self.assertTrue(status(self.project)["ok"])

    def test_cli_refuses_apply_without_the_guard_and_accepts_the_flag(self) -> None:
        out = self.prepare_update_preview("cli-flag")
        previous = Path.cwd()
        os.chdir(self.project)
        self.addCleanup(os.chdir, previous)
        runner = CliRunner()
        environment = {GUARD_ENV: "/nonexistent/pyjutsu"}
        with patch.dict(os.environ, environment):
            os.environ.pop(UNGUARDED_ENV, None)
            refused = runner.invoke(app, ["update", "--apply", str(out)])
            accepted = runner.invoke(app, ["update", "--apply", str(out), "--publish-unguarded"])

        self.assertEqual(2, refused.exit_code)
        self.assertEqual(0, accepted.exit_code, accepted.output)

    def prepare_child_preview(self, name: str) -> tuple[Path, Path]:
        """Add a colocated child workspace, as `gitman work` does, and preview an update there."""

        self.create()
        child = self.root / "child"
        JJ(self.project).run("workspace", "add", "--colocate", "--name", "child", str(child))
        template = self.source / "templates/settings/template.j2"
        template.write_text(
            template.read_text(encoding="utf-8") + f'\nrevision: "{name}"\n', encoding="utf-8",
        )
        out = self.root / f"{name}-preview"
        preview(child, out)
        return child, out

    def apply_in_child_and_keep_journal(
        self, child: Path, out: Path, **options: Any,
    ) -> dict[str, Any]:
        journals: list[dict[str, Any]] = []
        original_cleanup = workflow_module._cleanup_transaction

        def watch_cleanup(project: Path, journal: dict[str, Any]) -> None:
            journals.append(dict(journal))
            original_cleanup(project, journal)

        with patch.object(workflow_module, "_cleanup_transaction", watch_cleanup):
            apply(child, out, **options)
        return journals[0]

    def assert_child_keeps_published_commit(self, child: Path, prepared_head: str) -> None:
        """Run a plain jj command in the child and check that `@` stays on the published commit."""

        plain = subprocess.run(
            [resolve_jj(), "log", "--no-graph", "-r", "@-", "-T", "commit_id"],
            cwd=child, text=True, capture_output=True, check=False,
        )
        self.assertEqual(0, plain.returncode, plain.stderr)
        self.assertNotIn("Reset the working copy parent", plain.stderr)
        self.assertEqual(prepared_head, plain.stdout.strip())
        operations = JJ(child).run(
            "op", "log", "--ignore-working-copy", "--no-graph", "-n", "4",
            "-T", 'description ++ "\\n"',
        )
        self.assertNotIn("import git head", operations)

    @known_defect_while_jj_lib_is_old
    @unittest.skipIf(GUARD_MISSING, "pyjutsu guard not installed")
    def test_guarded_publication_in_a_colocated_child_workspace_keeps_the_published_commit(
        self,
    ) -> None:
        """Guard the pyjutsu jj-lib defect that moves `@` in a colocated child workspace.

        A jj-lib older than 0.45 ignores the per-workspace Git HEAD, and drops it from
        each operation it writes. The next jj 0.46 command in the child then imports the
        old Git HEAD and moves `@` off the published commit. jj prints no message,
        because the dropped Git HEAD looks like a first checkout. The test bypasses the
        CopyRoom refusal. It fails on pyjutsu 0.23.0 and passes on a fixed build.
        """

        child, out = self.prepare_child_preview("child-guarded")

        with patch.object(workflow_module, "is_colocated_child_workspace", lambda _: False):
            journal = self.apply_in_child_and_keep_journal(child, out)

        self.assert_child_keeps_published_commit(child, journal["prepared_head"])

    def test_apply_refuses_in_a_colocated_child_workspace_with_an_old_jj_lib(self) -> None:
        child, out = self.prepare_child_preview("child-refused")
        jj = JJ(child)
        operation, head = jj.operation_id(), jj.commit_id("@")
        journals_before = sorted((child / ".copyroom-local/journal").glob("*"))

        with (
            patch.dict(os.environ),
            patch.object(workflow_module, "resolve_guard", lambda: OLD_GUARD),
            self.assertRaises(LocalError) as raised,
        ):
            os.environ.pop(UNGUARDED_ENV, None)
            apply(child, out)

        self.assertEqual(2, raised.exception.code)
        message = str(raised.exception)
        self.assertIn("colocated child workspace", message)
        self.assertIn("jj-lib 0.44.0", message)
        self.assertIn("default workspace", message)
        self.assertIn("--publish-unguarded", message)
        self.assertEqual(operation, jj.operation_id())
        self.assertEqual(head, jj.commit_id("@"))
        self.assertTrue(out.is_dir())
        self.assertEqual(journals_before, sorted((child / ".copyroom-local/journal").glob("*")))

    def test_layer_add_refuses_in_a_colocated_child_workspace_with_an_old_jj_lib(self) -> None:
        child, _ = self.prepare_child_preview("child-layer")
        overlay = self.make_docs_overlay()
        journals_before = sorted((child / ".copyroom-local/journal").glob("*"))

        with (
            patch.dict(os.environ),
            patch.object(workflow_module, "resolve_guard", lambda: OLD_GUARD),
            self.assertRaises(LocalError) as raised,
        ):
            os.environ.pop(UNGUARDED_ENV, None)
            add_layer(child, overlay, overlay / "answers.json", "docs")

        self.assertEqual(2, raised.exception.code)
        self.assertIn("colocated child workspace", str(raised.exception))
        self.assertEqual([], self.leaked_layer_directories())
        self.assertEqual(journals_before, sorted((child / ".copyroom-local/journal").glob("*")))

    def test_cli_refuses_in_a_child_workspace_and_the_unguarded_flag_publishes(self) -> None:
        child, out = self.prepare_child_preview("child-cli")
        previous = Path.cwd()
        os.chdir(child)
        self.addCleanup(os.chdir, previous)
        runner = CliRunner()
        with patch.dict(os.environ), patch.object(workflow_module, "resolve_guard", lambda: OLD_GUARD):
            os.environ.pop(UNGUARDED_ENV, None)
            refused = runner.invoke(app, ["update", "--apply", str(out)])
            self.assertTrue(out.is_dir())
            accepted = runner.invoke(app, ["update", "--apply", str(out), "--publish-unguarded"])

        self.assertEqual(2, refused.exit_code)
        self.assertEqual(0, accepted.exit_code, accepted.output)

    def test_unguarded_publication_in_a_colocated_child_workspace_keeps_the_published_commit(
        self,
    ) -> None:
        """Check that `--publish-unguarded` is safe in a colocated child workspace.

        It runs `jj new` through the jj 0.46 CLI. That CLI writes the per-workspace Git
        HEAD, so the next command does not move `@`.
        """

        child, out = self.prepare_child_preview("child-unguarded")
        with patch.dict(os.environ, {GUARD_ENV: "/nonexistent/pyjutsu"}):
            os.environ.pop(UNGUARDED_ENV, None)
            journal = self.apply_in_child_and_keep_journal(child, out, publish_unguarded=True)

        self.assertEqual({"guard": False}, journal["publish_mode"])
        self.assert_child_keeps_published_commit(child, journal["prepared_head"])
        self.assertTrue(status(child)["ok"])


if __name__ == "__main__":
    unittest.main()
