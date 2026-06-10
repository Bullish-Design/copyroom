# Architecture

This is the map of the CopyRoom codebase: how it's layered, how a command flows
from `argv` to a Copier subprocess, and the design rules that keep it consistent.
Pair it with the [module reference](module-reference.md) for per-file detail.

---

## 1. The layers

CopyRoom is a small, layered Python package. Top to bottom:

```
            ┌─────────────────────────────────────────────┐
  CLI       │ cli.py                                       │  argparse, help text,
            │   _build_parser · COMMAND_FN · main()        │  error formatting,
            └───────────────┬─────────────────────────────┘  exit codes
                            │
            ┌───────────────▼─────────────────────────────┐
  Session   │ session/                                     │  mode detection,
            │   detector · dispatcher · model              │  command→mode gating
            └───────────────┬─────────────────────────────┘
                            │
   Domain   ┌───────────────▼─────────────────────────────┐
 workflows  │ project/   template/   workshop/             │  one guarded
            │ release/   manage/                           │  lifecycle per
            │   (model.py + workflow modules per package)  │  workflow
            └───────────────┬─────────────────────────────┘
                            │
  Compat    ┌───────────────▼─────────────────────────────┐
 boundary   │ _compat/                                     │  subprocess to
            │   copier · gitutil · shellcmd · treediff     │  copier & git;
            │   state_machine · errors                     │  shared primitives
            └─────────────────────────────────────────────┘
```

Each layer only depends **downward**. The domain workflows never touch `argparse`;
the CLI never shells out directly; everything that runs a subprocess goes through
`_compat`.

---

## 2. The request lifecycle

What happens when you run `copyroom update v2.0.0` (`cli.py:main`):

1. **Parse.** `_build_parser()` builds the argparse tree; `argv` is parsed.
   `--version` / no-command short-circuit to version/help.
2. **Bootstrap shortcut.** If the command is in `BOOTSTRAP_COMMANDS`
   (`adopt`, `templatize`), CopyRoom skips mode detection entirely and calls the
   handler — these run in unmanaged repos.
3. **Detect mode.** `_detect_and_report()` either honors `--mode` or calls
   `session.detector.detect_mode()`, which walks ancestors for markers. No mode →
   print the diagnostic and exit 1. Success advances a `CLISession` to
   `mode_detected`.
4. **Dispatch (gate).** `session.dispatcher.dispatch(cmd, session)` checks the
   command against `COMMAND_MODE_MAP`. Wrong mode / unknown command →
   `command_failed`, and the CLI prints an out-of-mode or unknown-command error
   and exits 1.
5. **Run.** The session advances to `command_running`; `COMMAND_FN[cmd]` (a thin
   `_cmd_*` wrapper) is invoked. The wrapper calls the domain workflow, catches
   `CopyRoomError`, formats output, and sets the exit code. The session advances
   to `command_complete`.

The `_cmd_*` functions are deliberately thin: argument unpacking, calling the
workflow, and turning the returned entity into human output + an exit code. All
real logic lives in the domain packages.

---

## 3. Domain packages: the consistent shape

Every domain package follows the **same shape**:

```
<package>/
├── model.py        # StrEnum statuses + VALID_*_TRANSITIONS + @dataclass entity
└── <workflow>.py   # rule functions + a high-level orchestrator
```

- **`model.py`** declares one or more lifecycle **entities** as dataclasses, each
  with a `status` field typed by a `StrEnum`, plus a `VALID_*_TRANSITIONS` table
  mapping each state to its allowed successors.
- **Workflow modules** implement the lifecycle as a sequence of small functions,
  each corresponding to one rule in the matching Allium spec (`.scratch/specs/`).
  Each function performs one step and transitions the entity's status via a shared
  `StateMachine`.
- A **high-level orchestrator** (`create_project`, `update_project`,
  `render_scenario`, `run_release_check`, `adopt`, …) chains the steps and returns
  the entity in its terminal state (`complete` / `failed` / `passed` / …).

The packages:

| Package | Entities | Commands |
|---------|----------|----------|
| `project/` | `ProjectCreation`, `TemplateUpdate` | `new`, `update` |
| `template/` | `TemplateCheckout`, `TemplatePreview` (+ `ValidateResult`) | `template-checkout/test/preview` |
| `workshop/` | `ScenarioRender`, `GoldenDiff`, `UpdateSimulation` | `render`, `test`, `golden`, `update-test` |
| `release/` | `ReleaseCheck` | `release-check` |
| `manage/` | `Adoption`, `Templatization` | `adopt`, `templatize` |
| `session/` | `CLISession` | (the dispatcher itself) |

Why this uniformity? It makes the whole codebase **predictable**: once you've read
one workflow, you can read any of them. It also makes the workflows **spec-faithful**
(each maps to an Allium rule) and **testable** in isolation (call the orchestrator,
assert the terminal state) — see [testing](testing.md).

---

## 4. The `_compat` boundary

`_compat/` is the only place that runs external processes or implements shared
primitives. Nothing above it shells out directly. It contains:

- **`copier.py`** — `copier_copy` / `copier_update`, the subprocess wrappers (with
  timeouts) for the Copier binary.
- **`gitutil.py`** — defensive git helpers (clone, fetch, worktree, snapshot,
  diff) that return `None` on a missing binary rather than raising.
- **`shellcmd.py`** — the **trust-gated** hook runner for template-supplied
  commands.
- **`treediff.py`** — the single tree-comparison used by golden and adopt
  (excludes `.copier-answers*.yml`).
- **`state_machine.py`** — the generic `StateMachine` every entity uses.
- **`errors.py`** — the single `CopyRoomError` type re-exported everywhere.

Full detail: [the `_compat` layer](compat-layer.md). The name signals its role —
a compatibility/isolation seam around tools CopyRoom delegates to.

---

## 5. Design rules (invariants worth preserving)

These are the rules the code already follows. Keep them when you extend it.

1. **Delegate, don't reimplement.** CopyRoom shells out to `copier` and `git`. It
   does not bind their Python APIs (cleaner error isolation, trivial stderr
   forwarding, no coupling to internals). New external work goes through
   `_compat`.
2. **Detect, don't guess.** Mode is resolved from markers; ambiguity is an error,
   not a fallback (`session/detector.py`).
3. **Guarded lifecycles.** Every workflow is a state machine with an explicit
   transition table; illegal transitions raise `InvalidTransitionError`. State is
   never assigned ad-hoc inside a workflow.
4. **One error type.** All workflows raise/return `CopyRoomError` (re-exported per
   module as `CreateError`, `RenderError`, etc. so existing imports keep working).
5. **Report-and-exit, never roll back.** On failure, print what happened and where
   state was left; exit non-zero; forward the underlying tool's stderr. The
   clean-worktree requirement is the safety net.
6. **Untrusted code stays gated.** Template hooks run only via `shellcmd` with
   `trust=True`; workshop checks (author's own) run freely.
7. **Scratch is isolated.** Edits → worktrees on scratch branches; previews/sims →
   temp dirs / the cache. The user's real tree is never the workspace.
8. **Additive config evolution.** Config readers tolerate unknown fields; new
   fields get defaults; old configs keep working.

---

## 6. Specs as the source of truth

The workflows are derived from **Allium specifications** in `.scratch/specs/`
(`copyroom-session`, `copyroom-project`, `copyroom-workshop`, `copyroom-release`).
Each rule function carries a comment pointing at the spec rule it implements
(e.g. `# Rule: VerifyCleanWorktree (spec L185-L192)`), and the transition tables
mirror the spec's state graphs. The spec-tier tests (`tests/spec/`) validate that
these tables and types stay internally consistent with the specs. When changing a
workflow's shape, update the spec and the transition table together.

## See also

- [Module reference](module-reference.md) — every file, what it owns.
- [State machines](state-machines.md) — the lifecycle pattern in detail.
- [The `_compat` layer](compat-layer.md) — the subprocess boundary.
- [Testing](testing.md) — how the layers are tested.
