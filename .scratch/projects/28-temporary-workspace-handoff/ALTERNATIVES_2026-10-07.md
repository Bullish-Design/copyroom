# Temporary workspace handoff: alternative designs

Date: 2026-10-07. This report extends the [historical spike](RESEARCH_REPORT.md).
It does not change CopyRoom runtime code or call a model provider.

## Decision

No tested design protects an in-place active project from every independent jj
and direct filesystem writer. The root devenv does not make those writers
cooperate. A PATH wrapper is advisory. A separate `devenv shell` can select the
pinned jj binary before an injected wrapper.

Two designs remain viable under different writer contracts:

1. Add a jj conditional workspace transaction. It must compare the expected
   operation, active workspace head, working tree, and marker while it owns the
   workspace mutation. It must reject before changing active `@`. Direct file
   writers must use the same working-copy lock or another enforced boundary.
   The current jj CLI does not provide this transaction.
2. Give a broker sole authority to publish immutable generations. Each
   generation contains a complete jj workspace and marker. The broker changes
   one active pointer after it records a durable journal. Every supported
   writer must publish a new generation through the broker. A plain writer in
   an old generation can be hidden. A plain writer in a new generation can
   change the reviewed result.

**Product decision:** decide whether managed projects may require all writers
to use the broker. If ordinary independent jj commands and direct file writes
must remain supported in the active path, neither current design meets the
handoff requirement. Keep apply blocked pending a jj change and a file-writer
contract. Do not replace the current guard with more prechecks.

## Live state and scope

`devenv shell -- gitman status --json` reported a canonical, published
`templateer-jj-local` lane at `f248838635586561267c0ea55c425616f2e1d87b`.
Trunk `main` was `4fbcb24ef71c741d738bf4fde36102debaa45942`, in sync with
`origin`. There were no foreign paths or anomalies before this investigation.
The two tracked, ignored project 26 files were already present. I did not
change them. The root shell reported:

```text
devenv 2.4.0+b904dcb (x86_64-linux)
Python 3.13.14
jj 0.43.0
copyroom 0.7.7
jj: /nix/store/w10748j1nsa40j6yjxvissjm8ljq4wlf-jujutsu-0.43.0/bin/jj
```

I got the CopyRoom version with `uv run copyroom --version status`. The CLI
requires a command even with `--version`. The root shell prints unrelated
MYPI and SecretSpec setup messages. They did not stop these probes. No nested
project 26 devenv result is used as root evidence.

The current code holds `fcntl.flock` on `.copyroom-local/write.lock` during
each CopyRoom command. It calls `jj` by PATH. Preview and apply run in separate
processes; the lock is not held while a person reviews the preview. Apply
checks state, runs active `jj new`, then writes and commits the marker.
`layer add` follows the same order. See local
[`jj.py`](../../../src/copyroom/local/jj.py) and
[`workflow.py`](../../../src/copyroom/local/workflow.py).

## Upstream findings

The [jj releases page](https://github.com/jj-vcs/jj/releases) listed v0.45.1
as the latest stable release on this date. I read its
[release notes](https://github.com/jj-vcs/jj/releases/tag/v0.45.1),
[v0.45.0 notes](https://github.com/jj-vcs/jj/releases/tag/v0.45.0), and
[tagged changelog](https://github.com/jj-vcs/jj/blob/v0.45.1/CHANGELOG.md).
The v0.45.0 stale-workspace fix concerns Git HEAD recovery. It does not add a
conditional handoff. This is an interpretation checked against the tagged
[`update-stale` source](https://github.com/jj-vcs/jj/blob/v0.45.1/cli/src/commands/workspace/update_stale.rs)
and [`edit` source](https://github.com/jj-vcs/jj/blob/v0.45.1/cli/src/commands/edit.rs).
Neither command accepts an expected operation, head, tree, or marker. The
root v0.43.0 sources have the same relevant shape:
[`update-stale`](https://github.com/jj-vcs/jj/blob/v0.43.0/cli/src/commands/workspace/update_stale.rs)
has an empty argument struct, and
[`edit`](https://github.com/jj-vcs/jj/blob/v0.43.0/cli/src/commands/edit.rs)
selects a revision and finishes a normal transaction.

The tagged [jj concurrency description](https://github.com/jj-vcs/jj/blob/v0.43.0/docs/technical/concurrency.md)
says a command loads one operation view and publishes an operation with that
view as parent. Concurrent commands can make operation forks. Later integration
preserves both operations. The
[`OpHeadsStore` contract](https://github.com/jj-vcs/jj/blob/v0.43.0/lib/src/op_heads_store.rs)
says its optional lock prevents duplicate *reconciliation* work. It is not a
lock that excludes ordinary writers. The
[`WorkingCopy::start_mutation` API](https://github.com/jj-vcs/jj/blob/v0.43.0/lib/src/working_copy.rs)
exposes a locked working copy with old operation and tree. It does not by
itself compare the global operation head and publish a conditional operation.
This scope statement is an interpretation of those interfaces.

The root CLI probe printed these results:

```text
jj workspace update-stale --help             -> no expected-state arguments
jj edit --help                               -> one revision argument
jj workspace update-stale --expected-operation=deadbeef -> exit 2, unknown argument
jj edit --expected-current=@ @               -> exit 2, unknown argument
jj --at-operation=<saved> --no-integrate-operation ... -> both forks exit 0
jj op integrate <fork>                       -> reconcile operation
jj workspace update-stale                    -> recovers stale working copy
```

The full commands, exit codes, operation graph, and recovery output are in
[`alternatives-2026-10-07-operation-fork.txt`](evidence/alternatives-2026-10-07-operation-fork.txt).
The [tagged operation integration source](https://github.com/jj-vcs/jj/blob/v0.43.0/cli/src/commands/operation/integrate.rs)
updates operation heads and reconciles divergent views. It does not reject a
stale handoff intent. The [tagged working-copy guide](https://github.com/jj-vcs/jj/blob/v0.43.0/docs/working-copy.md)
defines `update-stale` as recovery after an operation and checkout diverge.
Neither command proves atomic handoff.

## Devenv boundary

The actual [`dev/devenv.nix`](../../../dev/devenv.nix) adds `pkgs.jujutsu`
directly. It defines a `hello` script, lint and test tasks, and an `enterShell`
hook. It defines no jj wrapper, lock task, or broker process. `devenv info`
listed jj 0.43.0, those scripts, and those tasks; it listed no processes.
See [`devenv-2026-10-07-info.txt`](evidence/devenv-2026-10-07-info.txt).
I ran `devenv tasks run copyroom:lint`; it ran the configured lint task and
exited 0. The [task run log](evidence/devenv-2026-10-07-task-run.txt) shows no
writer coordination. `devenv processes status` requires a process name in
this version; the [probe log](evidence/devenv-2026-10-07-tasks-processes.txt)
records that usage error. The configured process set is empty.

The official [devenv basics guide](https://devenv.sh/basics/) says
`enterShell` runs on shell activation. The [task guide](https://devenv.sh/tasks/)
says task edges order selected tasks; `devenv:enterShell` is a lifecycle event.
The [process guide](https://devenv.sh/processes/) starts configured processes
with `devenv up`. The [packages guide](https://devenv.sh/packages/) adds package
executables to PATH. The [scripts guide](https://devenv.sh/scripts/) exposes
scripts in the shell. None of these documents claims that all commands in a
shell take one repository lock.

I injected a logging `jj` wrapper ahead of PATH in one root devenv process.
The [`devenv_probe.py`](devenv_probe.py) result records these checks:

| Launch | Resolved jj | Wrapper calls |
| --- | --- | --- |
| Ordinary `bash -c 'jj --version'` | Injected wrapper | Yes |
| CopyRoom `JJ(project).run('status')` | Injected wrapper | Yes |
| Absolute pinned jj path | Pinned executable | No |
| New `devenv shell -- bash -c 'jj --version'` | Pinned executable | No |
| Direct file write | No jj lookup | No |

The exact output is in [`devenv-2026-10-07-path.json`](evidence/devenv-2026-10-07-path.json).
The new devenv shell printed the `hello` hook again. This shows hook execution
per launch, not a shared lock. An editor terminal that inherits the injected
PATH may use the wrapper. An editor terminal that opens a new devenv shell may
not. I did not run an actual IDE terminal; this is an inference from the shell
probe. Tasks can launch a broker if configured, but ordinary commands need not
run through that task. Processes can host a broker if started, but this root
config has no broker process. An absolute executable path or another
environment bypasses a PATH wrapper.

## Fresh process experiments

All commands below ran through the root `devenv shell`. The harness uses the
resolved root jj executable in disposable repositories. CopyRoom child
processes use the root Python interpreter. The barrier wrapper pauses a real
jj command. It does not mock `JJ.run`.

```text
devenv shell -- bash -c 'uv run python .scratch/projects/28-temporary-workspace-handoff/harness.py > ...baseline.json'
devenv shell -- bash -c 'uv run python .scratch/projects/28-temporary-workspace-handoff/jj_operation_races.py > ...operation-fork.txt'
devenv shell -- bash -c 'uv run python .scratch/projects/28-temporary-workspace-handoff/alternatives_harness.py > ...run-04.json'
devenv shell -- bash -c 'uv run python .scratch/projects/28-temporary-workspace-handoff/generation_crash.py > ...crash-03.json'
devenv shell -- bash -c 'uv run python .scratch/projects/28-temporary-workspace-handoff/lock_crash.py > ...lock-crash-02.json'
devenv shell -- bash -c 'uv run python .scratch/projects/28-temporary-workspace-handoff/devenv_probe.py > ...path.json'
devenv shell -- bash -c 'uv run python .scratch/projects/28-temporary-workspace-handoff/fs_activation_probe.py > ...activation.json'
```

Each baseline run creates 14 fresh projects. The two complete baseline logs are
[`baseline.json`](evidence/alternatives-2026-10-07-baseline.json) and
[`baseline-02.json`](evidence/alternatives-2026-10-07-baseline-02.json).
The two final alternative runs are
[`run-04.json`](evidence/alternatives-2026-10-07-run-04.json) and
[`run-05.json`](evidence/alternatives-2026-10-07-run-05.json).
The crash runs are
[`crash-02.json`](evidence/generation-2026-10-07-crash-02.json) and
[`crash-03.json`](evidence/generation-2026-10-07-crash-03.json).
Each log records operation IDs and graphs, workspace heads and parents, tree
digests, marker bytes, render heads, source snapshot digests, barrier points,
writer commits where applicable, exit codes, reports, final files, and preview
state. The crash logs also record the killed publisher process ID and recovery
action. Temporary repository paths are removed after each run.

| Boundary and writer | Tested result in both baseline runs |
| --- | --- |
| Committed writer before preparation | Preview includes its head. Active files do not change during preparation. |
| Committed writer during preparation | Preview exits 2 on a stale temporary workspace. The writer remains active. `layer add` also exits 2. |
| Committed writer after preview, before apply | Apply exits 1 before active `jj new`. Preview remains. |
| Bookmark change after preview | Apply exits 0 because active head, tree, and marker match. The operation changed. |
| Committed writer immediately before `jj new` | Apply exits 1 **after** it has moved active `@`. The writer commit remains in jj, but active files hide it. |
| Uncommitted file immediately before `jj new` | jj snapshots the file, then active checkout omits it. Apply exits 1. Recovery needs the snapshot operation and `jj edit`. |
| Bookmark writer immediately before `jj new` | Apply exits 1 after active `@` moves. The bookmark operation remains. |
| Direct file writer during active checkout | The tested writer completed during real `jj new`; apply exited 1. This run does not prove all checkout writes are safe. |
| Committed writer after active `jj new` | Apply exits 1. The preview remains; inspect the graph before recovery. |
| Writer after marker commit, before cleanup | Apply exits 0 and removes the preview after a competing commit. This violates the success condition. |
| Writer before preview cleanup | Apply exits 0 despite the interleaving writer. |
| Divergent operation and fork | Both jj branches publish. Later integration reconciles; `update-stale` repairs the workspace. No stale intent is rejected at publication. |

The clean apply exits 0, but its temporary marker contains the old record.
Apply writes a different active marker after `jj new`. The source edit after
preview test exits 0 and applies saved render files, which supports the frozen
source rule for this path. The complete tree requirement still needs a prepared
marker in the temporary workspace.

## Candidate A: jj conditional workspace transaction

**Writer contract.** A new jj API or command must compare the active operation
head, workspace head, old working tree, and exact marker bytes while holding
the relevant working-copy mutation boundary. It must publish the active
workspace move only if all expected values still match. Every supported jj
writer must use the same jj repository and working-copy protocol. Direct file
writers must take an enforced working-copy lock for their full edit interval.
An unlocked editor write can still race the tree comparison and checkout.

**Preparation.** Save the expected active operation and a record of CopyRoom's
own preparation operations. A foreign operation during preparation or review
makes the preview stale, including a bookmark-only operation. Build a complete
prepared commit in the temporary workspace. Put exact next marker bytes,
source snapshots, generated output, and resolved files in that commit. Record
its head, parents, tree digest, render ancestry, and source identity. The
conditional transaction must consume that head without rerendering.

**Handoff.** The future jj transaction validates the expected state and
publishes the active workspace move as one conditional action. It must make
the checked-out result recoverable if the process stops after operation
publication. A separate journal records the prepared head before the call and
the published operation after it returns. A stale result exits 1 with active
`@` unchanged and the preview retained. A completed result reports success
only after it verifies the active tree and marker.

**Recovery.** Inspect journal, workspace state, and operation graph. If the
conditional operation was never published, keep the old active workspace and
preview. If it was published but checkout stopped, use the jj stale-workspace
recovery path after confirming the operation and prepared head. Preserve later
writer operations. Never restore an old operation over a later writer.

**Evidence limit.** No root or v0.45.1 jj CLI implements this transaction.
Thus no real crash injection or correctness proof exists for this candidate.
The exact operation publication, workspace lock order, and file snapshot
behavior need upstream implementation and tests. The current operation-store
lock cannot substitute for it.

## Candidate B: brokered immutable generations

**Writer contract.** The broker is the only supported publisher. A writer
requests an edit session for a named generation, edits its own workspace, and
publishes through the broker. A writer must identify the generation it read.
The broker rejects publication from an old generation after activation.
Ordinary jj, absolute-path jj, another environment, editors, scripts, and
watchers that write a generation directly bypass this contract. They can hide
work or change the reviewed generation. An advisory read-only bit does not
enforce immutability against the same user.

**Layout.** A stable control directory owns `journal/`, a broker lock, and
`generations/<id>/`. Each generation is a complete jj workspace with its own
`@`, render ancestry, source snapshot, generated output, and exact marker.
`active` is a symlink to one generation. Before activation, `active/@` is the
old workspace. During the atomic pointer replacement, path lookup sees either
old or new. After activation, `active/@` is the prepared workspace. The old
workspace remains registered and available. This changes CopyRoom's project
layout and the meaning of active `@`; it does not move the old workspace head.

The disposable prototype prepared a complete marker in a preview workspace,
committed it, then changed a symlink with `os.replace` and `fsync` on the
parent directory. The clean `update` and staged `layer add` runs selected the
reviewed head, tree, and marker. `layer add` left the old active files equal to
their pre-preparation digest. Its source snapshot digest matched its marker.
The prototype does not make generations immutable or enforce the broker
contract. It is a layout and recovery proof only.

**Crash sequence and recovery.** The crash harness sends `SIGKILL` to a
publisher after each durable step. Every case uses a fresh repository.

| Durable step at crash | Observed state | Recovery action |
| --- | --- | --- |
| Prepared journal `fsync` | Old pointer active; prepared workspace retained | Retry or discard only after checking the journal and writer state. |
| Pointer `os.replace` plus directory `fsync` | New pointer active; journal says prepared | Verify new head, tree, marker, source, and render; mark journal complete. |
| Complete journal `fsync` | New pointer active; both generations retained | Verify; keep complete record until cleanup. |
| Preview sidecar cleanup | New pointer active; old generation retained | Use journal and pointer for recovery. |
| Direct file writer after pointer | New tree differs; writer file remains | Stop. Do not report success or remove the writer file. |
| jj committed writer after pointer | New head and tree differ; writer commit remains | Stop. Inspect both operation and commit graph. |

The prototype recovery code never restores a previous jj operation. It keeps
both generations. The
[`crash-03.json`](evidence/generation-2026-10-07-crash-03.json) log contains
the exact heads, marker bytes, tree digests, operation graphs, and killed
process IDs. The earlier crash run repeated all outcomes.

The Linux [filesystem probe](evidence/fs-2026-10-07-activation.json) found that
`os.replace` of the symlink changed the active path to the new tree. An open
file handle still read the old bytes. A watch on the parent saw the pointer
rename; a watch on the old directory saw no new-directory write. Replacing a
nonempty directory with another nonempty directory failed with `ENOTEMPTY`.
Editors and watchers must reopen the active path after activation. The test
used one Linux filesystem. Cross-filesystem moves, Windows behavior, network
filesystems, and power-loss durability are unverified. The proposed layout
requires pointer and generations on one filesystem and a platform-specific
durability implementation.

The before-pointer direct-writer test wrote to the old generation. Activation
then hid that file from `active`. The after-pointer old-path writer also wrote
only to the old generation. The broker must refuse such writers or move them
to private edit generations before it can claim the product guarantee.

## Candidate C: cooperating lock or lease

The current `project_lock` serializes two CopyRoom apply processes. In two
fresh runs, the second process waited at the first process's real `jj new`
barrier. Without another writer, the first apply exited 0; the second exited
1 because the preview was stale. With a concurrent plain jj bookmark writer,
that jj command exited 0 while CopyRoom held its lock. The first apply then
exited 1 after active `@` moved. The second exited 1. See
[`run-05.json`](evidence/alternatives-2026-10-07-run-05.json).

I also killed a real CopyRoom child and its paused jj wrapper at six handoff
steps. The two fresh logs are
[`lock-crash-01.json`](evidence/lock-2026-10-07-crash-01.json) and
[`lock-crash-02.json`](evidence/lock-2026-10-07-crash-02.json). Both runs
recorded exit `-9` for each killed CopyRoom process. The wrapper was also
killed, so a queued `jj new` could not run after the crash injection.

| Crash step | State at crash | Recovery |
| --- | --- | --- |
| After preview `workspace add` | Active head and marker unchanged. jj lists the temporary workspace; `preview list` shows none because no sidecar exists. | Inspect `jj workspace list` and the temporary path. Keep or remove the orphan after checking its commits. |
| Before active `jj new` | Active head and marker unchanged. Preview is listed. | Retrying apply exited 0 in both clean crash runs. |
| After active `jj new` | Active head moved. Marker is old. Preview is listed. | With no later writer, `jj edit <old-head>` followed by apply exited 0. With a later writer, inspect the operation graph first and preserve its work. |
| After marker commit | Active head and marker changed. Preview remains listed. | Verify tree, marker, render, and operation graph. Then finish cleanup without rerendering. |
| Before preview cleanup | Active result is complete. Preview remains listed. | Verify, then finish cleanup. |
| After `workspace forget` | Active result is complete. Preview files and sidecar remain; `preview list` still shows it, but jj no longer lists that workspace. | Verify the active result. Remove stale preview files and state without a second blind `workspace forget`. |

These crash tests show recovery states, not a safe concurrent handoff. The
current lock still lets a plain jj or file writer interleave. A persistent
journal must make the orphan and partial handoff visible without relying on
the preview sidecar alone.

An operating-system lock is sufficient only when every supported mutating
entry point takes it. A `flock` held through human preview review requires a
long-lived broker or lease owner. A crash releases a process lock; a durable
journal must still identify the prepared preview and unfinished handoff. A
lease must use fencing tokens so an expired owner cannot publish later.
Neither mechanism protects an uncommitted file write or direct editor write
unless that writer cooperates for its whole edit interval. PATH wrappers help
ordinary commands but do not enforce this contract across separate shells,
absolute executable paths, or direct filesystem access.

## Other designs

A persistent journal improves listing and recovery. Alone, it does not stop a
writer between validation and active checkout. An explicit single-writer
policy can work operationally if the product forbids independent writers and
enforces the policy through the broker. A timed lease without fencing can
allow an expired writer to publish late. A filesystem pointer alone provides
atomic path selection, but it does not protect the selected generation from
direct writes. A raw directory rename cannot replace a nonempty project
directory on this tested Linux filesystem.

## Comparison

| Design | Correctness | Crash recovery | Writer limit | Complexity | Layout cost |
| --- | --- | --- | --- | --- | --- |
| Future jj conditional transaction | Can reject a stale operation, head, tree, and marker before active `@` moves if jj implements one serialized action. Not implemented or tested. | Journal plus jj operation graph and `update-stale`; checkout crash details need upstream proof. | Coordinates jj protocol writers. Direct file writers need an enforced working-copy lock. | High upstream change; modest CopyRoom integration. | Small. |
| Brokered immutable generations | Tested pointer and recovery shape. Safe only under a broker-only writer contract. | Journal and pointer select old or prepared generation. Tested `SIGKILL` at four steps. | Plain jj and file writes in a generation bypass it and can hide or alter work. | High broker and client work. | High: control root, pointer, retained workspaces. |
| Cooperating repository lock | Serializes tested CopyRoom processes. Plain jj bypassed it. | Six `SIGKILL` steps show orphan and partial handoff states; journal and recovery command still needed. | Every supported writer must lock, including editors and scripts. | Medium plus wrapper and lease policy. | Low. |
| Journal alone | Records state but has no atomic publication condition. | Good visibility, no race prevention. | None. | Low. | Low. |

## Recommended sequence after the product decision

If the product accepts broker-only writers, use this sequence for both
`update --apply` and `layer add`:

1. Open a broker edit session at a named active generation. Give the writer a
   private jj workspace. Save expected active pointer identity, operation ID,
   active head, tree digest, exact marker bytes, render heads, and source ID.
2. Prepare the complete result in that private workspace. Freeze the exact
   marker bytes, source snapshot, generated output, resolved files, render
   ancestry, head, parents, and tree digest. Review that result. Never rerender
   a source during apply.
3. Write and `fsync` a journal record. Under the broker publication lock,
   validate the active pointer and expected state. Reject if a supported
   writer published since preview. The lock excludes all broker writers until
   pointer publication finishes.
4. Atomically replace the active pointer with the prepared generation on the
   same filesystem. `fsync` the parent. This pointer change is the publication
   point. Verify the selected head, tree, marker, render ancestry, and source
   identity. Report success only after verification.
5. Mark the journal complete and `fsync` it. Keep the old generation and
   journal until cleanup is safe. Let `copyroom preview list` show prepared,
   activated, changed-after-activation, and cleanup-pending states.

On recovery, inspect the pointer, journal, both workspace heads, operation
graph, marker bytes, and tree digests. An old pointer means the prepared result
was not activated. A new pointer with matching reviewed data can finish the
journal. Any changed new generation means stop and preserve the writer's
files and commits. Never delete or reset a generation that has an unexamined
writer. A writer with an old generation token must rebase in a new edit session
or make a new preview.

If the product requires independent jj writers, pursue the jj conditional
transaction instead. Specify the operation-store and working-copy lock order
with jj maintainers. Add tagged upstream tests for every crash point before
CopyRoom uses the new API. Independent direct file writers still need an
enforced contract; a conditional jj operation alone cannot protect them.

The smallest follow-up for the broker route is a separate prototype command
that creates control state, journals a complete preview, switches a pointer,
and lists recovery states in disposable projects. Then route `update --apply`
and `layer add` through one publication helper. Keep the current runtime
untouched until the writer contract is approved and enforced.

## Evidence classes and limits

- **Tested:** root versions, CLI argument errors, operation forks, existing
  apply races, CopyRoom lock reach and crash states, PATH wrapper reach,
  generation pointer behavior, Linux watches, staged `layer add`, and the
  generation `SIGKILL` cases.
- **Upstream source or documentation:** jj operation publication, optional
  operation-head reconciliation lock, working-copy mutation interface, stale
  workspace recovery, and devenv shell/task/process/PATH behavior.
- **Interpretation:** a future jj transaction needs combined operation and
  working-copy conditions; the broker contract can make pointer validation
  safe among cooperating writers.
- **Unverified:** a jj conditional transaction implementation; robust immutable
  generations against hostile same-user writes; cross-platform pointer
  durability; real IDE terminal behavior; network filesystem behavior; power
  loss; complete broker recovery after arbitrary storage errors.

I ran the full `uv run pytest -q` suite; it exited 0 with 63 test dots.
The [pytest log](evidence/alternatives-2026-10-07-pytest.txt) has the coverage
report. `uv run ruff check src/ tests/` plus the investigation harnesses
also exited 0; see the [ruff log](evidence/alternatives-2026-10-07-ruff.txt).
The baseline and alternative process runs completed twice with fresh
repositories. These checks prove only the stated experimental boundaries.
