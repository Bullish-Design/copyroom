# Template layers — one repo, several templates

A **layer** is one template's management of a repo, recorded in its own Copier
answers file. A repo can have several layers, and they converge independently.

| Layer | Answers file | Typically ships |
|-------|--------------|-----------------|
| `base` | `.copier-answers.yml` | the whole repo skeleton — the *genome* |
| `<name>` | `.copier-answers.<name>.yml` | one focused part of the repo |

For example, a repo can use a genome and a documentation overlay:

```text
repo/
├── .copier-answers.yml              ← genome → copyroom update
└── .copier-answers.docs.yml         ← docs   → copyroom update --layer docs
```

## Why layers rather than a sync script

Copying files into many repos is easy. Keeping them current is harder. A layer is
a Copier template, so each repo gets:

- a **version record** — the release of the layer it uses;
- a **three-way merge** on update — local edits survive, and real conflicts need
  deliberate resolution;
- a report that shows which layers have updates available.

## Discovery, not configuration

CopyRoom finds layers by scanning the project root for answers files. Nothing
else declares them. This keeps the layer list in sync with Copier's records.
Delete an answers file to remove its layer link.

## Layers are independent

`copier update -a <answers file>` scopes the merge to one layer. An update does
not read, write, or merge another layer's files or answers. The behavior was
verified in [the layer-isolation spike](../../.scratch/projects/11-layer-isolation/SPIKE.md).
CopyRoom uses the same single-layer workflow for every layer.

## The commands

```bash
copyroom layer add <template> [--as NAME] [--ref REF] [--force]
copyroom layer list [--json]
copyroom update [REF] [--layer NAME]
copyroom update --all-layers
copyroom adopt <template> [--layer NAME] …
```

### `layer add` — apply a template as a layer

```bash
copyroom layer add gh:example/project-docs
```

The layer can name itself in `copier.yml` with `_answers_file`. For example,
`.copier-answers.docs.yml` selects the name `docs`. Then `--as` is optional.
Templates without this setting use `--as NAME` or the template directory name.

`layer add` runs `copier copy` for that answers file. It applies the layer's
files and records its source. Running it again reapplies those files. The
template's `_skip_if_exists` list protects repo-owned files. Retarget an existing
layer to another template only with `--force`.

**`add` overwrites files that the layer ships.** It must: a layer enters a repo
that already has files. Without `--overwrite`, Copier prompts for each conflict
and fails when no terminal is available. A repo edit to a layer-owned file is
replaced. After the first `add`, use `copyroom update --layer NAME` to merge
changes and report real conflicts. Review the worktree after `add`.

`layer add` runs in any repo, including one with no template link.

### `layer add` vs `adopt`

The commands answer different questions:

| | `adopt` | `layer add` |
|---|---|---|
| Question | Does this repo already match the template? | Should this template add its files? |
| Writes repo files | No, unless `--write` records its answers file | Yes |
| Output | A drift report and a reviewable patch | The paths the template wrote |

`adopt` also takes `--layer`. Use it when a repo already matches a partial
template and only needs the link recorded. Its drift report omits the repo-only
set for a non-base layer. An overlay does not manage every file in the repo.

### `update --layer` / `--all-layers`

```bash
copyroom update --layer docs          # converge one layer to its latest tag
copyroom update v0.3.0 --layer docs   # converge to a specific ref
copyroom update --all-layers          # converge every recorded layer
```

`--layer` defaults to `base`. A single-template project keeps its current
behavior.

`--all-layers` takes no ref. One ref cannot name versions from different
templates. CopyRoom commits each layer's result before it runs the next. Copier
refuses a dirty destination, so later layers require a clean tree. The last
layer stays uncommitted for review. A layer that leaves conflicts or rejects
stops the run.

### `layer list`

```text
Template layers → /path/to/project
  base         .copier-answers.yml
    template: project-template
    ref:      v1.4.0
  docs         .copier-answers.docs.yml
    template: project-docs
    ref:      v0.2.0
```

`copyroom inspect` and `copyroom status` report every layer. The JSON reports
include the same records. `status` computes `update_available` for each layer;
its top-level field is true when any layer is behind.

## Rollout order when layers ship the same file

Layers do not conflict when they manage separate files. Two templates can also
ship the same seed file with `_skip_if_exists`. The first template writes it;
the second leaves it unchanged. If a repo is behind on its genome, update the
genome before adding an overlay that ships the same file.

For example, suppose both templates can add `README.md`, and the repo has no
README. Update the base template first, then add the overlay. This avoids an
unnecessary merge when the base template later adds its own version.

## Writing an overlay template

An overlay is an ordinary Copier template. It can use `_answers_file` to name
its layer, preserve a symlink, and avoid rendering literal snippets:

```yaml
_subdirectory: template
_answers_file: .copier-answers.docs.yml
_preserve_symlinks: true
_copy_without_render:
  - "docs/snippets/**"
_skip_if_exists:
  - "README.md"
```

`_skip_if_exists` protects a file that may already belong to the repo. It also
applies during updates. Keep questions out of an overlay when its files should
be the same in every repo. Identical content gives each repo a clean merge.

## See also

- [Projects: new & update](projects.md) — the base-layer lifecycle.
- [Adoption](adoption.md) — `templatize` and `adopt`.
- [Copier overview §5](../copier/overview.md#5-copier-update--the-three-way-merge) — the merge each layer converges with.
