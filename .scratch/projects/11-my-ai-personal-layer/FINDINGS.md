# Findings — what `my-ai` is today, and what's wrong with it

Studied at `/home/andrew/Documents/Projects/my-ai` (3 commits: `951110a` initial,
`e21bb4e` "become the canonical agent-config source", `d12ee10` sync script as a
PEP 723 script).

## What it is

A repoman-managed repo (`managers = [copy git test]`, no `.copier-answers.yml`)
whose tracked payload is:

```
AGENTS.md                                  # "the canonical agent configuration"
CLAUDE.md -> AGENTS.md
.agents/skills/copyroom/SKILL.md           # copy of copyroom's package asset
.agents/skills/copyroom-adopt/SKILL.md     # copy of copyroom's package asset
.agents/skills/copyroom-template-edit/…    # copy of copyroom's package asset
.agents/skills/gitman/SKILL.md             # copy of gitman's own repo skill
.agents/skills/repoman/SKILL.md            # copy of a GENERATED router
.agents/skills/my-ai/SKILL.md              # genuinely my-ai's own
scripts/my-ai-sync.py                      # the distribution mechanism
devenv.nix / devenv.yaml / pyproject.toml / gitman.toml
```

`scripts/my-ai-sync.py` walks `.agents/skills/**/SKILL.md` and byte-copies each
into a target repo, writes `AGENTS.md` if absent (or on `--force`), and repairs
the `CLAUDE.md` symlink.

## The four problems

### 1. It is a second distribution mechanism, parallel to copyroom

`my-ai-sync` is a hand-rolled file copier. It has no version record, no
three-way merge, no conflict surfacing, no "what changed since", and no way to
answer *"which repos are behind?"*. CopyRoom exists to do exactly this job via
Copier, and the family already routes convergence through `copyroom update`. The
user's ask — *"updateable via copyroom through all my libraries"* — is precisely
the gap this creates.

### 2. It violates the family's own two-writer rule

`docs/AGENT-FILES.md` (repoman, the accepted family decision) fixes an
**ownership split**: tool-shipped skills (copyroom's canonical set), genome/fleet
skills (template-py under `template/.agents/`), repoman's *generated* router, and
the repo's overlay. `my-ai` currently redistributes files from three of those
owners:

| File in my-ai | Real owner | Materialized by |
|---|---|---|
| `copyroom`, `copyroom-adopt`, `copyroom-template-edit` | copyroom package assets | `copyroom agent-files export` |
| `repoman` | **generated per repo** from the runtime manager roster | `repoman install-skills` |
| `gitman` | gitman's own repo | its own sync |
| `my-ai` | **my-ai** ✅ | — |

Pushing a *snapshot of a generated router* into every repo is the sharpest
version of this: the router's content depends on that repo's
`repoman.managers`, so a copied one is wrong everywhere it lands.

my-ai's own `AGENTS.md` even states the rule (*"never hand-edit tool-shipped
skills as a second copy"*) while the repo does the copying.

### 3. `AGENTS.md` is repo-owned, and my-ai wants to overwrite it

The family decision assigns `AGENTS.md` to **the repo** ("may be seeded by the
genome/copyroom"). Every real repo's `AGENTS.md` is project-specific — copyroom's
describes modes and the workshop; gitman's describes lanes. `my-ai-sync --force`
would destroy them; without `--force` it silently does nothing, so the personal
layer never converges at all. The mechanism has no third option, because a
whole-file copy has none.

The cross-repo material in my-ai's `AGENTS.md` (the family contract, the
agent-files convention) is real and worth distributing — it just isn't
*`AGENTS.md`-shaped*. It's skill-shaped.

### 4. Nothing checks it

There is no `tests/` (though `pyproject.toml` sets `testpaths = ["tests"]`), no
golden render, and no `copyroom doctor` surface that would notice a repo drifting
off the personal config.

## The blocker on the obvious fix

"Make my-ai a Copier template" collides immediately: every target repo is
**already** generated from `template-py` and carries a `.copier-answers.yml`
pointing there. CopyRoom hard-codes that one filename in four places —

- `project/update.py:84` — `load_config` reads `<root>/.copier-answers.yml`
- `manage/adopt.py:44` — `_ANSWERS_FILENAME`, and the "already managed" refusal
- `template/workspace.py:56` — `read_answers` (feeds `inspect` / `status`)
- `session/detector.py:34` — `is_project`

— so a repo can be managed by exactly one template. That single assumption is
the whole engineering problem; see [`SPIKE.md`](SPIKE.md) for the proof that
Copier itself has no such limit, and [`DESIGN.md`](DESIGN.md) for the fix.

## Adjacent gap (noted, not fixed here)

`gitman`'s skill has no owner-side materializer: gitman ships it only in its own
repo, `repoman install-skills` writes only the router, and `copyroom agent-files
export` writes only copyroom's set. my-ai was informally papering over this by
carrying a copy. Removing the copy makes the gap visible rather than creating it
— it belongs to gitman/repoman (a `gitman agent-files export`, or repoman
installing each wired manager's tool-shipped skill), not to the personal layer.
