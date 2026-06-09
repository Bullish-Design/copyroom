# Concept: Adopt / templatize an existing repo

**Status:** Locked (decisions confirmed with the user)
**Date:** 2026-06-09

## The need

CopyRoom assumes a project is *born* from a template (`copyroom new`). There is no
on-ramp for an existing, hand-written repo. This feature adds one: a skill (+
deterministic CLI primitives) that takes a **non-CopyRoom repo and makes it managed**.

"Managed" has two senses in CopyRoom (both encoded in `session/detector.py`):
- a **project** — has `.copier-answers.yml`, linked to a template, can receive
  `copyroom update`s;
- a **workshop** — the authoring/test bench for a template (`copyroom.yml` +
  `registry/` + `scenarios/`).

## What we're building: interpretation **C** (bootstrap + adopt)

Two entry paths that converge on one ending:

```
unmanaged repo R
├── user NAMES a template T   → ADOPT(T)
└── NO template               → TEMPLATIZE(R)  → parameterize to golden no_diffs
                                → git init + tag v0.1.0 → ADOPT(extracted template)
```

Because extraction produces a template that already reproduces R, the final adoption is
near-zero-drift. Both paths end in the same `adopt` primitive.

The current CopyRoom model has **three artifacts**, and a workshop *references* a template
rather than containing it (`copyroom.yml` `templates.<id>.source`). Extraction therefore
produces all three: a **template repo**, a **workshop** that exercises it, and R turned
into a **managed project**.

## Locked decisions (and why)

1. **Interpretation C — bootstrap + adopt.** The full "make it managed" arc, not just
   adopt-under-existing (A) or templatize-only (B). C = B then A.

2. **Template is NAMED or EXTRACTED — never agent-proposed.** No fuzzy template-matching
   or registry suggestion. Either the user points at a template, or one is derived from
   the repo. (User was explicit: "Never need/want an agent to propose a template.")

3. **Extracted template = self-contained sibling repo with embedded workshop ("Home A").**
   Uses Copier's `_subdirectory: template` so workshop files (`scenarios/`, `golden/`)
   aren't rendered into generated projects. Chosen over "separate workshop dir" (Home B)
   and "build-in-cache-then-relocate" (Home C) because it yields the artifact people
   actually keep — one shippable, CI-testable template repo — and slots straight into the
   existing `source`/registry model.
   ```
   R/                     # → managed project
   R-template/            # NEW: copier.yml (_subdirectory: template) + template/ + workshop at root
     copier.yml
     template/ {{project_name}}/… + .copier-answers.yml.jinja
     copyroom.yml         # registry: <id>.source = <abs path to R-template>
     scenarios/<id>/default.yml   # answers reproducing R
     scenarios/<id>/probe.yml     # over-parameterization sanity render
     golden/<id>/default/         # snapshot of R (convergence target)
   ```

4. **Fidelity: report-only adoption + probe-scenario guard during extraction.**
   - *Report-only:* adoption writes `.copier-answers.yml` and a drift patch but **never
     rewrites the repo's files** (same philosophy as `template-preview`). Drift is
     information; the repo legitimately has extra/divergent content.
   - *Probe guard:* the golden loop proves the template reproduces R **for the default
     answers**, but can't catch *over*-parameterization (a var substituted too broadly
     that still renders right for one answer set). A second `probe.yml` scenario with
     different answers surfaces over-broad substitutions as obviously-wrong output for the
     agent to review. It has **no golden** (R is ground truth only for default answers),
     so it's a review/sanity render, not an automated pass/fail.

5. **Same split as prior features:** CopyRoom owns deterministic/testable steps; the agent
   owns judgment.
   - *Agent:* infer & **confirm** answers from R; decide what to parameterize; run the
     golden loop; author/review the probe; name the template; reconcile/explain drift.
   - *CopyRoom:* scaffold Home A; render-with-answers; tree-diff (drift); write
     `.copier-answers.yml`; snapshot golden.

## The elegant reuse

- **Extraction *is* the golden loop.** Scaffold a workshop whose golden is a snapshot of
  R; the agent parameterizes `template/` until `copyroom golden` reports `no_diffs`. The
  whole render→diff→report engine already exists (`workshop/`).
- **Adoption *is* the preview engine, reversed.** Render the template with inferred
  answers into a scratch dir, diff vs R for the drift report (same machinery as
  `template/preview.py`), then write the answers file.
- So genuinely new code is small: the Home A scaffolder, the `adopt` primitive, a shared
  `tree_diff` helper, and a modeless "bootstrap" command class.

## Key technical nuance (don't miss)

Copier renders a **git ref** (latest tag/HEAD), not uncommitted files. So during the
parameterization loop the extracted template is kept a **plain (non-git) directory** —
Copier renders a plain dir's working tree directly — and is turned into a git repo +
tagged only at *finalize*, right before adoption. **Verify this Copier behavior first**
(see plan); fallback is commit-per-iteration.

## Out of scope (v1)
- Agent-proposed template selection (explicitly unwanted).
- `--reconcile` (rewriting repo files toward the template).
- Auto-resolving "latest" template ref.
- Pushing the extracted template / upstream PRs.
