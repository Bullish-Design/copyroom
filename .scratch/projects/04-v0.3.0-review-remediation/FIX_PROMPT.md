# Kickoff prompt — v0.3.0 review remediation

Copy everything in the fenced block below into a fresh CopyRoom session to start the fixes.
It is self-contained: it points the agent at the report + guide and the developer docs, and
encodes the conventions and acceptance criteria.

---

```
# Task: remediate the v0.3.0 code-review findings on CopyRoom

You're working on **CopyRoom**, a mode-aware CLI wrapper around Copier
(/home/andrew/Documents/Projects/copyroom). A code review of the `feat/v0.3.0` branch
(PR #1) produced a report and a step-by-step refactoring guide. Your job is to execute that
guide. **Read these three files first, in order:**

1. `.scratch/projects/04-v0.3.0-review-remediation/CODE_REVIEW_REPORT.md` — the findings
   (P1 = merge-blockers, P2 = fix soon, P3 = cleanup), each with file:line and a fix
   direction.
2. `.scratch/projects/04-v0.3.0-review-remediation/REFACTORING_GUIDE.md` — the ordered
   remediation plan (Phases 0–6). Follow it top to bottom.
3. The developer docs it references: `docs/developer/architecture.md`,
   `state-machines.md`, `compat-layer.md`, `module-reference.md`, and
   `docs/developer/contributing.md`.

Then skim the modules under review: `src/copyroom/project/{config,create,update,inspect}.py`,
`src/copyroom/workshop/registry.py`, `src/copyroom/_compat/{gitutil,semver}.py`.

## Branch & version
Work on `feat/v0.3.0` (the PR branch) or a child branch off it. The package STAYS at
**0.3.0** — these are pre-release fixes to an unmerged branch, not a new release. Do not
bump the version.

## Hard conventions (do not violate)
- Run everything via `devenv shell --` (pins Python 3.13). Never ambient `uv`/`python`.
- Gate green BEFORE and AFTER every change: `uv run ruff check src/ tests/` and
  `uv run pytest -q` (currently **448** passing — keep them green and add new ones).
- Workflows are guarded state machines: transition only via `StateMachine.transition`,
  never assign `entity.status =`. Pure read-only commands may return a result dataclass
  (no machine) — keep that pattern.
- All subprocess/git/copier work goes through `_compat/`; git helpers fail soft
  (`None`/`False`) on a missing binary. No `subprocess.run("git"/"copier")` above `_compat`.
- One error type: `CopyRoomError` (re-export per module). Report-and-exit; forward the
  tool's stderr; never auto-roll-back.
- **Config evolution stays additive**: new fields default, unknown fields tolerated. This
  invariant is the heart of finding P1-1 — honor it.
- Keep `.scratch/specs/*.allium` and `docs/` accurate for every behavior change.
- **No AI-attribution trailers** anywhere (commits, PRs, code comments, docs). Omit
  Co-Authored-By / "Generated with" entirely.

## Method
Use a TaskList. For each finding: **write the regression test first** (it should fail
against current code), then apply the fix from the guide, then confirm it passes. Work the
guide's phases in order — Phase 1 (shared `_compat` primitives + the single registry
loader) unblocks several later fixes, so do it first.

## Scope & priority
- **Required (merge-blockers): P1-1, P1-2, P1-3.**
- **Strongly recommended in the same pass: P2-4 … P2-8** (small; P2-7 is the same change as
  P1-1, and P2-5 falls out of the registry loader refactor).
- **P3-9, P3-10** are cleanups that also remove the latent traps behind P2-5 and a
  missing-timeout in `verify_worktree` — do them if you're in the code, or split into a
  follow-up commit. Confirm with me if you want to defer them.

Do NOT change the public signatures of `resolve_template_source` / `load_checks` /
`list_templates` / `load_entry` (other modules and tests import them) — back them with the
new single loader instead.

## Acceptance criteria
- [ ] P1-1: a `copyroom.project.yml` with an invalid value for a known field (e.g. a future
      `project.kind`) no longer aborts `new`/`update`; hooks still run/skip correctly;
      truly unparseable YAML / non-mapping still errors.
- [ ] P1-2: a project whose `_commit` is a `git describe` string (`vX.Y.Z-N-gsha`) at the
      latest tag is a clean no-op for no-arg `update` and reports `update_available: false`
      in `status`. One shared `same_version` helper backs both call sites.
- [ ] P1-3: `registry add` refuses an id already defined in `copyroom.yml` (no shadowed
      file); P2-4: the written entry round-trips special characters (YAML-dumped).
- [ ] P2-5: a `registry:`-keyed workshop reports non-empty `checks`. P2-6: a `~/...` local
      source resolves. P2-7: configured post-update hooks are never silently skipped on a
      bad config. P2-8: a failed latest-ref resolution leaves the entity in `failed`.
- [ ] (if done) P3-9: one `gitutil.worktree_clean`; P3-10: `copyroom.yml` parsed once per
      command via a single `load_registry`.
- [ ] Ruff clean; full suite green (new regression tests included); docs + specs updated;
      version unchanged at 0.3.0; no AI-attribution trailers.

## Final verification
    devenv shell -- uv run ruff check src/ tests/
    devenv shell -- uv run pytest -q
    devenv shell -- bash demo/walkthrough.sh

Commit in logical groups (the guide's Phase 6 suggests a sequence). Then report what
changed and which findings remain (e.g. any P3 deferred).
```
