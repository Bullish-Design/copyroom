# CLI Reference

The complete command surface of CopyRoom 0.3.0. Commands are grouped by the
[mode](concepts.md) they run in. For task-oriented guides see
[projects](projects.md), [template editing](template-editing.md),
[workshop](workshop.md), and [adoption](adoption.md).

```
copyroom [--mode {workshop,project}] [--version] <command> [args…]
```

## Global options

| Option | Effect |
|--------|--------|
| `--mode {workshop,project}` | Force a mode instead of auto-detecting from directory markers. Bootstrap commands ignore this. |
| `--version` | Print `copyroom <version>` and exit 0. |
| `-h`, `--help` | Show grouped help and exit 0. |

Running `copyroom` with **no command** prints help and exits 0.

## Exit codes & output conventions

- **0** — success.
- **1** — any failure: unknown mode, out-of-mode command, unknown command, a
  workflow that ended in a `failed` state, or a non-zero from the underlying
  Copier/git call.
- Diagnostics and the underlying tool's stderr go to **stderr**; primary results
  go to **stdout**.
- CopyRoom **never auto-rolls-back**. On failure it reports what happened and
  where state was left; a clean worktree is your manual escape hatch.

---

# Project commands

Run inside a generated project (a directory, or descendant, with
`.copier-answers.yml` or `copyroom.project.yml`). For `new` in an empty dir, pass
`--mode project`.

## `copyroom new`

Create a new project from a template.

```
copyroom new <source> [target] [--answers FILE] [--trust]
```

| Argument / flag | Meaning |
|-----------------|---------|
| `source` (required) | Template source: local path or git URL (`gh:`/`gl:` shorthand, https, ssh). |
| `target` (optional, default `.`) | Target directory. Must be empty or non-existent. |
| `--answers FILE` | YAML answers file passed to Copier (non-interactive). |
| `--trust` | Execute the template's `post_project_create` hook commands (off by default — see [trust & safety](trust-and-safety.md)). |

**Behavior:** verifies the target is empty → validates the answers file (if any)
→ `copier copy --quiet --defaults` → runs trusted post-create hooks if
configured → prints next-step suggestions. **Fails** if the target is non-empty,
the answers file is missing/invalid, or Copier exits non-zero (its stderr is
forwarded).

## `copyroom update`

Update an existing project to a new template version.

```
copyroom update [target_ref] [--branch] [--trust]
```

| Argument / flag | Meaning |
|-----------------|---------|
| `target_ref` | Template version to update to (tag/branch/commit). **Optional** — omit it to update to the template's latest semver tag (see below). |
| `--branch` | Perform the update on an isolation branch named `template-update/<template_id>-<target_ref>`. |
| `--trust` | Execute the template's `post_template_update` hooks. |

**Behavior:** loads `.copier-answers.yml` (reads `_src_path`, `_commit`) →
**resolves the ref** → no-ops if already at it → **requires a clean git worktree**
(refuses a dirty one, listing the dirty files) → optional isolation branch →
`copier update --defaults --vcs-ref <ref>` → captures conflicts (inline markers)
and rejects (`*.rej`) → runs trusted post-update hooks → reports the outcome.

**Latest-ref resolution.** With no `target_ref`, CopyRoom reads `_src_path` and
picks the **highest semver tag** (`vX.Y.Z`; the `v` is optional, non-semver and
pre-release tags are ignored) — listing tags locally with `git tag` or, for a
remote source, with `git ls-remote --tags`. The concrete tag (not Copier's
implicit "latest") is then passed to `copier update`, so the chosen version is
deterministic, reported accurately, and gives a real "already at latest" no-op.
Passing an explicit `target_ref` skips resolution entirely and stays fully
offline; the no-arg path is fetch-class and may need the network or a warm cache.
If the source can't be reached or has no semver tags, the command fails with a
clear error rather than guessing.

## `copyroom inspect`

Print a full, read-only report on the current project and its template link.

```
copyroom inspect [--json]
```

| Flag | Meaning |
|------|---------|
| `--json` | Emit the report as JSON (stable schema, tagged `"command": "inspect"`). |

**Reports:** the project root, template id and source (`_src_path`), the recorded
`_commit`, the answers-file location, whether `copyroom.project.yml` is present,
and the configured command/hook lists (read through the validated config model).
A pure read — it changes nothing. Requires a `.copier-answers.yml` (i.e. a real
Copier project).

## `copyroom status`

A terse "where am I" for the current project.

```
copyroom status [--json]
```

| Flag | Meaning |
|------|---------|
| `--json` | Emit the status as JSON (stable schema, tagged `"command": "status"`). |

**Reports:** detected mode, the template (id/source), the current ref (`_commit`),
the **latest** ref (resolved via the same latest-tag logic as `update`), whether
an **update is available**, and worktree cleanliness (`clean` / `dirty`, or
`N/A` when the project isn't a git repo). Computing "update available" resolves
the template's latest tag, so it is fetch-class for remote sources.

## `copyroom template-checkout`

Resolve this project's template into an isolated, editable git worktree on a
scratch branch. First step of the [template-edit loop](template-editing.md).

```
copyroom template-checkout [--from REF]
```

| Flag | Meaning |
|------|---------|
| `--from REF` | Base the edit branch on `REF` (default: the template's current default branch). Use the project's recorded `_commit` to scope a preview to just your new change. |

**Behavior:** reads `_src_path` from `.copier-answers.yml`, clones a remote source
into the cache (or uses the local git repo), and `git worktree add`s a branch
`copyroom/edit/<project-slug>`. Prints the **Worktree** path, the **Branch**, and
the **Source**. Idempotent — re-running reuses the same worktree. Requires the
template source to be a **git repository**.

## `copyroom template-test`

Render-test the edited template with this project's own answers.

```
copyroom template-test [--from REF] [--check CMD]
```

| Flag | Meaning |
|------|---------|
| `--from REF` | Same base-ref meaning as `template-checkout`. |
| `--check CMD` | Shell command to run against the rendered output (e.g. `"pytest -q"`); a non-zero exit fails the test. |

**Behavior:** resolves the same scratch worktree, commits your pending edits onto
the edit branch, `copier copy --vcs-ref <edit-branch>` into a temp dir, and
(optionally) runs `--check` there. Reports success or the render/check failure.

## `copyroom template-preview`

Preview the update your project would receive from the edited template —
**without touching your working tree**.

```
copyroom template-preview [--from REF]
```

**Behavior:** commits pending edits → copies your project's **current working
tree** into a sandbox → `copier update --vcs-ref <edit-branch>` in the sandbox →
diffs baseline vs post-update → writes `.copyroom/preview/<timestamp>.patch` and
summarizes **Added / Modified / Removed**, plus **Conflicts** (inline markers)
and **Rejects** (`*.rej`). Nothing is applied. To take the change, commit/tag it
upstream and run `copyroom update <ref>`.

---

# Bootstrap commands

Run in an **unmanaged** repo (no markers). These bypass mode detection. Full
guide: [adoption](adoption.md).

## `copyroom templatize`

Scaffold a self-contained template repo from the current repo.

```
copyroom templatize [--into PATH] [--name NAME] [--id ID]
```

| Flag | Meaning |
|------|---------|
| `--into PATH` | Where to create the template repo (default: `<repo>-template` sibling). |
| `--name NAME` | Project name recorded as the template default (default: the repo directory name). |
| `--id ID` | Workshop/registry template id (default: a slug of `--name`). |

**Behavior:** creates a sibling repo that is *both* a Copier template
(`copier.yml` with `_subdirectory: template` + a **verbatim** `template/`) *and*
a workshop (`copyroom.yml`, `registry/`, `scenarios/<id>/{default,probe}.yml`,
`golden/<id>/default/` = a snapshot of the repo). Because the verbatim `template/`
reproduces the repo exactly, `copyroom golden <id> default` starts at **no
diffs**. Left as a plain (non-git) directory so edits show up immediately during
the parameterize loop.

## `copyroom adopt`

Link this repo to a template and report drift. **Report-only.**

```
copyroom adopt <template> [--ref REF] [--answers FILE] [--write] [--force]
```

| Argument / flag | Meaning |
|-----------------|---------|
| `template` (required) | Template source (local path or git URL). |
| `--ref REF` | Template VCS ref to render (tag/branch/commit). |
| `--answers FILE` | YAML answers file that reproduces this repo. |
| `--write` | Write `.copier-answers.yml` into the repo (otherwise report-only). |
| `--force` | Re-adopt even if the repo already has `.copier-answers.yml`. |

**Behavior:** renders the template with your answers into a scratch dir, tree-diffs
that against the repo, and prints drift: **Template adds** (files the template
produces the repo lacks), **Differs** (content mismatch), **Repo-only**
(legitimately-extra repo files). Writes a reviewable patch under
`.copyroom/adopt/`. With `--write` it copies the rendered `.copier-answers.yml`
into the repo — **the only repo file it ever modifies**. Refuses an
already-managed repo unless `--force`.

---

# Workshop commands

Run inside a workshop (a directory, or descendant, with `copyroom.yml` +
`registry/` + `scenarios/`). Full guide: [workshop](workshop.md).

## `copyroom render`

Render a template scenario into `generated/<template_id>/<scenario_id>/` and run
the template's configured checks.

```
copyroom render <template_id> <scenario_id>
```

Loads the scenario answers from `scenarios/<template_id>/<scenario_id>.yml`,
resolves the template source from the registry, `copier copy`s into `generated/`,
then runs the registry `checks` against the output (a failing check fails the
command). Re-rendering cleans the previous output first.

## `copyroom test`

```
copyroom test <template_id> <scenario_id>
```

Alias for `render` with a testing focus — identical workflow (render then run
checks).

## `copyroom golden`

Compare rendered output to a stored golden snapshot, or refresh the snapshot.

```
copyroom golden <template_id> <scenario_id> [--refresh]
```

| Flag | Meaning |
|------|---------|
| *(none)* | Render and tree-diff against `golden/<template_id>/<scenario_id>/`. Reports **OK (no diffs)** or **DIFFS FOUND** (added/modified/removed); exits non-zero on diffs. |
| `--refresh` | Overwrite the golden snapshot with the **current** `generated/` output. Requires a prior `render`. |

`.copier-answers*.yml` is excluded from the comparison (it carries
machine-specific paths/commits).

## `copyroom update-test`

Simulate a template upgrade end-to-end.

```
copyroom update-test <template_id> <scenario_id> <old_version> <new_version>
```

**Behavior:** renders the scenario at `old_version` into `.copyroom_sim/`,
git-snapshots it, applies deterministic edits from
`scenarios/<template_id>/<scenario_id>-edits.yml` (if present),
`copier update --vcs-ref <new_version>`, captures conflicts/rejects, then runs the
registry checks. Reports a clean upgrade or the conflicts/rejects found. The
edits-file DSL supports `append`, `set-field`, `create`, and `patch` actions.

## `copyroom release-check`

Run the full release-readiness gate for a template.

```
copyroom release-check <template_id>
```

**Behavior:** captures the git worktree state **first** (excluding `generated/`
and `.copyroom_sim/`), discovers all scenarios under
`scenarios/<template_id>/`, runs render+test for each (the **matrix**), then a
golden diff for each (reusing the matrix render). Passes only when **matrix
passes AND worktree is clean AND all golden diffs are empty**. Prints a report;
exits non-zero on failure. Advisory in v0.x — **tagging stays manual**.

## `copyroom registry`

Inspect the workshop's template registry. Read-only, except `add`, which only
ever **creates** a new `registry/<id>.yml` — `copyroom.yml` is never rewritten
(round-tripping it through a YAML library would drop comments and ordering).

```
copyroom registry list
copyroom registry show <template_id>
copyroom registry validate
copyroom registry add <template_id> --source <path-or-url> [--scaffold]
```

| Action | Behavior |
|--------|----------|
| `list` | Lists every registered template id (from `copyroom.yml` and `registry/*.yml`) with its resolved source and check count. |
| `show <id>` | Prints the full resolved entry (source + checks) for one template; errors on an unknown id. |
| `validate` | Checks every entry: the source resolves (local path exists and is a git repo, or a remote is reachable), carries at least one **semver tag**, and has a `scenarios/<id>/` directory. Reports problems and **exits non-zero** if any entry fails. |
| `add <id> --source <src>` | Writes a **new** `registry/<id>.yml`. Refuses when the id is already registered — whether by an existing `registry/<id>.yml` **or** an inline entry in `copyroom.yml` (which would shadow the new file) — pointing you at the existing definition. With `--scaffold`, also creates a `scenarios/<id>/default.yml` skeleton. The `source` is YAML-encoded, so values containing `#`, `{`, etc. round-trip safely. |

There is **no `remove`** — delete the `registry/<id>.yml` file directly. An
unknown action is rejected with the list of supported ones.

## Environment variables

| Variable | Effect |
|----------|--------|
| `COPYROOM_CACHE_DIR` | Override the template clone/worktree cache root (default `$XDG_CACHE_HOME/copyroom` → `~/.cache/copyroom`). |
| `XDG_CACHE_HOME` | Standard XDG cache base used when `COPYROOM_CACHE_DIR` is unset. |
