# Implementation — state and verification

This record describes the CopyRoom layer implementation and its original
verification. Fleet results are historical and do not describe current state.

## CopyRoom layer changes

| # | Change | State |
|---|---|---|
| 1 | `project/layers.py`: layer model, discovery, resolution, and answer names | shipped |
| 2 | `_compat/copier.py`: separate Copier's answers file from its data file | shipped |
| 3 | `project/update.py`: scoped updates and update-all workflow | shipped |
| 4 | `manage/layer.py`: add and list commands | shipped |
| 5 | `manage/adopt.py`: per-layer link and drift behavior | shipped |
| 6 | `session/detector.py`: recognize overlay-only projects | shipped |
| 7 | `template/workspace.py`: read a selected answers file | shipped |
| 8 | `project/inspect.py`: report every layer and update state | shipped |
| 9 | `cli.py` and `session/model.py`: layer commands and options | shipped |
| 10 | User and developer docs | shipped |
| 11 | Canonical skill asset | shipped |
| 12 | `demo/walkthrough.sh`: add and update an overlay | shipped |

`doctor` was not changed. It reports environment health. `layer list`, `inspect`,
and `status` report layer state.

## Verification

| What | How | Historical result |
|---|---|---|
| Copier supports separate answers files | [`spike-layers.sh`](spike-layers.sh) | all five questions passed |
| Layer behavior against a real managed repo | [`verify-overlay-layer.sh`](verify-overlay-layer.sh) | all checks passed |
| Independent layers on a real base template | [`verify-two-real-layers.sh`](verify-two-real-layers.sh) | all checks passed |
| Layer model | unit and integration tests | 40 passed |
| Full suite | `devenv shell -- uv run pytest -q` | 588 passed, 2 skipped |
| Lint | `devenv shell -- uv run ruff check src/ tests/` | clean |
| End-to-end demo | `devenv shell -- bash demo/walkthrough.sh` | passed |

The original real-repo verification checked that one layer kept the repo's
instructions, skills, and symlink intact. It also checked reapplication,
version updates, and seeding a missing file. Current integration tests use
neutral files and do not deploy agent configuration.

## Three implementation findings

### 1. `layer add` must pass overwrite behavior

The first real-repo verification failed when a layer-owned file already existed
with different content:

```text
Interactive session required: Consider using --overwrite
```

Copier prompts for conflicting files. It then fails without a terminal. The
first verification used targets where files were absent or byte-identical, so it
missed this case. CopyRoom now applies a layer with overwrite behavior. Updates
still use three-way merges. A regression test covers a locally changed file.

### 2. Template order mattered when both templates seeded one file

The original base and overlay templates could both add `AGENTS.md`. On a repo
six genome versions behind and missing that file, updating the genome first
produced conflicts in its changed files. Adding the overlay first caused one
more conflict on `AGENTS.md`:

| Conflicts during base update | Control | With overlay applied first |
|---|---|---|
| `devenv.nix`, `devenv.yaml`, `.gitignore`, `pyproject.toml`, `.agents/devenv/*` | yes | yes |
| `AGENTS.md` | no | yes |

`_skip_if_exists` prevented overwrites, but the first template still seeded the
file. The rollout guide therefore recommended updating the base before adding
an overlay when both shipped the same file. Current docs explain this rule with
a neutral README example.

### 3. `layer add` recorded a local clone as `_src_path`

The `gh:` source form first clones a template so CopyRoom can read `copier.yml`.
The early implementation passed that clone to Copier. Copier recorded the
machine-local cache path. A later update would fail on another machine or after
the cache was pruned.

CopyRoom now passes the caller's original source string to Copier. It uses the
clone only to read the template configuration. `copyroom new` already followed
this rule. The regression test checks that answers keep the caller's source.

## Update-all behavior

The first design used one up-front worktree check. Copier refuses a dirty
destination, so a second layer could not run after the first layer changed the
tree. CopyRoom now commits each layer's update before it runs the next. It leaves
the final layer uncommitted and stops if a layer reports conflicts or rejects.
`test_all_layers_commits_between_layers` covers this behavior.

## Historical release state

| Repo | State at the time |
|---|---|
| CopyRoom | `main` at `11a9a76`, tagged `v0.7.2`, pushed |
| Overlay template repository | `main` at `effb8e9`, tagged `v0.1.0`, pushed |
| Machine toolchain | CopyRoom installed editable from the main checkout |

CopyRoom tag history:

| Tag | Published | Note |
|---|---|---|
| `v0.7.0` | no | `layer add` lacked overwrite behavior |
| `v0.7.1` | yes | recorded a machine-local source path |
| `v0.7.2` | yes | fixed the recorded source path |

The published `v0.7.1` tag remains. It was not deleted because it had already
been pushed. Repos that used it needed to check their layer answers for a cache
path.

The overlay repository used a detached colocated Git head during its first
release. Gitman's local branch needed a fast-forward before publish. That issue
is part of the historical rollout record.

## Historical rollout procedure

The original rollout updated the base template first, then added the overlay:

```bash
copyroom update
copyroom layer add <template-source>
copyroom layer list
```

The overlay source and fleet state have since changed. Do not use the historical
counts below as a current inventory.

## Follow-up ownership findings

1. Gitman's skill had no owner-side materializer. Gitman and repoman own that
   gap. CopyRoom should continue to export only its own package set.
2. The family ownership document needed to list each source tool and generated
   router separately.
3. The Python genome could stop shipping duplicate CopyRoom skill files. That
   change belongs to the genome, because new projects receive those files from
   its template.
