# Module reference

Runtime modules live in `src/copyroom/`. This page lists the local workflow
entry points.

## `local/composer.py`

`compose(source, answers)` returns an immutable `RenderPlan`. The composer uses
Templateer's `TemplateRegistry`, validates the normalized model, and maps each
output to a path, file kind, exact bytes, mode, and owner. It rejects unsafe or
colliding paths before writing.

## `local/source.py`

Reads `.copyroom-local.json`, writes marker updates atomically, and saves source
snapshots by digest under `.copyroom-local/sources/`. A project can replay a
snapshot when its original source locator is unavailable.

## `local/jj.py`

`JJ` wraps plain jj commands for local project repositories. `project_lock`
serializes CopyRoom writes. The root repository still uses gitman.

## `local/workflow.py`

- `new` composes a base layer, initializes jj, saves a source snapshot, and
  writes the project marker.
- `preview` renders a new layer revision and merges it with the active project
  in a separate jj workspace.
- `apply` verifies the recorded state and applies the reviewed preview tree.
- `discard`, `list_previews`, `status`, and `inspect` support recovery and
  review.
- `add_layer` and `list_layers` manage independent output owners.

## `local/generation.py`

`generate` and `refresh` call Templateer's generation API after an explicit
request. They validate the returned artifact and store its exact bytes and
generation record. Normal updates replay those bytes.

## `local/manage.py`

`adopt` compares an existing tree with a rendered source. Report-only mode
writes nothing. Explicit adoption initializes jj and verifies that the project
tree stays unchanged. `templatize` extracts a source and checks that it renders
the original tree.

## `local/workshop.py`

Provides local registry operations, scenario renders, complete-tree golden
checks, `devenv test`, candidate workspaces, and disposable update previews.
Golden refresh runs Templateer's authoring audit first.

## Public CLI

`cli.py` contains one Typer application. Project commands require the local
project marker. Workshop commands require `copyroom.yml`, `registry/`, and
`scenarios/`. A legacy answer marker returns a migration error; CopyRoom does
not rewrite it automatically.
