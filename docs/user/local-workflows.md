# Local Workflows

CopyRoom uses local Templateer sources and jj. It does not fetch project
templates. Each managed project stores a source snapshot, its answers, a render
head for each layer, and a `.copyroom-local.json` marker.

## Source format

A source has a `manifest.json` file and a `templates/` directory. Each named
template is a Templateer artifact with `metadata.yml`, `schema.py`, and
`template.j2` files.

```json
{
  "templates": ["readme", "config"],
  "executable": ["scripts/setup.sh"],
  "static": [
    {"path": "assets/logo.bin", "source": "assets/logo.bin"}
  ],
  "symlinks": [
    {"path": "docs/current", "target": "../README.md"}
  ]
}
```

All templates in one source use the same Pydantic schema. Templateer validates
the model and each rendered artifact before CopyRoom writes a tree. Static
files retain their bytes. Executable files retain their mode. Symlinks must be
relative and must point to a path in the output tree.

Answers are JSON files that match the shared schema. The source path is a
locator. The project snapshot under `.copyroom-local/sources/<digest>` is the
saved input used to replay that render.

## Create and update

```bash
copyroom new ../app-template ./app --answers ../app-template/answers.json
cd app
copyroom status
copyroom update --out .copyroom-local/previews/update-1
```

Review files in the preview workspace. Apply the exact reviewed preview with:

```bash
copyroom update --apply .copyroom-local/previews/update-1
```

The active project does not change during preview. If the project changes after
preview, CopyRoom refuses the apply. A jj conflict remains in the preview
workspace. Resolve the file there, inspect the result, then apply it. Discard a
preview with `copyroom discard --preview PATH`.

The preview state records its active head, source digest, render head, and tree
digest. CopyRoom applies that exact tree. It does not rerender during apply.

## Layers

Each layer owns a separate set of paths and a separate jj render line. The base
layer is created by `new`. Add an overlay with a local Templateer source and
answers file:

```bash
copyroom layer add ../docs-template --as docs --answers docs-answers.json
copyroom layer list --json
copyroom update --layer docs --out .copyroom-local/previews/docs-2
```

CopyRoom rejects exact, prefix, case-folded, and project-owned path collisions
before it changes the active tree.

## Explicit generation

`generate` and `refresh` are the only CopyRoom commands that call a model.
Each saves the request, model name, validated model, Templateer source digest,
and exact artifact bytes. A normal update replays those bytes without a provider
call.

```bash
copyroom generate --source ../app-template --template config \
  --request "Add a local test command" --model openai:gpt-4.1-mini
copyroom refresh --layer gen-config --out .copyroom-local/previews/config \
  --request "Add a coverage command"
```

Review and apply a refresh preview with `copyroom update --apply PATH`.

## Adopt and templatize

`adopt` reports changed, project-only, and template-only paths. It does not
write unless `--write` is present. Use `--template-only keep` to save explicit
omissions for paths that should remain outside template ownership.

```bash
copyroom adopt ../app-template --answers answers.json
copyroom adopt ../app-template --answers answers.json --template-only keep --write
```

`templatize` extracts files, modes, binary files, and safe relative symlinks.
Selected paths can use `project_name`; the command checks the extracted source
against the original tree and then renders a changed probe answer.

```bash
copyroom templatize --into ../app-template --name app \
  --parameterize README.md
```

Copier answer files are not migrated automatically. Extract a local source,
then adopt it with an explicit answers file.

## Workshop

A workshop has `copyroom.yml`, `registry/`, and `scenarios/`. Each registry
source is a local Templateer source. A scenario is a YAML mapping that matches
the source schema.

```yaml
templates:
  app:
    source: ../app-template
```

Render and compare a scenario against `goldens/<id>/<scenario>/`:

```bash
copyroom render app basic
copyroom golden app basic
copyroom golden app basic --refresh
copyroom test app basic
copyroom release-check app
```

Golden comparison checks paths, bytes, modes, and symlink targets. Refresh is
explicit and runs Templateer's authoring audit first. `test` and
`release-check` run `devenv test` in the generated scenario and preserve the
output in `.copyroom-workshop/logs/`.

Use a separate jj workspace for template edits:

```bash
copyroom template-checkout app
# Edit files in the candidate path printed by the command.
copyroom template-test app
copyroom update-test app basic
copyroom template-preview app --project ../app --out ../app-preview
copyroom template-discard app
```

The active source remains unchanged while the candidate is edited. The project
preview is separate from the active project. Apply a reviewed project preview
from that project's directory with `copyroom update --apply PATH`.
