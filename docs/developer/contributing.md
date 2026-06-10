# Contributing

How to set up, what the quality gate is, the conventions to follow, and how to
add a new command. Read [architecture](architecture.md) and
[state machines](state-machines.md) first — they're the patterns every change
must fit.

---

## 1. Setup

```bash
devenv shell      # enters the dev environment (Python 3.13, git, uv, secretspec)
uv sync           # install the project + dev dependencies
copyroom --help   # the editable install puts the CLI on PATH
```

The dev environment is defined in `dev/devenv.nix` (pulled in by the root
`devenv.yaml`). It pins Python 3.13 via an editable uv venv and sets
`copyroom.enable = false` (the venv already provides the CLI; the packaged build
is for consumers). **Always work inside `devenv shell`** so you get the pinned
toolchain — never use an ambient `uv`/`python`.

---

## 2. The gate

Two commands must be green before and after every change:

```bash
uv run ruff check src/ tests/        # lint (and import sort)
uv run pytest -q                     # the full suite (see Testing)
```

Ruff config lives in `pyproject.toml`: line length 120, target `py313`, rule sets
`E,F,I,UP,B`, double-quote/space/lf formatting. `tests/**` and
`src/copyroom/_compat/**` are exempt from docstring (`D`) and annotation (`ANN`)
rules. `ruff format` applies the formatting.

Type checking is configured for `ty` (`[tool.ty]` in `pyproject.toml`, Python
3.13, `src` as root).

For the full verification ritual see
[`REFACTORING_GUIDE.md`](../../REFACTORING_GUIDE.md)'s final checklist.

---

## 3. Conventions

- **Match the surrounding code.** Every domain package has the same shape
  (`model.py` + workflow modules + an orchestrator). New work should look like its
  neighbors — same docstring style, same rule-function-per-spec-rule layout.
- **Delegate to `_compat` for anything external.** No `subprocess.run("git"/"copier")`
  outside `_compat/`. Add timeouts; fail soft on missing binaries.
- **Guard every workflow with a state machine.** Never assign `entity.status = …`
  directly; route through `StateMachine.transition`. See
  [state machines](state-machines.md).
- **One error type.** Raise `CopyRoomError` (re-export it from your module so the
  CLI's aliased import keeps working).
- **Report-and-exit, never roll back.** Forward the underlying tool's stderr;
  leave a clear "state left" message; exit non-zero.
- **Respect the trust gate.** Template-supplied commands go through
  `shellcmd.run_hook_commands(..., trust=…)`. Workshop checks (author's own) run
  freely.
- **Additive config only.** Tolerate unknown fields; give new fields defaults.
- **No AI-attribution trailers** in commits, PRs, code, or docs (omit
  `Co-Authored-By` / "Generated with" entirely).

---

## 4. Where things live

| You want to… | Touch |
|--------------|-------|
| Add/adjust a flag | `cli.py:_build_parser` (+ the `_cmd_*` handler) |
| Change mode detection | `session/detector.py` |
| Change command→mode gating | `session/model.py` (command sets) + `session/dispatcher.py` |
| Change a workflow's steps | that package's `model.py` (states/transitions) + workflow module |
| Change how Copier/git is called | `_compat/copier.py` / `_compat/gitutil.py` |
| Change the trust behavior | `_compat/shellcmd.py` |
| Change golden/adopt diffing | `_compat/treediff.py` |

---

## 5. Adding a new command

Worked example — the shape every command follows:

1. **Spec first.** Add/extend the rule and lifecycle in the relevant
   `.scratch/specs/*.allium`.
2. **Model.** In the package's `model.py`, add the `StrEnum` status, the
   `VALID_*_TRANSITIONS` table, and the entity dataclass (see
   [state machines](state-machines.md)).
3. **Workflow.** Write rule functions (one per spec rule, annotated with the spec
   line range) and a high-level orchestrator that returns the entity in its
   terminal state. Use the shared `StateMachine`, `CopyRoomError`, and `_compat`
   helpers.
4. **Register the mode.** Add the command name to `WORKSHOP_COMMANDS` /
   `PROJECT_COMMANDS` in `session/model.py` (or `BOOTSTRAP_COMMANDS` if it runs in
   an unmanaged repo and should bypass detection).
5. **Wire the CLI.** Add a subparser in `cli.py:_build_parser`, a thin `_cmd_*`
   handler (unpack args → call orchestrator → format output → exit code), and an
   entry in `COMMAND_FN`. Update `COPYROOM_DESCRIPTION`.
6. **Test.** Spec-tier tests for the transitions; an integration test driving the
   orchestrator against the fixture template; a regression anchor if fixing a bug.
   See [testing](testing.md).
7. **Document.** Add it to the [CLI reference](../user/cli-reference.md) and the
   relevant task guide; if it changes the Copier mapping, update the
   [Copier overview](../copier/overview.md#9-how-copyroom-maps-onto-copier).

---

## 6. Versioning

CopyRoom follows semver with an additive-only config promise:

- Patch (`0.x.y`): bug fixes.
- Minor (`0.2.0` → `0.3.0`): new commands, new config fields (with defaults).
  Deprecate with warnings; never remove within `0.x`.
- `1.0.0`: first backward-compat commitment.

Because config is additive-only, a CLI upgrade should never break an existing
project config — readers ignore unknown fields rather than failing. Bump
`__version__` in `src/copyroom/__init__.py` (and `version` in `pyproject.toml`)
together.

---

## 7. Commit & PR hygiene

- Branch off `main`; don't commit straight to it.
- Keep the gate green in every commit where practical.
- Conventional, scoped messages (`fix:`, `feat:`, `refactor:`, `test:`,
  `docs:`) — see the suggested sequence in `REFACTORING_GUIDE.md`.
- **No AI-attribution trailers** anywhere.

## See also

- [Architecture](architecture.md) · [State machines](state-machines.md) ·
  [The `_compat` layer](compat-layer.md) · [Testing](testing.md)
- [`REFACTORING_GUIDE.md`](../../REFACTORING_GUIDE.md) — phased history and the
  verification checklist.
