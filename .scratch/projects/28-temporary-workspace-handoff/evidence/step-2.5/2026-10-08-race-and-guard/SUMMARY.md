# Step 2.5: publication race and cleanup guard (2026-10-08)

## Gate results (run on the working tree, not on a landed lane)

| Command | Result |
| --- | --- |
| `devenv shell -- uv run pytest -q` | exit 0, 142 passed (counted from progress dots) |
| `devenv shell -- uv run pytest -q -m slow` | exit 0, 26 passed (the crash matrix) |
| `devenv shell -- uv run ruff check src/ tests/` | exit 0, all checks passed |
| `devenv shell -- bash demo/walkthrough.sh` | exit 0, "Walkthrough complete" |

Raw logs: `pytest.log`, `pytest-slow.log`, `ruff.log`, `walkthrough.log`, `exits.txt`.
Each log starts with a devenv `MYPI_AGENT_ROOT` traceback. It comes from shell entry and does not affect the gates.

## Change

- `apply` and `layer add` save `publish_from_operation` in the journal before `jj new`.
- `_verify_published` checks that the first operation after it put the prepared head under `@`.
  A mismatch, a merge operation, a long chain, or a missing field gives a finding.
- A finding exits `1`. The journal and the preview stay. `status` and `recover` keep reporting `published but unverified`.
- `apply` now reports the `unverified` finding after a command error. It said "publication did not complete".
- The cleanup guard in `tests/integration/test_local_templateer_jj.py` uses `workflow._workspace_repo`.
- Docs: `docs/user/local-workflows.md`, Recovery section.

## Tests added or replaced

- `test_apply_refuses_success_after_a_competing_writer` and `test_layer_add_refuses_success_after_a_competing_writer`
  failed on the old code (no error raised) and pass now.
- `test_apply_command_error_after_a_competing_writer_stays_a_finding`
- `test_journal_without_a_pre_publication_operation_is_unverified`
- `test_recover_finishes_after_a_later_foreign_commit` (a later writer is not a false finding)
- `test_cleanup_guard_finds_an_owned_layer_directory`

## Known limits

- Step 2.5 detects the race. It does not prevent it. `jj new` can move `@` before CopyRoom sees the foreign operation.
- The foreign commit stays readable but leaves the active line. The user moves it back with jj.
- A foreign writer after the publishing operation is not a finding. A foreign file edit before `jj new` is a finding, because jj records a snapshot operation first.
- The crash matrix was not extended. Its cases do not cover a foreign writer at the `jj new` boundary. The integration tests cover that boundary.
- The walk is limited to 64 operations. A longer chain gives a finding.
- An old journal in `publishing` with a published head now gives a finding. Resolve it by hand.
- The crash tests do not prove power-loss durability.
- Default guarded publication (pyjutsu) belongs to Steps 3 to 5.

## Version control

Not recorded. `gitman` is not installed in this devenv shell, so no lane, head, or publication exists.
Do not treat this directory as proof of a published lane.
