# AGENTS.md — CopyRoom

CopyRoom is a **mode-aware CLI wrapper around [Copier](https://copier.readthedocs.io/)**
(the templating engine): it creates projects from templates, updates them via a
three-way merge, lets you edit a template *from inside a generated project*
(preview-only), runs a template author's workshop, and adopts existing repos
under template management. Source lives in `src/copyroom`.

CopyRoom is a member of the **`*man` family** (copyroom, gitman, testee, docman —
orchestrated by repoman). Every family repo follows the same law.

## The family contract

- **Run everything inside the devenv shell** — it pins Python 3.13. Never invoke
  bare `uv`/`python`/`pytest`/`copier`/`git`.
- **Exit codes are an API:** `0` ok · `1` finding/decision · `2` infra/config ·
  `3` usage. Don't collapse them to `0`/`1`.
- **Structured plain-text reports** (no Rich coloring in `--json`; reports print
  as simple lines an agent can parse).

## Writing style

Write in **Simplified Technical English (ASD-STE100) style**. The rules live in
the personal layer: `.agents/skills/my-ai/SKILL.md`, section "Writing style".

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

- `src/copyroom/` — the package: `cli.py` (Typer frontend), `session/` (mode
  detection + dispatch), `project/` (new/update/inspect/status + `layers.py`),
  `template/` (checkout/test/preview), `workshop/` (render/golden/update-test),
  `manage/` (adopt/templatize/layer), `agent/` (the agent-files convention +
  canonical skills), `_compat/` (the only place that shells out to copier/git).
- `docs/` — three tracks: `docs/user/`, `docs/developer/`, `docs/copier/`.
  Docs are the detailed source of truth; skills link to them, never repeat them.
- `.scratch/` — concepting and per-project implementation guides (numbered).
- `demo/walkthrough.sh` — the scripted demo driving every command.
- `tests/` — `spec/` (state-machine invariants vs the Allium specs),
  `unit/`, `integration/` (real Copier renders in tmp dirs).

## Modes

CopyRoom detects which of four surfaces it is standing in from **markers**, never
guessing: project (`.copier-answers.yml`, `.copier-answers.<layer>.yml`, or
`copyroom.project.yml`), workshop (`copyroom.yml` + `registry/` + `scenarios/`),
template repo, or unmanaged repo (bootstrap commands `new`/`adopt`/`templatize`/
`layer` run anywhere). `--mode` forces it.

## Layers

A repo can be managed by **several templates at once** — the genome in
`.copier-answers.yml`, plus overlays like the personal layer (`my-ai`) in
`.copier-answers.my-ai.yml`. Layers are discovered by glob, never configured, and
converge independently (`copyroom update --layer NAME`). Details:
`docs/user/layers.md`.

## Agent-files convention

`.agents/skills/copyroom/SKILL.md` is the entry skill for CopyRoom work: it
states the law and routes to `copyroom-adopt` (adoption) and
`copyroom-template-edit` (template editing). `AGENTS.md` is canonical;
`CLAUDE.md` is a symlink to it. The canonical skill set ships as package assets
under `src/copyroom/agent/assets/skills/` and is materialized with
`copyroom agent-files export` — never hand-edit `.agents/skills/` as a second
copy. Details: `docs/user/agent-files.md`.

**Start at `.agents/skills/copyroom/SKILL.md`.**
