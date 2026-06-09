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
