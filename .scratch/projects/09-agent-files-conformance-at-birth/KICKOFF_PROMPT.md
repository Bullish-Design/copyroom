# Kickoff prompt — Agent-files conformance at birth (implementation planning)

Paste the block below into a **fresh session in the `copyroom` repo** to begin.
This session's job is **implementation planning only — do NOT implement.**
Produce the `IMPLEMENTATION_GUIDE.md` in
`.scratch/projects/09-agent-files-conformance-at-birth/`; do not edit `src/`,
`tests/`, `docs/`, or any consumer repo this pass. You *may* run read-only
commands and safe experiments in `/tmp` to verify the plan's mechanics hold.

---

You are planning the fix for **agent-files conformance at birth** in **copyroom**
(`/home/andrew/Documents/Projects/copyroom`): a freshly generated repo ships
stale canonical skills and stays `agent-files`-non-conformant until someone
manually runs `copyroom agent-files export`.

Read `.scratch/projects/09-agent-files-conformance-at-birth/FINDINGS.md` first —
it contains the observed evidence, root-cause, options (A–D), and acceptance
criteria. The owner's lean is **option A**: `copyroom new` and `copyroom update`
finalize the render with an agent-files export whenever the rendered project
declares the `agent:` convention in its `copyroom.project.yml` — idempotent,
`overlay`-respecting, independent of `--trust` (only the `post_*` hook commands
stay trust-gated).

## Planning checklist

1. **Locate the finalize seam.** Where does `new` finish rendering
   (`src/copyroom/project/`)? Where does `update` finish its three-way merge?
   What is the cleanest shared choke point both can call?
2. **Detect the convention.** How to decide "this project opted into the agent
   convention" from the rendered `copyroom.project.yml` (`agent:` section,
   `skills_dir`/`instructions` keys, all defaulted) — without failing on
   templates that don't declare it.
3. **Reuse, don't duplicate.** The export logic already exists in
   `src/copyroom/agent/` (used by `agent-files export`). Plan to call the same
   code path — verify it is idempotent and safe when everything is current, and
   confirm it never: replaces an existing `AGENTS.md`, dereferences the
   `CLAUDE.md` symlink, or touches overlaid skills.
4. **`--trust` orthogonality.** Spell out how the finalize runs even when
   `post_project_create`/`post_template_update` hooks were skipped (no
   `--trust`), and confirm the trust gate is untouched.
5. **Error handling.** What happens if the export fails mid-`new`/`update`
   (warn + continue? abort?) — pick per the family exit-code contract.
6. **Tests.** Which existing tests cover `agent-files` (`tests/`)? Plan unit +
   integration coverage: fresh `new` → `check` green without manual export;
   `update` refreshes stale skills; overlay untouched; no-`agent`-section
   templates unaffected.
7. **Doctor text.** Optionally extend the `agent-files` WARN in `doctor` to
   name the exact repair command.

## Deliverable

`IMPLEMENTATION_GUIDE.md` — phase-by-phase, with file paths, the finalize seam,
detection rule, export-reuse plan, edge cases, and the test matrix. Verify
anything uncertain with safe experiments in `/tmp` (e.g. render a throwaway
project and inspect what `copyroom.project.yml` looks like post-render).

Do not implement. Do not commit changes to `src/`.
