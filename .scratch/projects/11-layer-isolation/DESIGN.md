# Design — independent Copier layers

CopyRoom needed to manage repos with more than one Copier template. This design
added a layer model and kept each template's answers and update history separate.

## The model

> A **layer** is one template's management of a repo, recorded in its own Copier
> answers file.

| Layer | Answers file | Ships | Owner |
|---|---|---|---|
| `base` | `.copier-answers.yml` | the repo skeleton | the genome template |
| `docs` | `.copier-answers.docs.yml` | documentation files | the documentation template |
| `<name>` | `.copier-answers.<name>.yml` | any focused file set | that template |

**Discovery, not configuration.** CopyRoom scans for answers files. It does not
read layer names from `copyroom.project.yml`. A layer link is removed by deleting
its answers file.

**Layers are independent.** Tests showed that an update to one answers file does
not touch another layer's files or answers. CopyRoom runs the same single-layer
workflow for every layer.

## CLI surface

```text
copyroom layer add <template> [--as NAME] [--ref REF]
copyroom layer list [--json]
copyroom update [REF] [--layer NAME]
copyroom update --all-layers
copyroom adopt <template> [--layer NAME]
```

`layer add` is separate from `adopt`. `adopt` records a link when the repo
already matches a template. `layer add` copies a template's files into a repo.
This keeps `adopt` report-only unless the caller passes `--write`.

`layer add` reads `_answers_file` from `copier.yml`. This setting names the
layer, so `--as` is optional when the template declares it. The command falls
back to `--as` or the template directory name when it does not.

`layer add` applies files with `copier copy`. The command passes overwrite
behavior because Copier otherwise prompts for each conflict and fails without a
terminal. `_skip_if_exists` protects repo-owned files. Use `update --layer` for
later three-way merges. Use `--force` only to retarget an existing layer.

## Updating every layer

`--all-layers` takes no ref because each template has its own version history.
Copier refuses a dirty destination. CopyRoom therefore commits each layer's
result before it runs the next. The final layer stays uncommitted for review. A
conflict stops the run. The clean-worktree check runs once before any update.

## Code changes

| File | Change |
|---|---|
| `project/layers.py` | Added the `Layer` model, discovery, name parsing, and resolution. |
| `_compat/copier.py` | Added an `answers_file` argument for Copier's `-a` option. Renamed the old `--data-file` parameter. |
| `project/update.py` | Added layer-scoped updates and layer-qualified branch names. |
| `manage/layer.py` | Added `layer add` and `layer list`. |
| `manage/adopt.py` | Added per-layer links and drift reports for partial templates. |
| `session/detector.py` | Recognizes a repo managed by an overlay alone. |
| `template/workspace.py` | Reads the selected answers file. |
| `project/inspect.py` | Reports each layer and update state. |
| `cli.py` | Added layer commands and update/adopt options. |

`doctor` was not changed. It reports environment health. `layer list`, `inspect`,
and `status` already report layer state.

## Compatibility and ownership

Every command defaults to `base` and `.copier-answers.yml`. A single-template
repo keeps its prior behavior.

The existing file ownership split remains:

| Owner | Files | Materialized by |
|---|---|---|
| CopyRoom | its canonical package files | `copyroom agent-files export` |
| Genome | project-specific scaffold files | `copyroom update` on the base layer |
| Repo manager | the generated manager router | `repoman install-skills` |
| Repo | any other project file | the repo |

Layers add another template owner. They do not change the owner of existing
files.

## Rejected alternatives

| Alternative | Reason |
|---|---|
| Keep a file-copy script | It has no version record, merge base, or conflict report. |
| Copy tool-owned skills into every repo | The copies can drift from their source. |
| Put user preferences in a language genome | That couples a language template to one user's setup. |
| Use a symlink to a shared directory | The target is machine-local and invisible to version control. |
| Add a second sync system to CopyRoom | Layers reuse Copier's existing update workflow. |
