# The Workshop

The workshop is the **template author's workbench**. It answers the questions a
template maintainer must keep answering for the life of a template:

1. Does the template still render?
2. Does the generated output still match what I expect (golden)?
3. Can an existing project be updated to a new version *safely*?
4. Is the template ready to release?

A directory is a workshop when it has `copyroom.yml` **and** a `registry/`
directory **and** a `scenarios/` directory. Workshop commands then work from that
directory or any descendant.

---

## Workshop layout

```
my-workshop/
├── copyroom.yml                 # registry: template ids → source + checks
├── registry/                    # (marker dir; per-template registry files)
├── scenarios/
│   └── <template_id>/
│       ├── basic.yml            # a set of Copier answers
│       ├── basic-edits.yml      # (optional) deterministic edits for update-test
│       └── full.yml
├── golden/
│   └── <template_id>/
│       └── basic/               # the locked-down expected output tree
├── generated/                   # scratch render output (gitignore this)
└── .copyroom_sim/               # scratch update-sim output (gitignore this)
```

> **Gitignore `generated/` and `.copyroom_sim/`.** They are scratch areas
> CopyRoom writes into. `release-check` deliberately excludes them from its
> worktree check, but you should keep them out of git entirely.

### `copyroom.yml` (inline registry form)

```yaml
templates:
  aurora:
    source: ../aurora-template      # local path or git URL
    checks:
      - "test -f README.md"
      - "test -f pyproject.toml"
```

`source` is anything Copier accepts. `checks` are shell commands run against the
rendered output by `render`/`test`/`update-test` and used by `release-check`.
Alternatively, put a per-template file at `registry/<template_id>.yml` with the
same `source`/`checks` keys. See [configuration](configuration.md) for the full
schema.

### Scenarios

A scenario is a named, stable set of answers:

```yaml
# scenarios/aurora/basic.yml
project_name: Demo Service
package_name: demo_service
description: A scenario rendered by the workshop.
author: The Workshop
```

Create scenarios for *durable risk areas* (minimal, full-featured, edge-case
names, CI-enabled), not for every possible answer combination.

---

## The commands

### `render` / `test` — does it generate?

```bash
copyroom render aurora basic
copyroom test   aurora basic      # alias, same workflow
```

Renders `scenarios/aurora/basic.yml` into `generated/aurora/basic/` via
`copier copy`, then runs the registry `checks` against the output. A failing
check fails the command. Each run cleans the previous output first.

### `golden` — did the output change intentionally?

```bash
copyroom golden aurora basic --refresh   # capture the current output as golden
copyroom golden aurora basic             # diff future renders against it
```

`golden --refresh` snapshots the current `generated/aurora/basic/` into
`golden/aurora/basic/`. A plain `golden` re-renders and tree-diffs against that
snapshot:

- **OK (no diffs)** → output is stable.
- **DIFFS FOUND** → added/modified/removed files are listed; exit code is
  non-zero. If the change is intentional, review it and re-run with `--refresh`;
  if not, you've caught a regression.

Copier's `.copier-answers*.yml` is excluded from the comparison (it carries
machine-specific `_src_path`/`_commit`).

> Golden testing is **selective regression detection**, not a byte-museum.
> Snapshot what matters — trees and key files — and refresh deliberately.

### `update-test` — will an upgrade break downstream projects?

```bash
copyroom update-test aurora basic v1.0.0 v2.0.0
```

This is the most important workshop command, because `copier copy` succeeding is
not enough — long-lived templates must remain *updatable*. It:

1. renders the scenario at `v1.0.0` into `.copyroom_sim/aurora/basic/` and
   git-snapshots it (the baseline an existing user would have);
2. applies deterministic **user edits** from
   `scenarios/aurora/basic-edits.yml` if that file exists (simulating local
   divergence) and commits them;
3. runs `copier update --vcs-ref v2.0.0` (the upgrade);
4. captures conflicts (inline markers) and rejects (`*.rej`);
5. runs the registry `checks` against the updated output.

It reports a clean upgrade or the conflicts/rejects it found. If no edits file
exists, the edit step is a no-op (zero edits) and the update still runs.

#### The edits-file DSL

`scenarios/<template_id>/<scenario_id>-edits.yml` describes deterministic edits
to apply to the *old* render before updating. Supported actions:

```yaml
edits:
  - file: README.md
    action: append
    content: "\n## Local notes\nAdded by the user.\n"

  - file: pyproject.toml
    action: set-field          # YAML/TOML field by path
    path: [project, version]
    value: "9.9.9"

  - file: docs/EXTRA.md
    action: create
    content: "A file the user added locally."
    mode: ""                   # add "x" to mark executable

  - file: src/app.py
    action: patch              # apply a unified diff
    patch: |
      --- a/src/app.py
      +++ b/src/app.py
      @@ ...
```

These let you reproduce a realistic "user has diverged" situation so the update
test exercises real merge behavior.

### `release-check` — is the template ready to tag?

```bash
copyroom release-check aurora
```

The release gate. It:

1. captures the git worktree state **first** (so its own render output doesn't
   dirty the result; `generated/` and `.copyroom_sim/` are excluded),
2. discovers every scenario under `scenarios/aurora/`,
3. runs render+test for each (the **matrix**),
4. runs a golden diff for each (reusing the matrix render — one Copier run per
   scenario, not two),
5. passes only when **matrix passes AND worktree is clean AND every golden diff
   is empty**.

```
Release Check: aurora
  Matrix:     ✅ PASSED (2/2 scenarios rendered, tested)
  Worktree:   ✅ CLEAN
  Golden:     ✅ OK (2/2 scenarios match golden)
  Result:     🟢 PASSED

Note: Release checks are advisory in v0.x.
Tagging is manual: git tag v0.4.0 && git push --tags
```

Release checks are **advisory** in v0.x — CopyRoom reports readiness, but **you**
do the actual `git tag` / `git push --tags`. If the workshop isn't a git repo at
all, the worktree line reads `N/A` and doesn't block the pass.

### `registry`

```bash
copyroom registry list                                   # all template ids + sources + check counts
copyroom registry show <template_id>                     # one resolved entry
copyroom registry validate                               # check every entry; non-zero on failure
copyroom registry add <id> --source <src> [--scaffold]   # create a new registry/<id>.yml
```

`list`/`show`/`validate` are read-only. `validate` confirms each template's
source resolves (a local path exists and is a git repo, or a remote is
reachable), carries at least one **semver tag**, and has a `scenarios/<id>/`
directory — and exits non-zero if anything is off, so it's CI-friendly.

`add` is **create-only**: it writes a fresh `registry/<id>.yml` (refusing to
overwrite an existing one) and, with `--scaffold`, a `scenarios/<id>/default.yml`
skeleton. It **never rewrites `copyroom.yml`** — round-tripping that file through
a YAML library would lose its comments and ordering, so inline-registry edits and
removals stay manual (delete the `registry/<id>.yml` file to remove an entry).

---

## A typical authoring loop

```bash
# 1. iterate on the template, render a scenario, eyeball it
copyroom render aurora basic

# 2. once it's right, lock it in
copyroom golden aurora basic --refresh

# 3. prove an upgrade path from the last release
copyroom update-test aurora basic v1.0.0 HEAD

# 4. before tagging
git add -A && git commit -m "template: …"
copyroom release-check aurora
git tag v2.0.0 && git push --tags
```

## See also

- [Configuration](configuration.md) — `copyroom.yml` and registry schema.
- [Adoption](adoption.md) — `templatize` scaffolds a workshop for you.
- [Copier overview](../copier/overview.md) — what render/update actually do.
