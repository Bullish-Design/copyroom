# 06 — Typer migration + `doctor` command

Two coupled changes to CopyRoom's CLI:

1. **Migrate the CLI frontend from `argparse` to Typer** — aligns CopyRoom with the
   rest of the agentic-manager family (testee, gitman, zelligate all use Typer) and
   gives a cleaner, sub-command-grouped surface.
2. **Add a `copyroom doctor` command** — an *environment precondition* check
   (Copier present, git present, cache writable) that runs in any directory, distinct
   from `inspect`/`status` (which report *project state* and need a managed project).

**Why now:** RepoMan (the conductor) wants to drive every manager's `doctor` uniformly.
CopyRoom is currently the only core manager without one, so `repoman doctor` skips it.
This closes that gap and makes the pillar conform — see RepoMan's `SPIKE.md` finding
"managers don't all implement every verb."

- **[IMPLEMENTATION_GUIDE.md](IMPLEMENTATION_GUIDE.md)** — the detailed, phased guide.

Scope note: this is CLI-frontend + one new command only. Core logic under
`project/`, `template/`, `workshop/`, `manage/`, `release/`, `session/` is **not**
touched (the session/dispatcher mode model is reused as-is).
