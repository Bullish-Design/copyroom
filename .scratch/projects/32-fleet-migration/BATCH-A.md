# Batch A migration report

Date: 2026-10-12

## Summary

Five repos now converge with template-py v0.8.0. The user waived Eventic's Testee gate. Flora also has no test result by user direction.

CopyRoom v0.8.5 is the minimum version for this migration. Its tag points to `a267243e`. Template-py v0.8.0 points to `851a7112`.

## Repo results

| Repo | Result | Main commit | Checks |
| --- | --- | --- | --- |
| agentman | migrated and pushed | `d35bb734` | Testee passed; status pins v0.8.0; second update returned no-change |
| argentic | migrated and pushed | `b45e0555` | Testee passed; status pins v0.8.0; second update returned no-change |
| eventic | migrated and pushed | `c1f27c248ff82e2318ba4700ef8bf89fe3e5672c` | Testee waived by user; CopyRoom status pins v0.8.0; second update returned no-change |
| flora | migrated and pushed | `5d8597a2` | Status pins v0.8.0; second update returned no-change; no tests ran by user direction |
| flora-core | migrated and pushed | `9bb0668b` | Testee passed 4/4; status pins v0.8.0; second update returned no-change |

Eventic `main` is `c1f27c248ff82e2318ba4700ef8bf89fe3e5672c`, and origin matches. The migration preserved the devman links and the project ignore rules, including `*.db`. CopyRoom status exits 0 with the v0.8.0 pin. A second update returns `no-change`. The user waived Testee on the real tree. No post-migration tests ran there.

Flora's migration commit uses the canonical source path `/home/andrew/Documents/Projects/template-py/source`. The marker pins ref `v0.8.0` at `851a7112`. CopyRoom status exited 0. A second update returned `no-change`. Flora's Testee gate did not run, as directed.

## Eventic gate evidence

The disposable baseline clone came from Eventic `main` at `cb2ca22b`. It kept the pre-migration Copier marker and project files. Its Testee command exited 2 before running checks:

```text
testee: module_missing: this repository does not import the Testee module.
Add the testee input and `imports: [ testee/nix/testee.nix ]` to devenv.yaml.
```

The baseline fails `testee verify` because it does not have the Testee module.

For a project-level comparison, the disposable baseline ran `uv sync --locked --extra test` and `uv run --no-sync pytest -q`. The lock stayed unchanged. Pytest finished in 191.66 seconds with 226 passed, 9 skipped, and 6 failed. The failures were pre-existing setup gaps: `alembic` was absent, two migration-dependent tests then failed, and three wheel tests required `uv build`. This run confirms that the pre-migration project also has a red raw pytest run. It does not provide a same-environment Testee comparison.

The first disposable migrated tree was stable at commit `9fbb6b89`, tree `9db07737`. Testee 0.6.1 ran full gate `20261012T220311Z-0a3521566cba`. It exited 1 with one passed check and three failed checks:

| Check | Result | Evidence |
| --- | --- | --- |
| pytest | failed, exit 2 | 219 tests collected; collection failed in `tests/property/test_canonical.py:8` and `tests/property/test_four_way.py:13` because `hypothesis` was missing |
| ruff | passed, exit 0 | no diagnostics |
| ruff-format | failed, exit 1 | `tests/conformance/test_memory_concurrency.py:41` needs formatting; one file would change |
| ty | failed, exit 1 | 84 errors; examples include invalid `ENCODINGS` typing, a `Store.search` argument type, and unresolved `alembic` imports |

This evidence does not show that the template update caused these findings. The baseline lacks Testee, so its checks did not run under the same environment. The migrated Testee run did not install the optional `test` extra.

The reviewed Eventic configuration now follows its existing continuous integration (CI) scope. `testee.prepare` installs the `test`, `postgres`, and `migrate` extras, then builds the wheel. Testee runs ruff, ruff-format, basedpyright, and pytest with `-W error`. `pyproject.toml` keeps `basedpyright` scoped to `src/eventic`. One Ruff-format line was fixed. This changes no check scope.

The user waived the real Eventic Testee gate and directed the migration to proceed without another test run. The exact-scope disposable gate was canceled, so the reviewed configuration has no green Testee result. No post-migration tests ran on real Eventic.

## Migration driver guard

The migration driver minimum is CopyRoom 0.8.5. Its guard now treats only `.agents` and `.claude/skills` as devman view paths. It no longer rejects project files such as `.claude/settings.json` or `.claude/scheduled_tasks.lock`.

Seven direct cases passed for root, nested, near-match, and project-owned `.claude` paths. Ruff passed with `B904` ignored. The file has a pre-existing `B904` diagnostic in its PyYAML fallback; this change did not add that diagnostic.

## References

- CopyRoom v0.8.5: `a267243e`.
- Template-py v0.8.0: `851a7112`.
- Migrated Eventic Testee run: `20261012T220311Z-0a3521566cba`.
- The task-owned pilot directories and Testee cache entries were removed after this report recorded their results.
