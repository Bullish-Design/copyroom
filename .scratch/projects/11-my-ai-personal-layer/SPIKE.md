# Spike — can a second Copier template layer onto a repo that already has one?

Run: `devenv shell -- bash .scratch/projects/11-my-ai-personal-layer/spike-layers.sh`
Environment: **Copier 9.17.1**, git 2.55.0, Python 3.13 (devenv shell).

The spike builds two real template repos (a "genome" stand-in and a `my-ai`
stand-in), generates a project from the first, layers the second on top, bumps
**both** templates, and updates each layer independently.

## Questions and results — all PASS

| # | Question | Result |
|---|----------|--------|
| Q1 | Does `copier copy -a .copier-answers.my-ai.yml` write **only** that answers file, leaving `.copier-answers.yml` untouched? | ✅ both files present, each pointing at its own template |
| Q2 | Does `_answers_file:` in the overlay's `copier.yml` make that the default? | ✅ (the `-a` flag is belt-and-braces, not load-bearing) |
| Q3 | Does `copier update -a <layer answers>` update **only** that layer? | ✅ personal skill went v1→v2, a brand-new personal skill was added, the genome's skill stayed v1, `.copier-answers.yml` was not mutated |
| Q4 | Does `_skip_if_exists: [AGENTS.md]` protect a repo-owned `AGENTS.md`? | ✅ on **both** the `copy` and the `update` path |
| Q5 | Does `_preserve_symlinks: true` keep `CLAUDE.md` a symlink? | ✅ through copy, through the overlay update, and through the genome update |

Plus the reverse direction: updating the **base** layer (no `-a`) converged the
genome's skill to v2 and left the personal layer's files untouched.

## What this establishes

1. **Copier has no one-template-per-project limit.** The limit is CopyRoom's —
   four hard-coded `.copier-answers.yml` reads (see `FINDINGS.md` §"blocker").
2. **`_skip_if_exists` is the right primitive for `AGENTS.md`.** It gives the
   personal layer the "seed, never clobber" semantics that
   `copyroom agent-files export` already applies to its blueprint — but enforced
   by Copier itself, on the update path too, where `my-ai-sync --force` could
   only choose between "destroy the repo's instructions" and "never converge".
3. **Layers are independent, not ordered.** Neither layer's update reaches into
   the other's files or answers. There is no merge order to get right, and no
   need for CopyRoom to sequence them — which is why the layer concept can be
   discovery-based and configuration-free.

## Caveats found

- Copier prints `Make sure Git >= 2.24 is installed to improve updates.` on the
  update path even with git 2.55 present; it is cosmetic (the update succeeds)
  and comes from Copier's own subprocess environment.
- An overlay template is **partial** by construction, so a whole-tree
  repo-vs-rendered diff reports the entire repo as "repo-only". `adopt --layer`
  must scope its drift report to the layer's own file set (handled in the
  design).
