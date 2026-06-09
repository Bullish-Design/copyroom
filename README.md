# CopyRoom

Mode-aware CLI for template-driven project workflows, built on [Copier](https://copier.readthedocs.io/).

CopyRoom lives on top of Copier's lower-level operations, providing mode-aware command
routing, safe lifecycle management, workshop testing, and release readiness checks.

## Development

```bash
devenv shell
uv sync
copyroom --help
```

## Editing the template from a project (agentic)

From inside a generated project you can drive a change *back into the template*
and preview the update your project would receive — without touching your
working tree. CopyRoom provides the mechanical primitives; an agent (or you) do
the editing and orchestrate them:

```bash
copyroom template-checkout            # template → isolated worktree on a scratch branch
# …edit the template files under the printed worktree path…
copyroom template-test                # render-test the edit with this project's answers
copyroom template-preview             # diff: current working state → post-update state
```

`template-preview` writes a unified diff to `.copyroom/preview/<timestamp>.patch`
and summarises files added/modified/removed plus any conflicts with your local
edits. Nothing is applied: once the template change is committed/tagged, pull it
in with `copyroom update <ref>`.

This is **preview only** and safe by construction — template edits live on a
scratch branch (never pushed) and the update is simulated against a throwaway
copy of your project. Remote template sources are cloned into a cache
(`$XDG_CACHE_HOME/copyroom`, or `$COPYROOM_CACHE_DIR`); local sources must be git
repositories. Agents can follow the `copyroom-template-edit` skill
(`.agents/skills/copyroom-template-edit/`) to run this loop end to end.

## Trust model

CopyRoom delegates project generation to Copier in a subprocess. A template's
`copyroom.project.yml` may define `post_project_create` / `post_template_update`
hook commands. Because templates are often fetched from remote sources, these
commands are **not executed by default** — running them would be arbitrary code
execution. Pass `--trust` to `copyroom new` / `copyroom update` to run them:

```bash
copyroom new gh:org/template --trust
copyroom update v1.2.0 --trust
```

Workshop registry `checks` (run by `test`, `render`, and `release-check`) are the
workshop author's own commands, executed against their own templates, and run
without a trust gate.
