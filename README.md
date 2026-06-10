# CopyRoom

Mode-aware CLI for template-driven project workflows, built on [Copier](https://copier.readthedocs.io/).

CopyRoom lives on top of Copier's lower-level operations, providing mode-aware command
routing, safe lifecycle management, workshop testing, and release readiness checks.

## Documentation

Full documentation lives in [`docs/`](docs/README.md), in three tracks:

- **[User Guide](docs/user/)** — [getting started](docs/user/getting-started.md),
  [concepts & modes](docs/user/concepts.md), the full
  [CLI reference](docs/user/cli-reference.md),
  [projects](docs/user/projects.md),
  [editing a template from a project](docs/user/template-editing.md),
  [the workshop](docs/user/workshop.md),
  [adoption](docs/user/adoption.md),
  [configuration](docs/user/configuration.md), and the
  [trust & safety model](docs/user/trust-and-safety.md).
- **[Developer Guide](docs/developer/)** —
  [architecture](docs/developer/architecture.md),
  [module reference](docs/developer/module-reference.md),
  [state machines](docs/developer/state-machines.md),
  [the `_compat` layer](docs/developer/compat-layer.md),
  [testing](docs/developer/testing.md), and
  [contributing](docs/developer/contributing.md).
- **[Copier Overview](docs/copier/overview.md)** — a detailed, self-contained
  explanation of the [Copier](https://copier.readthedocs.io/) engine CopyRoom is
  built on (templates, `copier.yml`, `.copier-answers.yml`, the three-way-merge
  update, and how each CopyRoom command maps onto Copier).

## Development

```bash
devenv shell
uv sync
copyroom --help
```

## Demo

A scripted, end-to-end walkthrough drives every command against real Copier
templates, projects, and a workshop in a throwaway directory — nothing mocked:

```bash
devenv shell -- bash demo/walkthrough.sh          # full run
devenv shell -- bash demo/walkthrough.sh --pause  # press Enter between acts
devenv shell -- bash demo/walkthrough.sh --keep   # keep the scratch workspace
```

It covers, in order: mode awareness → `new`/`update` → the agentic
`template-checkout`/`template-test`/`template-preview` loop → the workshop
(`render`/`golden`/`update-test`/`release-check`) → repo adoption
(`templatize`/`adopt`).

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

## Adopting / templatizing an existing repo (agentic)

CopyRoom can also bring an **existing, hand-written repo** under management —
either by adopting it under a template you name, or by extracting a brand-new
template from the repo and adopting that. These two commands are *bootstrap*
commands: they run in an unmanaged repo (no `.copier-answers.yml`, no workshop
markers) and resolve their own context.

```bash
# Path A — you already have a template:
copyroom adopt <template> --ref v1.0.0 --answers answers.yml   # report drift
copyroom adopt <template> --ref v1.0.0 --answers answers.yml --write  # + record link

# Path B — no template yet: extract one, converge it, finalize, then adopt:
copyroom templatize --into ../demo-template --name demo
( cd ../demo-template && copyroom golden demo default )        # → no diffs when faithful
# …parameterize template/ (rename files to *.jinja, insert {{ project_name }})…
( cd ../demo-template && git init -q && git add -A \
    && git commit -qm t && git tag v0.1.0 )
copyroom adopt ../demo-template --ref v0.1.0 --answers answers.yml --write
```

`templatize` scaffolds a self-contained sibling template repo — a Copier template
(`copier.yml` with `_subdirectory: template` + a verbatim `template/`) **and** the
workshop that exercises it (`copyroom.yml`, `scenarios/`, and a `golden/` snapshot
of the repo). Because Copier only renders `*.jinja` files, the verbatim template
reproduces the repo exactly, so the golden loop starts at **no diffs**; you
introduce parameters without breaking the match, then finalize to a tagged git
repo.

Adoption is **report-only**: it renders the template with your answers, diffs that
against the repo for a drift report (and a patch under `.copyroom/adopt/`), and —
only with `--write` — drops a `.copier-answers.yml` into the repo. **No other repo
file is ever modified.** It refuses an already-managed repo unless you pass
`--force`. Agents can follow the `copyroom-adopt` skill
(`.agents/skills/copyroom-adopt/`) to run the whole arc.

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
