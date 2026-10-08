# Implement Step 2.5 and Steps 3 to 5 of the temporary workspace handoff

Date: 2026-10-08.
Scope: `copyroom update --apply`, `copyroom layer add`, `copyroom recover`,
`copyroom status`, `copyroom inspect`, `copyroom adopt`, the crash harness, and
the publication guard.

Steps 1 and 2 of [HANDOFF_DESIGN_2026-10-08.md](HANDOFF_DESIGN_2026-10-08.md)
landed on `main` as `98d2cc7` and `0e53915`. A review of that work found 19
findings. This guide turns those findings into a landable order, then carries
on into the design's Steps 3 to 5.

**Read the design report first.** This guide does not repeat its analysis. It
records what the review found, what to change, and how to prove each change.

## Line numbers in this guide

Every `path:line` below comes from `main` at `0e53915` on 2026-10-08. Line
numbers move. Find each function by name before you edit it:

```bash
devenv shell -- grep -n 'def <name>' src/copyroom/local/workflow.py
```

## The one result that reorders the design's plan

The design's Step 1 promises that the applied tree equals the reviewed tree.
The shipped code checks that, then discards the result. `apply` wraps its
post-publication checks in `except Exception` (`workflow.py:1343`), calls
`_reconcile_journal`, and returns **success** when that function decides the
publish landed (`workflow.py:1350-1351`). `_reconcile_journal` decides
landedness from commit ancestry alone (`workflow.py:1071-1084`). `layer add`
repeats the shape at `workflow.py:637-645` and `:648`.

Measured: inject one failure after `jj new` succeeds — a wrong tracked-tree
digest, a non-empty `JJ.conflicts`, or a wrong marker digest. All three gave
exit 0, an empty journal directory, a removed preview, a forgotten preview
workspace, and `copyroom status` reporting `ok: true`.

Steps 3 to 5 add a compare-and-swap to a publication path that cannot report
its own failure. Fix the reporting first. That is Step 2.5.

## Rules that every phase must preserve

1. Run every command inside the devenv shell. It pins Python 3.13 and jj
   0.43.0. Never invoke bare `uv`, `python`, `pytest`, `jj` or `git`.
2. Keep the exit-code API: `0` ok, `1` finding or decision, `2` infrastructure
   or state error, `3` usage. Do not collapse them.
3. Keep `--json` free of terminal color and prose.
4. Keep the marker bytes stable. `write_json` output is part of recorded
   digests. Do not change its serializer.
5. Use one word for one meaning: `layer`, `mode`, `marker`, `genome`,
   `workshop`, `overlay`, `converge`.
6. Write in Simplified Technical English. The rules live in the `writing`
   skill.
7. Use gitman for all version control in this repository. Use plain jj only
   inside disposable or managed project repos created by a test.

## Version control

`gitman` was **not on PATH** inside or outside the devenv shell during the
review (`command not found`, exit 127). Resolve that before any lane work:

```bash
devenv shell -- bash -c 'which gitman && gitman status'
```

If it stays missing, stop and report it. Do not fall back to raw `git` or `jj`
in this repository.

Land one lane per phase. Each phase leaves the gate green:

```bash
devenv shell -- uv run pytest -q
devenv shell -- uv run ruff check src/ tests/
devenv shell -- bash demo/walkthrough.sh
```

The baseline at `0e53915` is 98 tests passed, 0 skipped, ruff clean, and a
walkthrough that leaves nothing in the working tree. Record that before you
start, so a later regression is visible.

---

# Step 2.5 — make the landed work say what it did

## Phase A — Baseline

1. Run the three gate commands. Save the output under
   `.scratch/projects/28-temporary-workspace-handoff/evidence/step-2.5/baseline/`.
2. Confirm `devenv shell -- jj --version` prints `jj 0.43.0`.
3. Confirm `gitman status` works.

No code change. This phase exists so every later claim has a reference.

## Phase B — Make publication verification fatal (finding F1)

**The defect.** A post-publication check cannot fail the command.

**The change.** Separate two questions that the code now conflates:

- *Did the publish land?* Ancestry answers this. Recovery needs it.
- *Is the published result correct?* The tree, marker, conflict and render-head
  checks answer this. The user needs it.

### B1. Add one verification helper

Add a function beside `_check_active_state` (`workflow.py:323`):

```python
def _verify_published(
    project: Path,
    jj: JJ,
    expected_head: str,
    expected_tree: str,
    expected_marker: str,
    project_id: str,
    layer: str,
    expected_render: str,
) -> list[str]:
    """List every way the published result differs from the prepared result."""
```

Return a list of plain problem strings. Return an empty list when the result
matches. Check, in this order: the parent of `@` is `expected_head`; `jj`
reports no conflicts; `tracked_tree_digest(project, jj) == expected_tree`; the
marker bytes digest equals `expected_marker`; the render head equals
`expected_render`. Raise nothing.

### B2. Use it in `apply`

In `apply` (`workflow.py:1250`), replace the raise-based block at
`workflow.py:1329-1342` with a call to `_verify_published`. Then:

- Empty list: set the journal phase to `published`, run cleanup, return the
  success dict.
- Non-empty list: **the publish landed and the result is wrong.** Write the
  problems into the journal under a new `verification` key, leave the phase at
  `publishing`, keep the preview, and raise
  `LocalError("published result does not match the reviewed preview; run copyroom recover: " + "; ".join(problems), 1)`.

Keep the `except Exception` block only for the case where `jj new` itself
raised. In that case the old behaviour is right: re-read jj state, and never
infer "nothing published" from a non-zero exit.

### B3. Teach `_reconcile_journal` the same distinction

`_reconcile_journal` (`workflow.py:1050`) must not declare `published` on
ancestry alone for `kind == "update"`. Add the verification call after the
ancestry test passes. On a non-empty problem list, return a row with
`action: "published but unverified; inspect the project"` and leave the phase
at `publishing`. Do not clean up. Do not remove the preview.

`_publish_layer_transaction` (`workflow.py:987`) already returns
`publication-uncertain; run recover again` for the same condition
(`workflow.py:1036-1043`). Keep that, and reuse `_verify_published` there so
the message names the actual problem.

### B4. Mirror the change in `layer add`

Apply B2 to `_attach_layer` (`workflow.py:637-645`, catch at `:648`).

### B5. Tests

Add to `tests/integration/test_local_templateer_jj.py`:

| Test | Asserts |
| --- | --- |
| `test_apply_reports_a_published_tree_mismatch` | Patch `tracked_tree_digest` to return a wrong value only after `jj new` returns. Assert `LocalError` code 1, the journal file still exists with `journal_state == "publishing"`, the preview directory still exists, and `copyroom status` does not report `ok: true`. |
| `test_apply_reports_a_published_conflict` | Same shape, patching `JJ.conflicts` to return one path once after publication. |
| `test_apply_reports_a_published_marker_mismatch` | Same shape, patching the marker digest once after publication. |
| `test_layer_add_reports_a_published_tree_mismatch` | The `layer add` equivalent. |
| `test_recover_does_not_publish_an_unverified_result` | Build the mismatch state, then call `recover`. Assert it reports `published but unverified`, exits 1, and removes nothing. |

Use the counting-wrapper shape already present at
`tests/integration/test_local_templateer_jj.py:118-139`, extended to fire the
injection only after the publication call returns.

**Land this phase on its own.** Every later phase needs apply to be able to
fail.

## Phase C — Re-run the preflight at publication (findings F2, F11)

**The defect.** `_preflight_paths` runs only in `preview`
(`workflow.py:743`, `:765`) and `_attach_layer` (`workflow.py:558`). `apply`
never re-checks. An ignored file created at a render-owned path **after**
preview survives jj's checkout, so the active tree diverges from the published
tree.

Measured: retarget a template output to `dist/new.txt`, run `preview`, append
`dist/` to `.git/info/exclude`, create `dist/new.txt` with user bytes, run
`apply`. The command reached
`LocalError('applied tree differs from the reviewed preview (expected 0e7d…, got c3a0…)')`
and still exited 0. The user's bytes stayed on disk, and `jj diff --stat` then
showed them as a modification of the rendered file in `@`.

### C1. Call the preflight inside `apply`'s lock

In `apply`, after the marker and render-head checks and **before**
`jj.run("new", …)` at `workflow.py:1328`, add:

```python
_preflight_paths(
    project, data, layer, dict(state["owners"]), tracked_paths=jj.tracked_paths("@"),
)
```

Exit code 1, as the preflight already raises. Do the same in
`_publish_layer_transaction` before its `jj new` (`workflow.py:1016`).

### C2. Close the absent-path hole in the preflight itself

`_preflight_paths` (`workflow.py:237-241`) guards on
`path.exists() or path.is_symlink()`. A render-owned path that does not exist
yet and is matched by an ignore rule passes. Measured: `preview` and `apply`
both succeed, the file is never written and never tracked, and the path is
still recorded as a layer owner.

Fix it where the answer is definitive. The preview workspace shares `.jj/repo`
with the active workspace, so it shares the repository's ignore rules. In
`preview`, after the render commit at `workflow.py:804-807`, compare the plan
against the preview's own tracked set:

```python
rendered = JJ(out).tracked_paths("@-")
untracked = sorted(name for name in plan.files if name not in rendered)
if untracked:
    raise LocalError(
        "render-owned path is ignored by this repository: " + ", ".join(untracked), 1,
    )
```

This catches the existing and the absent case in one test, and it needs no
extra jj call. Add the same check to `_attach_layer` after its render commit
(`workflow.py:610-613`).

### C3. Tests

| Test | Asserts |
| --- | --- |
| `test_apply_refuses_an_ignored_render_path_created_after_preview` | The C-phase reproduction. Assert exit 1, the user's bytes unchanged, and no new jj operation. |
| `test_preview_refuses_an_ignored_render_path_that_does_not_exist` | Ignore `dist/`, make the source own `dist/x.txt`, leave the file absent. Assert exit 1 from `preview`. |
| `test_ignored_render_owned_path_is_refused_before_preview_workspace` (existing, `:160`) | Strengthen it. Record `JJ(project).workspaces()`, `operation_id()`, and the file list of `.copyroom-local/journal` before the call. Assert all three unchanged and no sidecar exists. The current assertion `not out.exists()` also passes on a late failure with cleanup. |
| `test_layer_add_refuses_an_ignored_render_path` | The `layer add` equivalent. None exists today. |

## Phase D — Make the ignore rules work in every project (finding F3)

**The defect.** `exclude_local_state` (`source.py:175-190`) writes the four
rules into `<project>/.git/info/exclude`. jj reads that file only in a
colocated repository. `manage.py:146-150` runs `jj git init --colocate` only
when `.jj` is **absent**, so adopting an existing non-colocated jj repo skips
colocation.

Measured, jj 0.43.0:

- In a `jj git init --no-colocate` repo, jj ignores `<workdir>/.git/info/exclude`
  entirely. An excluded path still appears in `jj file list`.
- `.git` itself stays untracked, so the stray file is inert, not committed.
- Real `copyroom adopt` on such a repo exits 0 with `"result": "adopted"`, and
  `jj file list -r @` then includes `.copyroom-local/write.lock`.
- `copyroom update` then fails every time with
  `Error: active project changed during preview` (exit 1), because the journal
  and preview-state writes are snapshotted into `@` and move the commit id. The
  failed preview leaves the working copy divergent.
- The same flow on a colocated project passes end to end.

### D1. Resolve the right exclude file

Add to `source.py`:

```python
def _exclude_file(project: Path) -> Path | None:
    """Return the file jj reads for this repository's exclude rules."""
```

Return `project / ".git" / "info" / "exclude"` when `project / ".git"` is a
directory or a file (a worktree pointer). Otherwise return
`project / ".jj" / "repo" / "store" / "git" / "info" / "exclude"` when that
store exists. Return `None` when neither exists.

Change `exclude_local_state` to use it. **Stop creating `.git/info`
unconditionally** — the current `mkdir(parents=True, exist_ok=True)` at
`source.py:179` plants a bogus `.git` directory in a non-colocated project.

### D2. Verify the rules took effect

`exclude_local_state` is called before every JSON write in a managed project.
After it writes, assert the result once per command, not once per write. Add a
check in `preview`, `apply`, `_attach_layer` and `recover`, after
`exclude_local_state`:

```python
if MARKER_STATE_PATHS & jj.tracked_paths("@"):
    raise LocalError(
        "CopyRoom local state is tracked by jj; the exclude rules did not take "
        "effect in this repository", 2,
    )
```

Build `MARKER_STATE_PATHS` from the known prefixes
(`.copyroom-local/previews/`, `.copyroom-local/journal/`,
`.copyroom-local/write.lock`) and the `.copyroom-tmp-` prefix. Exit code 2 is
right: this is a repository-state problem the user must fix.

### D3. Repair a project that is already damaged

Adoption on a non-colocated repo already tracked `.copyroom-local/write.lock`.
Add a repair to `recover`: when a local-state path is tracked, name it and, with
`--prune`, run `jj file untrack <path>`. Report detected paths under
`tracked_local_state`; list paths untracked by `--prune` under the new
`repaired` key. Do not fail before `recover` can make this repair.

### D4. Decide adoption

Pick one and state it in the docs:

1. **Refuse** — `adopt` exits 2 on a non-colocated jj repo and names
   `jj git init --colocate` as the remediation. Smallest change, honest.
2. **Colocate** — `adopt` runs `jj git init --colocate` on an existing
   non-colocated repo.

Recommendation: ship 1 now, because D1 and D2 make the failure explicit either
way, and 2 changes a repository the user did not ask CopyRoom to change.

### D5. Tests

| Test | Asserts |
| --- | --- |
| `test_adopt_refuses_a_non_colocated_project` | Exit 2 and the remediation text. |
| `test_exclude_rules_take_effect_in_a_colocated_project` | After `preview`, no preview, journal, lock, or `.copyroom-tmp-*` path is in `jj file list -r @`. Source snapshots under `.copyroom-local/sources/` are persistent project inputs and can remain tracked. |
| `test_recover_untracks_local_state` | A project with `.copyroom-local/write.lock` tracked. Assert `recover` names it under `tracked_local_state`, and `recover --prune` untracks it and lists it under `repaired`. |
| `test_exclude_local_state_creates_no_git_directory` | On a non-colocated repo, `project / ".git"` does not exist afterwards. |

## Phase E — Make `recover` safe and complete (findings F4, F6, F7, F8, F9, F19)

### E1. Stop pruning a live preview (F4)

`workflow.py:1178-1183` classes every jj workspace whose name starts with
`copyroom-` and has no journal as an orphan. `workflow.py:1214-1222` then
forgets it and `rmtree`s its directory. `_ensure_preview_journal`
(`workflow.py:944-952`) backfills a journal only inside `apply`, so a preview
prepared by Step-1-era code qualifies.

Measured: delete the journal of a valid prepared preview, then
`recover(prune=True)`. The preview directory is gone, including any conflict
resolution done in it.

Three changes:

1. A workspace is orphan only when it has **no journal, no
   `_state_path(project, name)` and no `_preview_sidecar(path)`**. Backfill a
   journal for the rest, the way `apply` does.
2. Tighten the name test. Use `re.fullmatch(r"copyroom-[0-9a-f]{12}", name)`.
   The workshop registers `copyroom-<template_id>` (`workshop.py:393`) and
   `adopt` registers `copyroom-<uuid12>` (`manage.py:158`); the first would
   otherwise be pruned.
3. Give the prune path `_cleanup_transaction`'s safety checks
   (`workflow.py:400-427`): refuse a symlink, refuse a path inside the project,
   refuse a path that contains the project.

### E2. Clear a stuck `layer_add` journal (F6)

`_reconcile_journal` returns `project moved; keep prepared result`
(`workflow.py:1096-1098`) with no cleanup, and
`status.has_pending_publication` (`workflow.py:1545-1548`) is true for **any**
`layer_add` transaction in any state. So `status.ok` is false forever, `recover`
exits 1 forever, `--prune` does not touch it, `discard` needs a sidecar that
layer add never writes, and a successful retry never removes it.

Measured: crash layer add before `jj new`, move the project head, `recover`,
retry `add_layer` (succeeds), then `recover` and `status` both stay not-ok.

Changes:

1. When a `layer_add` journal's project head has moved and the layer now exists
   in the marker, the prepared result is dead. Name it and let `--prune` remove
   the journal, the workspace and the temporary directory.
2. When the layer does **not** exist in the marker, keep the prepared result and
   say so, with a retry instruction.
3. Narrow `has_pending_publication` to a `publishing` transaction or a prepared
   `layer_add` transaction that has a `prepared_head`. A prepared update is
   pending review, not pending publication.

### E3. Separate pending review from pending recovery (F7)

`workflow.py:1233-1236` sets `pending` for any transaction that is not
published, so an ordinary un-applied preview gives `ok: false` and exit 1
(`cli.py:263-264`). `test_recover_reports_prepared_update_and_keeps_preview`
enshrines it. Exit 1 then stops meaning "a crash was found".

Return two keys: `pending_review` (a prepared preview waiting for a human) and
`pending_recovery` (a transaction that needs action). Compute
`ok = not pending_recovery and not damaged and (prune or not has_orphans)`.
Update the existing test to assert exit 0 with `pending_review` naming the
workspace.

### E4. Handle a missing preview directory for an update (F8)

Measured: `rmtree(out)`, then `recover` twice. Both exit 1 with
`prepared; retry update --apply or discard`. `discard(out)` fails with
`preview workspace is missing`, the jj workspace stays registered, and the
recover path rewrites the state for the missing preview
(`workflow.py:1104-1105`), so `list_previews` keeps listing it.

Mirror the layer-add branch (`workflow.py:1004-1005`): when
`kind == "update"` and `workspace_path` is not a directory, report
`prepared workspace missing; discard this transaction` and let `--prune` forget
the workspace and remove the journal and state. Also make `discard` succeed
when the directory is gone but the state files remain.

### E5. Survive one bad journal (F9)

The loop at `workflow.py:1164-1170` has no per-journal guard. A missing
`prepared_head` commit makes `_is_ancestor` (`workflow.py:1074`) raise; a moved
or copied project trips the project-path check (`workflow.py:1056`). Either way
`recover` exits 2 and reports no other journal and no orphans.

Wrap each journal in a per-journal exception handler, collect failures into a
`damaged` list with the file path and the message, and carry on. Report
`damaged` in the output and count it in `ok`. The CLI has no journal selector,
so `--prune` must keep damaged journals and their workspaces. Do not infer which
damaged data the user meant to remove.

Make the temporary-directory checks `TMPDIR`-independent.
`_cleanup_transaction` requires the layer directory's parent to equal the live
`tempfile.gettempdir()` (`workflow.py:411-417`) and the orphan scan globs only
that directory (`workflow.py:1190-1192`). Trust the journal's own
`temporary_path`, and keep the safety checks that matter: the name starts with
`copyroom-layer-`, the path is not a symlink, the path is not inside the
project, and `workspace_path == temporary_path / "workspace"`.

### E6. Stop pruning another project's in-flight temporary (F19)

`_orphan_temporaries` scans the shared preview parent directories through
`direct_roots` (`workflow.py:1126-1150`). A second project writing a sidecar
into the same default `.copyroom-previews/` can lose its `.copyroom-tmp-*` file
before its `os.replace`. The CLI has no path selector. Skip external preview
parents. Scan only the project and verified temporary workspaces for this jj
repository.

Also verify the `ignored` field instead of hardcoding `"ignored": "true"`
(`workflow.py:1143`, `:1149`).

### E7. Tests

| Test | Asserts |
| --- | --- |
| `test_recover_prune_keeps_a_journal_less_preview` | A preview with a sidecar and no journal survives `--prune`, and a journal is backfilled. |
| `test_recover_prune_keeps_a_workshop_workspace` | A `copyroom-<template_id>` workspace survives `--prune`. |
| `test_recover_clears_a_dead_layer_journal` | The E2 reproduction. After `--prune`, `status.ok` is true and the temporary directory is gone. |
| `test_recover_reports_pending_review_and_exits_zero` | A normal prepared preview gives exit 0 and `pending_review`. |
| `test_recover_handles_a_missing_preview_directory` | After `rmtree(out)`, `--prune` clears the transaction and `list_previews` is empty. |
| `test_recover_reports_a_damaged_journal_and_continues` | Two journals, one with a `prepared_head` that does not exist. Assert the good one is reconciled, the bad one is in `damaged`, and the orphan report is present. `--prune` keeps the damaged journal because it cannot name one journal. |
| `test_recover_works_under_a_changed_tmpdir` | Prepare a layer transaction, change `TMPDIR`, then recover. |
| `test_recover_does_not_prune_a_shared_preview_temporary` | A temporary in a shared preview parent remains while another project runs `recover --prune`. |

## Phase F — Turn the crash matrix into an asserting test (finding F5)

**The defect.** The reported matrix — A1 to A6, L1 to L4, L0, A1w to A3w, L1w to
L3w, A1k, A3k, L1k — means "ran without a harness error", not "recovered
correctly". Verified by reading
`evidence/2026-10-08/harness/driver.py` and `harness.py`:

- **No pass criterion.** `harness.py` contains no assertion about recovery.
  `writer_check` (`harness.py:134-147`) returns booleans that `main`
  (`harness.py:237-250`) never reads. `capture` dumps state and never compares
  it. `main` catches every `Exception`, records `HARNESS ERROR`, and still ends
  with exit 0.
- **No crash lands in the window that matters.** `jj_after`
  (`driver.py:43-49`) runs the real jj command **first**, then dies. A1 and L1
  therefore fire after `jj new` has published. Nothing fires between the
  `publishing` journal write and `jj new` (`workflow.py:1326-1328`; layer add
  `:634-636`), between the `prepared` and `publishing` writes, or inside the
  `jj new` subprocess. So `_publish_layer_transaction`
  (`workflow.py:987-1047`), `project moved; keep prepared result`
  (`:1096`), the `publishing`-to-`prepared` reset (`:1090`) and
  `publication-uncertain` are never exercised.
- **The `w` cases are not races.** `second_writer` (`harness.py:125-132`) runs
  after the crashed process has exited (`harness.py:243-244`), sequentially,
  with no barrier. The writer always lands on already-published history, so
  recovery always takes the published branch.
- **The committed evidence is not the reported run.**
  `evidence/2026-10-08/crash/summary.json` has **no `recover` key for any
  case** — its steps are `retry-apply`, `discard`, `fresh-update` and
  `manual-*`, the pre-`recover` harness. No `.txt` or `.crashlog` exists for
  A4, L0, L3, L4, A2w, A3w, L2w, L3w or A3k. The run matching the current
  driver lives only under `/tmp`.
- **Kill mode.** Plain and `w` cases use `os._exit(137)` (`driver.py:30-31`),
  equivalent to SIGKILL for process state. The three `k` cases send a real
  SIGKILL (`harness.py:101-107`) at the same instruction point, after the jj
  child has exited. Process death keeps the page cache, so no case is a
  power-loss analogue.
- **Not reproducible.** `harness.py:6` hardcodes `/tmp/cr-crash-2578910`; the
  `tpl/base` and `tpl/overlay` fixtures exist only there; `main()` runs at
  import.

### F1. Move it into the suite

Create `tests/crash/test_publication_crash_matrix.py` and
`tests/crash/driver.py`. Requirements:

- Build the project from `.scratch/projects/26-templateer-jj-slice/example`,
  the fixture the integration tests already use. Copy it into `tmp_path`. No
  path outside the repository.
- Keep the driver a separate process, started with `sys.executable`, because
  the crash must kill a real process.
- Keep the monkeypatch injection. A grep of `src/` for `_exit`, `environ`,
  `getenv`, `FAULT`, `CRASH` and `inject` found nothing, so no hook can fire in
  production. Keep it that way: the driver stays in `tests/`, never in `src/`.
- Mark the full matrix `@pytest.mark.slow`, register the marker, and add
  `-m 'not slow'` to pytest's default options. This keeps the default gate near
  its current 84 s. Run the matrix with
  `devenv shell -- uv run pytest -q -m slow`.

### F2. Add the two missing crash points

| Point | Where | Why |
| --- | --- | --- |
| `X0` | after `_set_journal_phase(..., "prepared", ...)`, before the `publishing` write | A crash between two journal writes. |
| `X1` | after `_set_journal_phase(..., "publishing", ...)`, **before** `jj new` returns | The window the whole journal exists for. |

Implement `X1` by patching `_set_journal_phase` and dying on
`phase == "publishing"` — the current driver already has that hook shape at
`driver.py:57-63`, pointed at `published` instead. Add an `X1j` variant that
kills during the `jj new` subprocess: put a shim named `jj` first on `PATH`,
wait at a FIFO barrier, then `exec` the real jj.

Run each new point with and without a competing writer.

### F3. Assert an end state per case

Replace the capture-only `recover()` step. For each case assert:

1. The crash fired. The driver's `CRASH` line is present and the return code is
   `137` or `-9`. A missing hook makes the CLI run to completion and recovery
   see nothing to do, which reads as a pass today.
2. `recover` exits 0, or exits 1 with a named reason the case expects.
3. `tracked_tree_digest(project)` equals the recorded `prepared_tree`, or the
   pre-crash tree when the case must not publish.
4. The marker bytes digest equals the recorded `prepared_marker_digest`.
5. The publication commit is an ancestor of `@` when the crash point follows
   publication. A prepublication crash without a writer leaves the active tree
   unchanged.
6. A completed recovery leaves `.copyroom-local/journal/` empty.
7. A completed recovery leaves only `default` in `jj workspace list`.
8. A completed recovery removes every `copyroom-layer-*` directory.
9. A second `recover` leaves the result unchanged. It exits 0 after cleanup;
   an unverified publication keeps the same named pending result and exits 1.

Record `prepared_tree` and `prepared_marker_digest` **before** the crash. The
journal is deleted at cleanup, so those values do not survive it.

### F4. Make the writer concurrent

Use a FIFO barrier. `evidence/2026-10-08/harness/barrier_driver.py` already
demonstrates the technique against the old apply path; reuse it. The writer
must finish **inside** the crash window, while the driver process is alive.
For each `w` case assert the writer's exact README bytes, `writer-notes.txt`,
and `writer-wip.txt` bytes. For postpublication cases, assert that both the
writer commit and prepared head are ancestors of `@`. For X0w, X1w, and X1jw,
assert that the writer commit is an ancestor and that recovery keeps the
prepared preview for review; the prepared head cannot be an ancestor before
publication.

### F5. State the power-loss limit

No case is a power-loss analogue. Say so in the test module docstring, and say
that `write_json`'s fsync discipline (`source.py:54-82`) is therefore unproven.
A real test needs a crash-consistent filesystem layer such as `dm-flakey`. Do
not claim durability the harness does not prove.

### F6. Regenerate the committed evidence

The earlier capture-only evidence now lives in
`evidence/2026-10-08/crash-pre-phase-f/`. Commit the run that matches the new
test at
`evidence/step-2.5/phase-f/2026-10-08T1810Z/`. Update the design report's §3
table: the crash-point labels changed
meaning (A3 is now `workspace forget`, not "after `jj commit`"; A5 is the
state unlink; A6 is the sidecar unlink).

## Phase G — Exit codes, cleanup, and the smaller findings

### G1. Count the active mutation honestly (F10)

`apply` adds **two** operations to the shared repository: `jj new`
(`workflow.py:1328`) and `jj workspace forget` from the project cwd
(`workflow.py:431`). `test_apply_performs_one_active_working_copy_mutation`
(`tests/integration/test_local_templateer_jj.py:118`) passes only because its
filter is the allow-list `{new, commit, restore}` (`:129`).

Replace the allow-list with a deny-list of read-only verbs (`log`, `file`,
`op log`, `status`, `workspace list`, `resolve --list`, `show`, `diff`), assert
the recorded mutating calls are exactly `[("new", …), ("workspace", "forget", …)]`,
and rename the test and the claim to "one active-head mutation plus a cleanup
forget". Also patch `subprocess.run` to catch any call that bypasses `JJ.run`.

Add `test_apply_does_not_write_the_marker_before_publication`: wrap `JJ.run`
and, on the `("new", prepared_head, …)` call with the project cwd, assert the
marker bytes still equal the old marker and `tracked_tree_digest(project)`
still equals `state["active_tree"]`. Nothing asserts this today.

### G2. Report a cleanup failure as a cleanup failure (F12)

`_cleanup_transaction` sits outside the `try` in `apply`
(`workflow.py:1362-1363`), so a failing `jj workspace forget` or `rmtree`
escapes as code 2 or a raw `OSError` although `@` is already published. In
`layer add` it sits inside the `try` (`workflow.py:646-647`), so the same
failure becomes `layer add outcome is uncertain`, exit 1.

Wrap it in both places. On failure report
`published; cleanup pending: <detail>; run copyroom recover` and exit 1. A
re-run is already safe (`workflow.py:1263-1266`); only the message is wrong.

Add `test_apply_reports_a_cleanup_failure_after_publication`.

### G3. Keep the exit-code API at the boundary (F13, F18)

`cli._call` (`cli.py:50-58`) catches only `LocalError`, so a raw `OSError`,
`KeyError` or subprocess fault surfaces as a traceback. Catch `Exception` too
and exit 2 with a one-line message. Keep `LocalError`'s own code.

`workflow.py:1358-1361` wraps a plain exception as code 1. Use 2 for an
infrastructure fault.

`write_json` calls `path.parent.mkdir()` outside its `try` (`source.py:65`), so
a `PermissionError` on a read-only parent escapes as a traceback. Move it
inside. Reproduced.

### G4. Fsync a new directory's own entry (F14)

`write_json` is otherwise correct: temp file in the target directory, `fsync`,
`chmod 0644`, `os.replace`, directory `fsync`, removal on failure
(`source.py:54-82`). The gap is that `path.parent.mkdir` never fsyncs the
*parent* of a newly created `journal/` directory, so the first journal write
can vanish with the directory after power loss. When `mkdir` creates a
directory, fsync its parent. Keep `_fsync_directory`'s deliberate `OSError`
swallow (`source.py:38-49`) and keep its comment.

### G5. Tracked-tree digest limits (F15)

`tracked_tree_digest` (`workflow.py:108-129`) trusts `jj file list`. Two real
blind spots, both confirmed: jj leaves a new file above
`snapshot.max-new-file-size` (1 MiB default) untracked and prints "Refused to
snapshot some files"; and a user config with `snapshot.auto-track = none()`
hides new files. Phase C's preview check closes the render-owned case. For the
rest, add a note to `docs/user/local-workflows.md` and surface jj's "Refused to
snapshot" warning instead of discarding it in `JJ.run`.

`jj.py:49` uses `splitlines`, which breaks on a path containing a newline.
Either use `-T` with a `\0` separator, or refuse such a path at preflight.

Make `status.ok` include `has_conflicts` (`workflow.py:1551-1553`). A project
with unresolved jj conflicts reports `ok: true` today.

### G6. `status` and `inspect` reporting (F16, F17)

Detection is correct. `_marker_render_mismatches`
(`workflow.py:1416-1464`) compares the expected render subject per layer against
the visible render heads, and it covers every layer. Three gaps:

1. `status` exits 1 on a mismatch (`cli.py:240-251`) and `inspect` exits 0
   (`cli.py:230-237`). Decide and document it. `inspect` is a report command,
   so exit 0 is defensible; say so.
2. A render head for a layer the marker does not list appears in the top-level
   list with `marker_render: null` but gets no per-layer flag, because `inspect`
   loops over marker records only (`workflow.py:1496-1518`). That branch
   (`workflow.py:1457`) is uncovered. Add the per-layer entry.
3. `status` exits 1 with compact JSON on stdout and nothing on stderr. Print a
   one-line `mismatch: <layer> marker=<subject> head=<subject>` to stderr when
   it exits 1. This follows the structured plain-text report law.

Remove the dead re-assignment of `has_marker_render_mismatch` in `status`
(`workflow.py:1555`); `inspect` already sets it.

Tests to add: the `status` CLI exit code on a mismatch (`cli.py:244-250` is
uncovered), `inspect` exit 0 on a mismatch, a layer mismatch with the per-layer
flag, the orphan-layer branch, and two heads for one layer. Also add `status` to
`demo/walkthrough.sh`, which runs only `inspect --json` (`demo/walkthrough.sh:79`).

### G7. Find the test leak

One `/tmp/copyroom-layer-<32hex>` directory remained after a full `pytest` run,
with `workspace/.jj/repo` pointing at a deleted test project. It did not recur.
Find the test and make it clean up, or add an autouse fixture that fails a test
which leaves a `copyroom-layer-*` directory behind.

## Phase H — Documentation

Fix `docs/user/local-workflows.md`:

| Line | Problem |
| --- | --- |
| 44 | "`copyroom update` prints the preview path." It prints the whole preview state as compact JSON; the path is one field. |
| 78-79 | "keeps a prepared update preview when the active project has moved." Recovery keeps the preview in **every** non-published case, reporting `prepared; retry update --apply or discard`. |

Add what the new behaviour needs:

- The journal location `.copyroom-local/journal/` and its three states
  `prepared`, `publishing`, `published`.
- `recover`'s exit codes, and the Phase E split between pending review and
  pending recovery.
- That `layer add` stages in the system temporary directory as
  `copyroom-layer-*`.
- That `status` exits 1 on a mismatch or a pending publication, and `inspect`
  always exits 0.
- The new JSON field names: `marker_render_mismatches`,
  `has_pending_publication`, `pending_transactions`, `pending_previews`,
  `pending_review`, `pending_recovery`, `damaged`, `repaired`.
- That plain `update` with no change returns `no-change` and exits 0. Only
  `update-test` is documented today, at lines 196-198.
- That `update-test` exits 1 on conflicts.
- The colocation requirement from Phase D.
- The Phase G5 tracked-tree limits.

Style pass: the document mixes "render head" (line 5) and "render line"
(line 88), uses "orphan" without defining it, and runs several sentences past
20 words (lines 62-65, 78-84). Line 83 packs three ideas into one sentence.
Keep "update" and "apply" as command names; use "converge" only for the layer
concept.

## Step 2.5 exit gate

Step 2.5 is complete when all of these hold:

```bash
devenv shell -- uv run pytest -q
devenv shell -- uv run pytest -q -m slow
devenv shell -- uv run ruff check src/ tests/
devenv shell -- bash demo/walkthrough.sh
```

- The suite is green with no skipped test.
- The crash matrix asserts an end state per case, covers `X0`, `X1` and `X1j`,
  and uses a concurrent writer.
- `apply` and `layer add` exit non-zero when the published result does not match
  the reviewed result.
- An ignored render-owned path is refused at preparation and at publication.
- A non-colocated project is refused or repaired, never silently broken.
- `recover --prune` destroys no live preview, no workshop workspace and no
  in-flight temporary.
- `recover` exits 0 for a normal pending preview.
- The docs match the code.

---

# The decision gate before Steps 3 to 5

§14 of the design report asks the user one question: **may CopyRoom depend on
pyjutsu for the publication step?** It also asks a second: **is D-A alone
enough?** D-A meets every underlying goal — exact reviewed tree, writer work
always visible, no false success, recoverable crashes — and fails only the
literal "reject before `@` moves".

That second question needs the half-applied-state evidence the design wanted.
Step 2.5 Phase F produces it for the first time. **Answer the question after
Phase F, not before.** If the transiently moved `@` is acceptable, Steps 3 to 5
are unnecessary and the project ends at Step 2.5.

---

# Step 3 — the pyjutsu guard

## Verified facts that change this step

Checked against the pyjutsu repository and PyPI on 2026-10-08:

- pyjutsu is first-party: `github.com/Bullish-Design/Pyjutsu`. Current release
  **0.22.0**, tagged 2026-09-17.
- **It has no `publish_if` and no `StalePublishError`.** A grep across
  `python/`, `src/`, `docs/` and `tests/` returns nothing. `Transaction.commit`
  calls jj-lib's `tx.commit(description)` — the unconditional publish, with no
  expected-parent, expected-head or expected-operation argument. There is no
  public op-log transaction handle and no locking primitive.
- **It has no console script.** No `[project.scripts]` and no `__main__.py`.
- It is **not on PyPI**. Both `pypi.org/simple/pyjutsu/` and the JSON endpoint
  return 404.
- It binds `jj-lib = "=0.44.0"` through PyO3 and maturin, in process. The one
  escape hatch is `ws.run_jj(...)`.
- `requires-python >=3.13`, `abi3-py313`, sole runtime dependency
  `pydantic>=2.12`.
- The prebuilt wheel is
  `pyjutsu-0.22.0-cp313-abi3-manylinux_2_39_x86_64.whl` — linux x86-64,
  glibc >= 2.39. Other platforms build from the sdist and need Rust >= 1.89.
- `pyproject.toml` declares MIT, but the repository ships **no LICENSE file**
  and GitHub reports no license.

So §0 of the design report overstates the state. The guard exists only as
`evidence/2026-10-08/prototype/full-diff.patch` and
`publish_if_method.rs.txt`. The `/tmp/pj-proto-*` tree is gone. **That patch is
the only source. Port from it.**

## What to build

Follow §9.2's ordering exactly; the order is forced by jj's locking:

1. `Workspace::start_working_copy_mutation()` — take `working_copy.lock` and
   hold it for the whole method.
2. `repo_loader.load_at_head()`, then `WorkingCopyFreshness::check_stale`.
   Reject a stale working copy with `stale-working-copy`; never snapshot it.
3. `locked_wc.snapshot(...)` — **in memory only**. This publishes no operation
   and writes no state file.
4. Snapshot tree differs from the working-copy commit's tree: reject
   `dirty-working-copy` **without** snapshotting the writer's bytes into a
   commit. The writer's bytes stay on disk.
5. Working-copy commit id is not `expected_wc_commit`: reject `commit-moved`.
6. `tx.repo_mut().check_out(name, onto)`, then `rebase_descendants`.
7. `tx.write(description)` to an `UnpublishedOperation`. Record its id and
   parent ids.
8. Take `op_heads_store().lock()`; verify `get_op_heads()` equals the operation
   loaded at step 2; `update_op_heads(parent_ids, op_id)`; release. On mismatch
   reject `op-heads-moved`.
9. `locked_wc.check_out(...)`, then `locked_ws.finish(op_id)`.
10. Release `working_copy.lock`.

Three traps from §9.2, all load-bearing:

- **Never call `UnpublishedOperation::publish()`.** It takes the op-heads lock
  internally and calls `update_op_heads` with no comparison, which is the exact
  defect being fixed. Call `leave_unpublished()` to consume the `#[must_use]`
  handle, then do your own compare-and-swap.
- **Never take the op-heads lock before the working-copy lock.** jj's own order
  is working-copy then op-heads.
- **Load the repo at head after taking the working-copy lock**, not before.

Carry in all six §16.6 items, plus three this review adds:

1. **`sync_colocated` is mandatory, not optional.** CopyRoom projects are
   colocated (`workflow.py:507` runs `jj git init --colocate`). The prototype
   leaves git `HEAD` and the index at the old parent.
2. **Add the LICENSE file** before CopyRoom takes pyjutsu as a hard
   requirement.
3. **Add `[project.scripts]`**, not just `python -m`, because CopyRoom resolves
   the executable by absolute path.

Delete `src/proto_hooks.rs`. It holds FIFO barriers and the `PJ_NO_CAS` switch.
It must not ship.

## Acceptance, in pyjutsu's own suite

Keep every §13 Step 3 test. Two matter most:

- **The full race sweep.** 144 runs in the prototype, each ending in exactly one
  of the two legal outcomes and never a third.
- **The `PJ_NO_CAS` comparison.** With the compare-and-swap removed, third
  outcomes must reappear — the prototype measured 8 of 96. This is the only
  test that protects the compare-and-swap from being deleted as redundant.

Also keep: the happy path with exactly one new operation; rejection on a
committed foreign write from both a 0.43 and a 0.44 writer, with the operation
log unchanged; rejection on a direct file edit with the writer's bytes still
reachable; lock blocking; SIGKILL at each of the four §16.3 points; and
`sync_colocated` leaving git `HEAD` and the index consistent.

## On jj: no version change is warranted

Checked the changelog through **0.46.0** (2026-10-07) against the pinned
**0.43.0**. Nothing adds conditional publication:

- `--at-op` forks the operation log rather than asserting a precondition.
- `--no-integrate-operation` (0.41.0) is prepare-then-publish, still
  unconditional.
- 0.45.0 made git `HEAD` per-worktree and changed `update-stale` for colocated
  repos. 0.46.0 added `workspace remove`, `workspace add --colocate`, and
  cross-workspace `undo`/`redo`. None is a compare-and-swap.
- The official concurrency document states the design goal directly: an
  operation "cannot fail to commit". The primitive is absent by intent.

**Keep jj 0.43.0.** The one real alignment argument is matching pyjutsu's
`jj-lib = "=0.44.0"`, and the design report already tested those two on-disk
formats as compatible in both directions. Treat that as Step 6, not a blocker.

---

# Step 4 — distribute the guard

Bump the Vendomat and nix-meta pins as §10.1 says. One correction to the plan:

**Resolve pyjutsu the way gitman already does** — a GitHub release-wheel URL in
`[tool.uv.sources]`:

```toml
[tool.uv.sources]
pyjutsu = { url = "https://github.com/Bullish-Design/Pyjutsu/releases/download/v<TAG>/pyjutsu-<TAG>-cp313-abi3-manylinux_2_39_x86_64.whl" }
```

gitman moved **off** Vendomat's wheelhouse because it failed to resolve in a
repository not wired to the same Vendomat revision. CopyRoom has no pyjutsu
entry today, and its `[tool.uv.sources]` holds only a templateer path source.
Vendomat stays the distribution route for the system toolchain; it is not the
resolution route for CopyRoom's own lock.

State the platform limit in the docs: the prebuilt wheel is linux x86-64 with
glibc >= 2.39. Any other platform needs Rust >= 1.89 to build the sdist.

Acceptance, unchanged from §10.1: `nix eval .#packages.x86_64-linux.pyjutsu.outPath`
changes and builds; `share/vendomat/toolchain.json` records the new version; a
clean login shell resolves the entry point by absolute path; Vendomat's
`checks.<system>.vendomat-consumer-module` still passes.

---

# Step 5 — use the guard

Changes 4, 6, 8, 10 and 12 of §12, plus two that Step 2.5 makes necessary.

1. **Replace the publication block with one guarded call** (`workflow.py:1328`,
   `workflow.py:636`):
   `pyjutsu publish-if --repo <project> --expect-wc <H> --onto <P> -m <desc>`.
   - Exit 1, stale: nothing mutated, the preview kept, the message names the
     observed `@`.
   - Exit 0: `@` is an empty child of `P`, and the active tree including the
     marker equals the reviewed tree.
2. **Keep the Phase B verification fatal.** A stale rejection stays exit 1 with
   nothing mutated. A landed-but-unverified publish stays exit 1 and leaves the
   journal at `publishing`.
3. **Keep the Phase C preflight inside the guard region.** The §16.4 data-loss
   case — a file the checkout rewrites — is irreducible in jj. The preflight is
   what keeps a render-owned path out of that class.
4. **Use `--ignore-working-copy` on all read helpers** (`jj.py:37-110`), and
   snapshot exactly once, inside the guard. Reads currently mutate the
   repository and can make a preview stale.
5. **Resolve jj and pyjutsu once by absolute path** from `COPYROOM_JJ` and
   `COPYROOM_PYJUTSU`. `jj.py:25-28` calls `shutil.which("jj")` only as an
   existence test, then spawns `["jj", ...]`, which resolves the bare name
   again.
6. **Delete the `jj op restore` branch.** The update and layer paths no longer
   have one. `manage.py:197` still does, guarded by an operation-id check;
   remove it there too. Never infer "nothing published" from a non-zero exit.
7. **Add the capability probe and `--publish-unguarded`.** With the guard
   absent, `update --apply` exits 2 and names the remediation.
   `--publish-unguarded` exits 0 and records `"guard": false`.

## Acceptance

- Every Step 2.5 test still passes.
- `test_apply_rejects_before_at_moves` — barrier at the pre-publication point,
  release a committed foreign writer, assert exit 1 **and** `@` unchanged
  **and** no new operation published. The current code fails this in 35 of 35
  runs.
- The same test for each §2.4 writer class, including the two direct-write
  classes and the operation fork.
- `test_no_silent_success_window` — barrier at the former window; assert it no
  longer exists.
- `test_refuses_without_capability` and the `--publish-unguarded` path.
- `layer add` gets the same matrix.

## What Step 5 still does not promise

State all four limits in the docs. None is fixable here:

1. A direct file write that lands inside the checkout phase. A new file, an
   untouched file and a path the checkout *adds* all survive. **A file the
   checkout rewrites is silently overwritten**, and `jj status` then reports a
   clean working copy. Lost in stock jj for any `jj new`.
2. An operation-graph fork by a writer that had already loaded the previous
   operation. It publishes afterwards and jj merges; its content stays visible,
   its `@` move does not.
3. Durability against power loss. jj does not fsync the operation head file or
   any directory.
4. A raw colocated `git` write. The jj CLI takes `git_import_export.lock`;
   pyjutsu does not. This gap exists today, independent of this work.

Rollback: `--publish-unguarded` restores Step 2.5 behaviour without a redeploy.

---

# Appendix — findings to phase map

| # | Finding | Severity | Phase |
| --- | --- | --- | --- |
| F1 | Post-publication verification can never fail the command | Critical | B |
| F2 | `apply` has no apply-time preflight; an ignored render path diverges the tree | High | C |
| F3 | Ignore rules do nothing in a non-colocated jj project; `adopt` does not colocate | High | D |
| F4 | `recover --prune` destroys a journal-less but valid preview | High | E1 |
| F5 | The crash matrix asserts nothing and misses the dangerous windows | High | F |
| F6 | A stuck `layer_add` journal makes `status` and `recover` permanently not-ok | Medium | E2 |
| F7 | `recover` reports a normal pending preview as a failure | Medium | E3 |
| F8 | An update whose preview directory was deleted cannot be cleared | Medium | E4 |
| F9 | One bad journal aborts the whole `recover` | Medium | E5 |
| F10 | "One active jj mutation" is false as worded | Medium | G1 |
| F11 | Preflight only fires for a path that already exists | Low/Medium | C2 |
| F12 | Cleanup after publication can turn a success into an error | Low | G2 |
| F13 | Non-`LocalError` exceptions escape as tracebacks | Low | G3 |
| F14 | A new directory's own entry is never fsynced | Low | G4 |
| F15 | Tracked-tree digest false negatives; `status.ok` ignores conflicts | Low | G5 |
| F16 | `inspect` exits 0 on a mismatch while `status` exits 1 | Low/Medium | G6 |
| F17 | An orphan render head gets no per-layer flag | Low | G6 |
| F18 | `write_json` `mkdir` outside its `try` | Low | G3 |
| F19 | `recover --prune` can delete another project's in-flight temporary | Low | E6 |

## What the review confirmed as sound

Do not re-litigate these. They are supported by code reading and by a green
gate of 98 tests, 0 skipped, ruff clean, and a walkthrough that leaves nothing
behind:

- The preview commits the exact next marker bytes. One serializer
  (`source.py:64`), written at `workflow.py:822`, committed at `:824`.
- `apply` and `layer add` never write the marker in the active workspace. Only
  four marker writes exist, and none targets the active project during
  publication.
- `apply` compares jj-tracked trees, not the raw working directory.
  `working_digest` survives only in `inspect` and `adopt`.
- The journal is written before the mutation it describes, and unlinked last. A
  lost `published` is harmless, because recovery re-derives the truth from jj
  ancestry.
- No `op restore` or `undo` runs in the recover path.
- `write_json` is atomic: temp file in the target directory, fsync, chmod,
  `os.replace`, directory fsync, removal on failure.
- Marker-versus-render-head detection is correct and covers every layer.
- `--version`, the default preview path, relative `..` paths, and
  `update-test` no-change all work.
