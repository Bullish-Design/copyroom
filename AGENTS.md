# AGENTS.md — CopyRoom

CopyRoom is a **mode-aware CLI for local Templateer sources and jj**. It creates
projects, previews and applies source updates, manages independent layers,
freezes explicit generated artifacts, runs a local workshop, and adopts
existing repos. Source lives in `src/copyroom`.

CopyRoom is a member of the **`*man` family** (copyroom, gitman, testee, docman —
orchestrated by repoman). Every family repo follows the same law.

## The family contract

- **Run everything inside the devenv shell** — it pins Python 3.13 and jj. Never
  invoke bare `uv`/`python`/`pytest`/`jj`/`git`.
- **Exit codes are an API:** `0` ok · `1` finding/decision · `2` infra/config ·
  `3` usage. Don't collapse them to `0`/`1`.
- **Structured plain-text reports** (no Rich coloring in `--json`; reports print
  as simple lines an agent can parse).

## Writing style

Write in **Simplified Technical English (ASD-STE100) style**. The rules live in
the `writing` skill.

CopyRoom's fixed vocabulary — use one word for one meaning, and never swap in a
synonym: `layer`, `mode`, `marker`, `genome`, `workshop`, `overlay`, `converge`.

## Working here

```bash
devenv shell -- uv run pytest -q       # full suite (spec/unit/integration)
devenv shell -- uv run ruff check src/ tests/
devenv shell -- bash demo/walkthrough.sh   # scripted end-to-end demo
```

The gate before any PR: `pytest` green, `ruff` clean, the walkthrough passes.

## Where things live

- `src/copyroom/local/` — Templateer composer, source snapshots, jj lifecycle,
  layers, generation, adoption, templatize, and workshop workflows.
- `src/copyroom/cli.py` — the public CLI. `src/copyroom/local/` — the
  Templateer composer, source protocol, jj workflows, generation, adoption, and
  workshop.
- `docs/` — current user/developer guides and one historical migration note.
  Docs are the detailed source of truth; skills link to them, never repeat them.
- `.scratch/` — concepting and per-project implementation guides (numbered).
- `demo/walkthrough.sh` — the scripted demo driving every command.
- `tests/` — `spec/` (local workflow contracts), `unit/`, and `integration/`
  (disposable local project and workshop workflows).

## Modes

CopyRoom detects project mode from `.copyroom-local.json`. Legacy answer markers
receive a clear migration refusal; CopyRoom does not convert them. Workshop
mode uses `copyroom.yml`, `registry/`, and `scenarios/`. Bootstrap commands run
anywhere. `--mode` forces a supported mode.

## Layers

A repo can be managed by several local sources. Each layer owns one path set and
one jj render line. Layers converge independently with
`copyroom update --layer NAME`. Details: `docs/user/local-workflows.md`.

## Agent skills

The fleet's agent surface is machine-local. The devman central overlay keeps one
copy of each skill and links it into each project's `.agents/`. CopyRoom no
longer ships or materializes skills. `AGENTS.md` stays canonical; `CLAUDE.md` is
a symlink to it.

**Start at `.agents/skills/copyroom/SKILL.md`.**
