# Getting Started

CopyRoom creates projects from local Templateer sources and tracks their render
history with jj. Start with the [local workflow guide](local-workflows.md) for
source format and command details.

## Requirements

- Python 3.13
- Templateer from the sibling `templateer_v2` checkout
- jj from the root devenv
- devenv in projects that use the workshop test commands

Run CopyRoom commands from its devenv shell:

```bash
devenv shell
uv sync --locked
copyroom doctor
```

`copyroom doctor` checks Templateer and jj, and reports the pyjutsu guard. It exits with code `2` if either
dependency is missing.

## Create a project

The source has `manifest.json`, `templates/`, and an answers file that matches
the Templateer's shared schema.

```bash
copyroom new ../app-template ./app --answers ../app-template/answers.json
cd app
copyroom status
```

CopyRoom writes the source snapshot and a `.copyroom-local.json` marker. jj
records the initial render as the base layer.

## Preview and apply an update

```bash
copyroom update --out ../app-update-1
# Review the separate preview workspace.
copyroom update --apply ../app-update-1
```

The preview workspace must be outside the project. Run `copyroom update` with
no `--out` to let CopyRoom name the path for you.

CopyRoom refuses to apply a stale preview. Resolve jj conflicts in the preview
workspace, then apply the exact reviewed tree. See [Local Workflows](local-workflows.md)
for layers, explicit generation, adoption, templatize, and workshop commands.

## Run the checks

```bash
uv run pytest -q
uv run ruff check src/ tests/
bash demo/walkthrough.sh
```
