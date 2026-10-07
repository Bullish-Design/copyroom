"""Prove current handoff limits with real jj processes and barriers."""

from __future__ import annotations

import unittest

from harness import (
    run_clean_apply,
    run_interleaving,
    run_source_edit_after_preview,
    run_writer_before_preparation,
    run_writer_during_active_update,
)


class TemporaryWorkspaceHandoffTests(unittest.TestCase):
    """Keep the concurrency evidence repeatable without mocking jj calls."""

    def test_prepared_workspace_does_not_hold_the_updated_marker(self) -> None:
        result = run_clean_apply()
        self.assertEqual(
            result["active_before"]["tree_digest"],
            result["active_during_preview"]["tree_digest"],
        )
        self.assertEqual(
            result["active_before"]["marker_hex"],
            result["active_during_preview"]["marker_hex"],
        )
        self.assertEqual(result["active_before"]["marker_hex"], result["prepared_marker_hex"])
        self.assertNotEqual(result["prepared_marker_hex"], result["active_marker_after_hex"])
        self.assertNotEqual(result["preview_tree_digest"], result["active_after"]["tree_digest"])

    def test_apply_uses_the_reviewed_render_after_source_changes(self) -> None:
        result = run_source_edit_after_preview()
        self.assertNotEqual(result["source_digest_before"], result["source_digest_after"])
        self.assertTrue(result["reviewed_files_equal_active_files"])

    def test_writer_before_preparation_becomes_the_preview_parent(self) -> None:
        result = run_writer_before_preparation()
        self.assertEqual(result["competitor"]["commit"], result["preview_state"]["active_head"])
        self.assertEqual(result["active_before"]["head"], result["active_after"]["head"])
        self.assertEqual(result["active_before"]["tree_digest"], result["active_after"]["tree_digest"])
        self.assertIn("before-preparation.txt", result["preview_workspace"]["files"])

    def test_stale_project_before_apply_keeps_writer_and_preview(self) -> None:
        result = run_interleaving("before-apply")
        self.assertEqual(1, result["result"]["code"])
        self.assertEqual(result["competitor"]["commit"], result["active_after"]["head"])
        self.assertTrue(result["preview_kept"])
        self.assertIn("before-apply.txt", result["active_after"]["files"])

    def test_writer_during_preview_keeps_active_writer_and_refuses_preview(self) -> None:
        result = run_interleaving("preview-during-preparation")
        self.assertEqual(2, result["returncode"])
        self.assertEqual(result["competitor"]["commit"], result["active_after"]["head"])
        self.assertIn("during-preview.txt", result["active_after"]["files"])
        self.assertFalse(result["preview_exists"])

    def test_bookmark_writer_at_handoff_moves_active_workspace_before_refusal(self) -> None:
        result = run_interleaving("bookmark-at-handoff")
        self.assertEqual(1, result["result"]["code"])
        self.assertTrue(result["competitor_commit_visible"])
        self.assertNotEqual(result["competitor"]["commit"], result["active_after"]["head"])
        self.assertIn("external-writer", result["bookmarks_after"])
        self.assertNotEqual(result["competitor_state_before_release"]["operation_id"],
                            result["active_after"]["operation_id"])
        self.assertTrue(result["preview_kept"])

    def test_bookmark_change_since_preview_is_not_rejected_as_stale(self) -> None:
        result = run_interleaving("bookmark-before-apply")
        self.assertNotEqual(result["operation_before_writer"], result["competitor"]["operation_id"])
        self.assertNotIn("active_operation", result["preview_state"])
        self.assertEqual(0, result["copyroom_exit_code"])
        self.assertTrue(result["result"]["ok"])
        self.assertIn("before-apply-writer", result["bookmarks_after"])

    def test_writer_at_handoff_is_reported_but_active_workspace_moves(self) -> None:
        result = run_interleaving("before-handoff")
        self.assertEqual(1, result["result"]["code"])
        self.assertTrue(result["competitor_commit_visible"])
        self.assertNotEqual(result["competitor"]["commit"], result["active_after"]["head"])
        self.assertTrue(result["preview_kept"])
        self.assertEqual(result["competitor"]["commit"], result["recovery_active"]["head"])

    def test_writer_after_jj_new_is_preserved_and_apply_refuses(self) -> None:
        result = run_interleaving("after-new")
        self.assertEqual(1, result["result"]["code"])
        self.assertEqual(result["competitor"]["commit"], result["active_after"]["head"])
        self.assertTrue(result["preview_kept"])

    def test_filesystem_writer_during_jj_checkout_survives_and_apply_refuses(self) -> None:
        result = run_writer_during_active_update()
        self.assertTrue(result["target_had_prepared_bytes_before_writer"])
        self.assertTrue(result["writer_during_real_jj_new"])
        self.assertTrue(result["writer_finished_while_real_jj_new_running"])
        self.assertTrue(result["writer_bytes_survived"])
        self.assertEqual(1, result["copyroom_exit_code"])
        self.assertFalse(result["result"]["ok"])
        self.assertTrue(result["preview_kept"])

    def test_uncommitted_writer_is_not_in_the_active_tree_after_gap(self) -> None:
        result = run_interleaving("uncommitted-at-handoff")
        self.assertEqual(1, result["result"]["code"])
        self.assertNotIn("uncommitted.txt", result["active_after"]["files"])
        self.assertTrue(result["preview_kept"])
        self.assertTrue(result["uncommitted_snapshot"]["workspace_head"])
        self.assertEqual(
            ["jj", "edit", result["uncommitted_snapshot"]["workspace_head"]],
            result["recovery_command"],
        )
        self.assertIn("uncommitted.txt", result["recovery_active"]["files"])

    def test_writer_after_handoff_checks_can_still_get_success(self) -> None:
        result = run_interleaving("before-cleanup")
        self.assertTrue(result["result"]["ok"])
        self.assertEqual(0, result["returncode"])
        self.assertEqual(result["competitor"]["commit"], result["active_after"]["head"])
        self.assertIn("after-handoff.txt", result["active_after"]["files"])

    def test_writer_after_marker_commit_can_get_success(self) -> None:
        result = run_interleaving("after-marker-commit")
        self.assertEqual(0, result["returncode"])
        self.assertTrue(result["result"]["ok"])
        self.assertEqual(result["competitor"]["commit"], result["active_after"]["head"])
        self.assertFalse(result["preview_kept"])

    def test_layer_add_detects_a_stale_workspace_without_a_stale_decision(self) -> None:
        result = run_interleaving("layer-add-during-preparation")
        self.assertEqual(2, result["returncode"])
        self.assertIn("working copy is stale", result["result"]["error"])
        self.assertEqual(result["competitor"]["commit"], result["active_after"]["head"])
        self.assertNotIn("docs", result["active_after"]["marker"]["layers"])


if __name__ == "__main__":
    unittest.main()
