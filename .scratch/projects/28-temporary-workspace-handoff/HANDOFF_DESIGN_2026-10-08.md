# Temporary workspace handoff — design report

Date: 2026-10-08.
Scope: `copyroom update --apply` and `copyroom layer add`.
Status: design and implementation plan. The handoff changes remain open. The incidental fixes in §1 have landed. No system configuration changed or deployed for this design. No model provider was called.

Current-state update: 2026-10-08, after the `templateer-jj-local` and incidental-fix lanes landed on `main`. §1 records the investigation baseline. Later sections keep their original measurements and line numbers as historical evidence. Find current code locations before editing.

This report adds to `RESEARCH_REPORT.md` (2026-10-07) and `ALTERNATIVES_2026-10-07.md`. It does not replace them. Their findings stay as the historical record. Where this report contradicts them, it says so and gives the new evidence.

Labels used throughout:

- **TESTED** — a command ran in this investigation and produced the quoted result.
- **CODE-READ** — read from source at a named file and line.
- **UPSTREAM** — read from jj source or official jj documentation at a pinned tag.
- **INTERPRETATION** — a conclusion drawn from the above.
- **UNVERIFIED** — stated but not checked.

---

## 0. Summary

**The defect.** Both `update --apply` and `layer add` read the active state, then call an unconditional `jj new` on the active workspace. The operation check runs **after** `@` has already moved, and a later stretch has no check at all. Measured: in 35 barriered runs at the critical gap, CopyRoom exited 1 in every run but `@` had already moved and the project was left half-applied with `copyroom status` reporting `ok: true`. In 40 unbarriered runs, 7 of the 11 writes that landed after `jj new` produced a **silent exit 0**.

**The root cause is structural, not a missing check.** The reviewed tree is incomplete: the new marker exists nowhere until apply writes it into the active project. That forces publication to be three durable steps instead of one, and every crash state and race window follows from it.

**The fix, in two halves.**

1. **Make the prepared result complete** — commit the exact next marker into the preview workspace, so publication is one jj mutation. Pure CopyRoom work, no jj change, no new package. This alone deletes the silent-success window, the marker lost update, and ten of the twelve measured crash states.
2. **Make that one mutation conditional** — publish only if the active `@` is still exactly the commit that was reviewed against.

**The precondition is one token, not four.** In jj the working-copy commit *is* the working-copy tree, so `@ == H`, compared after an in-guard snapshot, subsumes the tree check and the marker check. Verified: the marker is jj-tracked and any tracked edit rewrites `@`. An operation-id precondition is not merely unnecessary but impossible, because preparation shares `.jj/repo` and advances the operation head by five operations per `copyroom update`.

**The agreed architecture direction can be simplified.** A Vendomat-packaged custom jj is **not needed**. The conditional publication was built and tested as one method in **pyjutsu**, which is first-party, already shipped by Vendomat, and already a gitman dependency — using only public jj-lib 0.44.0 API. It compiles clean, passes the existing suite, and across **144 real-process races produced no third outcome**. See §16.

**The writer contract is small and enforced by jj itself.** *Writers mutate the working copy through jj or jj-lib, so they take `.jj/working_copy/working_copy.lock`.* No writer has to cooperate with CopyRoom and no writer needs the patched build — only the publisher does. Measured on both engines.

**What cannot be promised.** A direct file write landing inside the checkout phase. §16.4 gives the path-by-path account: most such writes survive, but a write to a file the checkout rewrites is **silently overwritten**, in stock jj, for any `jj new`. No design here fixes it.

**One real surprise.** Two independent jj engines already write these repositories: CopyRoom uses the jj **CLI 0.43.0**, and gitman uses **jj-lib 0.44.0** in process via pyjutsu. They share the relevant locks, so the contract holds — but they are pinned separately and should be aligned.

**The next work is Steps 1 and 2 in §13.** They need no new tool dependency. The later product decision is in §14: may CopyRoom depend on pyjutsu for the publication step?

---

## 1. Investigation baseline and current state

The tables below record the state tested during the investigation on 2026-10-08. They are not live version or lane reports. Treat the 2026-10-07 reports' versions as earlier historical records.

### State after the incidental fixes landed

| Item | Current state on 2026-10-08 |
| --- | --- |
| CopyRoom version | 0.7.7 in `pyproject.toml` |
| Gitman | `CANONICAL`; `main` at `151ef1fa76a6727fedd10731f6ae55b8847219cf`, in sync with origin; no lanes |
| Last full gate | 88 tests completed, Ruff passed, walkthrough passed |
| Handoff | The reviewed preview still has the old marker. `apply` still writes the next marker in the active project after `jj new`. No journal or `copyroom recover` exists. |
| Fixed incidental defects | `--version` exits 0; default and relative preview paths work; `update-test` returns structured `no-change`; JSON temporaries use `.copyroom-tmp-` and an ignore rule. |

`write_json` keeps its temporary file beside the target to preserve atomic rename. It now removes the file on an exception and fsyncs the parent directory after the rename. `exclude_local_state` installs the unanchored `.copyroom-tmp-*` rule for new projects and backfills it in existing projects before JSON writes. A crash can still leave an ignored temporary file. Step 2 should list such files in `copyroom recover`.

The path helper resolves each parent and keeps the last path segment. This lets relative `..` paths work while preserving the target symlink check. An existing marker's stored source path can change to the normalized form on its next apply. Review that behavior if a source uses a symlinked parent.

### Repository at investigation time

| Item | Value |
| --- | --- |
| gitman status | `CANONICAL`, 1 lane |
| trunk | `main` @ `4fbcb24ef71c741d738bf4fde36102debaa45942`, in sync with origin |
| lane | `templateer-jj-local`, published, 1 change, +120147 −19440 |
| CopyRoom version | 0.7.7 (`pyproject.toml`) |
| pytest | `63 passed in 40.17s`, exit 0 |
| ruff | `All checks passed!`, exit 0 |
| `demo/walkthrough.sh` | passes, exit 0 |

The lane carried in-flight project 28 work from an earlier session. This report preserved it. The lane has since landed.

### Toolchain

| Item | Value |
| --- | --- |
| Python | 3.13.14, `.devenv/state/venv/bin/python` |
| devenv | `2.4.0+b904dcb (x86_64-linux)` |
| jj in CopyRoom's devenv | `jj 0.43.0` at `/nix/store/w10748j1nsa40j6yjxvissjm8ljq4wlf-jujutsu-0.43.0/bin/jj` |
| jj on a clean login PATH | **none** |
| Templateer | 0.4.1 |
| Latest jj release | 0.46.0 (2026-10-07) |

**Correction to an assumption in the task brief.** There is no system-wide jj today. `nix-store -q --requisites /run/current-system | grep -ci jujutsu` returns `0`. No NixOS, home-manager or `nix profile` declaration installs jj. The only jj on this machine's interactive PATH arrives through CopyRoom's own devenv shell. Making Vendomat the system jj owner is therefore an **addition**, not a replacement.

### Vendomat and the system configuration

| Item | Value |
| --- | --- |
| Vendomat | `/home/andrew/Documents/Projects/vendomat`, HEAD `169de6e`, version 0.4.4 |
| Real system config | `/home/andrew/Documents/Projects/nix-meta` (**not** `/etc/nixos`) |
| Running system | `/nix/store/c0xapipihnv7z781g2x3lkw4b2670qnf-nixos-system-server-26.11.20260705.d407951` |

`nix eval --raw .#nixosConfigurations.server.config.system.build.toplevel.outPath` in nix-meta returns exactly the running system path. That confirms nix-meta builds the running system. `/etc/nixos/configuration.nix` is inert: it has no `flake.nix` beside it, it names a different host, and its `environment.systemPackages` contains no jj. A reboot is pending (`/run/booted-system` is generation 143, `/run/current-system` is 144).

Vendomat's packaging model, CODE-READ:

- No nixpkgs overlay output exists. `nix eval .#` shows no overlay attribute.
- `packages.<system>` are `agentman copyroom default docman devman-plane gitman pyjutsu pyjutsu-wheel repoman repoman-toolchain-core templateer templateer-uv2nix vendomat wheelhouse`.
- Tool sources are `flake = false` git tags in `flake.nix` (pyjutsu v0.22.0 at line 34, copyroom v0.7.7 at 47, gitman v0.9.1 at 55).
- `mkUv2nixCli` (line 173) builds one CLI per tool. `mkToolchain` (`lib/mkToolchain.nix`) symlink-joins them and writes `share/vendomat/toolchain.json`.
- `devenvModules.default = import ./modules/devenv.nix` (line 320).
- `nixosModules.default` (line 326) sets `environment.systemPackages = [ self.packages.${system}.vendomat ]` and `environment.pathsToLink = [ "/share/vendomat" ]` (lines 349-350).
- A machine manifest ships at `/run/current-system/sw/share/vendomat/machine.json`. It currently holds `"toolchain":"/nix/store/iilwbhx0zmrzc33wm4vr1x2ib5f3f60a-repoman-toolchain-core"`. `modules/devenv.nix:341-346` reads it in "store mode".

nix-meta consumes Vendomat three ways: a pinned flake input (`flake.nix:55`, rev `bd26fea8`), the toolchain package (`profiles/developer.nix:15-16`, appended to PATH **last** at line 171 on purpose), and `inputs.vendomat.nixosModules.default` (`machines/server.nix:68`). The nix-meta pin is older than Vendomat HEAD: it carries repoman v0.7.5 where HEAD has v0.10.0.

### CopyRoom's jj, verified

The task brief's claim is correct. Both modules add stock `pkgs.jujutsu`:

- `modules/copyroom.nix:44` — `packages = [ cfg.package pkgs.jujutsu ];` (the importable consumer module).
- `dev/devenv.nix:20` — `pkgs.jujutsu` in the dev package list.
- `dev/devenv.nix:39` sets `copyroom.enable = false`, so only the dev entry applies in the root shell.
- `devenv.lock` pins nixpkgs to `cachix/devenv-nixpkgs 6004ea8c…`, which yields jujutsu 0.43.0.

The system's own nixpkgs (`NixOS/nixpkgs d407951`) happens to evaluate `jujutsu` to the **same** store path. Nothing pins the two together. That coincidence will break on the next bump of either input.

CopyRoom reaches jj as a subprocess by **bare name**: `src/copyroom/local/jj.py:25-28` calls `shutil.which("jj")` only as an existence test, then spawns `["jj", *args]`, which resolves the name again. `workflow.py:892` repeats the `shutil.which` probe.

### Two jj engines coexist on this machine

This is new and it matters for the writer contract.

| Writer | Engine |
| --- | --- |
| CopyRoom | jj **CLI 0.43.0**, subprocess |
| gitman | **jj-lib 0.44.0**, in process through pyjutsu 0.22.0 |

gitman does not use the jj CLI at all. `pyjutsu/Cargo.toml:16` pins `jj-lib = "=0.44.0"` from crates.io (`Cargo.lock:1445-1448`, checksum `0d58fe15…`). gitman writes through `ws.snapshot()`, `ws.transaction()`, `git_import`/`git_export`, `restore_operation`, `add_workspace`/`forget_workspace` at many sites in `gitman/src`.

The formats are compatible, TESTED in both directions: the CLI 0.43 created a repo, pyjutsu/jj-lib 0.44 snapshotted and committed in it, then the CLI 0.43 read it, wrote more operations and reconciled divergent operations 0.44 had written. No format error, all exits 0. The protos are byte-identical between the two tags; `lock/unix.rs`, `simple_op_heads_store.rs`, `simple_op_store.rs` and `stacked_table.rs` are byte-identical.

**Consequence.** A `copyroom`-managed project is colocated (`.git` exists — TESTED, `copyroom new` creates it) and is itself a candidate for gitman management. Both engines can write the same repository. Any writer contract must name both.

### Incidental defects found and later fixed

These findings describe the investigation baseline. The first three are fixed on `main`. The fourth remains part of Step 1.

1. `copyroom --version` prints `Usage: …` and `Error: Missing command.`, exit 3. The option is advertised in `--help` and does not work. TESTED twice by two agents.
2. `docs/user/local-workflows.md` tells the reader to run `copyroom update --out .copyroom-local/previews/update-1`. That path is rejected: `Error: preview must be outside the project`, exit 2. TESTED.
3. `source.write_json` stages its temp file as `.<name>.XXXX` **in the project root**. A crash between the write and `os.replace` leaves a stray `..copyroom-local.json.<rand>` in the managed tree, and jj then snapshots it into history. TESTED (crash run `A2pre`).
4. `working_digest` (`workflow.py:71`) hashes every file on disk except `STATE_EXCLUDES` (`.git .jj .devenv .direnv .venv __pycache__ .pytest_cache .ruff_cache`), the lock file and `.copyroom-local/previews/**`. It ignores `.gitignore`. A `dist/`, `build/`, `.loci/`, `.pi/` or `node_modules/` artifact in a managed project therefore changes `working_digest(project)` but not `working_digest(out)`, which makes the apply tree comparison fail. It also reads the whole tree on every check, which is O(repo size) and widens the race window.

---

## 2. Architecture at investigation time and the exact race

`W` below means `src/copyroom/local/workflow.py`. These line numbers refer to the investigation baseline. Later fixes shifted them. Search the current functions before implementation.

### 2.1 What preparation does

`preview` (`W:506`) holds `project_lock` (an `fcntl.flock` on `.copyroom-local/write.lock`, `jj.py:86`), then:

1. Reads the render head, the active `@` commit id and `working_digest(project)` (`W:556-558`).
2. `jj workspace add --name copyroom-<12hex> -r <old_render> <out>` (`W:562`) — the first durable step.
3. `clear_workspace`, `write_tree` (`W:564-565`).
4. `jj commit` of the render in `out` (`W:567`); `next_render = @-`.
5. `jj new <active_head> <next_render> -m copyroom:preview` in `out` (`W:576`) — the merge; jj materialises conflicts here.
6. Source snapshot plus a commit when new (`W:578-581`).
7. One staleness check: `@` and `working_digest(project)` must be unchanged (`W:583`).
8. Writes the state twice (`W:612`): `project/.copyroom-local/previews/<ws>.json`, then the sidecar `<out>.copyroom-preview.json`.

**Preparation leaves active project files unchanged.** TESTED: `@` and the sha256 of every project file are identical before and after `copyroom update`.

**Preparation does not leave the operation graph unchanged.** The preview workspace shares `.jj/repo` with the active workspace — `preview1/.jj/repo` is a 19-byte file containing `../../proj/.jj/repo`. TESTED: one `copyroom update` advanced the shared operation head by five operations, from `6af6f802…` to `5f14dbd6…`.

**The reviewed tree is incomplete.** The preview workspace keeps the **old** marker bytes. The new marker does not exist anywhere until apply writes it into the active project. `apply` asserts this at `W:697`. This single fact is the root cause of the multi-step publication and of most crash states.

### 2.2 What publication does

`apply` (`W:654`) holds the same lock and runs, in order:

Checks before any active mutation: preview sidecar schema (`W:659`), project identity (`W:660,665`), `@ == active_head` and `working_digest == active_tree` (`W:669`), marker bytes digest (`W:671`), render head (`W:673`), `next_render`'s parent (`W:675`), preview conflicts (`W:679`), preview head and tree (`W:684-695`), and the preview's marker digest (`W:697`).

Then:

```
W:700   operation = jj.operation_id()
W:701   _check_active_state(…, expected_operation=operation, …)   # last read
W:707   jj new <preview_head> -m copyroom:update                  # FIRST ACTIVE MUTATION
W:709   _check_operation_parent(operation)                        # post-hoc detection
W:713   tree comparison against preview_tree
W:754   write_json(project/MARKER, next_data)
W:755   jj commit -m "copyroom:project inputs"
W:757   render-head recheck
W:775   _discard  →  jj workspace forget; rmtree(out); unlink both state files
```

`layer add` (`_attach_layer`, `W:362`) has the identical shape at `W:423-425` then `W:426`, with no preview file and no reviewed step — it prepares and publishes in one command.

`manage.py:179` (adoption) and `workshop.py:393` (template checkout) repeat the same unconditional `jj new` pattern. They are out of scope here but they share the defect.

### 2.3 Three defects, not one

**Defect 1 — the operation check compares a value with itself.** `_check_active_state` (`W:266`) receives `expected_operation` and compares it against a fresh `jj.operation_id()`. In both call sites the caller passes the value it read one statement earlier (`W:700-701`, `W:421-423`). CODE-READ. No operation id is saved at preview time — the sidecar's 25 keys contain none (TESTED, full key list in §9.1). So the only real staleness tests are `@`, the file digest, the marker digest and the render head.

That is not simply a bug to fix: §4.2 shows an operation-id precondition is **not expressible** in this design, because preparation itself advances the shared operation head.

**Defect 2 — detection happens after the mutation.** `jj new` at `W:707` moves `@` and rewrites the working copy. `_check_operation_parent` at `W:709` then reads the current operation and requires its parents to be exactly `[operation]`. On mismatch it raises, and the `except` handler takes the "repository advanced" branch, which does **not** roll back.

TESTED, 35 barriered runs at the exact gap between `W:701`'s last read and the `jj new` subprocess launch (barrier before `JJ.run` ordinal 9, args `new <preview_head> -m copyroom:update`):

| Writer class | Runs | Exit | Did `@` move before rejection? | Preview kept |
| --- | --- | --- | --- | --- |
| committed jj write | 5 | 1 | yes | yes |
| uncommitted new file | 5 | 1 | yes | yes |
| `jj bookmark set` | 5 | 1 | yes | yes |
| `--at-operation` fork | 5 | 1 | yes | yes |
| two concurrent `bookmark set` | 5 | 1 | yes | yes |
| direct write to an owned path | 5 | 1 | yes | yes |
| direct write to an unowned path | 5 | 1 | yes | yes |

In 35 of 35 runs CopyRoom exited 1 and never claimed success — but `@` had already moved to a `copyroom:update` commit on the preview head, the working copy already held the preview files, and the marker still read revision 0.

The resulting state is **half-applied and invisible**. The render head query `heads(::@ & subject(glob:"copyroom:render <id> <layer> *"))` already returns `next_render`, because `@` descends from the preview merge. So the commit graph reports converged while the marker reports revision 0. `copyroom status` after the failure returns `ok: true, revision: 0, has_conflicts: false`. Nothing warns the user. TESTED, 35/35.

This corrects a prediction in my own brief and a claim in the 2026-10-07 reports: an uncommitted or direct edit at this barrier is **not** silently accepted. `jj new` snapshots the edit as its **own** operation, so the published operation's parent is the snapshot operation rather than the saved one, and the parent check trips. The writer's bytes survive in a commit that is not an ancestor of `@` — for one run, commit `682e54d6`, sitting under the now-divergent preview head. Nobody tells the user. In one class the rebased preview head is additionally marked `(conflict)` in `jj workspace list`, again silently.

**Defect 3 — a later window reports success.** Between `_check_operation_parent` (`W:709`) and the marker commit (`W:755`) there is no further operation or tree check. A writer landing there is swept in and CopyRoom exits 0.

TESTED with a barrier placed after `jj.conflicts()` — that is, after the tree comparison: **6 of 6 runs exited 0** and the foreign edit was absorbed. TESTED without any barrier, writer delay uniform over 0–1.5 s across 40 runs: of the 11 writes that landed after `jj new`, **7 were silent successes** and 2 of those folded the foreign file into the `copyroom:project inputs` commit. Measured exposure is roughly 80–100 ms of every 0.4–0.6 s apply, dominated by `op log` and `jj new` process startup rather than by the 0.2 ms gap between two Python statements.

There is also a lost update on the marker. `apply` reads `data = marker(project)` at `W:664`, before the mutation, and writes the derived document at `W:754`. A concurrent edit to `.copyroom-local.json` in between is overwritten. CODE-READ.

**The rollback branch is dead code.** The `except` handler rolls back with `jj op restore` only when `current_operation == last_operation`. TESTED across every barriered and stress run: that branch was never reached, because every failing path first adds a snapshot operation or a foreign operation. Keeping it is a hazard — were it ever reached after a foreign operation, `op restore` would hide that writer's work.

### 2.4 Writer classes, separated

| Class | Detected before `@` moves? | Where the work ends up |
| --- | --- | --- |
| committed jj write | no — after | visible side head, not an ancestor of `@` |
| uncommitted working-copy edit | no — after | snapshotted into a non-ancestor commit; gone from disk |
| direct filesystem write (non-jj tool) | no — after | same as above |
| bookmark change | after preview: **not detected at all** (exit 0); in the gap: after | bookmark survives |
| divergent operations / operation fork | no — after | both heads survive; jj merges on next load |
| any class in the `W:709`–`W:755` window | **not detected**; exit 0 | swept into CopyRoom's own commit |

The bookmark row deserves a note. TESTED: a bookmark moved after preview and before apply gives exit 0, and the bookmark survives. The 2026-10-07 report called this "the main correctness hole". It is better read as harmless: a bookmark move loses no work and the bookmark is still there afterwards. §4.3 argues it should stay outside the precondition on purpose.

### 2.5 Reads mutate the repository

Only `JJ.operation_id()` passes `--ignore-working-copy` (`jj.py:48-51`). `commit_id`, `render_head`, `conflicts` and `operation_parents` all snapshot the working copy. CODE-READ, confirmed TESTED.

So CopyRoom's staleness *reads* are durable writes. A read can rewrite `@`, which rebases the preview workspace's descendant commits and can make the preview stale. TESTED: an uncommitted edit before apply makes `W:669`'s `commit_id("@")` snapshot it, which rewrites `active_head`, which rebases the preview workspace, after which the preview workspace errors with `The working copy is stale`. One unbarriered stress run reached exit 2 by this route.

### 2.6 Render ancestry and replay

`new` builds `root() → R0 → inputs → empty @`. Preparation creates `R1` as a child of `R0` in the preview workspace, merges `jj new <active_head> R1`, and optionally adds a source-snapshot commit. Publication makes `@` a child of the preview head, so `R1` becomes an ancestor and the render-head revset returns `R1`.

**Apply never re-renders.** It never calls `compose`. It reuses the tree already written in the preview workspace. The only apply-time computation is the new marker document, built from the preview state (`W:732-753`). TESTED: a source edit after preview does not change the applied result. This part of the product goal already holds.

Two weaknesses in the ancestry mechanism, CODE-READ: the render head is found by **subject text glob**, not by an id stored in the marker, so any commit with a matching subject perturbs the query; and each layer's render line is rooted at `root()` independently, so layer renders are never ancestors of one another.

---

## 3. Crash states and recovery, measured

Phase F uses `tests/crash/test_publication_crash_matrix.py` and a separate
`tests/crash/driver.py` process. Each case requires a crash record and the
expected exit code, runs `recover`, checks the tracked tree and marker, checks
the workspace and journal, and runs `recover` a second time. The full matrix
passed with 26 cases. The earlier capture-only run is in
`evidence/2026-10-08/crash-pre-phase-f/`.

| Run | Crash point | Recovery result |
| --- | --- | --- |
| A1 | after `jj new` returns for update | `recover` verifies publication and removes the journal, workspace, and preview state |
| A2 | after the `published` journal write | `recover` completes cleanup |
| A3 | after `workspace forget`, before preview removal | `recover` removes the preview directory and state |
| A4 | after preview `rmtree` | `recover` removes the remaining state and journal |
| A5 | after the preview state unlink | `recover` removes the sidecar and journal |
| A6 | after the preview sidecar unlink | `recover` removes the journal |
| L0 | after layer `workspace add` | `recover` removes the incomplete workspace and temporary directory |
| L1 | after layer `jj new` returns | `recover` verifies publication and removes the journal and temporary directory |
| L2 | after the `published` journal write | `recover` completes cleanup |
| L3 | after layer `workspace forget` | `recover` removes the temporary directory and journal |
| L4 | after layer temporary `rmtree` | `recover` removes the journal |
| X0 | after `prepared`, before `publishing` | `recover` keeps the preview for review; `discard` removes it |
| X1 | after `publishing`, before `jj new` | `recover` resets the journal to `prepared`; `discard` removes the preview |
| X1j | while the real `jj new` process is blocked at its working-copy lock | `recover` resets the journal to `prepared`; `discard` removes the preview |

### 3.1 What this means

The writer variants check the exact bytes of `README.md`, `writer-notes.txt`,
and `writer-wip.txt`, the combined tracked tree, the marker digest, and commit
ancestry. The writer's committed change remains an ancestor of `@` in all
writer cases. For X0w, X1w, and X1jw, the project moved before publication, so
the prepared head is not an ancestor of `@`; recovery keeps the preview for
review until the test discards it. For A1w and L1w, recovery reports publication
as unverified and keeps the journal and workspace. Other published writer
cases clean the journal and workspace.

A1k, A3k, and L1k use a real `SIGKILL`. X1j also kills the real jj binary after
the test confirms that the shim has executed it. These process kills do not
simulate power loss. The `write_json` fsync discipline in `source.py:54-82`
remains unproven; a crash-consistent filesystem layer such as `dm-flakey` is
needed to test it.

---

## 4. What jj guarantees, and what it does not

Pinned bases for every citation in this section:

- `V43` = `https://github.com/jj-vcs/jj/blob/89f62ede8c1c611eaf134c0c49252efd65c7945d/`
- `V46` = `https://github.com/jj-vcs/jj/blob/7d382314f9420b4b8d932245b49c99492c812b9f/`

jj 0.46.0 (2026-10-07) is the latest release. The concurrency core is unchanged between 0.43 and 0.46 apart from refactors (async `consume`, `merge_operation(base_op, other_op)`, a pluggable workspace store, a new `jj workspace remove`). Six key experiments were re-run on the 0.45.1 binary with identical results.

### 4.1 Locks and publication boundaries

All locks are advisory `flock` files (`V43 lib/src/lock/unix.rs` L32-L112; identical at V46). On drop, jj unlinks the lock file and then unlocks; a waiter that sees `st_nlink == 0` re-creates and retries.

| Component | Lock | What it protects | Durable publication point |
| --- | --- | --- | --- |
| Operation store | none | nothing exclusive; objects are content-addressed, temp file + `fdatasync` + rename | invisible until a head file points at it |
| Operation heads | `.jj/repo/op_heads/heads/lock` | **only** stops two processes resolving the same divergent heads | the `heads/<opid>` file appearing |
| Transaction commit | the op-heads lock, for the file swap only | — | `update_op_heads(parent_ids, op_id)` |
| Working copy | `.jj/working_copy/working_copy.lock` | snapshot, `check_out`, `reset`, `recover`, `finish` for **one** workspace | `finish()` writes `tree_state` then `checkout` |
| Workspace store | `.jj/repo/workspace_store/index.lock` | the name→path map | in 0.43, `jj workspace forget` updates it **before** publishing — outside the transaction |
| Git import/export | `.jj/repo/git_import_export.lock` | colocated repos only; **CLI only** | — |

Lock order, traced with `strace -f -e flock,openat,rename,unlink,fdatasync` on `jj new` (TESTED):

```
[colocated only] git_import_export.lock
working_copy.lock          (snapshot)
  op_heads/heads/lock      (publish the snapshot operation, if dirty)
  write tree_state, checkout temp files
working_copy.lock RELEASED          ← snapshot phase ends here
write view and operation to the op store
op_heads/heads/lock        (add new head, remove old head)
working_copy.lock          (write tree_state and checkout)
working_copy.lock RELEASED
```

Nesting is always working-copy lock → op-heads lock, never the reverse.

**The single most important fact for this design: the CLI releases the working-copy lock between snapshot and publish.** The guard region we need therefore cannot be assembled by an external process that takes a lock and then shells out to `jj` — jj would block on the same lock. TESTED. Only an in-process library caller can hold the working-copy lock across snapshot → compare → publish → checkout.

**Durability is weaker than it looks.** Only temp files get `fdatasync`. The `heads/<id>` file is created with a plain `fs::write` and is never fsynced. No directory fsync appears anywhere in the trace. TESTED. jj issue [#4423](https://github.com/jj-vcs/jj/issues/4423) (open) reports repository corruption after a hard reboot. Crash-consistency claims in this report cover **process death, not power loss**.

### 4.2 There is no conditional publication, and one conditional checkout

**No compare-and-swap on operation heads.** `update_op_heads` is `fs::write(head, "")` followed by `remove_file` of the old heads, and a missing old head is silently ignored (`V43 lib/src/simple_op_heads_store.rs` L79-L100). Nothing compares the current heads against the parents. The trait doc says its lock is "not needed for correctness" (`V43 lib/src/op_heads_store.rs` L63-L71). The design document states the principle outright: "The operation cannot fail to commit (except for disk failures and such)" (`V43 docs/technical/concurrency.md` L84). jj's own library test asserts the behaviour — `test_concurrent_operations`, "we should have two op-heads on disk" (`V43 lib/tests/test_operations.rs` L131-L183).

**One conditional does exist, on the working-copy tree.** `Workspace::check_out(op_id, old_tree: Option<&MergedTree>, commit)` returns `ConcurrentCheckout` when the recorded on-disk tree id differs from `old_tree` (`V43 lib/src/workspace.rs` L452-L480; test `V43 lib/tests/test_local_working_copy_concurrent.rs::test_concurrent_checkout` L35-L88). It runs under the working-copy lock. **The CLI only calls it after the operation is already published.** So the primitive we need is partly built in jj-lib already; it is simply wired in the wrong order.

Adjacent features that do **not** provide a condition, all TESTED:

| Feature | What it suggests | What it does |
| --- | --- | --- |
| `--at-operation=X` on a mutating command | run only if X is current | forks the operation log; exit 0, two heads. Docs: "equivalent to having run concurrent commands" |
| `--ignore-working-copy` | read-only | skips snapshot and checkout only; still merges heads and still takes the publish lock |
| `--no-integrate-operation` | dry run | `tx.write()` then `leave_unpublished()`; writes the op and unreachable objects. The closest "prepare, publish later" primitive |
| `jj op integrate <op>` | safe publish | unconditional `update_op_heads` with **no lock and no check** |
| `jj op restore` | — | an ordinary transaction, no precondition |
| `jj op abandon` | safe cleanup | remaps only the current workspace's working-copy operation; other workspaces become "sibling", exit 255 |
| `jj workspace update-stale --expected-operation=…` | — | **no such flag**; `WorkspaceUpdateStaleArgs` is empty. Re-verified |
| `jj edit --expected-current=…` | — | **no such flag**. Re-verified |

**Two findings that directly bite CopyRoom's error handling:**

1. A non-zero exit does not mean nothing was mutated. With P running `jj commit` and Q running `jj new` in the same workspace, P exits **255** with `Internal error: Failed to check out commit … Caused by: Concurrent checkout` — **after** its operation was already published. TESTED on 0.43 and 0.45.1. jj issue [#9408](https://github.com/jj-vcs/jj/issues/9408) open; PR [#9706](https://github.com/jj-vcs/jj/pull/9706) open, turns it into a warning. CopyRoom's handler currently infers "nothing happened" from a failure.
2. A direct file edit arriving **during** the checkout phase is **lost**. With P at `jj new main` blocked at the working-copy lock for its checkout, a user edit to a tracked file was deleted and ended up in no commit; P exited 0. `check_out` has no content guard. TESTED. This bound applies to **every** design in this report.

**Staleness compares tree ids, not `@` commit ids.** `WorkingCopyFreshness::check_stale` (`V43 lib/src/working_copy.rs` L346-L400) treats an ancestor working-copy operation as `Fresh` when the tree ids match. TESTED: describing another workspace's `@` from `default` did not make it stale; a squash that changed the tree did. Stale text, exit 1: `Error: The working copy is stale (not updated since operation <id>). Hint: Run 'jj workspace update-stale' to update it.`

**Concurrent writers merge silently and never fail.** The merge is published by the *next load of any command*, including a read-only one — `jj log -r @` created a `reconcile divergent operations` operation. The only signal is one stderr line, `Concurrent modification detected, resolving automatically.` (`V43 cli/src/cli_util.rs` L729). Bookmarks can end up conflicted with both writers at exit 0; `jj new main` then fails with `Error: Name 'main' is conflicted`.

**No upstream request exists for this.** About 25 tracker queries for "compare-and-swap", "optimistic concurrency", "precondition", "conditional operation", "expected operation", "op heads atomic" and "TOCTOU" found no issue or PR asking for conditional publication. The nearest open items are #9408, #9706, #9314 (sibling after concurrent `workspace add`), #7538 (frequent stale errors), #6663 (grouping scripted op-log entries, whose author notes it is "not atomic") and #4423. On #9408 a maintainer wrote "I still don't think we should automatically resolve it."

### 4.3 The precondition collapses to one token

This is the central analytical result of this report, and it shrinks the required change substantially.

In jj, the working-copy commit **is** the working-copy tree. Any snapshot of a dirty working copy rewrites `@` and gives it a new commit id. TESTED four ways in a disposable project:

| Change | `@` after a snapshotting read |
| --- | --- |
| edit the marker `.copyroom-local.json` | `9a74095e…` → `79dd2c93…` (changed) |
| edit an ordinary tracked file | `7ef5dee8…` → `f3bcbd20…` (changed) |
| create a new non-ignored file | changed (auto-track is on) |
| create an ignored file | unchanged |

The marker is tracked: `jj file list -r @` includes `.copyroom-local.json`, and `copyroom new` sets `snapshot.auto-track = all()`. The project ships no `.gitignore` and no `.jjignore`. TESTED.

Therefore, **if a snapshot runs inside the guard region and `@`'s commit id still equals the expected `H`, then no process has committed anything that moved `@` and no process has edited any tracked file — including the marker.** The separate tree digest and marker-digest checks are redundant with it.

What `@ == H` does **not** cover, and the right disposition of each:

| Not covered | Disposition |
| --- | --- |
| a bookmark move | **leave it out on purpose.** It loses no work and survives publication. Including it would only add false refusals |
| an operation in another workspace of the same repo | leave it out. It does not touch this workspace's `@`; jj merges the heads and both survive |
| ignored files (`.copyroom-local/previews/**`, the lock file, anything in `.git/info/exclude` or the global git ignore, e.g. `*.sqlite`) | **leave them out on purpose.** They are not part of the managed tree, and including them is exactly the current false-refusal source (§1, defect 4) |
| empty directories | leave out; jj does not track them |
| a rendered path that the project's own `.gitignore` excludes | **must be refused at preflight.** Such a path is invisible to `@`, so the precondition would not cover it. See §8, CopyRoom change 9 |
| a direct file write during the checkout phase | **irreducible.** Lost in jj itself (§4.2). Must be stated in the contract, not papered over |

Why an operation-id precondition is not merely unnecessary but **impossible** here: the preview workspace shares `.jj/repo`, so preparation advances the shared operation head (TESTED: five operations per `copyroom update`). A check of the form "the operation head is unchanged since preview" would always fail with no foreign writer present. Any such check would first have to subtract CopyRoom's own preparation operations, and no operation id is persisted to subtract from.

**Conclusion.** The **caller** supplies one expected value — the active workspace's `@` commit id, compared after an in-guard snapshot. Not four. The `--expect-working-copy <id>` shape is the natural API, and it has an established precedent to cite upstream: `git push --force-with-lease`.

**One correction to this reasoning, from experiment (§16).** I first concluded that the `@` comparison alone is sufficient, because the working-copy lock excludes other jj writers. That is wrong. A jj CLI writer takes the working-copy lock only briefly for its own snapshot, then **releases it and publishes afterwards** (§4.1). It can therefore publish while the guard holds the lock. Measured: with the guard's internal compare-and-swap disabled, 8 of 96 races produced divergent operation heads, a stale working copy, and in some runs a competitor `jj` exit 255 with `Concurrent checkout`. With the compare-and-swap enabled, the same 8 windows became clean rejections.

So the implementation needs **two** comparisons, and they live at different levels:

| Comparison | Supplied by | Compared against |
| --- | --- | --- |
| working-copy commit id | the **caller** (`H`, recorded at preparation) | the value read inside the lock, after the in-guard snapshot |
| operation heads | the **implementation**, internally | the operation head the implementation itself loaded inside the lock, moments earlier |

This does not resurrect the impossible precondition. The operation comparison is against an operation read **inside the guard**, not against one recorded at preparation time. CopyRoom still persists exactly one token.

---

## 5. One change that every design needs first

Before comparing designs, isolate the part that is common to all of them and is pure CopyRoom work.

**Make the prepared result complete.** Write the exact next marker document into the preview workspace and commit it there, so the reviewed tree equals the final active tree byte for byte. Then publication is a single jj mutation: make the active `@` an empty child of the prepared head `P`.

This change alone:

- collapses publication from three durable steps (`jj new`, marker write, `jj commit`) to **one**;
- removes the marker lost update (§2.3), because no marker is written in the active project at publication time;
- removes the `W:709`–`W:755` silent-success window (§2.3, defect 3) by deleting the window;
- reduces the crash matrix from the twelve states of §3 to two — "prepared" and "published";
- makes the reviewed tree genuinely equal to what gets published, which is what the product goal asks for;
- is a precondition for every candidate below.

The 2026-10-07 report proposed this as step 1 of its plan and correctly noted that it "does not make the handoff conditional". That is right. It is necessary and not sufficient. It is also the single highest-value change in this report, and it needs no jj change, no new package and no new dependency.

**Second common change: a durable journal.** Three states (`prepared`, `publishing`, `published`), written with fsync, listed by `copyroom preview list`, and acted on by a new `copyroom recover`. Journalling is a component of every design, not an alternative to one. §3 shows why: the current state files are written in two places with no ordering guarantee, and five of the twelve crash states are either invisible or unrecoverable.

---

## 6. Candidate designs

Each candidate below assumes §5 is already done.

### D-A — Single-command publish with stock jj, plus a reconciliation report

**Mechanism.** Publication is one `jj new P` in the active workspace. Afterwards, CopyRoom reads what `@`'s previous value actually was. If it was not `H`, CopyRoom reports that a writer interleaved, names the writer's commit, and prints the command to integrate it. It does not claim a clean success and it does not roll back.

**Publication point.** The `jj new` operation becoming the head.

**Writer contract.** None required. Any writer may write at any time.

**Bypasses.** `@` moves even when a writer interleaved. A file watcher or build daemon observes the tree change. The reviewed result is published against a head the user did not review.

**Crash recovery.** Two states. Crash before: nothing happened; retry or discard. Crash during: jj's own semantics — either the operation published or it did not; a published-but-unchecked-out working copy is stale and `jj workspace update-stale` repairs it. Crash after: the preview workspace is a listable orphan.

**Layout cost.** None.

**Operational complexity.** Lowest of all candidates.

**What it meets.** Writer work stays visible (TESTED: in all 35 barriered runs the writer's work survived). CopyRoom does not claim success on an interleave. Crash states are listable and recoverable.

**What it does not meet.** The stated requirement "a stale operation, active head, tree or marker must cause rejection **before** active `@` moves". It cannot meet it, because stock jj has no conditional publication (§4.2).

### D-B — Conditional publication in pyjutsu

**Mechanism.** Add one method to pyjutsu that, in one process holding `.jj/working_copy/working_copy.lock` throughout: snapshots the working copy; compares the resulting working-copy commit id against the expected `H`; on mismatch aborts, leaving the operation unpublished and the disk untouched; otherwise writes the transaction, publishes it under the op-heads lock with a heads comparison, checks out the new commit, and calls `finish(op_id)`. CopyRoom calls it for the publication step.

**Why pyjutsu and not a jj fork.** pyjutsu is first-party (`Bullish-Design/pyjutsu`), Vendomat already builds and ships it (`flake.nix:34`, `packages.<system>.pyjutsu`, `pyjutsu-wheel` with an `abi3` build), gitman already depends on it, and every jj-lib item the method needs is **already public** at the pinned 0.44.0: `Transaction::write()` → `UnpublishedOperation`, `leave_unpublished()`, `RepoLoader::op_heads_store()`, `OpHeadsStore::{lock, get_op_heads, update_op_heads}`, `Workspace::start_working_copy_mutation()`, `LockedWorkspace::{locked_wc, finish}`, `LockedWorkingCopy::{old_operation_id, old_tree}`, `WorkingCopyFreshness::check_stale`. So this needs **no jj change and no maintained fork**.

**Publication point.** `update_op_heads` under the op-heads lock, inside the held working-copy lock.

**Writer contract.** *Every writer mutates the working copy through jj or jj-lib, so it takes `.jj/working_copy/working_copy.lock`.* No cooperation with CopyRoom is needed — the lock is taken by jj itself. This is why the contract is enforceable: it is not a convention that writers must remember, it is a property of the tool they already use.

**Bypasses.** A process writing files directly during the checkout phase (irreducible, §4.2). A writer in another workspace of the same repo (harmless — jj merges, both survive). A writer that had already loaded the old operation still publishes afterwards and forks (harmless — its work is visible, and jj merges on the next load). A `--ignore-working-copy` command that skips the working-copy lock entirely (harmless for the same reason).

**Crash recovery.** As D-A, two states. `flock` is released by process death — TESTED across 21 crash runs.

**Layout cost.** None.

**Operational complexity.** One new pyjutsu method, one Vendomat pin bump, one CopyRoom call site. CopyRoom gains a dependency on pyjutsu (or on a small pyjutsu CLI entry point, which keeps CopyRoom's subprocess shape — see §9.3).

### D-C — Conditional publication in a Vendomat-packaged custom jj

**Mechanism.** The same guard, implemented in jj and exposed as a flag, for example `jj new --expect-working-copy <H> <P>`. Vendomat packages the patched jj and distributes it to the system, to CopyRoom's root devenv, and to the importable consumer module.

**Writer contract, bypasses, publication point, crash recovery, layout cost.** Identical to D-B. The guard protects the *publisher's decision*; other writers need only the lock they already take, so they do not need the patched binary.

**Operational complexity.** Higher than D-B by exactly the cost of maintaining a jj fork. §4.2 shows upstream has no such request, states the opposite principle in its design document, and has a maintainer on record resisting automatic resolution of the adjacent case. An opt-in library API is plausible upstream; a fork is the realistic near-term position. Against that, CopyRoom's own change is the smallest of any candidate: one flag on one existing command.

### D-D — External flock on jj's own lock file, with `--no-integrate-operation`

**Mechanism.** Prepare the operation with `jj --no-integrate-operation`, then take `.jj/repo/op_heads/heads/lock` from outside, verify `get_op_heads() == [X]` by reading the directory, and publish with `jj op integrate <prepared-op>`.

**Status.** TESTED and it works: exit 0, one head, and a concurrent jj writer blocked at the publish lock until release.

**Why it is still rejected.** It depends on `.jj/repo/op_heads/heads/lock`, a `SimpleOpHeadsStore` implementation detail with no stability promise, and on an `OpHeadsStore::lock` that the trait documents as optional. It guards the operation head only — there is no working-copy guard, so the tree and the marker are unprotected. And it cannot hold the working-copy lock while shelling out to jj (§4.1). It buys a fraction of D-B's guarantee for more fragility.

### D-E — Brokered immutable generations

**Mechanism.** A control directory holds `generations/<id>/`, each a complete jj workspace. An `active` symlink is replaced with `os.replace`. A broker is the only publisher.

**Writer contract.** Broker-only. Every writer must acquire an edit session from the broker.

**Why it is rejected.** The contract is strictly larger than D-B's and is **not** enforceable — a plain `jj` or an editor can write into a generation directly, and the 2026-10-07 prototype measured exactly that: `direct_writer_in_old` true, `direct_writer_in_active` false. A non-cooperating writer's work is **silently hidden** by the pointer switch. That is worse than D-A/D-B, where the same writer is detected and its work stays visible. The layout cost is high: the project path becomes a symlink, which collides with jj workspace registration, git colocation, absolute paths held by editors and build caches. It needs a long-lived process. Its tested prototype enforced neither immutability nor the broker contract.

### D-F — Repository-wide lock or lease

**Mechanism.** An OS lock, or a fenced lease, taken by every mutating entry point and held across human review.

**Why it is rejected as protection.** Measured reach: two CopyRoom applies serialise on `write.lock`, and a plain `jj bookmark create` run while CopyRoom held it exited **0**. TESTED. A PATH wrapper is bypassed by an absolute path, by a separate `devenv shell`, and by any direct file write — also TESTED. An unfenced timed lease lets an expired owner publish late. Keep `project_lock` for what it actually does: serialise CopyRoom's own commands. Do not present it as protection from a writer that does not cooperate.

### D-G — Journal alone

Not an alternative. It is the recovery component of every design (§5). On its own it stops nothing between validation and checkout.

---

## 7. Comparison

"Rejects before `@` moves" is the stated requirement. "No false success" and "writer work visible" are the underlying goals.

| | D-A stock jj | D-B pyjutsu guard | D-C custom jj | D-D external flock | D-E generations | D-F lock/lease |
| --- | --- | --- | --- | --- | --- | --- |
| Rejects before active `@` moves | **no** | yes | yes | partly (op head only) | yes | no |
| No false success on interleave | yes (reported) | yes | yes | partly | yes | no |
| Competing writer stays visible | yes | yes | yes | yes | **no — hidden** | no |
| Reviewed tree published exactly | yes | yes | yes | yes | yes | yes |
| Crash states listable | yes | yes | yes | yes | yes | partly |
| Crash recovery without discarding others' work | yes | yes | yes | unclear | yes | no |
| Writer contract size | none | **smallest enforceable** | smallest enforceable | none, but fragile | broker-only, unenforceable | cooperative, unenforceable |
| Contract enforced by | n/a | jj's own working-copy lock | jj's own working-copy lock | private lock path | nothing | nothing |
| Bypasses | `@` moves transiently | direct write during checkout | direct write during checkout | tree and marker unguarded | any direct writer | any non-cooperating writer |
| Project layout cost | none | none | none | none | **high** (symlinked path) | none |
| New long-lived process | no | no | no | no | **yes** | yes, for review-spanning |
| Ongoing complexity | lowest | one first-party method | **a maintained jj fork** | fragile | highest | low but ineffective |
| CopyRoom code change | small | moderate | **smallest** | moderate | large | small |
| Covers `update --apply` and `layer add` | yes | yes | yes | yes | yes | yes |

Three rows decide it. D-E hides a writer's work, which is worse than the defect being fixed. D-F does not protect anything. D-D trades most of the guarantee for a dependency on a private path. That leaves D-A, D-B and D-C, which differ only in whether the rejection happens before or after `@` moves, and in what it costs to get there.

---

## 8. Writer-contract decision

A contract is only worth stating if something enforces it. The table below gives the decision for each viable design, and names the enforcer.

### 8.1 For D-B and D-C (recommended family)

**Contract.** *A writer that mutates a CopyRoom-managed working copy does so through jj or jj-lib.*

**Enforcer.** jj itself. Every jj CLI command and every jj-lib caller takes `.jj/working_copy/working_copy.lock` for any working-copy mutation. TESTED on both engines: with an external process holding that lock for 3 s and each writer started 0.5 s in, the jj CLI 0.43 `jj new` blocked 2.54 s, pyjutsu `snapshot()` blocked 2.56 s, and pyjutsu `transaction(new)` blocked 2.55 s. The same holds for the op-heads lock (2.52 / 2.50 / 2.52 s).

This is what makes the contract enforceable rather than aspirational: CopyRoom does not ask writers to cooperate with CopyRoom. It relies on a lock those writers already take as a side effect of using their normal tool.

**Who is covered**, by class:

| Writer | Covered? | Why |
| --- | --- | --- |
| `jj` inside the devenv | yes | takes the lock |
| `jj` outside the devenv, or by absolute path, or a different version in the nix store (0.41, 0.42, 0.45.1, 0.46) | yes | lock paths and `flock` semantics are byte-identical across 0.43–0.46; the guard does not need to be in *their* binary |
| gitman, via pyjutsu / jj-lib 0.44 | yes | TESTED, takes the same locks |
| other pyjutsu callers | yes | same |
| linkman / devman invoking `copyroom new` | yes | goes through CopyRoom |
| an editor or script that writes files and never runs jj, **quiescent** when CopyRoom takes the lock | yes, **detected** | the in-guard snapshot absorbs the edit, `@` therefore differs from `H`, and the publish is refused with nothing mutated |
| the same writer, writing **during** the checkout phase | **no** | irreducible. jj's `check_out` has no content guard and the edit is lost — TESTED in stock jj, independent of CopyRoom |
| a writer in **another workspace** of the same repo | not excluded, and does not need to be | it does not touch this workspace's `@`; the operation graph forks and jj merges; both sides survive |
| `jj --ignore-working-copy …` concurrent with the guard | not excluded, and does not need to be | same reason |
| a colocated raw `git` write | **no** | the CLI takes `git_import_export.lock` and pyjutsu does **not** (TESTED: pyjutsu was not blocked by it). This is a pre-existing gap between the two engines, not one this design introduces |

**Decision on direct file writers: keep them supported, with a stated edge.** They are supported in the sense that matters — a direct edit cannot cause a wrong publication, and it cannot be silently swallowed. It is detected and the publish is refused. The one case outside the guarantee is a write that lands inside the checkout window, and that case is unprotected in jj itself for any `jj new`, so no CopyRoom design can fix it. The honest product workflow is therefore: **publication is short and the user is told not to edit during it**; CopyRoom prints the window and refuses rather than guessing. Do not claim more.

### 8.2 For D-A (the no-new-primitive fallback)

**Contract.** None. No writer is constrained.

**Guarantee.** Weaker and precisely bounded: the published tree always equals the reviewed tree; a competing writer's work is never destroyed and always remains reachable; and CopyRoom never reports a clean success when a writer interleaved. It does **not** guarantee that `@` stays put when a writer interleaves — `@` moves and the interleave is reported afterwards.

This is a legitimate product position. It must be documented as such, and the word "atomic" must not appear next to it.

### 8.3 For D-E (rejected)

**Contract.** Broker-only: every writer must take an edit session from the broker. **Nothing enforces it.** A writer that ignores the broker has its work hidden by the pointer switch. That is the reason for rejection, not merely a cost.

### 8.4 What must never be claimed

- A cooperative `flock` is not protection from a writer that does not take it. Measured: a plain `jj bookmark create` succeeded while CopyRoom held `write.lock`.
- A PATH wrapper is not protection. Measured: bypassed by an absolute path, by a separate `devenv shell`, and by any direct file write.
- A system-wide default jj is a delivery mechanism, not proof that every writer uses it. Two other jj versions sit in the nix store and a third engine (jj-lib via pyjutsu) is already in use.
- A recent operation read is not a precondition. Measured: the current code's operation read is 0.2 ms before the mutation and the observed exposure is 80–100 ms.
- `jj op integrate` is not a compare-and-swap. It calls `update_op_heads` with no lock and no check.
- A non-zero jj exit code is not proof that nothing was published (jj #9408, exit 255 after publish).

---

## 9. The proposed interface

### 9.1 What CopyRoom must persist

The preview sidecar's 25 keys today are: `active_head, active_tree, answers, composer_digest, conflicts, layer, manifest_digest, marker_digest, next_render, old_render, owners, path, preview_head, preview_tree, project, project_id, record_metadata, render_digest, revision, schema, source, source_digest, templateer_digest, templateer_version, workspace`. TESTED — the sidecar and the per-workspace state file are byte-identical and both equal the JSON `update` prints.

With §5 and §4.3 applied, the identity material reduces to:

| Key | Meaning | Used for |
| --- | --- | --- |
| `active_head` | the `@` commit id at preparation, `H` | **the one precondition** |
| `prepared_head` | the prepared commit `P`, whose tree is the exact final tree **including the new marker** | the publication target |
| `next_render` | the new render commit | post-publication assertion |
| `journal_state` | `prepared` / `publishing` / `published` | recovery |
| `jj_capability` | the resolved jj or pyjutsu build and whether the guard is present | refusal and audit |

`active_tree` and `marker_digest` become redundant assertions. Keep `marker_digest` as a cheap single-file check; drop `active_tree` as a precondition, because it is the O(repo-size) false-refusal source (§1 defect 4).

### 9.2 D-B: the pyjutsu method

```python
ws.publish_if(
    expected_wc_commit: str,   # H, 40-hex
    onto: str,                 # P, the prepared commit
    description: str,
) -> str                       # the new operation id

# raises StalePublishError(observed_wc_commit=..., expected=...) and mutates nothing
```

Implemented in Rust, in **one** process, in this order — the order matters and is forced by §4.1:

1. `Workspace::start_working_copy_mutation()` — take `working_copy.lock` and hold it for the whole method.
2. `repo_loader.load_at_head()`, then `WorkingCopyFreshness::check_stale`. A stale working copy must not be snapshotted — reject with `stale-working-copy`.
3. `locked_wc.snapshot(...)` — **in memory only.** This publishes no operation and writes no state file.
4. If the snapshot tree differs from the working-copy commit's tree, the working copy is dirty: reject with `dirty-working-copy`, **without** snapshotting the writer's bytes into a commit. The writer's bytes stay on disk, untouched.
5. If the working-copy commit id is not `expected_wc_commit`, reject with `commit-moved`.
6. `tx.repo_mut().check_out(name, onto)` — a new empty child of `onto`, set as `@`, with the discardable old `@` abandoned; then `rebase_descendants`.
7. `tx.write(description)` → `UnpublishedOperation`; record its id and parent ids.
8. Take `op_heads_store().lock()`; verify `get_op_heads() == [the operation loaded at step 2]`; `update_op_heads(parent_ids, op_id)`; release. On mismatch reject with `op-heads-moved`.
9. `locked_wc.check_out(...)`, then `locked_ws.finish(op_id)`.
10. Release `working_copy.lock`.

Step 3 being in-memory is what makes the abort clean, and it is a better shape than the one I first sketched. `LockedWorkingCopy::snapshot` changes in-memory tree state and returns the tree; only `finish` writes the state file. Dropping the locked handle without `finish` therefore saves nothing. Reject reasons to expose to the caller: `commit-moved`, `dirty-working-copy`, `stale-working-copy`, `op-heads-moved`.

Three implementation traps:

- **Do not call `UnpublishedOperation::publish()` at all.** It takes the op-heads lock internally and then calls `update_op_heads` with no comparison, so the publish would be unconditional — the exact defect being fixed. Call `leave_unpublished()` to consume the `#[must_use]` handle, then do your own compare-and-swap publish. This is the same pair of calls `jj op integrate` makes, with the comparison added.
- **Never take the op-heads lock before the working-copy lock.** The CLI's own order is working-copy → op-heads, and reversing it risks deadlock against any concurrent snapshot.
- **Load the repo at head *after* taking the working-copy lock,** not before. Loading first would make the internal operation comparison compare against a value already stale by the time the lock is held.

### 9.3 Keeping CopyRoom's subprocess shape

CopyRoom calls jj as a subprocess everywhere. To avoid giving CopyRoom a native Python dependency, expose the method through a small pyjutsu entry point and call it the same way:

```
pyjutsu publish-if --repo <path> --expect-wc <H> --onto <P> -m <desc>
  exit 0  → stdout: {"operation": "<id>", "wc_commit": "<new @>"}
  exit 1  → stderr: stale; stdout: {"error":"stale","expected":"<H>","observed":"<id>"}
  exit 2  → infrastructure or config error
```

This maps onto CopyRoom's existing exit-code API (`0` ok, `1` decision, `2` infra, `3` usage) with no new conventions.

### 9.4 D-C: the jj flag, and the upstream proposal

If the guard goes into jj instead:

```
jj new --expect-working-copy <COMMIT_ID> <REVSET>
jj edit --expect-working-copy <COMMIT_ID> <REVSET>
```

Semantics: after the snapshot and before the transaction publishes, fail with exit 1 if the working-copy commit is not exactly `<COMMIT_ID>`, and mutate nothing. Pitch it upstream as **`--force-with-lease` for the working copy** — the precedent is `git push --force-with-lease` and it is the shortest route past the "the operation cannot fail to commit" design principle, because the flag is opt-in and changes no default.

Minimal library form to propose first:

```rust
impl UnpublishedOperation {
    pub fn publish_if_heads(
        self,
        expected: &[OperationId],
    ) -> Result<Arc<ReadonlyRepo>, PublishError>;
    // under op_heads_store.lock(): get_op_heads() must equal `expected`,
    // else PublishError::HeadsChanged { actual } and nothing is mutated
}
```

Honest limit to disclose in the proposal: `OpHeadsStore::lock` is documented as optional, so a custom store would need either a real lock or a new `compare_and_update_op_heads` default method.

Upstream tests the patch should extend, at `V43` paths:

- `lib/tests/test_operations.rs` — `test_concurrent_operations` (L131), `test_unpublished_operation` (L68)
- `lib/src/simple_op_heads_store.rs` — the `test_op_heads` unit test
- `lib/tests/test_local_working_copy_concurrent.rs` — `test_concurrent_checkout` (L35)
- `cli/tests/test_concurrent_operations.rs` — `test_concurrent_operation_divergence` (L23)
- `cli/tests/test_op_integrate_command.rs` — `test_integrate_sibling_operation` (L40), `test_integrate_concurrent_operations` (L185)
- `cli/tests/test_global_opts.rs` — the new flag
- `cli/tests/test_workspaces.rs` — `test_workspaces_update_stale_*` (L1223, L1293)

Likelihood: an opt-in library API is plausible; a default behaviour change is not. Precedent for scripting-oriented additions exists — `--no-integrate-operation` landed in 0.41.0 via PR [#8882](https://github.com/jj-vcs/jj/pull/8882), closing [#2562](https://github.com/jj-vcs/jj/issues/2562). **Do not make the plan depend on upstream acceptance.**

Two separate bug reports are worth filing upstream regardless of which design is chosen, because both are jj defects this investigation measured independently:

1. A direct file edit during the checkout phase is lost; `check_out` has no content guard. Related to the #9408 family.
2. The operation head file is written without `fsync` and no directory is fsynced, which matches the corruption report in #4423.

---

## 10. Vendomat packaging path

Nothing here was changed or deployed. These are the exact files and attribute paths a change would touch.

### 10.1 For D-B (recommended): ship the pyjutsu guard

1. **pyjutsu** — add the method and the `publish-if` entry point; tag a new version. First-party repo, no fork.
2. **Vendomat** — bump the `pyjutsu` input in `flake.nix:34` from `v0.22.0` to the new tag. `packages.<system>.pyjutsu` and `pyjutsu-wheel` already exist and rebuild from it; `repoman-toolchain-core` already joins it.
3. **nix-meta** — bump the Vendomat pin at `flake.nix:55` (currently rev `bd26fea8`) and re-lock. `machines/server.nix:68` already imports `inputs.vendomat.nixosModules.default`, and `profiles/developer.nix:15-16,171` already puts the toolchain on PATH.
4. **CopyRoom root devenv** — make the entry point reachable. Either add `vendomat` as a flake input in `devenv.yaml` and use `inputs.vendomat.packages.${pkgs.stdenv.system}.pyjutsu` in `dev/devenv.nix`, or import Vendomat's own devenv module and let its store mode read `/run/current-system/sw/share/vendomat/machine.json` (`vendomat/modules/devenv.nix:341-346`).
5. **CopyRoom consumer module** — `modules/copyroom.nix:44`: add a `copyroom.pyjutsuPackage` option, default `null`, and include it in `packages` when set. Consumers on stock tooling keep working in D-A mode (§11, step 5).

Important mechanic, CODE-READ: a `flake: false` input gives only a source tree, so it **cannot** carry flake outputs. CopyRoom's existing `flake: false` pattern therefore cannot deliver a shared package. Vendomat must be a **flake** input wherever a package attribute is consumed. The comment at `copyroom/devenv.yaml:18-20` already states the matching rule for imports: an import is a path inside an input and the file must be named `devenv.nix`.

### 10.2 For D-C: ship a custom jj

1. **Vendomat** — add a flake input `jujutsu = { url = "github:jj-vcs/jj?ref=refs/tags/vX.Y.Z"; flake = false; }` and build with `pkgs.jujutsu.overrideAttrs` (override `src` and `cargoHash`) or `rustPlatform.buildRustPackage`. Expose it as `packages.<system>.jujutsu` in the attrset at `flake.nix:299-315`.
2. **System default** — add `self.packages.${system}.jujutsu` to `environment.systemPackages` in `nixosModules.default` (`flake.nix:349`). Also add a `jujutsu` key to the machine manifest (`flake.nix:280`) so store-mode consumers can read an **absolute** path.
3. **nix-meta** — bump the pin at `flake.nix:55` and re-lock. Nothing else is needed; the module is already imported. Note this would be the first system-wide jj on this machine.
4. **CopyRoom root devenv** — `dev/devenv.nix:20`: replace `pkgs.jujutsu` with `inputs.vendomat.packages.${pkgs.stdenv.system}.jujutsu`; add `inputs` to the module arguments at line 7; add the flake input to `devenv.yaml`; run `devenv update`.
5. **CopyRoom consumer module** — `modules/copyroom.nix:44`: add `copyroom.jujutsuPackage` with default `pkgs.jujutsu`, and use `packages = [ cfg.package cfg.jujutsuPackage ];`.

### 10.3 Resolving the executable, in both designs

The PATH facts, TESTED:

- devenv **prepends** its profile, so a devenv binary shadows a system one. The Vendomat toolchain is appended **last** on purpose (`nix-meta/profiles/developer.nix:163-172`), so it never shadows anything. A system-default jj would therefore be shadowed by CopyRoom's devenv jj, not the reverse.
- A nested `devenv shell` replaces `DEVENV_*` and the `.devenv` paths, so the venv bin and profile entries change. Never run `devenv` inside a target repo with another project's config; `nix-meta/AGENTS.md` warns it overwrites that repo's `devenv.lock`. `devenv --dir` no longer exists in devenv 2.2.2+.
- No `jj` alias or wrapper script exists on this machine. `type -a jj` shows one entry. `~/.config/jj/config.toml` is config only.
- Three jujutsu versions beyond the active one sit in the nix store (0.41.0, 0.42.0, two distinct 0.43.0 derivations). **A version string does not identify a build — use the store path.**

Therefore: **CopyRoom must stop resolving jj by bare name.** Set `COPYROOM_JJ` to an absolute store path from the devenv module and the consumer module, resolve it once per process, and use that absolute path for every call. Today `jj.py:25-28` uses `shutil.which("jj")` only as an existence test and then re-resolves the bare name at spawn, which is a PATH time-of-check-to-time-of-use gap on top of everything else.

### 10.4 Capability check, and behaviour without it

Record in the journal, at every publication: the resolved executable's absolute path, its version, and whether the guard is present.

Probe, in order: read `COPYROOM_JJ` / `COPYROOM_PYJUTSU`; run the tool's version; then confirm the guard by invoking it in a way that must fail cleanly (for D-B, `publish-if` with a deliberately impossible expected commit against a scratch path, expecting the structured stale error; for D-C, check the flag is accepted). Do not infer the capability from a version number alone — two distinct 0.43.0 derivations exist.

**When the capability is absent: refuse by default.** `copyroom update --apply` and `copyroom layer add` exit **2** with a message naming the required build and the remediation. Provide one explicit opt-in — `--publish-unguarded` — which runs D-A, prints the weaker guarantee, and records `"guard": false` in the journal. Refusing by default makes the Vendomat rollout the forcing function; the opt-in keeps consumers of the importable module working on stock tooling.

### 10.5 Cadence and rollback

- **Cadence.** Bump pyjutsu (or the jj pin) deliberately, not on a schedule. pyjutsu's own `Cargo.toml:13-14` already states that the exact `jj-lib` pin is the API contract and that a bump is a deliberate port. Follow that rule.
- **Align the engines.** Today CopyRoom runs jj-lib 0.43 (via the CLI) and gitman runs jj-lib 0.44 (via pyjutsu) against the same repositories. The formats are compatible for this pair (TESTED both directions) but nothing pins them together, and jj offers no cross-version promise. Pin both from Vendomat to one jj-lib version. This is worth doing on its own merits.
- **Rollback.** Nix gives it for free: revert the pin in nix-meta and `nixos-rebuild` to the previous generation, and revert `devenv.lock`. CopyRoom's own rollback is the `--publish-unguarded` path plus the journal, which records which build published each result. Keep D-A working for exactly this reason — it is both the fallback and the rollback.

---

## 11. Recommendation

**Do §5 first, then D-B. Keep D-A as both the fallback and the rollback. Propose the guard upstream but do not depend on it.**

Ranked reasoning:

1. §5 (complete prepared result plus journal) is required by every candidate, needs no jj change and no new package, and by itself removes the silent-success window, the marker lost update, and ten of the twelve crash states. It is the largest correctness gain per unit of change in this report.
2. D-B gets the stated "reject before `@` moves" requirement with the **smallest enforceable contract** — one that jj's own working-copy lock enforces, with no cooperation from other writers — and with **no third-party fork**, because pyjutsu is first-party and every jj-lib API it needs is already public.
3. D-C is equivalent in behaviour and smaller in CopyRoom code, but costs a maintained jj fork against an upstream that documents the opposite principle. Choose it only if CopyRoom must stay CLI-only (see §13).
4. D-D, D-E and D-F are rejected for the reasons in §6. D-E would make things worse by hiding a writer's work.

### 11.1 The recommended handoff sequence

Preparation, `copyroom update` (no active mutation at any step):

1. Take `project_lock` — to serialise CopyRoom's own commands, and for nothing else.
2. Read `H = @` with a **snapshotting** read, once and deliberately. Read the render head.
3. Preflight: every render-owned path must be jj-tracked. Refuse otherwise (§12, change 9).
4. `jj workspace add --name copyroom-<id> -r <old_render> <out>`. Journal: `prepared`, with the workspace name and path, before anything else is written.
5. Write the render, commit it as `R1`.
6. `jj new H R1` in the preview workspace. Add the source snapshot and commit it when new.
7. **Write the exact next marker document into the preview workspace and commit it.** The preview tree is now byte-identical to the intended final active tree.
8. `P = @` in the preview workspace. Journal: `prepared`, with `H`, `P`, `R1`, and the resolved tool identity. fsync.
9. Human review happens here. No lock is held.

Publication, `copyroom update --apply`:

1. Take `project_lock`. Load the journal and the sidecar.
2. Cheap assertions: project identity, the preview has no unresolved conflicts, `P`'s tree equals the recorded prepared tree, `P`'s ancestry contains `R1` and `H`.
3. Journal: `publishing`, with `H`, `P` and the tool identity. fsync.
4. **One call:** `publish-if --expect-wc H --onto P`. It holds the working-copy lock across snapshot → compare → publish → checkout.
   - stale → exit 1, nothing mutated, the preview is kept, and the message names the observed `@`.
   - ok → the active `@` is an empty child of `P`; the active tree, including the marker, equals the reviewed tree exactly.
5. Assert: `@-` is `P`; the render head is `R1`.
6. Journal: `published`. fsync.
7. `jj workspace forget <ws>`; `rmtree(out)`; remove the state files. Each is idempotent.

`layer add` uses the same two phases. Give it a journal entry and a prepared head even when it stays a single command, so the L1 crash state (§3) becomes listable and recoverable.

### 11.2 The recovery sequence

`copyroom recover [--project P]` reads the journal and reconciles it against jj. Five cases, which is the whole matrix:

| Journal | jj state | Action |
| --- | --- | --- |
| `prepared` | `@ == H` | offer retry or `discard`. Nothing was published |
| `prepared` | `@ != H` | the project moved during review. Report it, keep the preview, and offer a fresh `update`. **Never** `op restore` |
| `publishing` | `@- != P` | the publish did not land. Same as `prepared` |
| `publishing` | `@- == P` | the publish landed and the process died before journalling. Finish: assert the render head, mark `published`, clean up |
| `published` | any | finish the cleanup. Idempotent |

Plus two orphan classes that the journal makes visible for the first time: a registered preview workspace with no journal entry, and a `$TMPDIR/copyroom-layer-*` directory. `copyroom recover --prune` forgets and removes them after naming them.

Two hard rules in the recovery code:

- **Never run `jj op restore` automatically.** It would hide a later writer's operations. Delete the existing dead branch (§2.3) rather than keeping it.
- **Never infer "nothing was published" from a non-zero exit.** Always re-read jj state. jj #9408 exits 255 after publishing.

### 11.3 What the recommendation does not claim

- It does not protect a file write that lands inside the checkout window. §16.4 gives the path-by-path account: a new file, an untouched file and a path the checkout *adds* all survive; **a file the checkout rewrites is silently overwritten**, and `jj status` then reports a clean working copy. That is lost in stock jj for any `jj new` (§4.2), and no design here changes it. Under heavy mid-checkout writing, 3 of 14 runs instead failed with the operation published and the working copy stale, recoverable by `jj workspace update-stale`.
- It does not prevent an operation-graph fork by a writer that had already loaded the previous operation. That writer publishes afterwards and jj merges; its work stays visible.
- It does not make publication durable against power loss. jj does not fsync the operation head file or any directory (§4.1, jj #4423).
- It does not cover a raw colocated `git` write, because the jj CLI takes `git_import_export.lock` and pyjutsu does not. That gap exists today, independent of this work.

---

## 12. CopyRoom changes, in dependency order

The line numbers below refer to the investigation baseline. Items 11 and 15 have landed. The other items remain open. Search the current code before editing.

| # | Change | Where | Why |
| --- | --- | --- | --- |
| 1 | Write the next marker into the preview workspace and commit it; delete the active-side marker write and its commit | `W:576-612`, `W:752-755` | §5. Makes publication one step |
| 2 | Add a journal (`prepared`/`publishing`/`published`) with fsync; write it before the first durable step | new, beside `_store_preview_state` `W:300` | §11.2. Makes crash states listable |
| 3 | Add `copyroom recover` with `--prune`; surface orphan workspaces and `copyroom-layer-*` dirs | `cli.py`, `W:799` | §3. Five crash states are currently invisible or unrecoverable |
| 4 | Replace the publication block with one guarded call | `W:700-757`, `W:421-443` | §11.1. Removes defects 1–3 |
| 5 | Give `layer add` a prepared head and a journal entry | `W:362-466` | §3. L1 is the worst crash state |
| 6 | Use `--ignore-working-copy` on all read helpers; snapshot exactly once, inside the guard | `jj.py:37-82` | §2.5. Reads currently mutate the repo and can make the preview stale |
| 7 | Remove the disk-wide `active_tree` precondition and post-publication `working_digest` equality check; compare jj-tracked trees for the reviewed result, and keep `marker_digest` as a cheap assertion | `W:669`, `W:713`, `W:266` | §4.3. An ignored file must not trigger a false refusal before or after publication. |
| 8 | Resolve jj/pyjutsu once by absolute path from `COPYROOM_JJ`/`COPYROOM_PYJUTSU` | `jj.py:25-28`, `W:892` | §10.3. Removes the bare-name PATH gap |
| 9 | Preflight that every render-owned path is jj-tracked; refuse otherwise with exit 1 | `_preflight_paths` `W:159` | §4.3. An ignored render path is invisible to the tracked-tree comparison. |
| 10 | Delete the `jj op restore` branch; never infer "nothing published" from a non-zero exit | `W:759-774`, `W:445-463` | §11.2. Dead in practice and dangerous if reached |
| 11 | **Done:** use a same-directory `.copyroom-tmp-` prefix, remove failed temporaries, fsync the parent, and backfill the ignore rule | `source.py`, `workflow.py` | Fixes §1 defect 3 without changing JSON bytes or atomic rename. Step 2 still needs to list orphan temporaries. |
| 12 | Add the capability probe and `--publish-unguarded` | `cli.py`, `W:880` | §10.4 |
| 13 | Make `status`/`inspect` flag a marker-versus-render-head mismatch | `W:821`, `W:868` | §2.3. `status` reports `ok: true` on a half-applied project |
| 14 | Apply the same publication path to adoption and workshop checkout | `manage.py:179`, `workshop.py:393` | They repeat the identical unconditional `jj new` |
| 15 | **Done:** fix `--version`, the default preview parent, relative `..` paths, `update-test` no-change, and the command examples | `cli.py`, `workflow.py`, `workshop.py`, `docs/user/` | §1 incidental defects 1–2 and related command failures |

Items 1–3 are independent of the chosen design and can land first.

---

## 13. Implementation plan

Each step is landable on its own and leaves the suite green. Acceptance tests are named per step. Run `devenv shell -- uv run pytest -q`, `devenv shell -- uv run ruff check src/ tests/`, and `devenv shell -- bash demo/walkthrough.sh` before landing. Keep the historical race and crash captures as evidence; do not use their old line numbers as current code locations.

### Step 1 — CopyRoom: complete prepared result (no jj or Vendomat work)

Open changes 1, 7, and 9. Change 11 is complete. Compare the prepared and published jj-tracked trees. A disk-wide digest includes ignored files and will still reject a valid apply after `jj new`. Acceptance:

- `test_prepared_tree_equals_applied_tree` — the preview tree digest equals the post-apply active tree digest, including the marker. This currently **fails by design**; the 2026-10-07 harness records `prepared_marker_hex != active_marker_after_hex`.
- `test_apply_performs_one_active_mutation` — count `JJ.run` calls with the project cwd that mutate; assert exactly one.
- `test_ignored_artifact_does_not_block_apply` — create `dist/x.whl` in the project after preview; apply must succeed.
- `test_ignored_render_path_is_refused` — a render-owned path ignored by jj must fail preflight before a preview workspace is created.
- Keep the existing `write_json` byte, mode, cleanup, fsync, ignore, and backfill tests green. A killed process may leave an ignored `.copyroom-tmp-*` file; Step 2 must report it.

Rollback: revert the commit. No external dependency.

### Step 2 — CopyRoom: journal and `copyroom recover`

Changes 2, 3, 5, 13. Start from the committed crash driver at `evidence/2026-10-08/harness/driver.py`. Adapt its hooks as Step 1 changes the publication calls. Acceptance:

- For each of A1–A6 and L1–L4: `copyroom recover` lists the state and returns it to either `prepared` or `published` with no manual jj command.
- `test_recover_preserves_competing_writer` — repeat the six paired writer runs (A1w…L3w); the writer's commit, file and uncommitted file must all survive every recovery path.
- `test_status_flags_half_applied` — after an A1 crash, `copyroom status` must not report `ok: true`.
- `test_recover_prune_lists_orphan_workspaces` — a crash after `workspace add` must be listable.
- `test_recover_lists_orphan_write_temporaries` — list ignored `.copyroom-tmp-*` files without treating them as managed project content.

Rollback: revert. The journal is additive and ignored by older code.

### Step 3 — pyjutsu: the guard

**A working prototype was tested** (§16). The committed `evidence/2026-10-08/prototype/` directory contains `full-diff.patch` and `publish_if_method.rs.txt`. The `/tmp/pj-proto-2714908/pyjutsu` copy was present during this update, but `/tmp` is not a durable source. Port from committed evidence and harden it. Carry in the six changes in §16.6. Delete `src/proto_hooks.rs`; it contains test barriers.

Add `publish_if` plus the `publish-if` entry point (§9.2, §9.3); tag a release. Acceptance, in pyjutsu's own suite — all of these are already demonstrated by the prototype and should be kept as regression tests:

- happy path: `@` becomes an empty child of `P`; exactly one new operation.
- stale on a committed foreign write: raises; **no** new operation; `@` unchanged; the foreign work intact.
- stale on a direct file edit: raises; the writer's bytes still reachable; name where.
- blocks on a held `working_copy.lock` (hold 3 s, start 0.5 s in, expect ~2.5 s).
- the full race sweep (144 runs in the prototype), each ending in exactly one of the two legal outcomes and never a third.
- **the `PJ_NO_CAS` comparison, kept as a test**: with the compare-and-swap removed, third outcomes must reappear. This is the only test that protects the compare-and-swap from being deleted as "redundant".
- cross-engine: a jj CLI 0.43 writer is correctly rejected or serialised.
- SIGKILL at each of the four points in §16.3: the lock is released, and the documented recovery applies.
- `sync_colocated` leaves git `HEAD` and the index consistent after a publish (§16.4).

Rollback: Vendomat keeps the previous pyjutsu tag.

### Step 4 — Vendomat and nix-meta: distribute it

§10.1 steps 2–3. Acceptance:

- `nix eval .#packages.x86_64-linux.pyjutsu.outPath` changes and builds.
- `share/vendomat/toolchain.json` records the new version.
- a clean login shell resolves the entry point by absolute path.
- Vendomat's existing `checks.<system>.vendomat-consumer-module` still passes.

Rollback: revert the pin; `nixos-rebuild` to the previous generation.

### Step 5 — CopyRoom: use the guard, with the capability gate

Changes 4, 6, 8, 10, 12. Acceptance:

- all of Step 1's tests still pass;
- `test_apply_rejects_before_at_moves` — barrier at the pre-publication point, release a committed foreign writer, assert exit 1 **and** that `@` is unchanged **and** that no new operation was published. This is the test that the current code cannot pass in 35 of 35 runs.
- the same test for each writer class in §2.4, including the two direct-write classes and the operation fork;
- `test_no_silent_success_window` — barrier at the former `W:709`–`W:755` window; assert the window no longer exists (one mutation only);
- `test_refuses_without_capability` — with the guard absent, `update --apply` exits 2 and names the remediation; `--publish-unguarded` exits 0 and records `"guard": false`;
- `layer add` gets the same matrix.

Rollback: `--publish-unguarded` restores Step 1 behaviour without a redeploy.

### Step 6 — upstream and alignment

Open the two jj bug reports (§9.4). Propose `publish_if_heads` as an opt-in library API. Separately, pin CopyRoom's jj CLI and pyjutsu's jj-lib to one version from Vendomat (§10.5). Neither blocks steps 1–5.

---

## 14. The remaining product decision

The evidence settles the mechanism. It does not settle one question, and that question is the user's:

**May CopyRoom depend on pyjutsu for the publication step?**

§16 removes the technical half of this question. D-B is built, compiles, and passes 144 races with no third outcome, using only public jj-lib API. D-C — the Vendomat-packaged custom jj named in the agreed architecture direction — is **no longer necessary to get the guarantee**, and it costs a maintained fork against an upstream that documents the opposite principle. I recommend dropping it as the primary route and keeping it only as a contingency if CopyRoom must stay CLI-only for a reason outside this report.

- If CopyRoom **may** depend on pyjutsu: D-B. The subprocess shape is preserved by the `publish-if` entry point (§9.3), so the cost is a packaging dependency, not a rewrite. CopyRoom calls one more executable, which it already does for jj.
- If it **may not**: D-C, with the §9.4 flag, and the fork maintained in Vendomat until upstream accepts it.

Note the shape of the dependency either way: Vendomat already builds pyjutsu as an `abi3` wheel and already joins it into `repoman-toolchain-core`, and gitman already depends on it. D-B adds no new component to the fleet.

Two smaller decisions follow from it:

1. **Default when the guard is absent:** refuse with exit 2 (recommended), or degrade to D-A with a warning. Recommending refusal makes the rollout the forcing function; it will also break any consumer of the importable module that is on stock tooling until they pin the Vendomat package.
2. **Is D-A alone enough?** D-A meets every underlying goal — exact reviewed tree, writer work always visible, no false success, recoverable crashes — and fails only the literal "reject before `@` moves". If the cost of a transiently moved `@` is acceptable (the observable consequence is that a file watcher or build daemon sees the tree flip, and that a reviewed result is published onto an unreviewed head), then steps 1–2 are the entire project and steps 3–5 are unnecessary. This is a genuine product call and the evidence cannot make it.

My recommendation on (2): do steps 1–2 now regardless, then decide 3–5 with the half-applied-state evidence in hand. Steps 1–2 are unambiguous wins and they are a prerequisite either way.

---

## 15. Evidence

All of today's captures are committed under `evidence/2026-10-08/`. The 2026-10-07 captures stay where they are, unchanged.

Every run used a **fresh disposable project** under `/tmp`, a real `copyroom` CLI child process, and real `jj` processes. Barriers are real FIFOs or sentinel files polled on a condition. Where a result depends on timing rather than a barrier, the report says so and gives the hit rate.

### 15.1 Layout

| Path | Contents |
| --- | --- |
| `race/versions.txt` | jj, copyroom, Python and Templateer versions and absolute paths for the race runs |
| `race/results.jsonl` | the 35 barriered T4 runs plus T1, T2, T3, T5, T6 |
| `race/results-t5x.jsonl` | the **silent-success** window: 6 runs, all exit 0 |
| `race/results-t5y.jsonl`, `race/results-d1x.jsonl` | two further windows; the operation-fork variant with no intervening repo load |
| `race/stress-reactive-b.jsonl` | 40 unbarriered runs triggered on the last read; 40/40 exit 1 |
| `race/stress-random-b.jsonl` | 40 unbarriered runs, writer delay uniform 0–1.5 s; 7 silent successes |
| `race/recovery.jsonl`, `race/reanalysis.jsonl` | post-failure retry and `copyroom status` output |
| `race/T4-*-r1/`, `race/T5x-a-r1/`, `race/T6-a-r1/` | per-run full captures: operation log, `log all()`, heads, `@` and `@-`, workspace list, tree digest, marker sha256 **and literal bytes**, sidecar dict, file set with contents, render head, preview existence, writer pids and argv, apply stdout/stderr/exit, the `JJ.run` trace with ordinals, and the barrier hit point |
| `crash/_digest.txt`, `crash/summary.json` | the 21-run crash matrix, exit codes and first message lines |
| `crash/A*.txt`, `crash/L*.txt` | per-crash captures plus the five CLI surfaces, recovery attempts and the manual recovery that worked |
| `crash/*.crashlog` | which call ordinal was matched for each injection |
| `verify/p1-*` | live versions, pytest, ruff, walkthrough, the literal constant values |
| `verify/p2*` | marker-tracking proof: `@` commit ids before and after each edit class |
| `verify/p3*` | shared-repo proof: operation head before and after `copyroom update`, and the full sidecar JSON with all 25 keys |
| `jj-upstream/e*.out`, `jj-upstream/s*.out` | the twelve jj timing-window experiments; `*_045.out` are the 0.45.1 repeats |
| `jj-upstream/cli.strace`, `jj-upstream/py.strace` | the `flock`/`openat`/`rename`/`fdatasync` traces that establish the lock order |
| `harness/` | `barrier_driver.py`, `lab.py`, `stress_driver.py` (race); `driver.py`, `harness.py` (crash) |
| `prototype/` | the `publish_if` prototype: method body, full diff, builds, race sweeps, crash runs, the write-during-checkout cases, and its own harness. Indexed in §16.7 |

### 15.2 How to reproduce

The harness scripts patch `copyroom.local.jj.JJ.run` in a child process and run the **real** CLI entry point, so they track live code rather than a copy of it. They need no change to CopyRoom. Run them inside the devenv:

```bash
devenv shell -- uv run --frozen --no-sync python <harness>/barrier_driver.py
```

`--frozen --no-sync` keeps uv from touching `uv.lock`.

The 2026-10-07 harness (`harness.py`, `test_handoff.py`, `jj_barrier.py`) remains usable. Two caveats carried forward: it intercepts jj only through a PATH wrapper, so an absolute-path jj bypasses it; and `jj_operation_races.py` calls raw `git init`, which breaks the repository's own rule against bare git.

### 15.3 Claims this report corrects

| 2026-10-07 claim | Correction |
| --- | --- |
| "latest stable jj is 0.45.1" | 0.46.0, released 2026-10-07. The concurrency core is unchanged from 0.43 |
| the bookmark-after-preview hole is "the main correctness hole" | it is harmless and should stay outside the precondition (§4.3). The real hole is the post-`jj new` window, measured here at 7 silent successes in 40 unbarriered runs |
| an uncommitted edit at the handoff barrier is swept in and apply reports success | refuted. 15 barriered runs all exit 1 — `jj new`'s snapshot becomes its own operation, so the parent check trips. The silent window sits slightly later |
| a jj change is required for a conditional publication | the primitive can be built from already-public jj-lib 0.44 API, with no jj change — see §16 |
| `jj workspace update-stale` recovers CopyRoom's crash states | no CopyRoom crash state produced a stale working copy. The word "stale" appears nowhere in the 21-run crash evidence |
| lane head `f248838635586561267c0ea55c425616f2e1d87b` | the lane has moved; see §1 |

One data-hygiene note carried forward: `evidence/focused-tests.txt` from 2026-10-07 is 0 bytes, and `ALTERNATIVES_2026-10-07.md` cites several evidence files by shorter names than the files actually have.

### 15.4 Reading the per-run captures

`apply.exit` is a one-byte exit code with no trailing newline. An empty `apply.stdout` or `apply.stderr` is a meaningful capture, not a failed one — a refused apply writes nothing to stdout, and a successful one writes nothing to stderr. Spot check:

```
T4-a-r1    exit=1  Error: apply overlapped a jj operation: expected parent operation d3200d1b…
T4-b-r1    exit=1  Error: apply overlapped a jj operation: expected parent operation a1619572…
T5x-a-r1   exit=0  (silent success — the foreign edit was swept in)
T6-a-r1    exit=0
```

---

## 16. D-B is proven, not assumed: the `publish_if` prototype

The recommendation in §11 rests on one claim that could not be settled by reading: that the guard is buildable from already-public jj-lib 0.44.0 API. It was built and tested. **It works.**

During the investigation, the prototype lived in a copy of pyjutsu at `/tmp/pj-proto-2714908/pyjutsu`. The durable patch and method body are committed in `evidence/2026-10-08/prototype/`. The real pyjutsu repository was only read during that investigation. The later incidental CopyRoom fixes did not implement this guard.

### 16.1 Build

| Step | Result |
| --- | --- |
| `cargo build --features pyo3/extension-module` | **compiled on the first attempt**, no errors, no warnings |
| `cargo clippy --all-targets -- -D warnings` | clean |
| the existing pyjutsu pytest suite | all pass |

**Nothing it needs is private.** Every jj-lib call is public at 0.44.0: `Workspace::start_working_copy_mutation` (`workspace.rs:446`), `LockedWorkspace::{locked_wc, finish}` (`:491, :495`), `LockedWorkingCopy::{snapshot, check_out, finish}` (`working_copy.rs:118, :124, :152`), `WorkingCopyFreshness::check_stale` (`:361`), `RepoLoader::{load_at_head, op_heads_store}` (`repo.rs:706, :698`), `ReadonlyRepo::start_transaction` (`:333`), `MutableRepo::check_out` (`:1613`), `Transaction::write` (`transaction.rs:135`), `UnpublishedOperation::{operation, leave_unpublished}` (`:209-240`), `OpHeadsStore::{lock, get_op_heads, update_op_heads}` (`op_heads_store.rs:48, :66, :71`).

So **D-C's jj fork is not needed to get D-B's guarantee.** That is the single most consequential result in this report.

### 16.2 Behaviour

All TESTED, with real subprocesses and FIFO barriers.

| Test | Result |
| --- | --- |
| happy path | exit 0; **exactly one** new operation ("publish_if: happy"); no `snapshot working copy` operation; `@` is an empty child of `P`; `diff P->@` empty; a following `jj status` adds no operation and reports no staleness |
| reject, committed foreign jj write (0.44 **and** 0.43 writers) | exit 1, `reason=commit-moved`; operation log unchanged; `@` unchanged; **the sha256 of every file under `.jj` identical before and after**; the foreign commit and file intact |
| reject, direct file edit | exit 1, `reason=dirty-working-copy`; **the writer's bytes still on disk**; operation log unchanged; the next ordinary `jj status` snapshots them into `@`, so they become reachable normally |
| lock blocking | an external holder kept `working_copy.lock` for 3.00 s; the call reached its pre-lock barrier at +0.70 s, was still waiting 1.0 s later with the operation log unchanged, and acquired at +3.00 s |
| **races** | see below |

The race sweep released the publisher and a jj CLI competitor against each other with the offset swept from −300 ms to +130 ms, classifying each run by exit code, operation log, commit topology, files, staleness and op-head count:

| Run set | Published, `@` empty child of `P`, competitor serialised after | Rejected, nothing of ours published, competitor intact | **Third outcome** |
| --- | --- | --- | --- |
| jj 0.44 competitor, 96 runs | 64 | 32 (23 `commit-moved`, 8 `op-heads-moved`, 1 `dirty-working-copy`) | **0** |
| jj 0.43 competitor, 48 runs | 32 | 16 (11 `commit-moved`, 4 `op-heads-moved`, 1 `dirty-working-copy`) | **0** |
| jj 0.44, **compare-and-swap disabled** | 64 | 24 | **8** |

144 races, no third outcome. The last row is the evidence that the internal compare-and-swap is load-bearing, and it is why §4.3 carries a correction.

### 16.3 Crash behaviour

| Kill point | State | Lock | Stale? | Recovery |
| --- | --- | --- | --- | --- |
| holding the lock, before publish | operation log unchanged | free immediately; an empty `working_copy.lock` file remains | no | none needed |
| operation written, before the compare-and-swap | operation log unchanged; orphan operation, view, index and commit objects remain as harmless garbage | free | no | none needed; `jj util gc` collects it |
| published, before checkout | the operation is in the log; the disk still holds the old files | free | **yes** | `jj workspace update-stale` exits 0 and fixes it |
| after checkout, before `finish` | files already written | free | **yes** | **messy** — `update-stale` exits 0 but prints `Attempted recovery, but the working copy is not stale`, resolves a divergent operation, and leaves a stray non-empty head. The final `@` is correct and **no data is lost** |

`flock` is released by process death, confirmed: immediately after the kill the lock was free and `jj status` did not hang.

The exact stale text, for CopyRoom's own messages to reference:

```
Error: The working copy is stale (not updated since operation cd3bcaa0f38f).
Hint: Run `jj workspace update-stale` to update it.
See https://docs.jj-vcs.dev/latest/working-copy/#stale-working-copy for more information.
```

### 16.4 The limits, measured precisely

This is where the prototype earns its keep: it turns "a direct write during checkout is unprotected" into a path-by-path account.

**A direct file write during the lock-held checkout phase.** The outcome depends on which path is written:

| Case | Outcome |
| --- | --- |
| a new untracked file | **survives**; absorbed into `@` at the next snapshot, so `@` is no longer empty |
| a file the checkout does not touch | **survives**; same absorption |
| a path the checkout *adds* | **survives** — jj's `can_create_new_file` (`local_working_copy.rs:778`) skips it; `publish_if` returns success and the next snapshot shows it modified |
| **a file the checkout *rewrites*** | **silently overwritten. Data loss.** `remove_old_file` plus rewrite is unconditional, and `jj status` afterwards shows a clean working copy |

Mid-checkout hammering, 25 000 files with a writer looping on two paths, 14 runs: 11 succeeded with the writer's last bytes winning and absorbed whole at the next snapshot; **3 failed** with `Failed to open file … for writing`, surfacing as "published but the working copy could not be checked out" (CLI exit 2) with the operation published and the working copy stale. `update-stale` recovered all three, but it first snapshotted the writer's file into a stray divergent commit and then overwrote it on disk.

**A lock-free writer that read the head before our publish and publishes after it** (an API transaction, or `jj --ignore-working-copy`). The compare-and-swap cannot see it. The result is divergent heads, which jj merges. In both tested variants `@` stayed our commit, and the stale writer's `jj new` commit survived as a stray visible head — so that writer's **`@` move** is lost while its **content** is not. No CLI writer triggered this in 144 runs, because a CLI writer takes the lock in its snapshot and reloads under it. The window exists and is small. INTERPRETATION: not reproduced deterministically.

**Colocated git is not synced.** `publish_if` leaves the git `HEAD` and index at the old parent; `git status` shows the new file as untracked. The caller must run `sync_colocated()`. This matters for CopyRoom, because `copyroom new` creates colocated projects (§1). The prototype's author notes the existing `PyTransaction::commit` path likely has the same gap — INTERPRETATION, worth checking in gitman too.

**A dirty abort is not byte-for-byte nothing.** It leaves three unreferenced git objects (two blobs and one tree) written by the in-memory snapshot. No commit, no operation, no state-file change. Harmless garbage.

### 16.5 The entry point

pyjutsu has **no** console script today — no `[project.scripts]` in `pyproject.toml` and no `__main__.py`. The prototype added one, and its exit codes already match CopyRoom's API:

```
python -m pyjutsu publish-if --repo DIR --expected <40-hex> --onto <40-hex> -m DESCRIPTION
  0  published; stdout: the new operation id
  1  precondition failed, nothing published; stdout: stale observed=<id> dirty=<0|1> reason=<reason>
  2  infrastructure error — including a published operation whose checkout failed
  3  usage error
```

Both ids must be full 40-hex; revsets and prefixes are rejected. Exit 3 for a missing argument and exit 2 for a non-workspace path are both confirmed.

### 16.6 What to carry into production

The prototype is a prototype. Before shipping:

1. **Remove `src/proto_hooks.rs`.** It exists only to provide FIFO barriers and the `PJ_NO_CAS` experiment switch. It must not ship.
2. **Add `sync_colocated` to the publication sequence**, or document that the caller must run it (§16.4).
3. **Decide the dirty-abort contract deliberately.** The prototype rejects *without* snapshotting, which keeps the writer's bytes on disk and is the right default. Offer the caller the alternative explicitly: call `ws.snapshot()` first if the foreign edit should be committed before the attempt.
4. **Add `[project.scripts]`** so the entry point is a real console script rather than `python -m`.
5. **Keep the 144-race sweep and the `PJ_NO_CAS` comparison as a regression test.** The compare-and-swap is easy to remove by accident and its absence shows up only under race.
6. **Garbage.** Rejections leave orphan operations, views, index files and commit objects. Document `jj util gc` as the cleanup, and do not let CopyRoom's own doctor report them as damage.

### 16.7 Prototype evidence

Committed under `evidence/2026-10-08/prototype/`.

| File | Contents |
| --- | --- |
| `publish_if_method.rs.txt` | the commented method body, 196 lines |
| `full-diff.patch` | the full diff against pyjutsu's tracked files |
| `__main__.py.txt`, `proto_hooks.rs.txt` | the new untracked files; `proto_hooks.rs` **must not ship** |
| `00-baseline-build.txt` … `04-existing-pytest.txt` | baseline build, both builds, clippy, the existing suite |
| `a-happy.txt`, `a-happy-colocated.txt` | happy path, plain and colocated (the colocated git gap is visible here) |
| `b-reject-committed-foreign-jj04{3,4}.txt` | rejection against both engine versions |
| `c-reject-dirty-file-edit.txt` | the clean abort — writer's bytes intact, operation log unchanged |
| `d-lock-blocks.txt` | the lock-blocking measurement |
| `e-race-jj04{3,4}.{txt,json}` | the 96- and 48-run sweeps |
| `e-race-jj044-NOCAS.{txt,json}` | the same sweep with the compare-and-swap disabled — 8 third outcomes |
| `crash-*.txt` | the four kill points of §16.3 |
| `h1`–`h5` | the path-by-path write-during-checkout account, including `h4-edit-file-checkout-rewrites.txt`, the data-loss case |
| `harness/` | `common.py`, `competitor.py`, `t_a_happy.py`, `t_bc.py`, `t_d_block.py`, `t_e_race.py`, `t_crash.py`, `t_limits.py`, `t_h5.py`, `t_h5_recover.py` |

The Rust source and the built artifact are **not** committed. The method body and the diff are enough to re-apply the change, and the build is reproducible from them.
