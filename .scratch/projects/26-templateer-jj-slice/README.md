# Local Templateer and jj vertical slice

This project runs one local base layer without Copier. Templateer renders five
text artifacts from one saved Pydantic model. A tree composer checks paths,
file modes, and artifact validators. Plain jj stores each render as a commit.
A separate jj workspace holds each preview until `update` or `discard`.

## Run

Enter this directory, then run:

```bash
devenv test
devenv shell -- bash walkthrough.sh
```

The walkthrough makes a disposable project under `.devenv/state`. It prints
the project path at the end. The [example](example) contains the local
Templateer source, manifest, and answers.

The direct command flow is:

```bash
devenv shell -- uv run python slice.py new \
  --source SOURCE --target PROJECT --answers ANSWERS.json
devenv shell -- uv run python slice.py preview \
  --project PROJECT --out PREVIEW
devenv shell -- uv run python slice.py update \
  --project PROJECT --preview PREVIEW
devenv shell -- uv run python slice.py discard --preview PREVIEW
devenv shell -- uv run python slice.py status --project PROJECT
```

`preview` leaves PROJECT unchanged. It writes the jj workspace at PREVIEW and
its state beside it at `PREVIEW.copyroom-preview.json`. `update` applies the
exact render commit from that preview. It rejects a changed project or preview.
`discard` removes the preview workspace and state. Keep PREVIEW outside the
project and source directories.
Use `preview --source MOVED_SOURCE` after a source move. Use
`preview --answers NEW_ANSWERS.json` to change saved answers with the update.

The source has `manifest.json` and a `templates/` directory. The manifest
lists Templateer artifact names and executable output paths. The composer
supports Templateer `full_file` text outputs. It checks every artifact with
Templateer before it writes a tree. It saves validated model values, source
and manifest digests, path owners, the Templateer version, and the render tree
digest in `.copyroom-local.json`. It also saves a digest of the installed
Templateer Python source, since this project uses an editable local package.
A jj render commit keeps the old output bytes for later merges.

## Results and limits

The [test suite](tests/test_slice.py) covers two updates, local edits,
conflicts, stale previews, path ownership, controlled rollback, and a source
edit after preview.
`devenv test` runs the suite and Ruff. The [research report](RESEARCH_REPORT.md)
records the commands and findings.

This slice supports one base layer and trusted local Templateer text templates.
It does not call a model provider. An explicit LLM generation command and
frozen generated artifacts belong in the next slice. It also has no adopt,
templatize, workshop, static binary, or symlink command. A conflict stays in
the preview; this slice does not apply it. Source paths remain absolute, with
`--source` available after relocation. A digest identifies source bytes but
does not retrieve a missing source.
