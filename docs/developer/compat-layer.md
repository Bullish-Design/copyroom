# Local runtime boundary

CopyRoom accepts local source directories and runs jj as a subprocess. The
runtime does not fetch template repositories or execute template hooks.

## Trusted source inputs

The source directory contains `manifest.json` and `templates/`. Templateer
loads each declared artifact. The local composer validates the shared answer
schema, output paths, duplicate paths, case-fold collisions, file kinds, modes,
binary bytes, and relative symlinks before it writes a project tree.

Templateer validators and Python schema modules run from the source directory.
Treat source directories as trusted code. CopyRoom rejects a source symlink and
records a content digest before it renders. The project keeps a source snapshot
for exact replay.

## jj boundary

`local/jj.py` is the only local project module that starts jj commands. It uses
argument lists, captures output, and checks exit status. Project write flows
hold an operating-system lock from the final state check through apply.

The repository that contains CopyRoom uses gitman for version control. Code in
`local/jj.py` operates only on disposable projects, managed projects, template
sources, and workshop candidates.

## Model generation

Generation is opt-in. A command must name the Templateer artifact, request,
model, and local source. CopyRoom validates and freezes the returned artifact.
An ordinary update reads frozen bytes and makes no provider call.

## Workshop checks

Workshop checks run `devenv test` in the rendered scenario or preview directory.
CopyRoom saves stdout, stderr, and the exit code under
`.copyroom-workshop/logs/`. It does not run shell commands configured by a
template registry entry.

## Error handling

`LocalError` carries the CopyRoom exit code. Usage errors use `3`, configuration
or infrastructure errors use `2`, and a finding or conflict uses `1`. The CLI
prints the message to stderr and keeps the code.
