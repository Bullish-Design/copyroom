# Testing

Run Python commands inside the root devenv shell. The shell pins Python and
provides jj.

```bash
devenv shell -- uv run pytest -q
devenv shell -- uv run ruff check src/ tests/
devenv shell -- bash demo/walkthrough.sh
```

## Test areas

- `tests/spec/` checks command and state invariants.
- `tests/unit/` checks reports, path validation, source metadata, and helper
  behavior.
- `tests/integration/test_local_templateer_jj.py` uses local Templateer
  sources and disposable jj repositories. It covers rendering, preview,
  apply, conflicts, snapshots, layers, frozen generation, adoption,
  templatize, workshop goldens, and candidate workspaces.
- `tests/integration/test_cli.py` checks public commands, exit codes, workshop
  mode, and refusal to rewrite legacy project markers.

The local integration tests use temporary directories. They do not change the
CopyRoom repository's jj or gitman state.

## Walkthrough

`demo/walkthrough.sh` is a narrated command-line walkthrough. It creates a
temporary local source, project, and workshop. It checks source updates,
project-owned files, full-tree goldens, adoption, extraction, and candidate
workspace isolation. `--keep` preserves the temporary tree for inspection.

## Consumer shell

Use a separate consumer directory that imports `modules/copyroom.nix`. Check
that `copyroom doctor --json`, `jj --version`, and `templateer --version` work.
The consumer runtime must not expose the removed template engine.
