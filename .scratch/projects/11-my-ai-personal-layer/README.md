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
| [`IMPLEMENTATION.md`](IMPLEMENTATION.md) | The work list and its state |

## Status

**Implemented and verified in both repos.** CopyRoom: 588 tests pass (40 of them
new, covering layers), `ruff` clean, `demo/walkthrough.sh` passes with a new ACT 6
driving `layer add → layer list → update --layer`. my-ai: restructured as the
overlay template and proven against a real repo by
[`verify-my-ai-layer.sh`](verify-my-ai-layer.sh).

One step is left for the user: **commit and tag `my-ai` v0.1.0.** A Copier
template is consumed *by tag*, so the layer isn't rollable-out until then. Full
checklist and rollout commands: [`IMPLEMENTATION.md`](IMPLEMENTATION.md).
