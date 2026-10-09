# Step 5: publish through the pyjutsu guard (2026-10-08)

Step 3 was already built and landed in pyjutsu 0.23.0 (`publish_if`, `pyjutsu publish-if`, `pyjutsu recover`).
The guide's Step 3 survey described 0.22.0 and is out of date.
This step makes CopyRoom use that guard. It was tested with a venv built from the local pyjutsu 0.23.0 wheel.

## Gate results (final tree, both modes)

| Command | Result |
| --- | --- |
| `uv run pytest -q`, no guard installed | exit 0; 154 passed, 4 skipped (the 4 guard-only tests) |
| `COPYROOM_PYJUTSU=… uv run pytest -q` | exit 0; 158 passed |
| `COPYROOM_PYJUTSU=… uv run pytest -q -m slow` | exit 0; 26 passed (crash matrix, forced unguarded) |
| `uv run ruff check src/ tests/` | exit 0 |
| `bash demo/walkthrough.sh`, no guard | exit 0 (adds `--publish-unguarded`) |
| `COPYROOM_PYJUTSU=… bash demo/walkthrough.sh` | exit 0 (publishes through the guard) |

Counts come from progress dots. Raw logs and `exits.txt` are in this directory.
An earlier run failed ruff on four import issues in files this step touched. They were fixed and every gate was rerun.

## Behavior

- `update --apply`, `apply`, and `layer add` run one `pyjutsu publish-if --expect-wc ACTIVE_HEAD --onto PREPARED_HEAD`.
- A stale result (committed writer, direct file edit) exits 1 before `@` moves. The journal returns to `prepared`.
  The preview or prepared layer stays. CopyRoom runs no jj read after the rejection, so the operation log is unchanged
  and a direct edit stays on disk.
- With no guard, apply and layer add exit 2 and name the fix. `--publish-unguarded` or `COPYROOM_PUBLISH_UNGUARDED=1` runs
  the Step 2.5 path. The journal records `publish_mode` (`{"guard": false}`, or the guard path and version).
- The guard is probed by making it fail in a known way (`result=error reason=repo-not-found`).
- `COPYROOM_PYJUTSU` and `COPYROOM_JJ` name the executables. CopyRoom spawns the resolved absolute path.
- An `incomplete` guard result runs `pyjutsu recover`, then the existing reconcile and verify.
- The Step 2.5 publication-origin check still runs after a guarded publish and passes.

## Tests added

- `tests/integration/test_guarded_publication.py` (8): happy path with no `jj new`; rejection after a committed writer
  (apply and layer add); rejection after a direct file edit; refusal without a guard (apply and layer add);
  `--publish-unguarded` record; CLI refusal and flag.
- `tests/unit/test_guard.py` (probe accept and reject cases), two `COPYROOM_JJ` tests in `tests/unit/test_jj.py`.
- 14 earlier tests that hook `jj new` now run unguarded on purpose. `tests/crash` forces the unguarded path.

## Not done, on purpose

- `manage.py` still has the `jj op restore` branch for adoption rollback. It runs only when no foreign operation occurred.
  Removing it would leave a half-adopted project. The guide asks for removal; this needs a decision.
- Read helpers do not use `--ignore-working-copy`. The guarded rejection path does not read through jj, which covers the
  rejection case. Reads can still snapshot a dirty working copy elsewhere.
- No test of the operation-fork writer class or of `op-heads-moved` (needs pyjutsu's test hooks). pyjutsu's suite covers both.
- No `pyproject.toml` pyjutsu dependency. The v0.23.0 GitHub release does not exist (latest is v0.22.0, which has no `publish-if`).
  The tag exists only in the local pyjutsu repo.
- Step 4 (Vendomat and nix-meta) is not started.

## Limits that remain (also in `docs/user/local-workflows.md`)

A direct write to a file the checkout rewrites; a late writer that forks the operation log; power loss; raw `git` in a colocated repository.
