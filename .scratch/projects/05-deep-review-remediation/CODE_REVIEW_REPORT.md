# CopyRoom — Deep Review Report

**Branch:** `feat/v0.3.0` · **Package version at review:** `0.3.1`
**Scope:** whole-library read — `cli.py`, `session/`, `project/`, `template/`, `workshop/`,
`release/`, `manage/`, `_compat/` (~7,700 LOC of `src/copyroom`).
**Method:** full-tree read of every source module + architecture/dev docs, cross-checked
against the test suite (419 tests, green; `pytest -q` exit 0) and `demo/walkthrough.sh`.

The architecture itself is sound and unusually consistent (strict downward layering;
one `model.py` + workflow-module + `StateMachine` per domain; report-only/scratch-isolation
safety model; trust-gated hooks; additive config). The findings below are mostly at the
**product-behavior** level, not code craft. Nothing here is caught by the current suite —
each lives on a path the fixtures don't exercise (bootstrap `new`, no-op `update`,
describe-suffix conflicts, the edits DSL's TOML/patch branches, relative workshop sources).

---

## Severity legend

| Tier | Meaning |
|------|---------|
| **P1** | Wrong/surprising behavior on the most common path — fix first. |
| **P2** | Correctness or contract issue on a reachable, narrower path. |
| **P3** | Cleanup / latent trap / layering — no wrong result today. |

---

## P1 — most-common-path behavior

### P1-1 · `copyroom new` cannot bootstrap itself — always needs `--mode project`
**Files:** `src/copyroom/session/model.py:62` (`new` ∈ `PROJECT_COMMANDS`),
`src/copyroom/cli.py:881-907` (dispatch flow).

`new` is gated as a project command, so dispatch requires project markers
(`.copier-answers.yml` / `copyroom.project.yml`) to *already* exist. But `new` is run to
**create** a project, so those markers don't exist yet (unless you're nested inside an
existing project). Every real invocation proves it: tests pass `--mode project`
(`tests/integration/test_cli.py:56,65`) and the demo does too (`demo/walkthrough.sh:227`),
and the demo shows bare `copyroom new` *failing* in an empty dir (`walkthrough.sh:135`).

**Why it matters:** the single most fundamental command doesn't work out of the box. It is
inconsistent with `adopt`/`templatize`, which correctly bypass detection via
`BOOTSTRAP_COMMANDS` and "resolve their own context from the repo and arguments" — exactly
what `new` does (it takes an explicit `source` + `target`).

**Fix direction:** move `new` into `BOOTSTRAP_COMMANDS` (runs anywhere; the empty-target
check is the real guard). See guide **§2**.

---

### P1-2 · A no-op `update` exits non-zero
**Files:** `src/copyroom/project/update.py:172` (`no_update_available`),
`src/copyroom/cli.py:228-247` (`_cmd_update`).

When the project is already at the target version, `no_update_available` transitions
`config_loaded → failed`; the CLI prints "Already at the latest version… nothing to update"
and then `sys.exit(1)`. An idempotent "nothing to do" reported as a **failure** breaks
scripting/CI on the common case (`copyroom update` in a Makefile/loop). Root cause is a
spec gap: `UpdateStatus` has no "up-to-date" terminal, so a no-op is forced through
`failed`.

**Fix direction:** add an `up_to_date` terminal state; treat it as success (exit 0) with the
existing friendly message. See guide **§3**.

---

## P2 — reachable narrower paths

### P2-1 · The real `update` path has the weakest, most fragile conflict detection
**Files:** `src/copyroom/project/update.py:496-512` (`_capture_conflicts_from_output`) vs.
`src/copyroom/template/preview.py:200-218` and `src/copyroom/workshop/simulate.py:467-473`.

`preview` and `simulate` detect conflicts robustly (scan changed files for
`<<<<<<<`/`>>>>>>>` markers + collect `*.rej`). But the production `update` command just
greps Copier's **stdout** for the substring `"conflict"` (case-insensitive). That is brittle
against Copier's wording/version and misses inline merge markers Copier writes silently. The
command that matters most has the weakest reporting.

**Fix direction:** extract a shared marker/reject scanner into `_compat`; after `copier
update` (worktree was verified clean first), scan the now-dirty files for markers. See guide
**§1** + **§4**.

---

### P2-2 · The edits DSL is the riskiest code and the least tested
**File:** `src/copyroom/workshop/edits.py` (27% coverage — lowest in the repo).

- `_apply_patch` (`:317`) shells out to the system **`patch`** binary — an undeclared,
  non-portable dependency — and on failure only prints a warning and **continues** (`:340`).
  A failed patch silently yields a wrong `update-test` simulation.
- `_set_toml_*` (`:250-301`) is hand-rolled string manipulation that won't survive inline
  tables, comments mid-section, arrays-of-tables, or quoted keys — yet it feeds the
  simulation path, so a botched edit produces a *misleading* result that looks
  authoritative.

Coverage is inverted relative to risk: pure/simple modules are ~100%; the gnarliest
string-manipulation code is lowest.

**Fix direction:** make patch failures fatal + check `patch` availability up front; replace
the TOML writer with `tomlkit` (or fail loudly on unsupported constructs); add per-action
tests. See guide **§5**.

---

### P2-3 · `UpdateSimulationResult.check_passed` defaults to `False` — a footgun, and the
CLI's "clean" message ignores conflicts
**Files:** `src/copyroom/workshop/model.py:40`, `src/copyroom/workshop/simulate.py:284-355`,
`src/copyroom/cli.py:653-662`.

Because the default is "checks failed," `simulate.py` must *manually flip it true* in three
places (`:286,:298,:348`), rebuilding the result dataclass repeatedly. Separately, the CLI
prints "✅ Update applied cleanly — no conflicts" whenever `check_passed` is true **without
checking `conflicts`/`rejects`** — so a conflicted update with passing checks is mislabeled
clean.

**Fix direction:** default `check_passed=True`; add a derived `clean` property
(`check_passed and not conflicts and not rejects`); gate the CLI message on it; delete the
flip gymnastics. See guide **§6**.

---

### P2-4 · Stale scratch edit-branches silently resurface; no discard/cleanup
**Files:** `src/copyroom/template/workspace.py:169-187`.

The edit worktree/branch `copyroom/edit/<slug>` is reused idempotently across runs
(`worktree_add` attaches to an existing branch). Commits from an **abandoned** prior edit
session reappear in the next `template-test`/`template-preview` with no warning, and there is
no command to reset them.

**Fix direction:** warn when reusing a branch that has commits beyond its base; add a
`template-discard` command. See guide **§7**.

---

### P2-5 · Workshop `checks` run untrusted shell commands with no gate (doc gap)
**Files:** `src/copyroom/workshop/render.py:194`, `simulate.py:303`, `release/check.py`
(matrix), vs. the carefully-gated `_compat/shellcmd.py`.

Registry `checks` run with `shell=True` and **no** trust gate (correctly, by design — "the
author's own commands"). But the trust boundary therefore assumes *you authored/vetted the
workshop you're standing in*. Cloning a third-party workshop and running
`render`/`release-check` executes arbitrary registry commands. The template-hook gate is
carefully built; this adjacent surface is closed only by understanding — and the docs don't
say so.

**Fix direction:** make the boundary explicit in `trust-and-safety.md`. See guide **§11**.

---

## P3 — cleanup / latent traps

### P3-1 · `update.create_branch` shells out to git directly, bypassing `_compat`
`src/copyroom/project/update.py:250` calls `subprocess.run(["git","checkout","-b",...])`
inline — the one place the otherwise-airtight `_compat` boundary leaks (architecture
invariant #1). See guide **§8**.

### P3-2 · `templatize` bakes an absolute source path into the registry (and relative
workshop sources are a latent bug)
`src/copyroom/manage/templatize.py:175` writes `source: {home}` (absolute). Move/re-clone
the template repo and the registry dangles. The deeper issue: the copier-facing callers
(`render`/`golden`/`simulate`/`release`) pass the registry `source` straight to `copier
copy` **without resolving relative paths against the workshop root**, so a relative source
only works when `cwd == workshop root`. See guide **§9**.

### P3-3 · Dead/unreachable branches in `cli.main()`
`cli.py:892` re-checks `unknown_mode` after dispatch, but `_detect_and_report` already
`sys.exit(1)`s on it (`:144`); `cli.py:905` guards `handler is not None`, but dispatch has
already validated the command exists. Harmless, but obscures control flow. See guide **§10**.

### P3-4 · CopyRoom never forwards `--trust` to Copier (Copier `_tasks` silently no-op)
`_compat/copier.py` never passes `--trust`, so a template's own Copier tasks/migrations
don't run. Appears intentional (CopyRoom has its own hooks) but is undocumented as a
limitation. See guide **§11** (doc) / **§12** (optional forwarding).

### P3-5 · The two worktree-cleanliness checks disagree on exclusions
`update.verify_worktree` (`update.py:207`) excludes nothing; `release-check` excludes
`generated/`/`.copyroom_sim/` (`release/check.py:143`). The difference is intentional
(Copier needs a truly clean tree to update) but uncommented. See guide **§11** (comment).

### P3-6 · Non-atomic config writes
`registry.add_template` (`registry.py:246`) and `edits._set_field_*` write in place
(`write_text`); a crash mid-write corrupts the file. Add a tiny atomic-write helper. See
guide **§13**.

### P3-7 · `copyroom test` is a silent alias of `render` (no golden)
`cli.py:561` — `_cmd_test` just calls `_cmd_render`. Documented in the docstring but a user
expecting "test" to be stronger than "render" (e.g. to run golden) is surprised. Clarify in
help text + cli-reference. See guide **§11**.

---

## Quick index

| ID | Title | Tier | Fix § |
|----|-------|------|-------|
| P1-1 | `new` can't bootstrap (needs `--mode`) | P1 | §2 |
| P1-2 | no-op `update` exits non-zero | P1 | §3 |
| P2-1 | fragile stdout-grep conflict detection in `update` | P2 | §1, §4 |
| P2-2 | edits DSL: `patch` dep + silent fail + hand-rolled TOML + untested | P2 | §5 |
| P2-3 | `check_passed` default footgun + "clean" ignores conflicts | P2 | §6 |
| P2-4 | stale edit-branches resurface; no discard | P2 | §7 |
| P2-5 | workshop checks untrusted (doc gap) | P2 | §11 |
| P3-1 | `create_branch` bypasses `_compat` | P3 | §8 |
| P3-2 | absolute registry source + relative-source bug | P3 | §9 |
| P3-3 | dead branches in `main()` | P3 | §10 |
| P3-4 | `--trust` not forwarded to Copier | P3 | §11, §12 |
| P3-5 | worktree-clean exclusion disagreement | P3 | §11 |
| P3-6 | non-atomic config writes | P3 | §13 |
| P3-7 | `test` is an alias of `render` | P3 | §11 |
