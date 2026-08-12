# Rollout — wave 1

Target: the 5 most recently committed repos (excluding `my-ai`, which already
applies its own layer). Sorted by last commit date, not directory mtime — build
artifacts churn mtime and it doesn't reflect actual work.

Applied with the portable form, which is the only correct one
([IMPLEMENTATION.md](IMPLEMENTATION.md) finding 3):

```bash
copyroom layer add gh:Bullish-Design/my-ai
```

## What landed

| Repo | Last commit | Commit | `AGENTS.md` | Also landed |
|---|---|---|---|---|
| `copyroom` | 2026-08-11 22:03 | in-tree | untouched ✓ | skill + answers |
| `pytuin` | 2026-08-11 21:59 | `acfa081` | **seeded** (had none) | skill + answers + `CLAUDE.md` |
| `nix-meta` | 2026-08-11 21:59 | `727993c` | untouched ✓ | skill + answers + `CLAUDE.md` |
| `nix-terminal` | 2026-08-11 21:39 | `ad404a8` | untouched ✓ | skill + answers + `CLAUDE.md` |
| `nix-nvim` | 2026-08-11 21:39 | `cb860b6` | untouched ✓ | skill + answers + `CLAUDE.md` |

Every one: `_src_path: gh:Bullish-Design/my-ai`, `CLAUDE.md` committed at git
mode `120000`, worktree clean afterwards. copyroom's own canonical skills were
untouched, and its `agent-files check` now reports `my-ai` under **Extras**
("template-shipped or overlay — reported, not judged") — the two-writer rule
behaving as designed.

## Why no genome-first step was needed

The documented order (base layer first, then the overlay) exists because both can
ship `AGENTS.md`. It didn't apply to any of these five:

- `copyroom`, `nix-meta`, `nix-terminal` — no base layer at all, and they already
  own an `AGENTS.md`.
- `nix-nvim` — has a base layer *and* an `AGENTS.md`, so `_skip_if_exists`
  settles it either way.
- `pytuin` — has no `AGENTS.md`, so ordering *would* matter, except its base
  layer is broken (below), which makes a genome update impossible anyway.

`argentic` was the next candidate by date and was **skipped**: 12 uncommitted
files. Rolling a layer into a dirty tree makes the review unreadable.

## Two things to fix, found during rollout

### 1. `pytuin`'s base layer points at a copyroom demo fixture

```yaml
_src_path: /home/andrew/Documents/Projects/copyroom/demo/fixtures/minimal-python-package
# and no _commit at all
```

It was generated from a throwaway fixture, not a genome. Because that path lives
*inside* the copyroom checkout, `copyroom status` resolves "latest ref" against
**copyroom's own tags** and cheerfully reports `v0.7.2` — a meaningless answer
that looks authoritative. Running `copyroom update` there would try to converge
pytuin onto a demo fixture.

**The lying part is fixed** (copyroom v0.7.3). `git tag --list` walks up to the
nearest enclosing repository, so `list_tags` on a path that is merely *inside* a
repo reported that outer repo's tags as its own. It now checks
`git rev-parse --show-toplevel` and returns nothing unless the path IS the repo
root. pytuin's status went from a confident `Latest ref: v0.7.2` to an honest
`Latest ref: unknown`. Regression tests in `tests/unit/test_layers.py`
(`TestListTagsScoping`).

The bogus base layer itself remains — re-adopting is a deliberate per-repo
decision, not part of a rollout:

```bash
cd ~/Documents/Projects/pytuin
copyroom adopt gh:Bullish-Design/template-py --ref <tag> --answers <answers.yml> --force
```

### 2. Four repos had no `.agents/` gitignore carve-out (added)

`.agents/` is dual-use: `.agents/skills/` is tracked, the rest is tool runtime
state. Only copyroom declared that (and its rules were verified adequate — skill
tracked, `.agents/pi/node_modules` ignored). The other four had no `.agents/`
directory at all until this rollout created one. Nothing bad landed — only
`SKILL.md` was present, checked before committing — but the next tool to write
runtime state under `.agents/` would have put it straight into git.

The personal layer **cannot** fix this: Copier writes whole files, and a
`.gitignore` shipped by the layer would clobber each repo's own. **Added per repo
instead** — appended to each of the four external repos' `.gitignore`:

```gitignore
.agents/**
!.agents/skills/
!.agents/skills/**
!AGENTS.md
!CLAUDE.md
```

Verified in each: `.agents/skills/**/SKILL.md` still tracked, a planted
`.agents/pi/node_modules/junk.js` ignored, no already-tracked file dropped.
It still belongs in the genome for repos generated from it in future.

## Pushed

| Repo | Commit |
|---|---|
| `pytuin` | `3e1abfe` |
| `nix-meta` | `fab9907` |
| `nix-terminal` | `4664e79` |
| `nix-nvim` | `202e2fc` |

Two commits each: the layer, then the `.gitignore` carve-out.

## Remaining fleet

~35 repos untouched.

For repos that *are* current on a real genome and lack an `AGENTS.md`, do the
genome update first (see [layers.md](../../../docs/user/layers.md) §"Rollout
order"). Expect real conflicts from accumulated genome drift — argentic was six
versions behind — so keep going one repo at a time rather than fanning out.
