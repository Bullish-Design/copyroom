# Project 07 — the agent-files convention

**Status:** shipped in `feat/agent-files` (CopyRoom **0.6.0**) · pilot for the
`*man` family's agent-files convention.

## What shipped

CopyRoom became the **reference implementation** of the family's agent-files
convention:

- **Self-adoption** — root `AGENTS.md` (canonical), `CLAUDE.md` symlink to it
  (git mode `120000`), `.gitignore` carve-out (`.agents/skills/` + `AGENTS.md` +
  `CLAUDE.md` tracked; the rest of `.agents/` stays tool state).
- **Canonical skills** as package assets — `src/copyroom/agent/assets/skills/`
  (`copyroom`, `copyroom-adopt`, `copyroom-template-edit`), each with a domain
  boundary + deferral footer. The repo's own `.agents/skills/` is materialized
  from them by `copyroom agent-files export`, never hand-maintained.
- **`copyroom agent-files export|check`** — export is idempotent (skills +
  blueprint `AGENTS.md` only if absent + `CLAUDE.md` symlink, never replacing a
  regular file); check is a warn-level conformance report.
- **`copyroom.project.yml` `agent:` section** — `skills_dir`, `instructions`,
  `claude_symlink`, `overlay` (all defaulted, unknown-ignored), round-tripped
  through `inspect`/`status`. `agent.overlay` maps to Copier `--exclude` on
  `update` (the permanently-diverge contract).
- **`doctor`** — warn-level, non-fatal `agent-files` check.
- **Docs** — `docs/user/agent-files.md` (convention, template shipping, overlay
  contract, `.agents/` dual-use), fixed the dangling skill references, CLI/config
  references, and a demo act.

## The spike that settled the design

`SPIKE.md` + `symlink-spike.sh`: Copier **dereferences** symlinks by default on
both `new` and `update`; with `_preserve_symlinks: true` it preserves them
(mode `120000`). Templates must also declare
`_copy_without_render: [".agents/skills/**"]` so literal `{{ }}` skill content
survives byte-for-byte. **Decision:** templates ship `CLAUDE.md` directly; no
CopyRoom finalize step is needed.

## Follow-ups (scoped out, now tracked separately)

1. **Family decision doc** (repoman) — the one convention, `.agents/` dual-use.
2. **template-py (the genome)** — embed the canonical set via
   `copyroom agent-files export`, AGENTS.md blueprint, CLAUDE.md symlink,
   `_copy_without_render` + `_preserve_symlinks`.
3. **repoman** — `skillsDir` `.claude/skills` → `.agents/skills`; shrink
   `install-skills` to the generated entrypoint router; doctor lints skill
   ownership; retire `.devman-source`.
4. **gitman / testee / docman / shellij** — self-adopt (AGENTS.md + CLAUDE.md
   symlink + own skills).
