# CopyRoom

CopyRoom manages local Templateer sources with plain jj. It creates projects,
previews and applies source updates, manages independent layers, freezes explicit
generated artifacts, adopts existing trees, and provides a local template
workshop.

Template sources stay on disk. CopyRoom saves a source snapshot and its digest
in each project. jj records each owner's render history and merges updates.
Normal renders and updates never call a model.

## Documentation

The detailed guides live in [`docs/`](docs/README.md):

- [Local workflows](docs/user/local-workflows.md) — source format, updates,
  conflicts, layers, generation, adoption, templatize, and workshop use.
- [CLI reference](docs/user/cli-reference.md) — command flags and exit codes.
- [Developer guide](docs/developer/) — architecture, project lifecycle, tests, and
  contribution steps.
- [Historical Copier overview](docs/copier/overview.md) — migration context only.

## Development

The root devenv pins Python 3.13 and provides jj. Templateer is a sibling local
checkout at `../templateer_v2`.

```bash
devenv shell
uv sync --locked
copyroom doctor
copyroom --help
```

Run the checks from the devenv shell:

```bash
uv run pytest -q
uv run ruff check src/ tests/
bash demo/walkthrough.sh
```

## Create and update a project

```bash
copyroom new ../my-template ./my-project --answers ../my-template/answers.json
cd my-project
copyroom update --out ../my-project-preview
# Review the preview workspace, then apply that exact tree.
copyroom update --apply ../my-project-preview
```

`new` and `update` accept local Templateer sources only. Each project stores
source snapshots under `.copyroom-local/sources/` and records them in
`.copyroom-local.json`. A preview uses a separate jj workspace. If jj reports a
conflict, resolve it in that preview and apply it after review. A changed active
project makes the preview stale.

Run `copyroom generate` or `copyroom refresh` to make a model call. CopyRoom
validates and saves the exact artifact bytes. Normal updates replay those bytes.

## Existing projects

Use `copyroom templatize --target ../my-template` to extract a local source with
an exact tree check. Use `copyroom adopt ../my-template --answers answers.json`
to review drift. Add `--write` to record the marker and jj history. Legacy answer
files are not converted automatically; templatize the project, then adopt the
resulting local source.

See the [local workflow guide](docs/user/local-workflows.md) for the complete
source format and workshop commands.
