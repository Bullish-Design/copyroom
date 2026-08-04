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

## Follow-ups (all completed — verified 2026-08-03, project 08)

The rollout shipped to every family repo; each item landed on its repo's `main`:

| # | Follow-up | Repo · main SHA |
|---|-----------|-----------------|
| 1 | **Family decision doc** — the one convention, `.agents/` dual-use | repoman `59d4b11` (`docs/AGENT-FILES.md`; repoman `main` has since advanced to `fa6d7f5`, project 12) |
| 2 | **template-py (the genome)** — canonical set embedded, AGENTS.md blueprint, CLAUDE.md symlink, `_copy_without_render` + `_preserve_symlinks` | template-py `5c0bcc3` (embed `d52b077`; tag `v0.1.3`) |
| 3 | **repoman** — `skillsDir` `.claude/skills` → `.agents/skills`; entrypoint-only install; doctor lints skill ownership; `.devman-source` retired | repoman `59d4b11` |
| 4 | **gitman / testee / docman / shellij** — self-adopt (AGENTS.md + CLAUDE.md symlink + own skills) | gitman `99813da` · testee `5d5d1b6` · docman `cd4c615` · shellij `f439086` |

**Verified end-to-end** (project 08, `E2E_PROOF.md`): a project generated from the
published genome (v0.1.3) carries the full convention byte-for-byte, `copyroom update
v0.1.4` converges a new genome skill with `{{ }}` intact, the `agent.overlay` contract
keeps a diverging skill local through v0.1.5, and `repoman doctor` reports
`skill:tool-shipped` / `skill:genome-overlay` OK in the generated project. The docman
roundtrip (44 assertions) and the gitman / testee / shellij suites are green.

Two post-rollout fixes from project 08's zero-dangling sweep: gitman `89b1d93` and
testee `5b0c22e` now scaffold their `init` agent skills under `.agents/skills/`
instead of `.claude/skills/`.
