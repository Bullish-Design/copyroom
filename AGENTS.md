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

Everything you write — docs, skills, code comments, docstrings, commit messages,
CLI help, error text, and replies to the user — follows **Simplified Technical
English ([ASD-STE100](https://www.asd-ste100.org/)) style** as closely as the
context allows:

- **One idea per sentence.** Keep sentences short: 20 words or fewer for
  descriptive text, 25 for procedures.
- **One paragraph per topic**, six sentences or fewer.
- **Use the active voice.** Name the actor: "CopyRoom reads the marker", not
  "the marker is read".
- **Use one word for one meaning.** Pick a term and keep it. `layer`, `mode`,
  `marker`, and `genome` mean exactly what the docs say they mean — never swap
  in a synonym for variety.
- **Use the imperative for instructions.** "Run the walkthrough." Not "You
  should probably run the walkthrough."
- **Say what to do, not only what not to do.**
- **Drop filler.** No "simply", "just", "of course", "as you know", "note
  that", or hedging that adds no information.
- **Spell out an abbreviation on first use** in each document.
- **No slang, no idioms, no metaphors** where a plain term works.

Where STE and clarity conflict, choose clarity. Where STE and an established
CopyRoom term conflict, keep the CopyRoom term.

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
