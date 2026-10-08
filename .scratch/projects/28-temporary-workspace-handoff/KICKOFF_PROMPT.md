# Prompt for a clean implementation session

Copy the text below the rule into a new session. Start that session in
`/home/andrew/Documents/Projects/copyroom`.

---

Implement Step 2.5 of the temporary workspace handoff, then continue into
Steps 3 to 5. Make code, test, documentation and configuration changes. Do not
stop after writing a plan.

Read these files first:

1. `AGENTS.md`, and the `copyroom`, `gitman` and `writing` skills it names.
2. `.scratch/projects/28-temporary-workspace-handoff/IMPLEMENTATION_GUIDE.md` —
   the phase order, the exact changes, and the acceptance test per phase.
3. `.scratch/projects/28-temporary-workspace-handoff/HANDOFF_DESIGN_2026-10-08.md` —
   the design and the evidence behind it. Its "current state" sections record a
   2026-10-08 investigation baseline and are historical. Find every function by
   name in the current source; never trust its line numbers.
4. `src/copyroom/local/workflow.py`, `jj.py`, `source.py`, and
   `src/copyroom/cli.py`.

## What already landed

Steps 1 and 2 are on `main`: `98d2cc7` (complete prepared result) and
`0e53915` (publication recovery journal). `copyroom update --apply` now
prepares the next marker in a temporary jj workspace and publishes that
prepared head. A journal records `prepared`, `publishing` and `published`, and
`copyroom recover` reconciles a crashed transaction.

The gate at `0e53915` is green: 98 tests passed, 0 skipped, ruff clean, and a
walkthrough that leaves nothing in the working tree. Record that baseline
before you change anything.

## Why Step 2.5 exists

A review of that landed work found 19 findings. Five are load-bearing, and all
five were reproduced:

1. **`apply` and `layer add` report success when their post-publication
   verification fails.** The checks are wrapped in `except Exception`, which
   calls `_reconcile_journal`; that function decides "published" from commit
   ancestry alone, and the command then returns success. Inject a wrong
   tracked-tree digest, a conflict, or a wrong marker digest after `jj new`
   succeeds: all three give exit 0, an empty journal directory, a removed
   preview, and `copyroom status` reporting `ok: true`.
2. **`apply` never re-runs the render-owned-path preflight.** An ignored file
   created at a render-owned path after preview survives jj's checkout, so the
   active tree diverges from the published tree. Measured: the code reached
   `LocalError('applied tree differs from the reviewed preview …')` and still
   exited 0.
3. **The ignore rules do nothing in a non-colocated jj project, and `adopt`
   does not colocate one.** jj reads `<workdir>/.git/info/exclude` only in a
   colocated repository. Adoption of a non-colocated jj repo exits 0, tracks
   `.copyroom-local/write.lock`, and then `copyroom update` fails every time
   with `active project changed during preview` and leaves a divergent working
   copy.
4. **`recover --prune` destroys a journal-less but valid preview.** Any
   `copyroom-*` jj workspace without a journal is classed an orphan, forgotten
   and `rmtree`d — including a reviewed preview with resolved conflicts, and
   including the workshop's own workspace.
5. **The reported crash matrix asserts nothing.** The harness has no assertion
   about recovery; its writer-survival booleans are computed and discarded;
   every crash point fires *after* the real jj command returns, so nothing
   crashes between the journal write and `jj new`; the competing writer runs
   after the crashed process has already exited, so no case is a race; and the
   committed evidence under `evidence/2026-10-08/crash/` has no `recover` step
   at all — it is the pre-`recover` harness.

Steps 3 to 5 add a compare-and-swap to a publication path that cannot report
its own failure. Fix the reporting first.

## Order of work

Land one gitman lane per phase. The guide gives the detail; this is the order:

- **Phase A** — record the baseline gate.
- **Phase B** — make publication verification fatal. Land this on its own.
  Every later phase needs `apply` to be able to fail.
- **Phase C** — re-run the preflight at publication, and close the hole where
  an ignored render-owned path that does not exist yet passes.
- **Phase D** — write the ignore rules where jj reads them, verify they took
  effect, and decide adoption for a non-colocated repo.
- **Phase E** — make `recover` safe and complete: no destroyed previews, a
  clearable layer journal, pending review separated from pending recovery, a
  missing preview directory handled, one bad journal survived, no pruning of
  another project's in-flight temporary.
- **Phase F** — move the crash matrix into `tests/`, add the `X0`, `X1` and
  `X1j` crash points, make the writer concurrent with a FIFO barrier, and
  assert an end state per case.
- **Phase G** — exit codes, cleanup robustness, the honest mutation count, and
  the remaining small findings.
- **Phase H** — documentation.

Then stop and report. Steps 3 to 5 depend on a user decision; see below.

## Invariants to preserve

- Run every command inside the devenv shell. It pins Python 3.13 and jj 0.43.0.
  Never invoke bare `uv`, `python`, `pytest`, `jj` or `git`.
- Exit codes are an API: `0` ok, `1` finding or decision, `2` infrastructure or
  config, `3` usage. Do not collapse them.
- `--json` carries no terminal color and no prose.
- `write_json` output is part of recorded digests. Do not change its
  serializer.
- Preparation changes no active project file and no active `@` commit.
- Publication is one active-head mutation. Say "plus a cleanup forget" when you
  mean it; `apply` adds two operations to the shared repository today.
- A preview stays until the user applies or discards it. Recovery never runs
  `jj op restore`, and never infers "nothing published" from a non-zero exit.
- Use one word for one meaning: `layer`, `mode`, `marker`, `genome`,
  `workshop`, `overlay`, `converge`.
- Write in Simplified Technical English. The rules live in the `writing` skill.

## Version control

Use gitman for every version-control action in this repository. Never run raw
`git` or `jj` here. Use plain jj only inside a disposable or managed project
repository that a test creates.

`gitman` was **not on PATH** inside or outside the devenv shell during the
review (exit 127, command not found). Check it first:

```bash
devenv shell -- bash -c 'which gitman && gitman status'
```

If it stays missing, stop and report it rather than falling back.

Check `gitman status` after shell entry and before `gitman start`. Review any
lockfile change shell entry produced. Land and push each phase's lane once its
verify step passes. Stop and ask when verify fails, when a merge conflict
appears, or when a lane touches secrets, CI configuration or a release branch.
Do not add attribution lines to commit messages.

## Gate per phase

```bash
devenv shell -- uv run pytest -q
devenv shell -- uv run ruff check src/ tests/
devenv shell -- bash demo/walkthrough.sh
```

After Phase F, also run the slow matrix:

```bash
devenv shell -- uv run pytest -q -m slow
```

No test may skip to pass. The baseline has 0 skipped tests; keep it that way.

## The decision gate before Steps 3 to 5

Phase F produces, for the first time, trustworthy evidence about the
half-applied state. The design report's §14 asks the user two questions, and
both need that evidence:

1. May CopyRoom depend on pyjutsu for the publication step?
2. Is D-A alone enough? D-A meets every underlying goal — exact reviewed tree,
   writer work always visible, no false success, recoverable crashes — and
   fails only the literal "reject before `@` moves".

**Stop after Phase H and report.** Do not start Step 3 until the user answers.
If the transiently moved `@` is acceptable, the project ends at Step 2.5.

## Facts to carry into Steps 3 to 5, when they start

These were verified on 2026-10-08. They change the design report's plan:

- **pyjutsu 0.22.0 has no `publish_if`, no `StalePublishError`, and no console
  script.** `Transaction.commit` calls jj-lib's unconditional
  `tx.commit(description)`. There is no public op-log transaction handle and no
  locking primitive. The guard exists only as
  `evidence/2026-10-08/prototype/full-diff.patch` and
  `publish_if_method.rs.txt`; the `/tmp/pj-proto-*` tree is gone. That patch is
  the only source.
- pyjutsu is **not on PyPI**. Its prebuilt wheel is cp313-abi3
  manylinux_2_39 x86-64 only; other platforms need Rust >= 1.89. It declares
  MIT but ships no LICENSE file. Add one before CopyRoom depends on it.
- **Resolve pyjutsu the way gitman does** — a GitHub release-wheel URL in
  `[tool.uv.sources]`. gitman moved off Vendomat's wheelhouse because it failed
  to resolve outside a matching Vendomat revision.
- **No jj release through 0.46.0 adds a conditional-publish primitive.** jj's
  operation log is lock-free by design; the official document states an
  operation "cannot fail to commit". Keep the devenv pin at **jj 0.43.0**. A
  version bump buys nothing for this feature.
- `sync_colocated` is mandatory in the guard, not optional. CopyRoom projects
  are colocated, and the prototype leaves git `HEAD` and the index stale.

## What to report when you stop

- The phases landed, with lane names and pushed commit ids.
- The gate output, including the slow matrix.
- Each finding closed, and each one deliberately left open, with the reason.
- Any guide detail that conflicted with tested jj, Templateer or pyjutsu
  behaviour. Record the finding, choose a safe correction, and continue.
- The two §14 questions, restated with the Phase F evidence in hand, so the
  user can answer them.
