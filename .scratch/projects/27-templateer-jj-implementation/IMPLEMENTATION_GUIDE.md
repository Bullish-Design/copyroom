# Implement local CopyRoom with Templateer and jj

Date: 2026-10-07

## Goal and scope

Replace CopyRoom's Copier engine with a local Templateer tree composer and
plain jj operations in managed project repositories. Keep the `copyroom` CLI.
Require jj and devenv in managed repositories. Accept local template sources
only. Make model generation an explicit option. Preserve the local project,
layer, adoption, and workshop workflows that remain useful.

The [concept evaluation](../25-templateer-jj-evaluation/RESEARCH_REPORT.md)
records the feasibility results. The [runnable slice](../26-templateer-jj-slice/README.md)
implements one base layer with `new`, `preview`, `update`, `discard`, and
`status`. It passed nine integration tests, Ruff, and its walkthrough.
Treat the slice as reference code. Move its behavior into maintained modules;
do not import code from `.scratch` at runtime.

This guide uses these fixed terms:

- **Source**: a local directory with `manifest.json` and `templates/`.
- **Artifact**: one Templateer `full_file` output.
- **Owner**: the one layer, generated snapshot, or external link that controls
  an output path.
- **Render commit**: a jj commit that holds one owner's output tree.
- **Project commit**: a jj commit that holds the user's project state.
- **Preview**: a separate jj workspace with a proposed merge.
- **Source snapshot**: a project-owned copy of the exact files used to render.

## Rules that every phase must preserve

1. Run project commands through devenv. Use Python 3.13 and the pinned jj CLI.
   Use plain jj only inside managed or disposable project repos. Use gitman
   for version control in the CopyRoom repository.
2. Keep exit codes stable: `0` success, `1` finding or decision, `2` bad
   environment or state, `3` invalid command use. Keep text reports easy to
   parse. `--json` must contain no terminal color or prose.
3. Keep each output path under one owner. Reject equal paths and file-directory
   prefixes before any active jj change. Compare case-folded paths too.
4. Put the old render bytes in jj. A new render commit T1 is a child of T0.
   The project and T1 must have T0 as their merge base. Store the current
   render-head identity per owner; do not store a Copier-style `_commit` in
   answers or resolve versions by semver scanning.
5. Freeze model output. A normal render or update must not call a model.
   Only an explicit `generate` or `refresh` command can call Templateer.
6. Keep the active project unchanged during preview. Apply the exact reviewed
   result, and refuse a stale preview. Report jj conflicts through jj state.
7. A local source path is a locator. Record a content digest and a source
   snapshot. Local `path:` and `git+file://` devenv inputs did not pin a
   revision in [spikes 19](../19-devenv-local-input/RESEARCH_REPORT.md) and
   [22](../22-devenv-git-file/RESEARCH_REPORT.md).

## Target layout and state contract

Keep the maintained engine under `src/copyroom/local/`. Use small modules with
one job each. This is the proposed file map; rename a module only when the
code makes a clearer boundary.

| Module | Job |
| --- | --- |
| `models.py` | Validate the project marker, source manifest, owner manifest, and preview state. |
| `source.py` | Resolve local paths, copy source snapshots, and verify content digests. |
| `composer.py` | Call Templateer, collect artifacts and static entries, apply modes, and validate output. |
| `ownership.py` | Build effective path sets and reject ownership collisions. |
| `jj.py` | Run jj without a shell and parse commit, workspace, operation, and conflict results. |
| `workflow.py` | Create, preview, apply, discard, inspect, and report a base layer. |
| `generation.py` | Make and refresh frozen Templateer generation results. |
| `layers.py` | Add, list, preview, and converge named layers. |
| `adoption.py` | Report drift and attach a render lineage to an existing jj project. |
| `workshop.py` | Run scenarios, golden checks, update tests, and candidate previews. |

Use one new marker, such as `.copyroom/project.json`. Detect it in
`src/copyroom/session/detector.py`. Keep legacy Copier markers readable during
the transition. If both marker systems exist in one directory, report an
explicit ambiguity. Do not infer one from the other.

The marker needs a schema version, project ID, and one record per owner. A
layer record needs a local source locator, source digest, source snapshot path,
validated answers, current render-head commit ID, output path manifest, saved
omissions, and renderer provenance. Generated records need the frozen model,
artifact bytes or artifact snapshot path, request and model identity, and
source provenance. Store paths as project-relative values where possible.

Example shape; the exact field names can change before the first migration:

```json
{
  "schema": 1,
  "project_id": "stable-id",
  "layers": {
    "base": {
      "source": {"locator": "../template", "digest": "sha256", "snapshot": ".copyroom/sources/sha256"},
      "answers": {"project_name": "example"},
      "render_head": "jj-commit-id",
      "paths": {"README.md": {"kind": "file", "mode": "0644"}},
      "omissions": [],
      "templateer_version": "0.4.1",
      "templateer_digest": "sha256"
    }
  },
  "generated": {},
  "external_paths": {}
}
```

The `render_head` field identifies the current render line. It is not a
version comparison or merge-base field. Verify that it is an ancestor of the
project before use. jj computes the merge base from the graph. Keep
`.copyroom/` project-owned; no template or generated owner may write there.

Store source snapshots at `.copyroom/sources/<digest>/`. Copy only
`manifest.json` and the declared `templates/` files. Record every path,
hash, and mode. Reject symlink escapes, path traversal, local environment
directories, and files above the chosen size limit. Track snapshots in the
project so a clone can replay an old render without the original source path.
An update to a *new* source version still needs the local source locator or an
explicit `--source` override. Verify source bytes before and after rendering.
Test replay from the snapshot after removing the original source directory.

For the source manifest, extend project 26's `templates` and `executable`
fields with explicit static files and relative symlinks. Templateer renders
UTF-8 text. Copy binary files as raw bytes. Preserve ordinary and executable
modes. Preserve a relative symlink only when its resolved target stays inside
the rendered tree. Treat CRLF or other encodings as static bytes unless the
manifest declares a tested renderer conversion. Reject device files and
unsupported modes. Do not silently normalize a source file.

## Phase 0 — baseline and migration boundary

1. Read `AGENTS.md`, the CopyRoom, gitman, and writing skills, this guide,
   project 26, and the reports for spikes 12–24.
2. Run the current root tests, Ruff, and `demo/walkthrough.sh`. Record the
   baseline. Classify any existing failure before changing runtime code.
3. Add a migration matrix to the implementation work log. Map each current
   command to its local replacement. Use the command map below as the start.
4. Add a temporary `copyroom local` command group to `src/copyroom/cli.py`.
   Route only the new marker to the new engine. Keep existing Copier projects
   on the old path until the local path passes its gates. Remove the temporary
   group at final cutover.
5. Add jj to the development environment in `dev/devenv.nix`. Update the
   importable module in `modules/copyroom.nix` so consumers receive jj. Update
   `packages/copyroom-cli.nix` and the Python dependency setup for Templateer.
   A clean devenv shell must import Templateer and run jj. A sibling local
   Templateer checkout is acceptable for this personal, local-only setup;
   document its path and verify its source digest at runtime.

**Gate:** Old behavior still passes its current tests. The local group reports
usage and dependency errors with the required exit codes. No Copier path
changes yet.

## Phase 1 — maintained composer and source protocol

1. Move the rendering logic from project 26 into `local/composer.py`. Use
   `TemplateRegistry.render_from_model()` and `validate_artifact()`. Validate
   one shared Pydantic schema and save the normalized model dump.
2. Render to an in-memory or staged tree before changing a project. Build a
   manifest of path, owner, file kind, content hash, and mode. Reject duplicate,
   prefix, case-fold, reserved, absolute, and traversal paths.
3. Add static bytes, executable modes, and safe relative symlinks. Keep
   Templateer artifact validators and local schema code in the trusted-source
   boundary. Report validator findings before writing.
4. Implement `local/source.py` and the source snapshot contract above. Record
   Templateer version and source digest, composer digest, manifest digest,
   validated answers, and rendered tree digest. Do not use `devenv.lock` as
   the source revision record.
5. Add focused tests for malformed models, schema mismatch, unsafe paths,
   modes, binary bytes, symlinks, changed defaults, and exact replay from a
   source snapshot. Use project 14 and project 23 fixtures as starting points.

**Gate:** A saved input model and source snapshot reproduce each tested output
byte and mode. A bad source or collision changes no active project file.

## Phase 2 — jj lifecycle, preview, and recovery

1. Move the jj flow from project 26 into `local/jj.py` and `local/workflow.py`.
   Run each jj command as an argument list. Capture stdout, stderr, and exit
   status. Keep jj details out of CLI handlers.
2. Implement `new`. Build the full plan first. Create T0 with only the base
   layer's output. Commit the project marker and source snapshot as project
   state. Verify T0's tree and parent before reporting success. Clean a newly
   created target after a controlled failure.
3. Implement `preview`. Check the current render-head ancestor and the active
   project fingerprint. Make T1 as a child of T0 in a separate workspace.
   Merge the active project commit with T1 there. Save parent IDs, operation
   ID, source digest, owner manifest, preview commit, and tree fingerprint in
   preview state outside the active tree. Show `jj diff --from <project> --to
   <preview>` and `jj resolve --list`.
4. Implement `apply` and `discard`. Recheck the active commit and tree. Apply
   the reviewed preview tree, then save the new marker. Project 26 reruns the
   merge and refuses a changed preview. For production, test `jj new
   <preview-merge>` in the active workspace so a resolved preview remains
   exact. If jj cannot use that commit while another workspace holds it,
   create a fresh merge and restore its tree from the reviewed preview.
   Verify parents, byte-for-byte tree equality, and render-head ancestry.
   The intended graph is `T0→T1`, `T0→P0`, `(P0,T1)→M`, `M→P1`.
   M is the reviewed merge. P1 saves the new project marker. A later T2 must
   use T1 as its merge base with P1.
5. Allow conflict resolution *in the preview workspace*. Report conflict
   paths with exit `1`. Let the operator edit or run `jj resolve` there.
   Apply only after `jj resolve --list` is empty and all protected marker
   paths still match the preview plan. A separate explicit option may apply
   unresolved conflicts later; do not make that the default.
6. Use a per-project operating-system lock for CopyRoom writes. Hold it from
   the final stale-state check through apply and cleanup. A process crash must
   release the lock. On a controlled apply failure, restore the saved jj
   operation only if no other actor advanced the repository. Keep the preview
   for inspection after failure. Add `preview list` and `discard` recovery for
   abandoned workspaces.
7. Implement `inspect`, `status`, and `doctor` for the new marker. Report
   source reachability, digest mismatch, render head, pending previews,
   conflicts, and missing jj or Templateer. A valid local project never
   requires a clean-working-tree guard.
8. Test two updates, local edits, deletion, delete/modify conflict, resolved
   conflict, stale preview, changed preview, controlled rollback, process
   interruption, and two concurrent apply attempts. Use disposable jj repos.

**Gate:** The active project stays byte-identical through preview. A clean
apply matches the reviewed preview. A resolved conflict also matches its
reviewed preview. A stale or rejected action changes neither active files nor
its jj `@` commit.

## Phase 3 — layers, ownership, and shared links

1. Move ownership checks into `local/ownership.py`. Build the **effective**
   output set for each owner. Include the base layer, overlays, generated
   snapshots, project-owned files, and declared Linkman paths.
2. Implement `layer add` and `layer list`. A new layer gets its own T0 render
   line and marker record. Reject a collision before making that line visible
   to the active project. Keep one owner per path. Save conditional seed
   omissions and apply them on every later render of that layer.
3. Implement `update --layer NAME`. Advance only that layer's render line.
   Test that a base update leaves an overlay unchanged and vice versa.
   Implement `--all-layers` only after single-layer updates pass. Use an
   n-parent merge when ownership sets are disjoint; report all proposed
   parent IDs and conflicts before apply.
4. Keep Linkman optional. Treat its declared symlink paths as external
   owners. A Templateer layer must omit them. Check both the raw link target
   and target existence; Linkman 0.1.0's `check` called a broken link clean in
   [spike 24](../24-linkman-jj/RESEARCH_REPORT.md). Do not claim that a jj
   commit records the central file bytes.
5. Test exact and prefix collisions at `new`, layer add, base update,
   overlay update, generated refresh, and ownership transfer. Require an
   explicit transfer command or reviewed migration for path reassignment.

**Gate:** No two active owners claim one path. Independent updates preserve
the other layers' render heads and output. A deleted shared path cannot
silently remove another layer's file.

## Phase 4 — optional Templateer generation

1. Add `generate` and `refresh` as explicit commands. Keep normal `new`,
   `preview`, `update`, `render`, and workshop golden checks free of provider
   calls. Default generation to off.
2. Call Templateer's generation API for one declared artifact. Validate the
   returned model and artifact. Save the exact artifact bytes, validated model,
   path, request, model name, Templateer digest, template source digest, and
   any available usage record. Record missing provider revision as unknown;
   do not invent it.
3. Give each generated artifact its own owner and frozen render line. Reuse
   the frozen bytes on every ordinary update. An explicit refresh makes a new
   render commit and previews its merge with project edits.
4. Run offline integration tests with a fake Agent through Templateer's real
   pipeline, as in [spike 16](../16-templateer-generation/RESEARCH_REPORT.md).
   Verify call counts, replay, refresh, collision rejection, and rollback.
   Add one opt-in live-provider smoke test only when credentials and cost are
   available. Do not make a live call part of the normal test suite.

**Gate:** A normal update performs zero model calls. A refresh preserves the
old frozen artifact and records a new reviewed artifact. Path ownership holds.

## Phase 5 — adoption and templatize

1. Implement report-only `adopt`. Render a proposed T0 and compare it with
   the existing project. Report changed, project-only, and template-only
   paths with bytes and modes. Require an explicit choice for template-only
   paths. Keep the report read-only.
2. On explicit adoption, create T0 in a separate workspace. Make an adoption
   merge with the existing project P0 and T0 as parents. Restore the project
   tree from P0. Verify byte and mode equality before saving the marker.
   A later T1 must use T0 as its merge base. Use the
   [adoption spike](../17-jj-adopt/RESEARCH_REPORT.md) as the first fixture.
3. Implement `templatize` as extraction plus a golden check. Start from
   verbatim UTF-8 text templates, static binary files, modes, and safe
   relative symlinks. Account for MiniJinja's final-newline behavior before
   comparing bytes. Parameterize selected sites only. The original answers
   must still render an exact golden tree; a probe answer must change only
   intended paths. Use [spike 23](../23-templateer-templatize/RESEARCH_REPORT.md).
4. Support an unmanaged directory by initializing jj only at the explicit
   adoption step. Keep `templatize` output separate from the source project.

**Gate:** Adoption leaves the original project tree unchanged and permits a
later update. Templatize reproduces the original tree exactly and passes a
parameterized probe.

## Phase 6 — workshop and template editing

1. Replace Copier workshop renders with the composer. Preserve scenario
   answers and full-tree golden comparisons. Compare bytes, paths, modes,
   and symlink targets. Run Templateer's artifact validators and authoring
   audit before golden refresh.
2. Give a candidate template its own jj workspace. Render it against every
   selected scenario. Preview the update in a separate project workspace.
   Keep the active template and project checkouts unchanged until explicit
   apply. Use [spike 18](../18-jj-template-workshop/RESEARCH_REPORT.md).
3. Replace the workshop `checks:` shell-command runner with `devenv test`
   for a generated scenario or preview workspace. Run checks from the
   explicit local trusted source. Preserve check output and exit codes.
4. Rebuild `template-checkout`, `template-test`, `template-preview`,
   `template-discard`, `render`, `golden`, `update-test`, and `release-check`
   around the same candidate/preview protocol. Do not keep a second merge
   algorithm for workshop commands.

**Gate:** Golden refresh is explicit. A candidate edit and project preview
change neither active checkout. A workshop update test covers local edits and
conflicts with the production backend.

## Phase 7 — cutover and Copier removal

1. Change `copyroom new` to accept a local source and write the new marker.
   Route project commands by marker during migration. Give legacy Copier
   projects a clear migration path or a clear refusal; never silently rewrite
   `.copier-answers*.yml` into the new marker.
2. Update `src/copyroom/cli.py`, `session/`, `project/`, `manage/`,
   `template/`, and `workshop/` to use the maintained local engine. Retire the
   temporary `copyroom local` group when public commands have parity. The
   current `cli.py` has both Typer commands and older argparse handlers;
   leave one public dispatch path after cutover. Keep mode detection based on
   the new project marker, source manifest, and workshop markers.
3. Replace the old integration fixtures and `demo/walkthrough.sh` with local
   Templateer sources and disposable jj repos. Update spec tests to express
   the new invariants. Keep meaningful state-machine checks; do not delete
   tests to make the gate green.
4. Remove Copier from `pyproject.toml`, `uv.lock`, `packages/copyroom-cli.nix`,
   and runtime imports. Remove obsolete patch/reject, remote template,
   semver-ref, clean-worktree, and hook-runner code after the new path passes.
   Review `_compat/copier.py`, `_compat/conflicts.py`, `_compat/refs.py`,
   `_compat/semver.py`, and old Git helpers for deletion. Keep a helper only
   when the local engine still calls it. Check for `copier` references in
   runtime code and packaging. Align the version in the Nix package with
   `pyproject.toml`. Keep a short migration note for historical projects.
5. Update `README.md`, `AGENTS.md`, `docs/user/`, `docs/developer/`, the
   importable devenv module, and the machine-local CopyRoom skill. Make the
   new marker, jj, Templateer, local-only source rule, and conflict workflow
   the documented contract. Archive or rewrite `docs/copier/` so it cannot
   read as current guidance.
6. Run the full gate in the root devenv shell:

   ```bash
   devenv shell -- uv run pytest -q
   devenv shell -- uv run ruff check src/ tests/
   devenv shell -- bash demo/walkthrough.sh
   ```

   Also run a fresh consumer devenv that imports `modules/copyroom.nix`.
   Verify that it has the CLI, jj, and Templateer with no Copier runtime.
7. Inspect the whole active worktree. Commit relevant code, tests, docs,
   lockfiles, and reports in reviewable increments. Push completed commits.
   Use no attribution line in commits or pull requests.

**Final gate:** Every requested local workflow uses Templateer and jj. The
root tests, Ruff, walkthrough, and consumer shell pass. Copier is absent from
runtime dependencies and active docs. Source snapshots and frozen generation
make updates reviewable and replayable from local files.

## Current command map

| Current command | Local behavior to implement |
| --- | --- |
| `new` | Render a local source, make T0, save marker and source snapshot. |
| `update` | Preview or apply a chosen layer's T1; accept an explicit local source override. |
| `inspect`, `status`, `doctor` | Read marker, jj graph, source state, conflicts, and external links. |
| `layer add`, `layer list` | Add or report one-owner render lines. |
| `adopt`, `templatize` | Report drift, attach T0, or extract an exact local template. |
| `template-checkout`, `template-test`, `template-preview`, `template-discard` | Use candidate and project jj workspaces. |
| `render`, `test`, `golden`, `update-test`, `release-check` | Use one composer, scenario goldens, and devenv tests. |
| New `generate`, `refresh` | Call a provider only on request and freeze the validated output. |

## Stop conditions and decisions

- If the project and template share a path, stop before jj mutation and report
  both owners. Do not treat equal bytes as shared ownership.
- If a preview has conflicts, return `1`, keep its workspace, and show the
  conflict paths. Let the operator resolve it in that workspace.
- If the source locator disappears, use the saved snapshot to replay old
  input. Require `--source` for a new source revision.
- If another actor changes the active project after preview, refuse apply.
  If another actor changes the repo during apply, do not restore an operation
  that would erase their work. Report the operation IDs for manual review.
- If a new design choice affects the marker or graph contract, write the
  decision and a disposable-repo test before broad migration.
