# CLI Reference

Run CopyRoom inside the devenv shell. Local projects use `.copyroom-local.json`.
Workshop commands use `copyroom.yml`, `registry/`, and `scenarios/`.

## Project commands

| Command | Behavior |
| --- | --- |
| `copyroom new SOURCE TARGET --answers FILE` | Create from a local Templateer source. |
| `copyroom update [--layer NAME] [--source DIR] [--answers FILE] [--out DIR]` | Create a separate update preview. |
| `copyroom update --apply DIR` | Apply the exact reviewed preview. |
| `copyroom apply --preview DIR` | Apply the exact reviewed preview. |
| `copyroom discard --preview DIR` | Discard a pending preview. |
| `copyroom preview list --project DIR` | List pending previews. |
| `copyroom status [--json]` | Report jj, source snapshots, conflicts, and previews. |
| `copyroom inspect [--json]` | Report source provenance, render heads, and path owners. |
| `copyroom layer add --source SOURCE --as NAME --answers FILE` | Add an independent layer. |
| `copyroom layer list [--json]` | List layer render heads and owners. |
| `copyroom generate --source DIR --template NAME --request TEXT` | Explicitly call a model and freeze the result. |
| `copyroom refresh --layer NAME --out DIR --request TEXT` | Generate and preview a new frozen result. |

With no `--out`, `update` creates a unique path beside the project in
`.copyroom-previews/`. Every `--out` path must be outside the project and the
source. CopyRoom creates the parent directory of `--out`. `--apply` cannot be
combined with preview inputs.
Remote refs, branch flags, and hooks are not supported by local updates.

## Adoption commands

| Command | Behavior |
| --- | --- |
| `copyroom adopt SOURCE --project DIR --answers FILE` | Report source drift without writing. |
| `copyroom adopt SOURCE --project DIR --answers FILE --write` | Record the source marker and jj history. |
| `copyroom adopt SOURCE --project DIR --answers FILE --template-only keep --write` | Keep template-only paths outside project ownership. |
| `copyroom templatize --project DIR --target SOURCE [--name NAME] [--parameterize PATH]` | Extract and exact-check a local source. |

`templatize` reads the current project tree. Its output source must be separate
from that tree. Legacy answer files are not rewritten.

## Workshop commands

| Command | Behavior |
| --- | --- |
| `copyroom render ID SCENARIO` | Render a local source scenario. |
| `copyroom test ID SCENARIO` | Render and run `devenv test`. |
| `copyroom golden ID SCENARIO` | Compare a full-tree golden. |
| `copyroom golden ID SCENARIO --refresh` | Audit Templateer, then refresh the golden. |
| `copyroom release-check ID` | Audit, compare all goldens, and run scenario tests. |
| `copyroom template-checkout ID` | Create a separate jj candidate workspace. |
| `copyroom template-test ID` | Compare candidate renders with all scenario goldens. |
| `copyroom update-test ID SCENARIO` | Preview the candidate against a disposable project and run `devenv test`. |
| `copyroom template-preview ID --project DIR --out DIR` | Preview a candidate update in a separate project workspace. |
| `copyroom template-discard ID` | Forget and remove the candidate workspace. |

## General options and exit codes

- `--json` emits a structured report where the command supports it.
- `--mode project` and `--mode workshop` force mode detection.
- `--version` prints the CopyRoom version.
- `copyroom doctor` checks Templateer and jj.

Exit codes are part of the CLI interface:

- `0`: the operation passed.
- `1`: a finding needs review, such as a golden difference or conflict.
- `2`: an infrastructure or state error blocked the operation.
- `3`: command usage or input is invalid.

See [Local Workflows](local-workflows.md) for the source format and full
conflict process.
