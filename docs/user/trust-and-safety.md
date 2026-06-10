# Trust & Safety Model

CopyRoom is designed to be **safe by construction** and **reversible by default**.
This page states exactly what runs, what is gated, and what is guaranteed — so you
can reason about what a CopyRoom command can and cannot do to your machine and
your files.

---

## The threat: templates are (often) remote code

A Copier template is frequently fetched from a remote source (`gh:org/repo`, a
git URL). A template can declare hook commands to run after generation or update.
Running those commands is, by definition, **arbitrary code execution from a
source you may not control**.

CopyRoom's stance: **don't run untrusted commands unless the user explicitly opts
in.**

---

## What is gated behind `--trust`

The template-supplied hook commands in a project's `copyroom.project.yml`:

- `commands.post_project_create` — would run after `copyroom new`.
- `commands.post_template_update` — would run after `copyroom update`.

By default these are **skipped with a warning**:

```
Skipping post-create command (re-run with --trust to execute): uv run pytest
```

Pass `--trust` to execute them:

```bash
copyroom new gh:org/template --trust
copyroom update v1.2.0 --trust
```

Even when trusted, a failing hook is **reported but never fatal** — post-hooks are
advisory and don't block the create/update from completing.

```
commands:                # from the generated project's copyroom.project.yml
  post_project_create:
    - "uv run pytest"     #   ← skipped unless --trust
```

---

## What is *not* gated (and why)

**Workshop registry `checks`** (run by `render`, `test`, `update-test`, and
`release-check`) are **not** behind a trust gate. The distinction is about
provenance:

| Commands | Source | Run on | Gated? |
|----------|--------|--------|--------|
| `post_project_create` / `post_template_update` | a fetched template | the consumer's machine | **Yes — `--trust`** |
| Workshop `checks` | the workshop author's own `copyroom.yml` | the author's own machine, against their own templates | No |

Workshop checks are the *whole point* of `test`/`release-check`: they're the
author's own commands, on their own machine, validating their own templates.
Gating them would defeat the feature.

---

## What CopyRoom never does

- **Never fetches scripts from URLs.** Template *sources* are git URLs handed to
  Copier; Copier does the fetch. CopyRoom adds no separate remote-fetch or
  remote-exec layer.
- **Never executes commands from a remote registry entry.**
- **Never auto-rolls-back.** On failure it reports what happened and where state
  was left. Automatic rollback of file/git operations is more dangerous than a
  clear error.

---

## The safety guarantees of each command

| Command | Guarantee |
|---------|-----------|
| `new` | Refuses a non-empty target; never overwrites existing files. |
| `update` | **Requires a clean git worktree** and refuses a dirty one; runs the merge in place (use `--branch` to isolate). A clean tree means `git checkout .` always undoes it. |
| `template-checkout` | Edits happen in an **isolated git worktree on a scratch branch**, never pushed; the template's main checkout is untouched. |
| `template-test` | Renders into a **temp directory**; touches nothing else. |
| `template-preview` | Runs on a **throwaway copy** of your working tree; **applies nothing**. Writes only a patch under `.copyroom/preview/`. |
| `templatize` | Creates a **new sibling directory**; reads (never writes) the source repo. |
| `adopt` | **Report-only.** Renders into a scratch dir and diffs. Writes **at most one file** into the repo — `.copier-answers.yml`, and only with `--write`. Refuses an already-managed repo without `--force`. |
| `render` / `golden` / `update-test` / `release-check` | Write only into the workshop's scratch areas (`generated/`, `.copyroom_sim/`, `golden/` on `--refresh`). |

---

## Isolation & scratch locations

- **Remote templates** are cloned (full clone, so `_commit` history is present for
  merges) into the cache: `$XDG_CACHE_HOME/copyroom/templates` (override with
  `COPYROOM_CACHE_DIR`).
- **Edit worktrees** live in that same cache on scratch branches
  (`copyroom/edit/<slug>`), never pushed.
- **Previews and simulations** run in OS temp dirs and are cleaned up afterward.
- **Generated artifacts** you might want to keep:
  - `.copyroom/preview/<timestamp>.patch` — from `template-preview`.
  - `.copyroom/adopt/<timestamp>.patch` — from `adopt`.

---

## Reversibility checklist

If something goes wrong:

1. **A bad `update`?** You started from a clean tree, so:
   `git checkout . && git clean -fd` (and delete the isolation branch if you used
   `--branch`).
2. **A surprising `adopt --write`?** Delete the added `.copier-answers.yml`; no
   other repo file was changed.
3. **Anything in scratch?** Previews/sims are in temp/cache — safe to delete the
   cache (`$COPYROOM_CACHE_DIR` or `$XDG_CACHE_HOME/copyroom`) at any time.

---

## The off-ramp

Removing CopyRoom from a project is a non-event: delete `copyroom.project.yml`,
optionally drop the `copyroom` dev dependency, and keep using `copier update`
directly. `.copier-answers.yml` is untouched. See [concepts](concepts.md#6-the-off-ramp).

## See also

- [Configuration](configuration.md) — where hook commands are declared.
- [Projects](projects.md) — the clean-worktree requirement in context.
- [Copier overview](../copier/overview.md#8-post-generation-tasks-and-why-copyroom-gates-them).
