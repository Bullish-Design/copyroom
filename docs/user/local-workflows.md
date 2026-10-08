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
copyroom new app-template ./app --answers app-template/answers.json
cd app
copyroom status
copyroom update
```

`copyroom update` prints a JSON preview state. Its `path` field names the
preview workspace. With no `--out`, CopyRoom creates a unique path beside the
project, in `.copyroom-previews/`. Set the path with `--out`:

```bash
copyroom update --out ../app-update-1
```

The preview workspace must be outside the project. If `--out` is inside the
project, `copyroom update` exits with code `2` and prints `preview must be
outside the project`. CopyRoom creates the parent directory of `--out`.

Review files in the preview workspace. Apply the exact reviewed preview with:

```bash
copyroom update --apply ../app-update-1
```

The active project does not change during preview. If the project changes after
preview, CopyRoom refuses the apply. A jj conflict remains in the preview
workspace. Resolve the file there, inspect the result, then apply it. Discard a
preview with `copyroom discard --preview PATH`.

The preview contains the next marker and the full prepared project tree. Its
state records the active head, source digest, render head, and tracked-tree
digest. CopyRoom publishes that prepared tree. It does not rerender during apply.

If the source and answers produce no change, `copyroom update` returns
`no-change` and exits `0`. It does not create a preview workspace.

If CopyRoom stops during an apply or layer add, inspect and reconcile the saved
state with:

```bash
copyroom recover
```

Transaction journals live in `.copyroom-local/journal/`. Each journal has one
of three states:

- `prepared`: CopyRoom built a result. Publication has not started.
- `publishing`: CopyRoom started publication. Recovery must check the result.
- `published`: publication passed its checks. Cleanup may still be pending.

`recover` keeps a prepared update preview for review. Apply it or discard it.
For layer add, recovery publishes a complete prepared layer when the active
head still matches. If another writer moved the head, keep the result and
retry the layer add or prune the dead result.

`recover` exits `0` when it has no pending recovery, damaged journal, or
unpruned finding. A prepared update is pending review. It does not make
`recover` exit `1`. The report separates `pending_review` from
`pending_recovery`. Exit `1` reports a finding. Exit `2` reports an error.

`recover` reports orphan workspaces, layer directories, and JSON write
temporaries. An orphan is a workspace or temporary that no journal protects.
Use `copyroom recover --prune` to remove safe orphans and temporaries. This
command also untracks CopyRoom local state when needed.

`layer add` stages its render under the system temporary directory. Its path
starts with `copyroom-layer-`. Recovery tracks this path through the journal.

`status` exits `1` when it finds a marker/render mismatch, a pending
publication, a conflict, or another unhealthy project state. It prints a
line for each finding to stderr. `inspect` reports the same mismatch data, but a
mismatch does not change its exit code. Both commands can emit JSON with
`--json`.

The inspection report includes `marker_render_mismatches`,
`pending_transactions`, and `pending_previews`. The status report adds
`has_pending_publication`. The recovery report includes `pending_review`,
`pending_recovery`, `damaged`, and `repaired`.

Tree checks use paths that jj tracks. jj can refuse new files above its
`snapshot.max-new-file-size` limit, which defaults to 1 MiB. The setting
`snapshot.auto-track = none()` can also hide new files. CopyRoom prints jj's
"Refused to snapshot some files" warning to stderr. A tree check cannot include
a new file that jj did not track.

Recovery also reports tracked preview, journal, lock, and write-temporary paths.
Use `copyroom recover --prune` to untrack those paths. It keeps their files on
disk.

## Layers

Each layer owns a separate set of paths and a separate jj render head. The
base layer is created by `new`. Add an overlay with a local Templateer source
and answers file:

```bash
copyroom layer add --source ../docs-template --as docs \
  --answers ../docs-template/docs-answers.json
copyroom layer list --json
copyroom update --layer docs --out ../docs-2
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
copyroom refresh --layer gen-config --out ../config-preview \
  --request "Add a coverage command"
```

The `refresh` preview is also outside the project. Review it, then apply it
with `copyroom update --apply PATH`.

## Adopt and templatize

`adopt` reports changed, project-only, and template-only paths. It does not
write unless `--write` is present. The report exits with code `1` when the
project differs from the source. Use `--template-only keep` to save explicit
omissions for paths that should remain outside template ownership.

`adopt --write` requires an existing jj repository to be colocated with its
Git directory. A non-colocated repository makes CopyRoom exit with code `2`.
Run `jj git init --colocate`, then retry adoption.

Run these commands from the directory that holds the project and the source.
Name the project with `--project`.

```bash
copyroom adopt app-template --project app --answers app-template/answers.json
copyroom adopt app-template --project app --answers app-template/answers.json \
  --template-only keep --write
```

`templatize` extracts files, modes, binary files, and safe relative symlinks.
Selected paths can use `project_name`; the command checks the extracted source
against the original tree and then renders a changed probe answer.

Run `templatize` from the directory that holds the project. The `--target`
source must be outside the project. With `--parameterize`, `--name` must equal
the project directory name.

```bash
copyroom templatize --project app --target app-template --name app \
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

Run `copyroom golden ID SCENARIO --refresh` first to create a golden. Without a
golden, `copyroom golden` exits with code `1`.

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
from that project's directory.

`copyroom update-test` exits `0` and reports `no-change` when the candidate
renders the same tree as the project. That result means the update path was not
exercised. It exits `1` when the update preview has conflicts.
