# Fix Prompt — CopyRoom Deep-Review Remediation

Paste this to an implementing agent to execute the remediation.

---

You are working in the CopyRoom repo on a child branch off `feat/v0.3.0`. Your job is to
remediate the findings in `.scratch/projects/05-deep-review-remediation/CODE_REVIEW_REPORT.md`
by following `.scratch/projects/05-deep-review-remediation/REFACTORING_GUIDE.md`
**exactly, in order**. Read both files first, plus `docs/developer/architecture.md`,
`state-machines.md`, and `compat-layer.md`.

**Hard rules:**
- Run everything via `devenv shell --` (pins Python 3.13). Never ambient `uv`/`python`.
- Before starting and after every section: `devenv shell -- uv run ruff check src/ tests/`
  and `devenv shell -- uv run pytest -q`. Keep the gate green.
- For each finding, **write the regression test first** (it must fail), then fix until green.
- Workflows are guarded state machines: change state only via `StateMachine.transition`, and
  update the matching `VALID_*_TRANSITIONS` table + `.scratch/specs/*.allium` together. Never
  assign `entity.status =` ad-hoc.
- All subprocess/git/copier work goes through `_compat/`. Git helpers fail soft.
- One error type: `CopyRoomError`. Report-and-exit; forward the tool's stderr; never
  auto-roll-back.
- Config stays additive (defaults + tolerate unknown fields).
- **No AI-attribution trailers** in commits, PRs, code, or docs.

**Order of work (guide sections):**
1. **Phase 1 / §1** — shared primitives: `_compat/conflicts.py`, gitutil branch+worktree
   helpers, `atomic_write_text`. (Unblocks §4, §6/§7, §13.)
2. **§2 (P1-1)** — move `new` into `BOOTSTRAP_COMMANDS`; update help text + spec; add a test
   that `new` works without `--mode`.
3. **§3 (P1-2)** — add `up_to_date` terminal state; no-op `update` exits 0; update spec.
4. **§4 (P2-1)** — replace the stdout-grep conflict detection in `update.py` with the shared
   marker/reject scan over post-update dirty files.
5. **§5 (P2-2)** — make `patch` failures fatal + check the binary; replace the hand-rolled
   TOML writer (tomlkit preferred, else fail-loud); add `tests/unit/test_edits.py`.
6. **§6 (P2-3)** — default `check_passed=True`, add `UpdateSimulationResult.clean`, delete
   the flip gymnastics, gate the CLI "clean" message on `.clean`.
7. **§7 (P2-4)** — warn on reused non-empty edit branch; add `copyroom template-discard`.
8. **§8–§10, §13 (P3)** — `create_branch` via gitutil; portable workshop sources
   (`resolve_source_for_copier` + relative `templatize` source); delete dead `main()`
   branches; atomic config writes.
9. **§11–§12** — docs: trust-and-safety (workshop checks), Copier `_tasks` limitation,
   worktree-exclusion comment, `test` vs `render`; optional `--trust` forwarding.
10. **Phase 7/8** — land all regression tests; run the verification ritual incl.
    `demo/walkthrough.sh` (drop `--mode project` from its `new` call); bump version to
    **0.4.0** as the final commit.

Commit in the logical groups listed in the guide's Phase 8. Stop and ask if any fix would
require changing a state-machine graph in a way the spec doesn't anticipate, or if adding
`tomlkit` as a dependency is not acceptable (use the no-new-dep fallback in §5 instead).

When done, report: tests added/passing, the version bump, and any finding you intentionally
deferred (e.g. the §7 minimal variant, or §12 if skipped).
