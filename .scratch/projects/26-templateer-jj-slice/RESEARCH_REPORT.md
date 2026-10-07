# Research report — local Templateer and jj vertical slice

Date: 2026-10-07

## Target and environment

Build a runnable `new → preview → update` flow in this numbered project.
Use actual Templateer artifact rendering and plain jj in disposable projects.
Keep the active project unchanged during preview. Apply the exact previewed
render commit. Run without Copier or a model provider.

The nested devenv supplied jj 0.45.1 and Python 3.13.14. The local uv project
installed Templateer 0.4.1 from `templateer_v2` through an editable path.
The [Nix configuration](devenv.nix), [devenv lock](devenv.lock), [uv lock](uv.lock), and
[Python version](.python-version) define the test environment. The project
marker records both Templateer's version and source digest. The uv lock alone
does not pin the bytes in an editable local package.

Run from this directory:

```bash
devenv test
devenv shell -- bash walkthrough.sh
```

The final [test log](evidence/2026-10-07-test.txt) shows nine integration
tests passing. `devenv test` also ran Ruff. The walkthrough made a local
project, previewed an updated Templateer artifact, applied it, and reported
revision one with no conflict. Both commands returned zero. The
[walkthrough log](evidence/2026-10-07-walkthrough.txt) records that run.

## Implementation

The [CLI](slice.py) has `new`, `preview`, `update`, `discard`, and `status`.
The [example](example) includes five Templateer artifacts and one shared
Pydantic schema. The composer validates the model, artifact content, output
path, path ownership, and executable mode. It saves validated model values
in the project marker.

`new` writes T0 as a jj render commit. It writes the project marker in a
later project commit. `preview` finds T0 from the project's render ancestry.
It makes T1 as a child of T0 in a separate jj workspace. It then makes a
preview merge with the active project commit as the other parent. The CLI
uses `jj diff --from <project> --to @` to show the change.

`update` checks the active commit, active files, preview commit, and preview
files against the preview state. It merges the same T1 into the active
project. It compares the applied tree with the preview tree before it saves
the new marker. A controlled failure after the active merge restores the jj
operation recorded before apply. A successful apply removes the preview
workspace and state.

## Results

- Two successive updates used T0 and then T1 as merge bases. Project edits
  survived both updates. An executable Templateer artifact kept its mode.
- A project edit and template edit to the same README line produced a jj
  conflict in the preview. The active project stayed unchanged. This slice
  refused to apply that conflict.
- A new template output could not claim a project-only path. Two Templateer
  artifacts could not claim the same path during `new`. Both checks ran before
  the relevant jj change.
- A changed active project made an existing preview stale. A source edit after
  preview did not alter the applied render; the CLI applied the recorded T1.
- A source prompt edit that changed no output still made a new render commit.
  The marker advanced its source digest and kept the same render tree digest.
- An injected check failure after the active merge restored the original
  commit and files. The preview remained available for review or discard.
- A moved source path failed without an override. `preview --source` recovered
  it and saved both the new path and changed answers after apply.
- A symlinked `templates/` root was rejected before `new` made a project.

The [jj working-copy guide](https://docs.jj-vcs.dev/latest/working-copy/)
describes separate workspaces. The
[jj command reference](https://docs.jj-vcs.dev/latest/cli-reference/) defines
the workspace and operation commands used here. The byte and commit results
above come from this local run.

## Limits

This is a first maintained flow inside `.scratch`, not a replacement for the
CopyRoom package. It supports one base layer and trusted local `full_file`
text artifacts. It does not implement direct LLM calls, frozen generated
artifacts, adoption, templatize, or the workshop. It does not copy binary or
symlink files from a template. A conflict can be inspected and discarded,
but this slice cannot apply or resolve it.

The marker stores an absolute local source path. `preview --source` recovers
from a source move, but no source snapshot or retrieval command exists. A
source digest identifies bytes but does not make them available. Controlled
rollback passed; process kills, concurrent edits, and filesystem errors
during preview cleanup remain untested. The source digest covers the manifest
and `templates/` files. A schema that imports code outside that tree needs an
additional source record. Each disposable project uses plain
jj. The active CopyRoom repository still uses gitman for version control.
