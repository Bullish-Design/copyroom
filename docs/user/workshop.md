# Workshop

A workshop uses `copyroom.yml`, `registry/`, and `scenarios/`. Each registry
entry points to a local Templateer source. A scenario supplies JSON-compatible
answers in YAML.

Use `copyroom render` to create output and `copyroom golden` to compare it with
the saved full-tree golden. Golden refresh is explicit. `copyroom test` runs
`devenv test` in the generated project and preserves its log.

See [Local Workflows](local-workflows.md#workshop) for registry, scenario,
golden, and candidate commands.
