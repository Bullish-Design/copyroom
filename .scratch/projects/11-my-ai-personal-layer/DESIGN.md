# Design — template *layers*, and `my-ai` as the personal layer

Two changes, one in each repo. CopyRoom learns that a project can be managed by
more than one template; `my-ai` becomes one of those templates.

---

## Part 1 — CopyRoom: the layer concept

### The model

> A **layer** is one template's management of a repo, recorded in its own Copier
> answers file.

| Layer | Answers file | Ships | Owner |
|---|---|---|---|
| `base` | `.copier-answers.yml` | the whole repo skeleton | the genome (`template-py`) |
| `my-ai` | `.copier-answers.my-ai.yml` | the user's agent files | `my-ai` (the personal layer) |
| *(any)* | `.copier-answers.<name>.yml` | whatever that template ships | that template |

**Discovery, not configuration.** The layer set is a glob:
`.copier-answers.yml` → the reserved name `base`; `.copier-answers.<name>.yml` →
`<name>`. Nothing is declared in `copyroom.project.yml`, nothing can drift out of
sync with reality, and a layer is removed by deleting one file.

**Layers are independent.** SPIKE Q3 proved neither layer's update touches the
other's files or answers. So CopyRoom never sequences, merges, or arbitrates
between layers — it runs the same single-layer workflow N times. This is what
keeps the feature small.

### CLI surface — one new command, two new flags

```
copyroom layer add <template> [--as NAME] [--ref REF]   # apply a template as a layer
copyroom layer list [--json]                            # every layer, its ref, whether an update is available
copyroom update [REF] [--layer NAME]                    # update one layer (default: base)
copyroom update --all-layers                            # update every layer to its latest tag
copyroom adopt <template> [--layer NAME] …              # record the link in that layer's answers file
```

`layer` mirrors the existing `agent-files <export|check>` idiom (an action
positional, runs anywhere, no mode gating) rather than inventing a new one.

**Why `layer add` and not `adopt`.** `adopt` answers *"this repo already looks
like the template — record the link."* It is report-only and writes no repo
files. Applying the personal layer to 40 existing repos is the opposite motion:
the files are **not** there yet and must land. That's a `copier copy`, so it gets
its own verb. Keeping them separate also keeps `adopt`'s report-only promise
intact.

**`--as` is usually unnecessary.** `layer add` reads `_answers_file` from the
template's `copier.yml` and derives the name from it (`.copier-answers.my-ai.yml`
→ `my-ai`), falling back to `--as`, then to the template's directory name. So
`copyroom layer add gh:Bullish-Design/my-ai` is the whole command.

**`layer add` is idempotent.** It is a `copier copy -a …`, so re-running it on a
repo that already has the layer re-lands the layer's files; `_skip_if_exists`
protects the repo-owned ones. Refuses to *retarget* an existing layer to a
different template without `--force`.

**`--all-layers` commits between layers.** Discovered during implementation, not
design: Copier refuses a dirty destination (*"Destination repository is dirty;
cannot continue"*), and the first layer's update necessarily dirties the tree, so
converging N layers in one pass is only possible if each layer's result is
committed before the next runs. That is also the history you want — one
reviewable commit per layer convergence. The clean-worktree guard therefore runs
once for the whole run (so `git reset --hard` is always the way out), the last
layer is left uncommitted for review like a single `update`, and a layer that
leaves conflicts stops the run rather than committing them unreviewed.

### Code changes

| File | Change |
|---|---|
| `project/layers.py` **(new)** | `Layer` dataclass, `discover_layers()`, `resolve_layer()`, `answers_filename()`, `layer_name_for()` |
| `_compat/copier.py` | add a true `answers_file=` (→ `-a`) to `copier_copy`/`copier_update`; rename the existing misnamed `answers_file` param (which maps to `--data-file`) to `data_file` |
| `project/update.py` | `update_project(..., layer="base")`; read the layer's answers file; pass `-a`; layer-qualified isolation-branch name |
| `manage/adopt.py` | `adopt(..., layer="base")`; per-layer "already managed" refusal; scope drift to the layer's rendered file set for non-base layers |
| `session/detector.py` | `is_project` also matches `.copier-answers.*.yml` |
| `template/workspace.py` | `read_answers(root, answers_file=…)` |
| `project/inspect.py` | `inspect`/`status` report every layer |
| `cli.py` | `layer` command; `--layer` / `--all-layers` on `update`; `--layer` on `adopt` |

`doctor` is deliberately **not** touched: it reports environment health (copier,
git, cache, agent-files conformance). The layer set is a project fact, and
`layer list` / `inspect` / `status` already report it three ways.

**Backward compatibility.** Every entry point defaults to `base` /
`.copier-answers.yml`, so a single-template repo behaves exactly as before. The
`agent:` config section, the `overlay` → `--exclude` mapping, and the whole
agent-files convention are untouched.

### What layers do *not* change

The ownership split from repoman's `docs/AGENT-FILES.md` stands. Layers add one
row to it:

| Owner | Files | Materialized by |
|---|---|---|
| tool-shipped | copyroom's canonical set | `copyroom agent-files export` |
| genome / fleet | `devenv-*` skills, `.agents/devenv/` docs | `copyroom update` (base layer) |
| **personal** ← new | the user's cross-repo agent files | `copyroom update --layer my-ai` |
| repoman's router | `.agents/skills/repoman/` | `repoman install-skills` (generated) |
| repo overlay | anything else | the repo |

---

## Part 2 — `my-ai`: the personal layer template

### New shape

```
my-ai/
├── copier.yml                              # _subdirectory, _answers_file, _preserve_symlinks,
│                                           # _copy_without_render, _skip_if_exists
├── template/                               # ← everything my-ai ships into a repo
│   ├── .copier-answers.my-ai.yml.jinja
│   ├── AGENTS.md                           # SEED ONLY (_skip_if_exists)
│   ├── CLAUDE.md -> AGENTS.md              # committed as mode 120000
│   └── .agents/skills/my-ai/SKILL.md       # the personal law
├── AGENTS.md / CLAUDE.md / .agents/        # my-ai's OWN agent surface (self-applied)
├── .copier-answers.my-ai.yml               # my-ai dogfoods its own layer
└── README.md, devenv.*, pyproject.toml
```

`copier.yml`:

```yaml
_subdirectory: template
_answers_file: .copier-answers.my-ai.yml
_preserve_symlinks: true
_copy_without_render: [".agents/skills/**"]
_skip_if_exists: ["AGENTS.md"]
```

No questions: the personal layer is the same in every repo. That is the point.

### What it ships, and why exactly this

1. **`.agents/skills/my-ai/SKILL.md` — the personal law.** The cross-repo
   material currently stranded in my-ai's `AGENTS.md` (the family contract, the
   agent-files convention, the standing preferences) moves here. It is skill-
   shaped: uniform in every repo, so its three-way merge is always clean, and it
   collides with nothing the repo owns.
2. **`CLAUDE.md -> AGENTS.md`** — uniform everywhere, and the one file the
   convention says must be identical in every repo.
3. **`AGENTS.md` — seed only.** `_skip_if_exists` means a repo with its own
   instructions keeps them (SPIKE Q4, on both paths), and a repo with none gets
   a blueprint that points at the personal skill. This replaces the
   `--force`/no-op dilemma with the correct third option.

### What it stops shipping

The copies of `copyroom`, `copyroom-adopt`, `copyroom-template-edit`, `gitman`,
and `repoman` skills are **not** in `template/`. Their owners materialize them
(FINDINGS §2). `repoman`'s especially: it is generated per repo from that repo's
manager roster, so a distributed snapshot is wrong wherever it lands.

my-ai's *own root* `.agents/skills/` keeps them — like every family repo, it
carries its own materialized agent surface. It just no longer redistributes them.

### `scripts/my-ai-sync.py` is deleted

`copyroom layer add` / `copyroom layer update` replace it, with a version record,
a three-way merge, conflict capture, and a fleet-wide "which repos are behind"
answer that the copy script structurally could not provide. `devenv.nix` drops
the `scripts.my-ai-sync` wiring and `enterShell` line.

### my-ai applies the layer to itself

`copyroom layer add . ` inside my-ai records `.copier-answers.my-ai.yml` at its
own root and materializes `.agents/skills/my-ai/SKILL.md` there. The repo then
*is* an instance of the thing it distributes, so `copyroom update --layer my-ai`
inside my-ai is a live self-check — the strongest available verification that the
mechanism works.

---

## Rollout across the fleet

Per repo, one command, then commit:

```bash
copyroom layer add gh:Bullish-Design/my-ai      # or the local path in dev mode
copyroom layer list                            # confirm both layers
```

Thereafter:

```bash
copyroom update --layer my-ai                  # converge the personal layer
copyroom update --all-layers                   # converge everything
```

## Rejected alternatives

| Alternative | Why not |
|---|---|
| Keep `my-ai-sync.py`, polish it | Rebuilds Copier's three-way merge badly; no version record; the `AGENTS.md` dilemma is unfixable in a file copier |
| Ship the personal skills as **copyroom package assets** | Wrong owner. The set is the *user's*, versioned on the user's schedule, not copyroom's release cadence — and it would put personal content in a published tool |
| Fold the personal files into **template-py** (the genome) | Couples "a Python project" to "this user's preferences"; only reachable by repos generated from that one genome; and updates the whole skeleton to change one skill |
| Point `agent.skills_dir` at a **symlinked shared directory** | Breaks per-repo divergence and the overlay contract; invisible to git; breaks on any machine without the checkout |
| Give copyroom a generic **multi-source `agent-files` sync** | A second convergence mechanism inside the tool whose job is convergence. Layers reuse the existing update workflow instead of adding a parallel one |
