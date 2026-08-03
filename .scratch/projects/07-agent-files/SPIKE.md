# Symlink spike — does Copier preserve `CLAUDE.md -> AGENTS.md`?

**Status:** decision recorded · Copier **9.17.0** · run `devenv shell -- bash symlink-spike.sh` to reproduce

## The question

Templates want to ship `AGENTS.md` (canonical instructions) and `CLAUDE.md` (a
symlink to it). If Copier preserves the symlink through `new` **and** `update`,
templates ship it directly and `copyroom agent-files export` just ensures it. If
not, CopyRoom's `new`/`update`/`adopt` need an idempotent finalize step that
recreates the symlink after the Copier run.

## Findings (all reproduced empirically)

| Scenario | Result |
|----------|--------|
| `copier copy`, default settings | **symlink dereferenced** — `CLAUDE.md` lands as a regular file with `AGENTS.md`'s content |
| `copier update`, default settings | **symlink dereferenced** the same way |
| `copier copy` with `_preserve_symlinks: true` | **symlink preserved** — `git ls-files -s CLAUDE.md` shows mode `120000` |
| `copier update` with `_preserve_symlinks: true` | **symlink preserved** through the three-way merge; `AGENTS.md` content advances, `CLAUDE.md` stays a symlink |
| skill file with literal `{{ }}`, `.md` suffix | copied verbatim (only `*.jinja` is rendered) — **but** a `.jinja`-suffixed sibling renders and **clobbers** the plain file |
| skill content under `_copy_without_render: [".agents/skills/**"]` | preserved byte-for-byte, `{{ }}` intact |
| `copier update -x ".agents/skills/<name>/**"` | template **stops managing** that skill — the project's local version survives the update; everything else still updates |

## Decision

**Templates ship `CLAUDE.md` as a symlink directly**, provided the template
declares `_preserve_symlinks: true` in `copier.yml`. Copier then preserves it
through `new` and `update` (mode `120000` in git). `copyroom agent-files export`
ensures the symlink on the template/seed side.

- **No CopyRoom finalize step in `new`/`update`/`adopt`.** The symlink survives
  the Copier run when the template declares the flag; `adopt` never writes
  repo files anyway (report-only), so there is nothing to recreate.
- **Template requirement (documented in `docs/user/agent-files.md`):**
  `_preserve_symlinks: true` + `_copy_without_render: [".agents/skills/**"]`.
  Without the latter, a `.jinja`-suffixed skill would be rendered and could
  clobber the plain `SKILL.md`; skills contain literal `{{ }}` examples that
  must survive byte-for-byte.
- **Overlay mechanism:** `copyroom update` reads `agent.overlay` from
  `copyroom.project.yml` and passes `--exclude <skills_dir>/<name>/**` to
  `copier update`, so a permanently-diverging skill is left alone (verified:
  local version preserved, rest of project still updates).

## Reproduction

The faithful spike script lives at `.scratch/projects/07-agent-files/symlink-spike.sh`.
Two gotchas encountered while writing it: the template must be a **git repo
before** `copier copy` (so `_commit` is recorded and update can find the old
template), and the project must be **git-tracked** before `copier update`
("Updating is only supported in git-tracked subprojects").
