# Spec-derived tests for CopyRoom

Tests in this directory are derived from the Allium specifications in
`.scratch/specs/` following the test-generation guide at
`.agents/skills/allium/references/test-generation.md`.

## Structure

```
tests/spec/
├── __init__.py                   # Package marker
├── conftest.py                   # Shared fixtures, dataclass helpers, transition maps
├── test_session_lifecycle.py     # CLISession lifecycle, mode detection, dispatch
├── test_project.py               # ProjectCreation, TemplateUpdate
├── test_release.py               # ReleaseCheck
├── test_workshop.py              # ScenarioRender, GoldenDiff, UpdateSimulation
└── test_invariants.py            # Cross-cutting invariants from copyroom.allium
```

## Test categories (per test-generation guide)

| Category | Coverage |
|----------|----------|
| Entity & value type tests | Fields present, correct types, optional/null behaviour |
| Enumeration tests | All values, comparability, set membership |
| State transition tests | Valid/invalid transitions, terminal states, bidirectional edges |
| State-dependent field tests | when-clause presence/absence |
| Rule tests | Requires clauses, ensures outcomes, conditional branching |
| Invariant tests | Expression-bearing invariants, prose invariants |
| Surface tests | Available operations, actor access |
| Scenario tests | Happy path through full lifecycle chains |
| Cross-spec invariants | Mode-gated access, error handling, off-ramp |

## Running

```bash
cd /path/to/copyroom
pytest tests/spec/ -v
```

## Status

Tests are currently **structural/declarative** — they validate that the
transition maps and type constraints in the spec are internally consistent.
Tests marked `pass  # Integration` require a running implementation to
exercise the actual CLI behaviour.

As CopyRoom is implemented, fill in the Integration-pass tests with actual
CLI invocations against the `CopyRoomCLI` helper in `conftest.py`.
