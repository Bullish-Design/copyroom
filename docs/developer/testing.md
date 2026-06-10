# Testing

CopyRoom's suite has **three tiers** under `tests/`. As of this writing the full
suite is **448 tests, green**, running in ~2 min (the time is dominated by real
Copier/git subprocesses in the integration tier).

```
tests/
├── spec/          # structural: the spec's transition tables & types are consistent
├── unit/          # fast, in-process: rule functions & helpers with fixture data
└── integration/   # end-to-end: real Copier renders against a real fixture template
```

The guiding lesson (learned the hard way — see `REFACTORING_GUIDE.md`): **test the
workflows, not just the models.** Several historical bugs lived in orchestrator
functions the model-only tests never called. The integration tier exists to drive
the public entry points end to end.

---

## Tier 1 — spec tests (`tests/spec/`)

Derived from the Allium specs in `.scratch/specs/` (see `tests/spec/README.md`).
They are **structural / declarative**: they assert that the
`VALID_*_TRANSITIONS` tables, the status enums, and the entity fields are
internally consistent with the spec — valid transitions are accepted, illegal
ones raise, terminal states have no outbound edges, required fields exist.

Files: `test_session_lifecycle.py`, `test_project.py`, `test_workshop.py`,
`test_release.py`, `test_invariants.py` (cross-cutting invariants like mode-gated
access and the off-ramp). These are fast and need no I/O.

## Tier 2 — unit tests (`tests/unit/`)

Fast, in-process tests of rule functions and helpers with fixture data — no real
templates, no network. Examples: `test_mode_detection.py` (the marker walk),
`test_dispatcher.py` (command→mode gating), `test_template.py`,
`test_manage.py`, `test_release_check.py`.

## Tier 3 — integration tests (`tests/integration/`)

The real thing: a tiny Copier template in a tmp git repo and a workshop whose
registry points at it, so the orchestrators run **genuine `copier copy`/`update`
and git** invocations.

The shared fixtures (`tests/integration/conftest.py`):

| Fixture | What it gives you |
|---------|-------------------|
| `template_repo` | A git repo holding `fixtures/template/`, committed and **tagged `v1.0.0`**. |
| `tag_v2(template_repo)` | Helper that adds a `CHANGELOG.md.jinja` and tags **`v2.0.0`** — for update tests. |
| `workshop` | A workshop dir whose `copyroom.yml` points template `demo` at `template_repo` (with a `checks` entry). |
| `git_workshop` | The `workshop` committed to git with `generated/` and `.copyroom_sim/` gitignored — for `release-check`. |

Test files: `test_cli.py`, `test_workflows.py` (drives `render_scenario`,
`golden_diff`, `refresh_golden`, `run_update_simulation`, `run_release_check`),
`test_template_edit.py`, `test_manage.py`, `test_harness.py`.

The fixture template lives at `tests/integration/fixtures/template/` (a `copier.yml`,
a `README.md.jinja`, and the answers-file template) and the workshop scaffold at
`tests/integration/fixtures/workshop/`.

---

## Running the suite

Always run inside the devenv shell (pins Python 3.13):

```bash
devenv shell -- python -m pytest                 # everything (with coverage)
devenv shell -- python -m pytest tests/unit      # just the fast tier
devenv shell -- python -m pytest tests/integration -q
devenv shell -- python -m pytest tests/integration/test_workflows.py::test_name
```

Coverage is on by default (`pyproject.toml`: `addopts = "-q --cov=copyroom
--cov-report=term-missing"`, `testpaths = ["tests"]`). Add `--no-cov` to skip it
for a quick run.

### Requirements at runtime

The integration tier needs `git` and `copier` on `PATH` — both are present in the
devenv shell. Git helpers degrade gracefully when git is absent (returning
`None`/`False`), but the integration tests assume it's there.

---

## What good coverage looks like here

For a workflow change, cover three things:

1. **The transition graph** (spec tier): the new edge is legal; the old illegal
   one still raises `InvalidTransitionError`.
2. **The orchestrator end to end** (integration tier): call the public function
   (`render_scenario`, `update_project`, …) against the fixture and assert the
   **terminal status** and the observable effect (a file exists, a `.rej` is
   captured, the worktree stays clean, etc.).
3. **Regression anchor**: where you're fixing a bug, write a test that **fails
   before** the fix and **passes after** — preferably first.

The `demo/walkthrough.sh` script is *not* a test (it's a narrated, real-CLI
walkthrough), but it doubles as an end-to-end smoke check: if it runs clean, the
whole command surface works against real Copier.

## See also

- [State machines](state-machines.md) — what the spec tier validates.
- [Architecture](architecture.md#6-specs-as-the-source-of-truth) — specs as truth.
- `tests/spec/README.md` and `REFACTORING_GUIDE.md` for the history.
