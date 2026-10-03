# Spike — can a second Copier template layer onto a managed repo?

Run: `devenv shell -- bash .scratch/projects/11-layer-isolation/spike-layers.sh`
Environment: **Copier 9.17.1**, Git 2.55.0, Python 3.13 in devenv.

The spike creates a base template and a documentation overlay. It generates a
project from the base, applies the overlay, updates both templates, and converges
each layer independently.

## Questions and results — all passed

| # | Question | Result |
|---|----------|--------|
| Q1 | Does `copier copy -a .copier-answers.docs.yml` write only that answers file? | Yes. Both answers files remain and each names its own template. |
| Q2 | Does `_answers_file` in the overlay's `copier.yml` set its default layer name? | Yes. The explicit `-a` flag is not load-bearing. |
| Q3 | Does `copier update -a <layer answers>` update only that layer? | Yes. The overlay guide moves from v1 to v2, a new file appears, and the base files and answers stay unchanged. |
| Q4 | Does `_skip_if_exists: [README.md]` protect a repo-owned README? | Yes, on both copy and update. |
| Q5 | Does `_preserve_symlinks: true` keep a documentation index symlink? | Yes, on copy, overlay update, and base update. |

Updating the base layer without `-a` changes only its files. The overlay files
remain unchanged.

## What this establishes

1. **Copier supports several templates per project.** CopyRoom initially assumed
   one answers file; the project layer model removed that limit.
2. **`_skip_if_exists` protects shared seed files.** Copier applies the rule on
   updates as well as copies.
3. **Layers update independently.** An update does not reach another layer's
   files or answers. CopyRoom can discover layers from their answers files.

## Caveats found

- Copier printed `Make sure Git >= 2.24 is installed to improve updates.` even
  with Git 2.55.0. The update succeeded; the warning came from Copier's process.
- An overlay is partial. A whole-tree comparison reports unrelated repo files
  as repo-only. `adopt --layer` must compare only files that the overlay manages.
