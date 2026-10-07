# Prompt for a clean implementation session

Copy the text below into a new session. Start that session in
`/home/andrew/Documents/Projects/copyroom`.

---

Implement the local Templateer and jj replacement for CopyRoom. Continue
through the implementation gates. Make code, tests, docs, and configuration
changes; do not stop after writing a plan.

Read these files first:

1. `AGENTS.md` and the CopyRoom, gitman, and writing skills named there.
2. `.scratch/projects/27-templateer-jj-implementation/IMPLEMENTATION_GUIDE.md`.
3. `.scratch/projects/26-templateer-jj-slice/README.md`, `slice.py`, and
   `tests/test_slice.py`.
4. `.scratch/projects/25-templateer-jj-evaluation/RESEARCH_REPORT.md` and
   the linked spike reports when you reach their workflows.

The user wants local files only and always has jj and devenv in managed
project repos. No remote template fetching is required. Templateer must be
the artifact renderer. Plain jj must hold each owner's render history and
merge updates. Linkman may own shared symlinks, but its paths must stay
outside Templateer output ownership. Pydantree is not part of this design.

Current evidence: project 26 has a working one-layer `new`, `preview`,
`update`, `discard`, and `status` flow with real Templateer renders. Its nine
integration tests, Ruff check, and walkthrough pass. The earlier spikes
proved repeated jj merges, preview isolation, explicit generation with a
fake Agent, path ownership checks, adoption, templatize, workshop flow, and
Linkman coexistence. They also disproved the idea that local `devenv.lock`
inputs pin template revisions. Use the guide's source snapshot and digest
contract instead.

Implement in the guide's phase order:

1. Record the current root test, Ruff, and walkthrough baseline. Add a
   temporary local CLI route while the Copier path still works.
2. Move the composer and source protocol into `src/copyroom/local/`. Add
   project-owned source snapshots, static binary and safe relative symlink
   support, exact modes, validated answers, and a versioned marker.
3. Move the jj lifecycle into maintained modules. Add exact preview apply,
   conflict resolution in the preview workspace, stale-state checks,
   controlled recovery, and concurrency protection. Add read-only reports.
4. Add independent layers and effective path ownership. Add optional Linkman
   path reservations and broken-target checks.
5. Add explicit Templateer `generate` and `refresh`. Save validated model and
   exact artifact bytes. Ordinary update and render paths must make zero
   provider calls. Test offline with a fake Agent.
6. Add report-first adoption, templatize with exact golden reproduction, and
   the local workshop and template-edit flow. Use devenv tests for checks.
7. Route the public CLI to the new engine. Rewrite relevant tests, docs,
   package configuration, `AGENTS.md`, and the walkthrough. Remove Copier
   from active runtime dependencies only after the new workflows pass.

Keep these invariants throughout:

- One owner per effective output path. Reject exact, prefix, and case-fold
  collisions before an active project mutation.
- T1 is a child of T0. Verify that jj finds T0 as the merge base with the
  project. Keep old rendered bytes in the graph; do not regenerate the base.
- A preview changes no active project file or active `@` commit. Apply the
  exact reviewed tree. A changed active project makes the preview stale.
- A conflict remains in the preview until the user resolves or discards it.
  Report it with exit code `1` and jj conflict paths.
- Save source identity and a project-owned source snapshot. A source path is
  only a locator. Do not treat `devenv.lock` as a local template revision.
- A model call happens only through explicit generation or refresh.
- Keep the exit-code API: `0` success, `1` finding, `2` infrastructure or
  state error, `3` usage. Keep plain-text and JSON reports structured.

Run all development commands inside the root devenv shell. Use gitman for
version control in this CopyRoom repository; use plain jj only in disposable
or managed project repos. Inspect status before each commit. Include all
relevant active changes, including lockfiles, tests, research, and docs.
Commit and push reviewable increments. Do not add attribution lines to any
commit or pull request text.

Run the root gate before declaring the migration complete:

```bash
devenv shell -- uv run pytest -q
devenv shell -- uv run ruff check src/ tests/
devenv shell -- bash demo/walkthrough.sh
```

Also test a fresh consumer devenv import. Confirm that the runtime no longer
imports or installs Copier. Report the implemented commands, test evidence,
source snapshot and conflict behavior, remaining limits, and pushed commit
IDs. If a guide detail conflicts with tested jj or Templateer behavior,
record the finding, choose a safe correction, and continue.
