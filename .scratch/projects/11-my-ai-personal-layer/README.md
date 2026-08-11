# Project 11 — my-ai as the *personal layer*

**Goal.** Integrate the `my-ai` repo into the copyroom/repoman suite so that it
provides the user's `AGENTS.md` / `CLAUDE.md` / `.agents/skills/` to **every**
repository, and so those files are **updateable via copyroom** across the whole
fleet.

**Answer in one line.** `my-ai` becomes a **Copier overlay template** with its
own answers file, and CopyRoom grows a first-class **layer** concept so a repo
can be managed by more than one template at once — the genome (`template-py`)
*and* the personal layer (`my-ai`) — each converged independently by
`copyroom update`.

## Documents

| File | What it holds |
|------|---------------|
| [`FINDINGS.md`](FINDINGS.md) | What `my-ai` is today, and the four things wrong with it |
| [`SPIKE.md`](SPIKE.md) | Empirical proof that Copier supports per-layer answers files |
| [`spike-layers.sh`](spike-layers.sh) | The runnable spike (5 questions, all PASS) |
| [`DESIGN.md`](DESIGN.md) | The layer concept, the CLI surface, and my-ai's new shape |
| [`IMPLEMENTATION.md`](IMPLEMENTATION.md) | The work list, both dogfooding findings, and what shipped |
| [`verify-my-ai-layer.sh`](verify-my-ai-layer.sh) | The real my-ai template applied to a real repo (gitman) |
| [`verify-two-real-layers.sh`](verify-two-real-layers.sh) | Two *real* layers: my-ai on a repo generated from the real genome (argentic) |

## Status

**Shipped.** copyroom `main` @ v0.7.1, my-ai `main` @ v0.1.0 (it applies its own
layer to itself). `copyroom layer` is live machine-wide. 589 tests pass, `ruff`
clean, the walkthrough passes with a new ACT 6, and both verify scripts pass
against real repos.

Dogfooding caught two things the design and the first verification missed — a
`--overwrite` bug in `layer add` (fixed) and a rollout-order interaction on
`AGENTS.md` (documented). Both are written up in
[`IMPLEMENTATION.md`](IMPLEMENTATION.md).

**Rollout has not started** — no production repo carries the layer yet, and the
order matters. Commands: [`IMPLEMENTATION.md`](IMPLEMENTATION.md#rollout--not-started).
