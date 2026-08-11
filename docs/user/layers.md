# Template layers — one repo, several templates

A **layer** is one template's management of a repo, recorded in its own Copier
answers file. A repo can have several, and they converge independently.

| Layer | Answers file | Typically ships |
|-------|--------------|-----------------|
| `base` | `.copier-answers.yml` | the whole repo skeleton — the *genome* (template-py, template-nix, …) |
| `<name>` | `.copier-answers.<name>.yml` | a slice of a repo, layered on top |

The motivating case is the **personal layer**: a template
([`my-ai`](https://github.com/Bullish-Design/my-ai)) that carries the user's
`AGENTS.md` seed, the `CLAUDE.md` symlink, and their personal skills, and applies
to *every* repo regardless of which genome generated it — or whether one did.

```
a repo
├── .copier-answers.yml          ← the genome         → copyroom update
└── .copier-answers.my-ai.yml    ← the personal layer → copyroom update --layer my-ai
```

## Why layers rather than a sync script

Copying files into N repos is easy; keeping them *current* is not. A layer is a
real Copier template, so each repo gets:

- a **version record** — which release of the layer it is on;
- a **three-way merge** on update, not an overwrite — local edits survive, and a
  genuine collision surfaces as a conflict to resolve deliberately;
- a **"which repos are behind"** answer, from `copyroom status` / `layer list`;
- the **overlay contract** — `agent.overlay` in `copyroom.project.yml` maps to
  Copier `--exclude`, so a repo can permanently diverge on one file.

## Discovery, not configuration

The layer set is a glob over the project root. Nothing declares it, so nothing
can drift out of sync with what Copier actually recorded, and a layer is removed
by deleting one file.

## Layers are independent

`copier update -a <answers file>` scopes the merge to a single layer: converging
one never reads, writes, or merges another's files or answers (verified
empirically — `.scratch/projects/11-my-ai-personal-layer/SPIKE.md`). There is no
ordering to get right and no arbitration to configure. CopyRoom runs the same
single-layer workflow once per layer.

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
copyroom layer add gh:Bullish-Design/my-ai
```

The layer **names itself**: `add` reads `_answers_file` from the template's
`copier.yml` (`.copier-answers.my-ai.yml` → `my-ai`), so `--as` is only for
templates that declare nothing.

It is a `copier copy` scoped to that answers file, so it is idempotent —
re-running re-lands the layer's files and `_skip_if_exists` protects the repo's
own. Retargeting an existing layer to a *different* template needs `--force`.

**`add` overwrites the files the layer ships.** It has to: a layer lands in a
repo that already has files, and without `--overwrite` Copier prompts per
conflict and then fails outright when stdin isn't a terminal — every agent and CI
invocation. So a repo-local edit to a layer-owned file is replaced, not merged.
That is the difference between *applying* a layer and *converging* it: after the
first `add`, use `copyroom update --layer NAME`, which three-way-merges and
surfaces a real collision as a conflict. Files the template declares in
`_skip_if_exists` (e.g. `AGENTS.md`) are never overwritten by either path. Review
`git status` after an `add`.

`layer add` runs anywhere, including a repo with no template at all.

### `layer add` vs `adopt`

They answer different questions, which is why they are different commands:

| | `adopt` | `layer add` |
|---|---|---|
| Question | *"this repo already looks like the template — record the link"* | *"this repo doesn't have these files — put them here"* |
| Writes repo files | **no** (report-only; only the answers file, under `--write`) | **yes** — that's the point |
| Output | a drift report + a reviewable patch | what landed |

`adopt` also takes `--layer`, for the case where a repo genuinely already matches
an overlay template and you only want the link recorded. Its drift report drops
the "repo-only" set for a non-base layer: an overlay template is *partial* by
construction, so every file it doesn't ship would otherwise read as drift.

### `update --layer` / `--all-layers`

```bash
copyroom update --layer my-ai          # converge one layer to its latest tag
copyroom update v0.3.0 --layer my-ai   # ...or to a specific ref
copyroom update --all-layers           # converge every layer
```

`--layer` defaults to `base`, so a single-template project behaves exactly as it
always has.

`--all-layers` takes no ref (a single ref is meaningless across different
templates) and **commits each layer's result before running the next**. That is
not a convenience: Copier refuses a dirty destination (*"Destination repository
is dirty; cannot continue"*), and the first layer's update necessarily dirties
the tree. It is also the history you want — one reviewable commit per layer. The
last layer is left uncommitted, exactly like a single `update`.

The clean-worktree guard runs **once, up front** for the whole run, so
`git reset --hard` back to the starting commit is always the way out. A layer
that leaves conflicts or rejects stops the run rather than committing them
unreviewed.

### `layer list`

```
Template layers → /home/andrew/Documents/Projects/gitman
  base         .copier-answers.yml
    template: template-py
    ref:      v1.4.0
  my-ai        .copier-answers.my-ai.yml
    template: my-ai
    ref:      v0.2.0
```

`copyroom inspect` and `copyroom status` also report every layer (including in
`--json`); `status` computes `update_available` per layer, and its top-level
`update_available` means *any* layer is behind.

## Rollout order matters when two layers ship the same file

Layers don't fight over files they each own exclusively — that's most of them.
But `AGENTS.md` is shipped by *both* the genome (template-py) and the personal
layer, because either may be the one to seed a repo that has none. `_skip_if_exists`
resolves that safely — **whoever gets there first wins, and nobody overwrites**.
Which means the order you apply them in decides who seeds it.

> **Bring the base layer current first, then add the personal layer.**
>
> ```bash
> copyroom update                                     # genome first
> git add -A && git commit                            # review, commit
> copyroom layer add gh:Bullish-Design/my-ai          # then the personal layer
> ```

Do it the other way round on a repo that is *behind* on its genome and has no
`AGENTS.md`, and you get one avoidable conflict: the personal layer seeds
`AGENTS.md`, then the genome's update tries to add its own version and
three-way-merges against a file it has never seen.

Measured on a real repo (argentic, 6 genome versions behind, no `AGENTS.md`): the
genome update conflicts on `devenv.nix`, `devenv.yaml`, `.gitignore`,
`pyproject.toml` and the `.agents/devenv/` docs either way — that's its own
catch-up drift — **plus `AGENTS.md`** only when the personal layer went first.

For a repo already current on its genome, or one with no genome at all, order
doesn't matter.

## Writing an overlay template

An overlay template is an ordinary Copier template with three extra
declarations:

```yaml
_subdirectory: template
_answers_file: .copier-answers.my-ai.yml    # the layer's identity
_preserve_symlinks: true                     # CLAUDE.md -> AGENTS.md survives copy AND update
_copy_without_render:
  - ".agents/skills/**"                      # skills carry literal {{ }} examples
_skip_if_exists:
  - "AGENTS.md"                              # seed only; never clobber a repo's own
```

`_skip_if_exists` is the key one for a layer that lands on repos which already
have their own version of a file. It holds on the **update** path too, which is
what lets a single layer serve dozens of repos that each own their `AGENTS.md`.

Keep questions out of an overlay template where you can: a layer that is
identical in every repo has a trivially clean three-way merge everywhere.

## See also

- [Agent files](agent-files.md) — the convention the personal layer delivers, and the skill-ownership split.
- [Projects: new & update](projects.md) — the base-layer lifecycle.
- [Adoption](adoption.md) — `templatize` and `adopt`.
- [Copier overview §5](../copier/overview.md#5-copier-update--the-three-way-merge) — the merge each layer converges with.
