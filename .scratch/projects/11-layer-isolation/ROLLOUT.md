# Historical rollout — wave 1

This record describes the earlier fleet rollout. It is not a current inventory.
The source template repository already had its own link and was excluded from
the first five targets. Targets were sorted by last commit date, not directory
mtime, because build artifacts change mtime.

The portable form used the source string from the caller:

```bash
copyroom layer add <template-source>
```

## What landed

| Repo | Last commit | Commit | `AGENTS.md` | Also landed |
|---|---|---|---|---|
| `copyroom` | 2026-08-11 22:03 | in-tree | unchanged | overlay files and answers |
| `pytuin` | 2026-08-11 21:59 | `acfa081` | seeded | overlay files and symlink |
| `nix-meta` | 2026-08-11 21:59 | `727993c` | unchanged | overlay files and symlink |
| `nix-terminal` | 2026-08-11 21:39 | `ad404a8` | unchanged | overlay files and symlink |
| `nix-nvim` | 2026-08-11 21:39 | `cb860b6` | unchanged | overlay files and symlink |

Each repo recorded the caller's template source. Each symlink was stored with
Git mode `120000`, and each worktree was clean after the change. CopyRoom's own
canonical skills were unchanged. The agent-files check reported the overlay as
an extra file source, which matched the two-writer rule.

## Why no base-first step was needed

The base-first order matters when both templates can seed `AGENTS.md`. It did
not affect these five targets:

- `copyroom`, `nix-meta`, and `nix-terminal` had no base layer and owned their
  own `AGENTS.md`.
- `nix-nvim` had a base layer and its own `AGENTS.md`, so `_skip_if_exists`
  protected that file.
- `pytuin` had no `AGENTS.md`, but its base layer was already invalid.

`argentic` was skipped because it had 12 uncommitted files. Updating a dirty
repo would have hidden unrelated work in the review.

## Issues found during rollout

### 1. `pytuin`'s base source pointed at a demo fixture

```yaml
_src_path: /home/andrew/Documents/Projects/copyroom/demo/fixtures/minimal-python-package
# no _commit was recorded
```

The repo came from a fixture, not a genome. Because the fixture lived inside the
CopyRoom checkout, `copyroom status` reported CopyRoom's latest tag, `v0.7.2`,
as the fixture's version. An update would have tried to converge `pytuin` to a
demo fixture.

CopyRoom v0.7.3 fixed the report. `list_tags` now confirms that the source path
is the repository root. A path inside another repo has no tags of its own. The
status changed from `Latest ref: v0.7.2` to `Latest ref: unknown`. Regression
tests live in `tests/unit/test_layers.py` under `TestListTagsScoping`.

The invalid base link remained a per-repo decision. The suggested repair was:

```bash
copyroom adopt gh:Bullish-Design/template-py --ref <tag> \
  --answers <answers.yml> --force
```

### 2. Four repos needed an `.agents/` ignore carve-out

`.agents/` held tracked skills and tool runtime state. Only CopyRoom had an
ignore rule. The other four repos had no `.agents/` directory before rollout.
The rollout added a carve-out to each repo's `.gitignore`:

```gitignore
.agents/**
!.agents/skills/
!.agents/skills/**
!AGENTS.md
!CLAUDE.md
```

The rollout checked that skills stayed tracked, planted runtime state was
ignored, and no tracked file was dropped. The genome still needed this rule for
newly generated repos.

## Published commits

| Repo | Commit |
|---|---|
| `pytuin` | `3e1abfe` |
| `nix-meta` | `fab9907` |
| `nix-terminal` | `4664e79` |
| `nix-nvim` | `202e2fc` |

Each repo received two commits: the overlay and the ignore carve-out.

## Historical wave 2

The second rollout used a shell script to apply or update the layer, export
CopyRoom's skills, and add the ignore carve-out. That deployment script was
removed because its fixed target list and write procedure are obsolete. The
results remain here as historical evidence.

**42 repos converged with no failures.** Each received the overlay at `v0.2.0`,
CopyRoom's canonical skills, a symlink, and the ignore carve-out. A separate
check verified those outputs.

The script applied the layer before exporting CopyRoom files. That order kept
the template's seed from replacing an existing `AGENTS.md`.

The overlay's `v0.2.0` release had to publish before the rollout. A writing rule
had changed locally, while the remote still had `v0.1.0`. Using the old tag
would have required a second update of all 42 repos. Repos already on `v0.1.0`
were updated instead of skipped; an earlier script version had skipped them.

### Eligibility

- **20 repos were skipped because their worktrees were dirty.** Those repos
  needed individual review after their existing work landed: `allium-env`,
  `argentic`, `devman`, `flora`, `foreman`, `forgelab`, `fornix`, `grail`,
  `llgym`, `lodestar`, `mypi-agent`, `nixvim`, `paloma-story-generation`,
  `pytuin-desktop`, `shellij`, `siteman`, `talkee`, `terminal-state`, `testee`,
  and `zelligate`.
- **Five detached-head repos needed branch handling.** The rollout moved their
  results onto the local branch before publish: `eventic`,
  `image-gen-pipeline`, `inferference`, `nix-paseo`, and `pydantree`. The source
  repository was later archived and is not part of the active workspace set.

The 20 dirty repos were the remaining targets at the time. For a repo that was
behind on its genome and lacked `AGENTS.md`, the rollout guide recommended
updating the genome first. Accumulated genome drift could produce real
conflicts; `argentic` was six versions behind.
