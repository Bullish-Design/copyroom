# Kickoff prompt — `copyroom new` birth-hook UX (implementation planning)

Paste the block below into a **fresh session in the `copyroom` repo** to begin.
This session's job is **implementation planning only — do NOT implement.**
Produce the `IMPLEMENTATION_GUIDE.md` in
`.scratch/projects/10-new-birth-hook-ux/`; do not edit `src/`, `tests/`,
`docs/`, or any consumer repo this pass. You *may* run read-only commands and
safe experiments in `/tmp` to verify the plan's mechanics hold.

---

You are planning the fix for **`copyroom new` birth-hook UX** in **copyroom**
(`/home/andrew/Documents/Projects/copyroom`): the trust gate is invisible until
you already know it exists, and the printed next-steps (`git init && git add . &&
git commit`) contradict the family's actual birth ceremony (gitman init/seed via
`post_project_create` hooks).

Read `.scratch/projects/10-new-birth-hook-ux/FINDINGS.md` first — it contains
the observed evidence, options (A–D), and acceptance criteria. The owner's lean
is **A+B now, C later**: (A) surface declared hooks in `new`'s output — list
them when `--trust` runs, and when it doesn't, state they were skipped + how to
run them; (B) replace the generic git next-steps with the *declared* ceremony
commands and the family's verify step (`repoman doctor`) when hooks are skipped.
C (`copyroom project hooks run`, an on-demand hook executor) is explicitly out
of scope this pass.

## Planning checklist

1. **Locate the output seam.** Where does `new` print its "Project created …
   Next:" block (`src/copyroom/project/`)? Where is the rendered
   `copyroom.project.yml` already parsed post-render, and what shape does the
   parsed `commands.post_project_create` take?
2. **Detect hooks.** How to read the rendered (not template) project's
   `commands.post_project_create` / `post_template_update` and distinguish
   "declared, ran" vs "declared, skipped" vs "none declared".
3. **Output shape.** Plain-text and `--json` variants — exact lines for the
   three template shapes in the acceptance criteria. Keep the family contract
   (parseable plain lines, no Rich in `--json`).
4. **No behavior change to the trust gate.** Verify hooks still only run with
   `--trust`; A+B are reporting-only. Confirm `update` needs the same treatment
   or explicitly defer it.
5. **Edge cases.** Hooks declared but template renders no `copyroom.project.yml`;
   multiple hooks (list them all); `--json` consumers (what keys change);
   interplay with project-09's finalize (agent-files export on new) if both land.
6. **Tests.** Unit tests around the output composer (mock the render/parse);
   integration: real render of `template-py` with and without `--trust`, assert
   stdout content. List the existing `new` tests that must stay green.

## Deliverable

`IMPLEMENTATION_GUIDE.md` — phase-by-phase, with file paths, the exact output
lines for each mode/shape, the JSON schema change, edge cases, and the test
matrix. Verify anything uncertain with safe experiments in `/tmp` (e.g. render
a throwaway project from `template-py` with and without `--trust` and capture
the current output to diff against).

Do not implement. Do not commit changes to `src/`.
