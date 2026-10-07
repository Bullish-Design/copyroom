# Local workflow contract tests

These tests check the user-visible rules for local Templateer sources and jj
projects. They cover replayable source snapshots, isolated previews, exact
apply, stale-state refusal, and unresolved conflicts.

The broader integration suite checks layers, generation, adoption, templatize,
and workshop behavior. It uses disposable project and workshop directories.

Run the contract tests inside the root devenv shell:

```bash
devenv shell -- uv run pytest tests/spec/ -q
```
