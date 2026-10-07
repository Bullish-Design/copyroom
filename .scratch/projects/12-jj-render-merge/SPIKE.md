# Spike — can jj replace Copier's three-way merge?

Run: `cd .scratch/projects/12-jj-render-merge && devenv test`
Environment: **jj 0.45.1**, Git 2.55.0, Python 3.13.14, in an isolated nested
devenv with `copier` deliberately absent. Recorded per run to
`$SPIKE_WORK/toolchain.txt`.

The design under test models a template render as a commit:

```
root
 |
 T0   render(template@v1, answers)     the scaffold; template files ONLY
 |\
 | \
 P   T1   render(template@v2, answers) T1 is a child of T0, NOT of P
 |   |
 \  /
  M = jj new P T1                      this is `update`
```

jj computes `merge-base(P, T1) = T0` from the graph. Nothing records it.

## Questions and results — all passed (57 assertions)

| # | Question | Result |
|---|----------|--------|
| Q8 | Is `render(template, answers)` byte-identical across runs? | Yes. Load-bearing, so it runs first and alone. Path segments template; an undefined variable is a hard error. |
| Q1 | Does jj merge a commit holding only a **subtree** of the project? | Yes. T1 never holds project files. jj treats them as additions on P's side, because they are absent from T0 too. |
| Q2 | Does `merge-base(P, T1)` equal T0? | Yes. **This is the field that replaces `_commit`.** |
| Q3 | Does a local edit to a template-owned file survive? | Yes. Non-overlapping edits to the same file merge with no conflict; both lines present. |
| Q4 | Does a file deleted between v1 and v2 get removed from trunk? | Yes (case A, untouched). Case B (project modified it) is a surfaced delete/modify conflict, with the project's edit preserved inside the markers. |
| Q5 | Is a conflict recorded in the commit, leaving other ops usable? | Yes. `conflicts()` matches the commit; `jj resolve --list` is authoritative. **Nothing was blocked** — status, log, diff, op log, new, commit, squash, rebase, describe all worked unresolved. |
| Q6 | Does jj reverse a merge completely? | Yes, byte-for-byte, via both `jj undo` and `jj op restore <id>`. Verified for content, modes, and absence of leftover paths — including from a *conflicted* merge. |
| Q7 | Does an n-parent merge converge layers, order-free? | Yes. A 3-parent merge converges two layers cleanly; both orders produce byte-identical trees. Converging one layer leaves the other at v1. |

## What this establishes

The design holds on every gate. These stop being code and become graph
properties:

1. **`_commit` in the answers file** → `merge-base`. The DAG knows which render
   is an ancestor of trunk.
2. **The clean-worktree guard** → unnecessary. jj has no dirty mid-operation
   state to protect.
3. **The `.rej` scanner and the inline `<<<<<<<` scan** → `jj resolve --list`
   and the `conflicts()` revset. A report can *ask* jj instead of parsing files.
4. **The preview sandbox** (temp copy, `_src_path` rewrite, baseline `git init`,
   patch emission) → `jj new P T1`, `jj diff --from P --to @`, `jj op restore`.
5. **Layer ordering and the commit-between-layers hack in `--all-layers`** →
   one n-parent merge. Independent convergence falls out of the graph, with no
   `-a` flag involved.

## Caveats and limits found

- **Fixture layers touch disjoint files.** Q7 does not show what happens when
  two layers edit the same path.
- **Q7 assumes the two layers are separate root-level lines.** Real layer
  templates may need a shared scaffold ancestor.
- **A conflicted commit's descendants stay conflicted** until resolved. The
  conflict propagates, but it never blocks.
- **`jj diff` on a merge commit is EMPTY** — a merge has no changes relative to
  its own auto-merged parents. A preview must use `jj diff --from <trunk> --to @`.
  Getting this wrong makes a working preview look like a no-op.
- **Conflict markers do materialise** in the working copy, in jj's format (with
  `%%%%%%%` / `+++++++` diff sections), not git's. A report may scan, but does
  not need to.
- **`jj undo` leaves `refs/jj/keep/<id>`** for the discarded preview commits.
  They are invisible and collectable, but the objects are not deleted.
- **Q8 proves the renderer's bytes, not jj tree-id equality.** Equality is
  expected, since jj tree ids derive from file bytes plus the exec bit, but it
  was not measured.

## Environment traps found — both nearly produced confident wrong answers

1. **`JJ_RANDOMNESS_SEED=0` corrupts jj.** jj 0.45.1 honours it. Every process
   then mints the same change-id, every commit shows `(divergent)`, and
   `jj new <T0>` dies with "Newly-created commit already exists" because the new
   empty commit matches an existing one in change id, parent, tree, author and
   timestamp. Combined with `>/dev/null` on construction calls, the spike built a
   linear chain instead of a diamond and reported a *false* Q2 failure. The
   determinism this design needs is of the renderer, not of jj's ids. Never pin
   it. `JJ_TIMESTAMP` is removed for the same reason.
2. **Scrubbing PATH to `$DEVENV_PROFILE/bin` exposed missing tools.**
   `find`, `grep`, `sed`, `awk` and `xargs` had been inherited from the host.
   The resulting `command not found` cascade read as seven failed jj
   experiments. `spike-versions` now asserts the whole toolbox resolves inside
   the profile.

Both failures shared one shape: **a broken precondition that looked like a
result.** The harness now refuses to be quiet about it — `jjq` aborts loudly on
any construction call, `require_dag` verifies the fork point before asserting,
`assert_parent` checks parent *identity* rather than arity, `assert_clean`
cross-checks two independent conflict signals, and `lib.sh` refuses to run at
all if the seed variables reappear.
