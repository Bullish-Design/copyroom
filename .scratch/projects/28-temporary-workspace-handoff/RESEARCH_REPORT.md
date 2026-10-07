# Research report: temporary workspace handoff

Date: 2026-10-07

## Decision

Do not change the CopyRoom runtime in this spike. The pinned jj command-line
interface (CLI) has no conditional workspace handoff. CopyRoom can check the
active project before and after `jj new`, but another process can write between
those commands. The real-process tests also show a race after CopyRoom's last
check where apply reports success after another jj writer commits.

The current preview workspace is not the complete result. It contains the new
render and any new source snapshot, but it keeps the old project marker. Apply
writes the new marker into the active project after it changes `@`.

The product decision is whether CopyRoom may require every project writer to
cooperate with one write lock. If the product must support arbitrary plain jj
writers in the active project, keep apply blocked until CopyRoom has a writer
protocol that can protect both jj state and direct file writes. jj 0.43.0 does
not provide that protocol. Preview state also omits the active operation ID.
A bookmark-only operation after preview does not change the head or tree, so
apply accepts that stale preview and reports success.

## Starting state

I ran `gitman status --json` inside the CopyRoom devenv before relying on the
provided commit. Gitman reported lane `templateer-jj-local` at
`408fcad000f12cfc290800708847cecda71a080e`. The lane was canonical and
published. Trunk was `main` at `4fbcb24ef71c741d738bf4fde36102debaa45942`, in
sync with `origin`. Gitman reported no foreign paths or anomalies.

Gitman also reported two tracked, ignored files in project 26:
`.python-version` and `devenv.lock`. I kept them unchanged. The status report
listed 118 files in the published lane change. This spike adds files under this
project 28 directory only.

The requested `src/copyroom/local/models.py` does not exist. Marker validation
and source snapshots are in `source.py`. Preview state and apply logic are in
`workflow.py`.

Before publication, I checked the lane again with `gitman status --json` and
`gitman log --revset 'main..templateer-jj-local'`. The live lane had advanced
from the initial `408fcad...` check to published head
`3dbd3aa7c31e97484c2894168bc561ff76099169`. I kept that head as the base. The
lane remains canonical, trunk remains in sync with origin, and the lane log has
one existing change. Gitman listed only this project 28 directory as foreign
active work. It still listed the two tracked, ignored project 26 files; I kept
them unchanged.

Later status calls saved the spike files into the same lane change. The final
pre-describe status remained canonical, with trunk in sync and no foreign paths
or off-canonical state. I reviewed the 11 project 28 files and the one existing
lane change before publication. Gitman still listed the two ignored project 26
files; I kept them unchanged.

## Environment and source basis

The current root devenv supplied Python 3.13.14 and `jj 0.43.0`. Project 26
recorded jj 0.45.1 for its earlier nested devenv. All experiments in this
report use the current root version, 0.43.0. The harness records the version
for each fresh run. No model-provider call ran.

The relevant implementation is in
[`workflow.py`](../../../src/copyroom/local/workflow.py): the operation guard
starts at line 250, layer attach at line 362, preview at line 506, apply at
line 654, and preview listing at line 799. The process lock is in
[`jj.py`](../../../src/copyroom/local/jj.py#L86). Atomic JSON replacement and
source snapshots are in
[`source.py`](../../../src/copyroom/local/source.py#L35).

The root devenv jj version differs from the old project 26 report. I did not
reuse its 0.45.1 behavior as evidence for this spike.

## Current preparation and handoff

Preview does not change the active project files. It does add a workspace to
the shared jj repository and writes the render into that workspace.

The current preview sequence is:

1. Read the active marker and compose the source plan.
2. Take CopyRoom's `write.lock` and capture the active head and tree digest.
3. Run `jj workspace add` at the old render head.
4. Write rendered files into the temporary workspace.
5. Commit the new render as a child of the old render.
6. Run `jj new <active-head> <new-render>` in the temporary workspace.
7. Copy a new source snapshot into that workspace and commit it when needed.
8. Write preview state to the project preview directory and to a sidecar next
   to the temporary workspace.

The marker in the temporary workspace still has the old render record. The
preview state stores the proposed source digest, answers, owner map, revision,
render digest, and optional generation metadata. It does not make those values
the marker bytes in the reviewed tree.

CopyRoom can prepare the source snapshot, render commits, resolved merge, and
generated files in the temporary workspace. The generation state is also saved
with the preview. It does not prepare the complete reviewed result because the
updated marker bytes are not in that workspace. A complete prepared result
would compute the next marker from the frozen preview state, write it into the
temporary workspace, commit it, and review that head, tree digest, and marker
bytes. Apply could then make an empty child of that prepared head. This keeps
the expected render ancestry. It does not make the handoff conditional.

Apply checks the active head, tree digest, marker digest, old render head, and
preview tree. It then runs `jj new <preview-head>` in the active workspace.
That command changes the active workspace head and writes the checkout files.
CopyRoom checks the new commit parent and compares the active files with the
preview tree. It then writes the new marker with a temporary file, `fsync`, and
atomic rename. A later `jj commit` records that marker. The code checks the
render head after that commit, then forgets the preview workspace and removes
its directory and state files.

`layer add` follows the same gap. It creates a render and merge in a temporary
workspace. It runs `jj new <merge-head>` in the active workspace. It writes
the new layer marker only after that handoff.

The active-project filesystem writes during apply are therefore:

- jj's checkout of the prepared preview tree after `jj new`;
- the atomic marker replacement from `write_json`;
- jj's snapshot and checkout during the marker commit;
- preview-state deletion during cleanup.

The jj operations include the active `new`, the marker `commit`, and the
workspace `forget`. Preview also writes workspace registration and commit
objects into the shared jj repository. The CopyRoom lock file does not lock a
plain jj process.

## CLI and operation-log findings

I ran these commands in disposable jj repositories:

```text
jj --version
jj workspace update-stale --help
jj edit --help
jj --at-operation=<saved-op> --no-integrate-operation new -m "parallel op"
jj op integrate <new-op-id>
```

The pinned version printed `jj 0.43.0`. `workspace update-stale` accepts no
expected head, tree, or operation ID. Its pinned source defines an empty
`WorkspaceUpdateStaleArgs` structure and calls
`recover_stale_working_copy()` directly. `jj edit` also has no expected-current
workspace condition.

The disposable CLI probe also ran
`jj workspace update-stale --expected-operation=deadbeef` and
`jj edit --expected-current=@ @`. Both commands rejected the unknown option.
The official CLI reference lists `jj workspace update-stale` with no
arguments.

The `--at-operation` test does not act as compare-and-swap (CAS). A mutating
command at an earlier operation creates a fork. The test created a rebase and a
new workspace change from the same saved operation. Both commands succeeded.
`jj op integrate` then created a reconcile operation with both parents. Before
`jj workspace update-stale`, `jj op log` and `jj workspace list` reported that
the default working copy was stale. `update-stale` recovered it and both
workspaces remained registered.

The jj concurrency documentation states that a command loads one operation
view at start and records its result with that operation as parent. Another
process's operation can arrive while it runs. jj integrates divergent
operation heads later. This design preserves operations. It does not reject a
stale intent before the operation commits.

Primary sources:

- [jj concurrency model](https://docs.jj-vcs.dev/latest/technical/concurrency/)
- [jj working copies and stale workspaces](https://docs.jj-vcs.dev/latest/working-copy/)
- [jj CLI reference](https://docs.jj-vcs.dev/latest/cli-reference/#jj-workspace-update-stale)
- [jj 0.43.0 `workspace update-stale` source](https://github.com/jj-vcs/jj/blob/v0.43.0/cli/src/commands/workspace/update_stale.rs)
- [jj 0.43.0 operation integration source](https://github.com/jj-vcs/jj/blob/v0.43.0/cli/src/commands/operation/integrate.rs)
- [jj 0.43.0 working-copy behavior](https://github.com/jj-vcs/jj/blob/v0.43.0/docs/working-copy.md)

The pinned source is useful for the exact CLI shape. The current jj concurrency
and working-copy docs explain the shared operation-log and stale-workspace
behavior.

## Repeatable experiments

[`harness.py`](harness.py) creates fresh projects from project 26's example.
It starts a separate CopyRoom process and puts a small `jj` wrapper at the
front of that child's `PATH`. The wrapper runs the real pinned jj binary. It
pauses before or after one selected jj command. A second real jj process then
changes the active project. The wrapper does not patch `JJ.run`.

[`jj_operation_races.py`](jj_operation_races.py) runs additional real jj
commands from two workspaces. It covers file writes, commits, bookmark changes,
new operations, and unintegrated operation forks. The exact stdout, operation
graphs, workspace listings, and recovery output are in
[`jj-operation-races.txt`](evidence/jj-operation-races.txt).

I ran the CopyRoom harness twice with fresh repositories. Each output records
the active head, parent commits, operation ID, tree digest, marker bytes,
tracked file digests, render heads, source snapshot identity, temporary
workspace state, competing commit and operation IDs, CopyRoom exit code and
report, and the final operation graph. See
[`run-01.json`](evidence/run-01.json) and
[`run-02.json`](evidence/run-02.json).

The operation log race, including both rejected conditional flags, is in
[`jj-operation-races.txt`](evidence/jj-operation-races.txt).

The exact focused test and lint output is in [`focused-tests.txt`](evidence/focused-tests.txt)
and [`ruff.txt`](evidence/ruff.txt). The harness uses the local Templateer
source. It does not call a model provider.

## Results by concurrency boundary

| Boundary | Observed result |
| --- | --- |
| Writer commits before preparation | Preview uses the writer's head as its active parent. The writer's file appears in the temporary preview. Active files stay unchanged during preview. |
| Writer commits during preview preparation | jj makes the preview workspace stale. `jj resolve --list` exits before CopyRoom's final active-state check. Preview exits with code 2 and removes the temporary preview. The writer's active commit remains. Layer add shows the same stale-workspace error and leaves its temporary workspace for recovery. |
| Writer commits after preview, before apply | Apply exits with code 1. The active head and writer file remain. The preview remains available. |
| Writer changes a bookmark after preview, before apply | The bookmark operation changes neither active head nor tree. Preview state has no operation ID. Apply exits with code 0 and accepts this stale preview. |
| Writer commits after apply's final check, before active `jj new` | Apply detects a changed operation parent and exits with code 1. However, `jj new` has already moved active `@` to the prepared result. The writer commit remains visible in jj, but it is no longer the active workspace head. |
| Writer edits a file without committing in that same gap | CopyRoom's `jj new` snapshots the file into an operation, then moves active `@` to the prepared result. Apply exits with code 1. The active checkout no longer contains the file, but the snapshot operation remains. `jj edit <snapshot-head>` restores the writer's file. |
| Writer changes a bookmark in that same gap | Apply exits with code 1 after `jj new`. The bookmark operation remains, but active `@` has moved to the prepared result. |
| Writer commits after active `jj new`, before CopyRoom checks the operation parent | Apply exits with code 1. The writer's new commit becomes active on top of the prepared result. The preview remains. |
| Writer commits after marker commit, before cleanup | Apply exits with code 0. The writer commit becomes the active head. CopyRoom deletes the preview and reports success. This violates the requested no-success-on-interleave rule. |
| Writer commits after all apply checks, while CopyRoom waits before workspace cleanup | Apply exits with code 0. The writer commit remains active, but CopyRoom does not detect it. |
| Two commands fork from one operation | Both commands succeed. Integration creates a reconcile node. The workspace becomes stale until `jj workspace update-stale` runs. |

The first check and the later operation-parent check are useful diagnostics.
They are not a conditional handoff. A competing operation between checks can
move the active workspace before CopyRoom rejects it. A competing operation
after the last check can be included while CopyRoom reports success.

The direct uncommitted-file test also matters. A file write does not have to
create an operation before CopyRoom reaches `jj new`. That command first
records a `snapshot working copy` operation. It then creates the prepared `@`
commit in a second operation. CopyRoom rejects the changed operation parent,
but the active workspace has already moved away from the snapshot head. The
harness reads the snapshot head from its operation view, runs `jj edit
<snapshot-head>`, and verifies that the file returns to the active tree. The
preview workspace remains available.

## Clean apply and saved render state

The clean apply test records the following graph:

```text
T0 ──> T1
│       \
P0 ─────> M ──> A ──> P1
```

`T0` is the old render. `T1` is the next render. `P0` is the active project.
`M` is the reviewed merge, including a new source snapshot when needed. `A` is
the active `jj new` working-copy commit. `P1` records the updated marker.

The current temporary workspace ends at `M`. Its marker bytes equal the old
active marker. Apply writes the new marker only after it changes active `@`.
Thus the active final tree does not equal the recorded preview tree digest.
The preview tree is exact for rendered files, source snapshot, and old marker.
It is not an exact review of the new marker bytes.

The source-edit test changes the source after preview. Apply still reproduces
the reviewed file tree. Apply does not call the composer or a model provider.
It uses the recorded render commit, source digest, and preview state. A generated
refresh follows the same frozen-plan path; the existing integration test uses
a fake provider and checks its call count.

Conflict resolution remains in the temporary workspace. Existing integration
coverage resolves a conflict there and compares the reviewed files with the
active files after apply. Layer add checks path ownership before it makes the
layer visible, but its marker remains an active-workspace write after `jj new`.

## Recovery and process crashes

The shared jj operation log preserves commits and workspace registrations.
It does not make the active workspace pointer conditional. Do not run
`jj op restore` automatically after another writer advances the repository.

For a rejected apply before `jj new`, keep the preview and the writer's active
head. Run `copyroom preview list --project <project>`, inspect the active
project, then discard with `copyroom discard --preview <path>` or create a new
preview with `copyroom preview create --project <project> --out <path>`. For an
interleave after `jj new`, run `jj op log` and inspect both the writer operation
and CopyRoom operation. If the writer commit is known, move the active
workspace back to it with `jj edit <writer-commit>`. Keep the CopyRoom preview
commit for inspection. Then create a new preview from the writer's active
project.

For the uncommitted file case, the current `jj new` operation has a snapshot
operation as its parent. Read that parent ID with
`jj op log --at-op=<current-op> -n 1 -T 'parents.map(|parent| parent.id()).join(" ")'`.
Read the working-copy head in that operation with
`jj --at-operation=<snapshot-op> log --ignore-working-copy --no-graph -r @ -T commit_id`,
then run `jj edit <snapshot-head>`. The harness verified that this returns the
plain file write to the active tree and keeps the preview workspace.

If two operations fork, inspect `jj op log` first. The experiment recovered by
integrating both operation IDs, then running `jj workspace update-stale`. The
resulting operation graph retained both operation branches and both workspace
registrations. A stale-workspace update can change visible files. Inspect the
working tree before running it on a managed project.

Crash points leave these states:

| Crash point | Remaining state | Recovery |
| --- | --- | --- |
| Before `workspace add` | No preview workspace | Start preview again. |
| After workspace add, before both preview-state files exist | jj registration and external workspace can remain. `copyroom preview list` may not find them. | Use `jj workspace list`; forget the registered workspace and remove its directory. |
| Between the project state JSON and external sidecar writes | Internal state can list the preview, but apply and discard need the missing sidecar. | Use `jj workspace list`, remove the workspace, and remove the internal state file. |
| After preview state is saved | Workspace and both state files remain. | Use `copyroom preview list`, then apply or discard. |
| After active `jj new`, before marker commit | Active `@` has moved; the marker is old or dirty. The preview remains. | Inspect the operation log. Restore only if no writer interleaved. Otherwise reconcile both commits and make a new preview. |
| After marker commit, before cleanup | The update is committed. The preview workspace and state remain. | Inspect active files, then discard the stale preview. |
| After `workspace forget`, before directory and state cleanup | The workspace registration is gone, but files or state can remain. | Remove the external directory and stale internal state manually. |

Layer add uses a random `/tmp/copyroom-layer-*` directory and has no preview
state file. A crash can leave a workspace registration and a temporary path.
Use `jj workspace list`, inspect its path, then forget the workspace and remove
the directory. A crash after the active `jj new` but before the marker commit
needs manual marker recovery or an operation restore when no writer interleaved.

## Proposed complete handoff

This sequence meets the tree and marker requirement only if jj adds a
conditional transaction or the product limits writers to a shared broker. The
command syntax below is a design sketch. jj 0.43.0 does not provide it.

1. Preview captures the active head, tree digest, marker bytes, operation ID,
   render heads, and source identity. It builds the render, source snapshot,
   generated files, resolved merge, and next marker in the temporary workspace.
2. CopyRoom commits the complete prepared tree. The review record stores the
   prepared head, parents, tree digest, exact marker bytes, source snapshot
   identity, and render ancestry. Apply uses this frozen record. It does not
   read or rerender a changed source.
3. Apply requests one conditional handoff, for example
   `jj workspace handoff --if-operation <op> --if-head <head> --if-tree <digest> --prepared <commit> --forget <preview-workspace>`.
   The jj transaction must serialize operation writers and protect the active
   working-copy checkout through the handoff. It must snapshot the active
   files, compare all expected tokens, and reject before changing `@` if any
   token differs.
4. On success, jj makes an active child of the prepared commit. The child tree
   and marker equal the reviewed tree, and the render commit remains in its
   reviewed ancestry. jj forgets the preview workspace in that same handoff
   transaction. CopyRoom emits success only after jj returns the committed
   operation ID. Sidecar cleanup is idempotent and can finish after a crash.
5. On rejection, active `@` stays on the writer's commit. CopyRoom keeps the
   prepared workspace and reports the conflicting token. The user can inspect
   both workspaces and make a new preview from the current active head.

The operation publication is the handoff's linearization point. A plain jj
operation ordered after it is a later write, not an interleave inside the
handoff. A process crash after operation publication but before filesystem
checkout leaves a stale working copy; the operation log plus
`jj workspace update-stale` must recover it without dropping the prepared
commit. A raw file writer that ignores jj's working-copy lock remains outside
this guarantee. This design needs jj changes and a product decision. It is not
an implementation result from this spike.

## Design comparison

| Design | Correctness | Recovery | Layout cost |
| --- | --- | --- | --- |
| In-place handoff with CopyRoom's current process lock | Works for CopyRoom writers that take the same lock. It does not protect against plain jj or direct file writes. A precheck does not close the gap. | Preview state helps before handoff. Mid-handoff recovery needs operation-log inspection. | No managed-project layout change. |
| jj conditional workspace transaction | A future jj command could compare the expected operation ID, workspace head, and tree while it serializes the handoff. It must include the complete marker in the prepared commit and move the workspace in the same transaction. All jj writers must use the same transaction boundary. Direct file writes must also honor the working-copy lock. | One transaction either rejects without moving `@` or records the prepared head. A crash after operation publication but before checkout recovery leaves a stale workspace that jj can recover. | Small CopyRoom layout change, but requires jj CLI or library work. jj 0.43.0 has no such command. |
| Brokered immutable generations with an atomic active pointer | Can publish one prepared generation atomically if all writers use isolated generations and the broker owns publication. A direct plain jj writer in the active generation remains outside the guarantee. | Keep old and prepared generations. On crash, inspect the pointer and resume or restore it. | Large change. Adds generation directories, an active pointer, and a writer broker. |

None of the current designs supports arbitrary plain jj writes to the same active workspace
with the current CLI. The in-place lock design changes the writer contract.
The generation pointer design changes the project layout and still needs a
broker. The jj conditional transaction is the smallest design that could
protect the same workspace from jj writers, but CopyRoom cannot implement or
verify it with the pinned CLI. Recommend that CopyRoom keep runtime apply
unchanged until the product chooses a cooperative-writer contract or funds jj
transaction support. Keep the generation layout as a broader alternative.

## Implementation plan after the product decision

If the product accepts a cooperative-writer contract:

1. Build the full next marker and write it into the temporary workspace before
   the review tree is recorded.
2. Save a durable prepared-state record with the expected active head, tree,
   marker digest, operation ID, render heads, source digest, and prepared tree.
3. Hold one documented writer lock from the final check through `jj new`,
   marker verification, and cleanup. Require all supported writers to take
   that lock for the full edit-and-commit interval.
4. Use the same flow for update apply, layer add, generated refresh, and
   adoption. Keep source snapshots and frozen generated artifacts in the
   prepared workspace.
5. Add a recovery command that lists prepared workspaces and distinguishes
   prepared, handed-off, and cleaned states. Do not restore an operation when
   the log shows a later writer.
6. Add barrier tests for every command boundary and direct file writes.

If arbitrary plain jj writers remain supported, do not implement steps 1–6 as
a claimed atomic solution. First choose a new writer boundary. Options include
isolated writer repositories with explicit converge, or a jj-level conditional
handoff plus a shared working-copy lock that every file writer honors. The
current jj CLI alone cannot supply either guarantee.

## Verification

The original focused real-process suite passed 13 tests. The current follow-up
suite passed 14 tests with the new checkout-window case. The exact command and
output are in
[`root-2026-10-07-focused-tests.txt`](evidence/root-2026-10-07-focused-tests.txt).
Ruff passed on the spike directory in the earlier spike. The two full barrier
runs, the operation-log race, and the follow-up checkout-window runs used jj
0.43.0. The `gitman publish` hook also ran `uv run --locked --extra dev pytest`
and passed. Runtime code stayed unchanged, so this follow-up did not run the
root Ruff check or walkthrough gate.

## 2026-10-07 follow-up: current jj release

### Release and source review

As of 2026-10-07, the latest stable jj release is **0.45.1**, released on
2026-09-03. The root CopyRoom devenv still supplies **jj 0.43.0**. I verified
the root version with `devenv shell -- jj --version`. All runtime experiments
below use that exact root version in disposable repositories. Project 26's
nested jj 0.45.1 remains source-review context only; it is not runtime test
evidence for the root devenv.

I inspected release-tagged v0.45.1 CLI source, library source, operation and
working-copy documentation, and the v0.45.0 and v0.45.1 release notes. The
release introduced no conditional workspace update or operation publication:

- In v0.45.1, `WorkspaceUpdateStaleArgs` is empty. The command calls
  `recover_stale_working_copy()`. It has no expected operation, head, or tree
  arguments.
- In v0.45.1, `EditArgs` accepts a revision positionally or with `-r`. It has
  no expected current workspace condition.
- The v0.45.1 operation documentation describes lock-free concurrent
  operations. A command loads one operation view, writes its result with that
  operation as parent, and leaves divergent heads for a later command to
  integrate. A mutating command with `--at-operation` makes an operation fork.
- The v0.45.1 library has a `WorkingCopy::start_mutation()` API. It returns a
  locked working copy with the old operation and tree, plus snapshot and
  checkout methods. This is a per-working-copy lock. The documented operation
  model does not use it to serialize operation publication or compare an
  expected repository operation. A raw file writer does not take this jj
  working-copy lock. This scope assessment is an inference from the API and
  operation model.
- `jj workspace update-stale` remains a recovery command. The v0.45.0 release
  fixed how it resets Git HEAD in colocated workspaces. That fix does not add a
  condition to the workspace update. The new `jj converge` command combines
  divergent commits after they exist. It is not a stale-intent check.
- Working-copy docs describe the normal snapshot, transaction, and checkout
  steps. They also describe stale working-copy recovery, including recovery
  commits when an operation was lost. They do not describe a conditional
  handoff that checks the expected operation, workspace head, tree, and marker
  before changing active `@`.

Official sources:

- [jj v0.45.1 release notes](https://github.com/jj-vcs/jj/releases/tag/v0.45.1)
- [jj v0.45.0 release notes](https://github.com/jj-vcs/jj/releases/tag/v0.45.0)
- [v0.45.1 `workspace update-stale` source](https://github.com/jj-vcs/jj/blob/v0.45.1/cli/src/commands/workspace/update_stale.rs)
- [v0.45.1 `edit` source](https://github.com/jj-vcs/jj/blob/v0.45.1/cli/src/commands/edit.rs)
- [v0.45.1 operation concurrency docs](https://github.com/jj-vcs/jj/blob/v0.45.1/docs/technical/concurrency.md)
- [v0.45.1 operation log docs](https://github.com/jj-vcs/jj/blob/v0.45.1/docs/operation-log.md)
- [v0.45.1 working-copy docs](https://github.com/jj-vcs/jj/blob/v0.45.1/docs/working-copy.md)
- [v0.45.1 working-copy API](https://github.com/jj-vcs/jj/blob/v0.45.1/lib/src/working_copy.rs)
- [v0.45.1 local working-copy implementation](https://github.com/jj-vcs/jj/blob/v0.45.1/lib/src/local_working_copy.rs)

### Tests on the root jj version

The release-source review found no candidate conditional command to test in
the latest stable CLI. The disposable root-version probes and operation races
remain the command evidence:

- `jj workspace update-stale --expected-operation=deadbeef` exits with an
  unknown-argument error.
- `jj edit --expected-current=@ @` exits with an unknown-argument error.
- The equivalent expected-operation and expected-current probes also reject
  in v0.43.0's parsed CLI.
- Two mutating commands from the same saved operation both succeed when run
  with `--at-operation=<saved-op> --no-integrate-operation`. They create
  divergent operation heads. A later `jj op integrate` adds a reconcile
  operation. The working copy then needs `jj workspace update-stale`.
- These commands do not act as compare-and-swap. They do not reject stale
  intent before a command writes a new operation.

The exact stdout, stderr, exit codes, operation graph, workspace list, and
recovery transcript are in
[`root-2026-10-07-operation-races.txt`](evidence/root-2026-10-07-operation-races.txt).

The expanded checkout-window case uses a separate real file-writer process.
It waits until `jj new` has checked out the prepared target bytes. It then
replaces that file while `jj new` is still running, while a 64 MiB trailing
file keeps the checkout active. In all three full records, the writer finished
while `jj new` was running, its bytes remained in the active tree, CopyRoom
exited with code 1, and the preview remained. The focused test also passed
this case. This result covers that controlled schedule only. It does not make
raw file writes safe in general. The separate uncommitted-at-handoff test still
shows that a file can be snapshotted and then left out of active `@`, with
manual recovery required.

Evidence:

- [`root-2026-10-07-in-flight-writer.json`](evidence/root-2026-10-07-in-flight-writer.json)
  records active and temporary heads, parents, operation IDs, tree digests,
  marker bytes, render heads, source snapshot identity, writer ID, final files,
  and the CopyRoom report. SHA-256:
  `911a48a640130d1e3447eb9f944b3bf25b8fa1dc5c983bf36c915d20b33dabeb`.
- [`root-2026-10-07-in-flight-writer-repeats.json`](evidence/root-2026-10-07-in-flight-writer-repeats.json)
  contains two more fresh-repository runs with the same result. SHA-256:
  `3577194bd469786d0a5b07ebddc1e1f41ff746f32002e9bd398d7598fb5bbb5a`.
- The two full barrier runs from this session cover the other cases and each
  used fresh repositories. Their files record their evidence hashes.
- [`root-2026-10-07-focused-tests.txt`](evidence/root-2026-10-07-focused-tests.txt)
  records 14 passing tests. The pytest command exited 0. SHA-256:
  `3931b35e53a8fa477e73ccc0a09bd9684dfb8018584f62eedb57d1ff2a5c96e1`.
- No live model provider ran.

### Boundary summary

| Boundary | Writer | Result on jj 0.43.0 |
| --- | --- | --- |
| Before preparation | Committed file change | The writer becomes the preview parent and appears in the temporary workspace. |
| During preparation | Committed file change or `layer add` | Preview or layer add exits with code 2. The active writer stays. A stale temporary workspace may remain for recovery. |
| After preview, before apply | Committed file change | Apply exits with code 1. The writer stays active and the preview remains. |
| After preview, before apply | Bookmark change | Apply exits with code 0. Preview state has no operation ID, so the changed operation is accepted. |
| Immediately before active `jj new` | Committed writer or bookmark change | Apply exits with code 1 after `jj new` has already moved active `@`. The writer remains visible in the operation log. Restore the writer head with `jj edit` only after inspecting the graph. |
| Immediately before active `jj new` | Uncommitted file write | `jj new` snapshots the file, then moves active `@`. Apply exits with code 1, but the active checkout omits the file. Recover the snapshot head with `jj edit`. |
| During active workspace update | Direct file write after the target path is checked out | In three fresh runs, the writer's bytes survived, CopyRoom exited with code 1, and the preview remained. The active `@` had already moved before CopyRoom rejected the operation overlap. |
| After active update, before marker commit | Committed file writer | Apply exits with code 1. The writer's commit becomes active on the prepared result. The preview remains. |
| After marker commit, before preview cleanup | Committed file writer | CopyRoom exits with code 0 and removes the preview while the writer commit is active. It reports success after an interleaving write. |
| While two operations fork | Two jj writers at one saved operation | Both operations succeed. Later integration creates a reconcile node. `update-stale` repairs the working copy. |

These results cover committed files, uncommitted files, bookmark operations,
divergent operations, and an independent filesystem write. A temporary
workspace, a just-read operation ID, and later operation integration do not
provide the required condition.

### Recommended handoff sequence

Use the same prepared-result and handoff design for `update --apply` and
`layer add`:

1. At preview, save the expected active operation ID, head, tree digest, exact
   marker bytes, render heads, and source identity.
2. Build the complete reviewed result in the temporary workspace. Include the
   exact next marker, source snapshot, generated artifacts, resolved conflicts,
   and expected render ancestry. Save its immutable head, parents, tree digest,
   and marker bytes. Apply must use this result. It must not rerender a source
   that changed after preview.
3. Before active `@` moves, ask one supported transaction to compare the
   expected operation, head, tree, and marker while it serializes operation
   publication and protects the workspace checkout. A mismatch must reject
   without changing active `@`. Any writer that can change project files must
   honor the same lock or write through the broker.
4. Record the committed handoff operation ID and prepared head in durable
   state. Verify the active tree, marker, and render ancestry against the
   reviewed record. Report success only after this state is durable.
5. Keep a durable recovery record until cleanup completes. `copyroom preview
   list` and a recovery command must show whether the result is prepared,
   published, checked out, or waiting for cleanup. Recovery must inspect the
   operation graph and preserve writer snapshots. It must not restore an old
   operation over a later writer.

jj 0.45.1 does not provide step 3. Do not implement a sequence of prechecks in
its place.

### Design comparison and product decision

The earlier comparison still applies. The two viable designs change who may
write and where the active project lives:

| Design | Correctness and writer limit | Recovery | Project layout cost |
| --- | --- | --- | --- |
| jj conditional workspace transaction | jj checks expected operation, workspace head, tree, and marker in one serialized publication. All jj workspace mutations use that boundary. Direct file writers must also take the working-copy lock; arbitrary raw writes remain unsupported. | A rejected transaction leaves active `@` unchanged. A durable journal identifies a published result whose checkout or cleanup stopped. Recovery inspects the journal and operation log, then finishes checkout and cleanup without dropping a captured writer snapshot. | Small CopyRoom change. It requires new jj CLI or library support for the conditional transaction. |
| Brokered immutable generations | The broker writes a complete immutable generation, then atomically changes one active-generation pointer. Every supported writer must create a new generation and publish through that broker. Plain jj or raw file writes inside an active generation are outside the contract. | Keep the old and prepared generations. After a crash, inspect the pointer and journal. Resume publication or keep the old pointer. Delete old generations only after recovery confirms no writer uses them. | Large change. Add generation directories, a pointer, a broker, and commands to list, publish, and recover generations. |

The required product decision is the writer contract. Should CopyRoom support
plain independent jj and direct filesystem writers in a managed project, or
require all writers to publish through a broker? If independent jj writers
must remain supported, CopyRoom needs jj-level conditional transaction
support and a separate contract for raw file writers. If the product chooses
the broker, direct in-place writers must be unsupported for managed projects.
Until that decision is made, leave runtime code unchanged.

### Lane verification for this continuation

Before using the published spike, gitman reported one canonical lane,
`templateer-jj-local`, at
`c8dd566f49756fbc3b58ec2d322367cc89a7e7d5`. The remote lane bookmark had the
same commit. Trunk was `main` at
`4fbcb24ef71c741d738bf4fde36102debaa45942` and was in sync with origin.
Gitman reported no foreign paths and a healthy repository. This matches the
provided handoff state. The ignored tracked project 26 files remain unchanged.
