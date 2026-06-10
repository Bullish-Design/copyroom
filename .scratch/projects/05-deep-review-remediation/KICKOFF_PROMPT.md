# Kickoff Prompt — CopyRoom Deep-Review Remediation

> Paste everything below the line into a **clean session** opened at the repo root
> (`/home/andrew/Documents/Projects/copyroom`). It is self-contained: it assumes no memory of
> the review conversation. The agent's first job is to read the three planning docs, not to
> start editing.

---

## Who you are / what this is

You are an implementing engineer working in **CopyRoom**, a mode-aware CLI wrapper around
[Copier](https://copier.readthedocs.io/) (the project-templating engine that can *generate* a
project from a template and later *update* it via a three-way merge). CopyRoom adds workflow,
safety, a template-author's testing "workshop", and repo-adoption bootstrapping on top of
Copier. Source lives in `src/copyroom` (~7,700 LOC).

A deep code review was completed and turned into an ordered remediation plan. **Your task is
to execute that plan.** All of the thinking is already done and written down — follow it.

- **Repo:** `/home/andrew/Documents/Projects/copyroom`
- **Current branch:** `feat/v0.3.0` · **Current version:** `0.3.1`
- **Work branch:** create a child branch off `feat/v0.3.0`, e.g.
  `feat/deep-review-remediation`. Do **not** commit straight to `feat/v0.3.0`.

## Read these first (in order), before touching any code

1. `.scratch/projects/05-deep-review-remediation/CODE_REVIEW_REPORT.md` — the 14 findings,
   each with an ID (P1-1 … P3-7), severity tier, exact `file:line`, and why it matters.
2. `.scratch/projects/05-deep-review-remediation/REFACTORING_GUIDE.md` — **your script.**
   Phased, top-to-bottom, with concrete code for every fix and a finding→section map.
3. `.scratch/projects/05-deep-review-remediation/FIX_PROMPT.md` — the condensed order of work
   (the guide is the source of truth; this is the checklist).
4. Then skim `docs/developer/architecture.md`, `docs/developer/state-machines.md`, and
   `docs/developer/compat-layer.md` so the invariants below are concrete.

## Environment & tooling (important — this repo pins Python via devenv)

- **Always** run commands through the devenv shell, which pins Python 3.13. **Never** use
  ambient `uv`/`python`:
  ```
  devenv shell -- uv run ruff check src/ tests/
  devenv shell -- uv run pytest -q
  devenv shell -- bash demo/walkthrough.sh
  ```
- If you need me to run an interactive command, tell me to type it with a leading `!` in the
  prompt.

## Baseline gate (run before you start; it must be green)

```
devenv shell -- uv run ruff check src/ tests/
devenv shell -- uv run pytest -q             # expect 419 passing
devenv shell -- bash demo/walkthrough.sh     # exits 0
```

If the baseline is not green, stop and tell me — do not build on a red baseline.

## Architecture invariants (do not break these — they are the whole point of the codebase)

1. **Strict downward layering:** `cli.py` → `session/` → domain packages (`project/`,
   `template/`, `workshop/`, `release/`, `manage/`) → `_compat/`. Each layer depends only
   downward. The CLI never shells out; **everything that runs a subprocess (git/copier/shell)
   goes through `_compat/`.**
2. **Guarded lifecycles:** every workflow is a state machine. Change state **only** via
   `StateMachine.transition(...)`, never `entity.status = ...` ad-hoc. When you add/redirect a
   transition, update the matching `VALID_*_TRANSITIONS` table **and** the corresponding
   `.scratch/specs/*.allium` graph in the same change.
3. **One error type:** `CopyRoomError` (re-exported per module as `CreateError`, `RenderError`,
   etc.). Report-and-exit; forward the underlying tool's stderr; **never auto-roll-back**.
4. **Additive config:** `copyroom.project.yml` readers default every field and tolerate
   unknown fields. Never make config stricter.
5. **Scratch is isolated:** template edits → git worktrees on scratch branches in a cache;
   previews/sims/adopt → temp-dir copies. The user's real tree is never the workspace.
   Report-only commands must stay report-only.
6. **Trust gating:** template-supplied `post_*` hooks run only with `--trust` (via
   `_compat/shellcmd.py`); workshop registry `checks` run unconditionally by design.
7. **`_compat` git helpers fail soft** (`None`/`False`) on a missing binary — preserve that.

## The work, at a glance (full detail in the guide)

Execute the guide's phases in order. Summary of what you'll change:

- **Phase 1 — shared primitives first** (unblock the rest): new `_compat/conflicts.py`
  (marker/reject scanner), gitutil branch/worktree helpers (`checkout_new_branch`,
  `commits_ahead`, `worktree_remove`, `delete_branch`), and `atomic_write_text`.
- **P1-1 (§2):** move `new` into `BOOTSTRAP_COMMANDS` so it runs without `--mode project`.
- **P1-2 (§3):** add an `up_to_date` terminal state; a no-op `update` exits **0**, not 1.
- **P2-1 (§4):** replace `update.py`'s stdout-grep conflict detection with the shared scan.
- **P2-2 (§5):** make `patch` failures fatal + check the binary; replace the hand-rolled TOML
  writer (prefer `tomlkit`, else fail-loud); add `tests/unit/test_edits.py`.
- **P2-3 (§6):** default `check_passed=True`, add `UpdateSimulationResult.clean`, delete the
  flip gymnastics, gate the CLI "clean" message on `.clean`.
- **P2-4 (§7):** warn on a reused non-empty edit branch; add `copyroom template-discard`.
- **P3 (§8–§10, §13):** `create_branch` via gitutil; portable workshop sources
  (`resolve_source_for_copier` + relative `templatize` source — also fixes a latent
  relative-source bug); delete dead `main()` branches; atomic config writes.
- **Docs (§11–§12):** trust-and-safety (workshop checks), Copier `_tasks` limitation,
  worktree-exclusion comment, `test` vs `render`; optional `--trust` forwarding.

## Working agreement

- **TDD per finding:** write the regression test described in the guide's Phase 7 **first**,
  confirm it fails, then fix until green. Findings live on inputs the current fixtures don't
  exercise (bootstrap `new`, no-op `update`, describe-suffix `_commit` conflicts, the edits
  DSL's TOML/patch branches, relative workshop sources) — the conftest pattern for generating
  a project at a **post-tag commit** is in `tests/integration/conftest.py`.
- **Keep the gate green** before and after each section (`ruff` + `pytest -q`).
- **Commit in the logical groups** listed in the guide's Phase 8; keep the gate green per
  commit where practical.
- **Version bump to `0.4.0`** (in `pyproject.toml` and `src/copyroom/__init__.py`) as the
  **final** commit — P1-1/P1-2 and the new `template-discard` command change observable
  behavior, so this is a minor bump, not a patch.
- **No AI-attribution trailers** anywhere — commits, PR descriptions, code comments, docs.
  Omit `Co-Authored-By`/`Generated-with` entirely.
- **Update the demo:** drop `--mode project` from the `new` invocation in
  `demo/walkthrough.sh` (P1-1), and optionally exercise `template-discard` once.

## Stop and ask me if

- Adding **`tomlkit`** as a dependency is not acceptable — use the no-new-dep fail-loud
  fallback in §5 instead (don't decide silently).
- A fix would require changing a **state-machine graph** in a way the `.allium` spec doesn't
  already anticipate (beyond the documented `up_to_date` addition in §3).
- The **baseline gate is red**, or a guide step conflicts with what you find in the code
  (the line numbers in the report are from the reviewed branch and may have drifted).

## When done, report back

Tests added and passing (with the new total), the version bump, the commit groups you made,
and any finding you intentionally deferred (e.g. the §7 minimal variant that ships only the
reuse warning, or §12 `--trust` forwarding if skipped).

**Start now by reading the three planning docs and running the baseline gate. Then post your
intended branch name and confirm the baseline before making changes.**
