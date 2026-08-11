# Agent files — the convention, how templates ship it, and the overlay contract

CopyRoom is the reference implementation of the **`*man` family's agent-files
convention** — one convention every repo follows, so any agent tooling works in
any family repo:

| File | Role |
|------|------|
| `.agents/skills/<name>/SKILL.md` | Skills — imperative, short, domain-bounded. The tool-agnostic standard (not `.claude/skills/`). |
| `AGENTS.md` | The **canonical** repo instructions file — one source of truth. |
| `CLAUDE.md` | A **symlink to `AGENTS.md`** — every tool reads the same file. |

The canonical skill set ships **inside the CopyRoom package** (assets under
`src/copyroom/agent/assets/skills/`) — one source of truth. `copyroom agent-files`
materializes and verifies it; templates carry the files; `copyroom update`
converges them; a repo can **overlay** its own divergence on top.

## The commands

```
copyroom agent-files export [--target DIR]   # materialize skills + AGENTS.md + CLAUDE.md
copyroom agent-files check   [--target DIR]   # conformance report (warn-level)
```

Both run **anywhere** (no mode gating), like `doctor`. The default target
resolves to: the nearest **git repo root** → `$DEVENV_ROOT` → the cwd. Inside a
template repo you can run it from any subdir, including `template/`.

### `export`

Idempotent materialization:

- copies the canonical skills into `<target>/.agents/skills/` (overwriting only
  the skills CopyRoom owns — see [the two-writer rule](#ownership-and-the-two-writer-rule));
- writes a blueprint `AGENTS.md` **only if absent** — an existing `AGENTS.md`
  (yours, or the template's) is never clobbered;
- ensures `CLAUDE.md` is a symlink → `AGENTS.md` — recreated if missing or
  broken, **never replaced when it's a regular file** (that may be a deliberate
  local divergence; export only flags it, `check` reports it).

### `check`

A warn-level conformance report: `AGENTS.md` present; `CLAUDE.md` a symlink to
it (a regular file is a WARN — flagged, not fixed); every canonical skill
present **and** matching the shipped assets at the current CopyRoom version; and
any extra files under `.agents/skills/` reported as present (they're legal —
template-shipped or a local overlay — and can't be distinguished statically).
`copyroom doctor` runs the same check at warn-level, so a non-conformant repo
never breaks `doctor`'s exit code.

## How templates ship the files

A template ships four things under its `template/`:

```
template/
├── AGENTS.md                              # canonical instructions (edit freely)
├── CLAUDE.md -> AGENTS.md                 # symlink, committed as such (git mode 120000)
├── .agents/skills/copyroom/SKILL.md       # the entry skill
└── copier.yml                             # declares _preserve_symlinks + _copy_without_render
```

Seed it with a single command from the template repo root (or its `template/`
subdir):

```bash
copyroom agent-files export
```

### The two `copier.yml` declarations (both required)

```yaml
_preserve_symlinks: true
_copy_without_render:
  - ".agents/skills/**"
  - ".agents/devenv/**"   # only if the template ships docs there (the genome does)
```

1. **`_preserve_symlinks: true`** — **required.** Without it, Copier dereferences the
   `CLAUDE.md` symlink into a regular file on both `new` and `update` (verified
   empirically, Copier 9.17 — see `.scratch/projects/07-agent-files/SPIKE.md`).
   With it, the symlink survives both, committed as a real symlink
   (`git ls-files -s` shows mode `120000`).
2. **`_copy_without_render`** — **required for every tracked `.agents/` subtree.**
   Skills contain literal `{{ }}` examples; a `.jinja`-suffixed skill would be
   rendered (and could clobber the plain `SKILL.md`). Declare `".agents/skills/**"`
   always, and add `".agents/devenv/**"` for templates that ship docs under
   `.agents/devenv/` (template-py does both) — that carve-out keeps everything
   under `.agents/` byte-for-byte.

> **No CopyRoom finalize step is needed.** Because Copier preserves the symlink
> when the template declares `_preserve_symlinks`, `copyroom new`/`update`/
> `adopt` ship the files as-is. (`adopt` is report-only and never writes repo
> files besides `.copier-answers.yml`.)

## How `copyroom update` converges them

`copier update` is a three-way merge ([overview §5](../copier/overview.md#5-copier-update--the-three-way-merge)):
the base is the template rendered at the recorded `_commit`, the new side is the
target ref, and the project's current tree is the merge input. So:

- a **new skill** added by the template converges cleanly (adds the file);
- an **edited skill** three-way-merges — a template change and a local edit on
  the same lines surface as a conflict, to resolve deliberately;
- a **removed skill** is removed by the update.

## The overlay contract — three ways to diverge

| Case | What happens | Who owns it |
|------|--------------|-------------|
| **Add** — a local file under `.agents/skills/` | `copyroom update` never touches it | the repo |
| **Edit** — a local edit to a template-managed skill | the next update three-way-merges it; a conflict means both sides changed — resolve deliberately | the repo + the template |
| **Permanently diverge** — declared in `agent.overlay` | the next update stops managing it (`--exclude`) | the repo |

To stop the template managing a skill forever (chronic conflicts are a design
smell — declare instead):

```yaml
# copyroom.project.yml
agent:
  overlay:
    - copyroom-adopt
```

`copyroom update` reads `agent.overlay` and passes
`--exclude .agents/skills/<name>/**` to `copier update`, so the template stops
touching that skill while everything else still updates (verified empirically —
the project's local version survives, the rest of the project updates).
`agent-files export`/`check` respect it too: an overlaid skill is left alone and
its divergence is expected, not a warning.

## Ownership and the two-writer rule

Every file under `.agents/skills/` has exactly one owner:

| Owner | Which skills | Materialized by |
|---|---|---|
| **tool-shipped** | CopyRoom's canonical set (`copyroom`, `copyroom-adopt`, `copyroom-template-edit`) | `copyroom agent-files export` |
| **genome / fleet** | the family's `devenv-*` literacy skills + `.agents/devenv/` docs | `copyroom update` (the base layer) |
| **personal** | the user's cross-repo skills | `copyroom update --layer my-ai` — see [layers](layers.md) |
| **repoman's router** | `.agents/skills/repoman/` — *generated* from the repo's manager roster | `repoman install-skills` |
| **repo overlay** | anything else | the repo |

CopyRoom owns only the canonical set — the skills under its package assets, plus
the `agent-files` command. It never fights another writer: it materializes
exactly its canonical set and reports, never rewrites, the rest.

> The **personal layer** is why this table has a row that is neither the tool nor
> the genome. Skills that belong to the *user* — true in every repo, versioned on
> the user's own schedule — can't live in CopyRoom's package (wrong owner, wrong
> release cadence) or in one genome (only reaches repos made from it). They ship
> as their own Copier layer instead. See [layers](layers.md).

> ⚠️ **`.agents/` is dual-use.** `.agents/skills/` is the convention and is
> tracked. The rest of `.agents/` (e.g. `.agents/pi/`, a pi package's
> `node_modules`) is platform/tool runtime state and stays gitignored. Repos
> adopting the convention should carve out `.agents/skills/`, `AGENTS.md`, and
> `CLAUDE.md` in `.gitignore` — CopyRoom's own repo does exactly this.

## The project-config section

`copyroom.project.yml` carries an advisory `agent:` section (all fields
defaulted; unknown fields ignored, like every other section):

```yaml
agent:
  skills_dir: .agents/skills   # default
  instructions: AGENTS.md       # default
  claude_symlink: true          # default; CLAUDE.md -> AGENTS.md
  overlay: []                   # skills this repo permanently diverges on (→ --exclude)
```

It round-trips through `copyroom inspect` / `copyroom status` (text and `--json`).

## See also

- [Template layers](layers.md) — how the personal layer delivers these files to every repo, whatever generated it.
- [Copier overview §5](../copier/overview.md#5-copier-update--the-three-way-merge) — the three-way merge `update` converges with.
- [Configuration](configuration.md) — the config files and owners; `copyroom.project.yml` is advisory.
- [Adoption](adoption.md) and [template editing](template-editing.md) — the two skills `copyroom-adopt` and `copyroom-template-edit` encode.
