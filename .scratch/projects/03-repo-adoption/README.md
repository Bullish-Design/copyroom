# 03 — Repo adoption (templatize + adopt)

**Status:** Implemented (2026-06-09) — `copyroom templatize` / `adopt` shipped;
the repo is also packaged as an importable devenv module (`modules/copyroom.nix`).
**Date:** 2026-06-09
**Purpose:** Self-contained context for implementing the "turn a non-CopyRoom repo
into a CopyRoom-managed repo" feature. This directory is the entry point for a fresh
session: read these three docs, then build.

## Read in this order
1. **`CONCEPT.md`** — what the feature is, why, and every locked design decision (with
   the rationale and the alternatives that were rejected).
2. **`IMPLEMENTATION_PLAN.md`** — the concrete build plan: components, file targets,
   reuse map, mode-gating change, test matrix, and the verification spike to do first.

## Where this sits in the codebase (as of this writing)
- Last shipped commit: `3b78570` — the **template-edit feature** (`copyroom
  template-checkout/test/preview`). Adoption reuses its engines heavily, so skim it:
  - `src/copyroom/template/` (workspace/validate/preview, state-machine models)
  - `src/copyroom/_compat/gitutil.py` (git helpers)
  - `src/copyroom/_compat/copier.py` (`copier_copy` now takes `vcs_ref`)
  - `tests/integration/test_template_edit.py` (the testing pattern to mirror)
- Tests currently green: **376 passed**, `ruff` clean across `src/` and `tests/`.
- Run gates: `uv run ruff check src/ tests/` and `uv run pytest -q`.

## First action when implementation starts
Do the **Copier non-git-dir spike** described in `IMPLEMENTATION_PLAN.md` →
"verification". The whole extraction loop's ergonomics depend on whether `copier copy`
renders a plain (non-git) local directory's working tree. Confirm before building the
golden loop.

## Prior project dirs for reference
- `../01-concepting/` — original CopyRoom concept.
- `../02-implementation-planning/` — the v0.1 implementation plan + Allium specs
  (`.scratch/specs/`).
