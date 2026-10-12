# Batch A migration report

Date: 2026-10-12

## Summary

Four repos now converge with template-py v0.8.0. Eventic remains unchanged because its disposable update has a red Testee gate. Flora passed CopyRoom status checks, but no test gate ran by user direction.

CopyRoom v0.8.5 is the minimum version for this migration. Its tag points to `a267243e`. Template-py v0.8.0 points to `851a7112`.

## Repo results

| Repo | Result | Main commit | Checks |
| --- | --- | --- | --- |
| agentman | migrated and pushed | `d35bb734` | Testee passed; status pins v0.8.0; second update returned no-change |
| argentic | migrated and pushed | `b45e0555` | Testee passed; status pins v0.8.0; second update returned no-change |
| eventic | skipped; real tree unchanged | `cb2ca22b` | Disposable migration gate failed; baseline lacks the Testee module |
| flora | migrated and pushed | `5d8597a2` | Status pins v0.8.0; second update returned no-change; no tests ran by user direction |
| flora-core | migrated and pushed | `9bb0668b` | Testee passed 4/4; status pins v0.8.0; second update returned no-change |

The real Eventic local and remote `main` both point to `cb2ca22b`. Its working tree was clean. No migration command ran in that repo.

Flora's migration commit uses the canonical source path `/home/andrew/Documents/Projects/template-py/source`. The marker pins ref `v0.8.0` at `851a7112`. CopyRoom status exited 0. A second update returned `no-change`. Flora's Testee gate did not run, as directed.

## Eventic gate evidence

The disposable baseline clone came from Eventic `main` at `cb2ca22b`. It kept the pre-migration Copier marker and project files. Its Testee command exited 2 before running checks:

```text
testee: module_missing: this repository does not import the Testee module.
Add the testee input and `imports: [ testee/nix/testee.nix ]` to devenv.yaml.
```

The baseline therefore fails `testee verify`, but it cannot compare the migrated Testee checks. The baseline does not have the Testee module.

For a project-level comparison, the disposable baseline ran `uv sync --locked --extra test` and `uv run --no-sync pytest -q`. The lock stayed unchanged. Pytest finished in 191.66 seconds with 226 passed, 9 skipped, and 6 failed. The failures were pre-existing setup gaps: `alembic` was absent, two migration-dependent tests then failed, and three wheel tests required `uv build`. This run confirms that the pre-migration project also has a red raw pytest run. It does not provide a same-environment Testee comparison.

The disposable migrated tree was stable at commit `9fbb6b89`, tree `9db07737`. Testee 0.6.1 ran full gate `20261012T220311Z-0a3521566cba`. It exited 1 with one passed check and three failed checks:

| Check | Result | Evidence |
| --- | --- | --- |
| pytest | failed, exit 2 | 219 tests collected; collection failed in `tests/property/test_canonical.py:8` and `tests/property/test_four_way.py:13` because `hypothesis` was missing |
| ruff | passed, exit 0 | no diagnostics |
| ruff-format | failed, exit 1 | `tests/conformance/test_memory_concurrency.py:41` needs formatting; one file would change |
| ty | failed, exit 1 | 84 errors; examples include invalid `ENCODINGS` typing, a `Store.search` argument type, and unresolved `alembic` imports |

This evidence does not show that the template update caused these findings. The baseline lacks Testee, so its checks did not run under the same environment. Its direct pytest run needed the optional `test` extra. The migrated Testee run did not install that extra. Keep Eventic blocked until its project owner fixes or waives the gate, then repeat the disposable migration.

## Migration driver guard

The migration driver minimum is CopyRoom 0.8.5. Its guard now treats only `.agents` and `.claude/skills` as devman view paths. It no longer rejects project files such as `.claude/settings.json` or `.claude/scheduled_tasks.lock`.

Seven direct cases passed for root, nested, near-match, and project-owned `.claude` paths. Ruff passed with `B904` ignored. The file has a pre-existing `B904` diagnostic in its PyYAML fallback; this change did not add that diagnostic.

## References

- CopyRoom v0.8.5: `a267243e`.
- Template-py v0.8.0: `851a7112`.
- Eventic disposable migration files and logs: `/tmp/copyroom-mode-pilot-rFEnww/work-eventic/`.
- Eventic baseline Testee output: `/tmp/copyroom-mode-pilot-rFEnww/eventic-baseline-testee.log`.
- Migrated Eventic Testee report: `/home/andrew/.local/state/testee/repos/c53585cb64b48466/slots/eventic-803e575b/runs/20261012T220311Z-0a3521566cba/report.json`.
