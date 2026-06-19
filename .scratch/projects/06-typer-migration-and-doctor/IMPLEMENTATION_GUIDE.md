# CopyRoom — Typer migration + `doctor` — Implementation Guide

Status: planned · Target version bump: **0.4.0 → 0.5.0** (CLI framework change + new command)

This guide is two deliverables in one branch:

- **A. CLI migration** — `argparse` → **Typer**, preserving the exact command surface,
  mode-gating behaviour, messages, exit codes, and JSON output.
- **B. `doctor` command** — a new environment-precondition check.

Everything lives in `src/copyroom/cli.py` plus one new module `src/copyroom/doctor.py`.
Core domain logic and the `session/` mode model are **reused unchanged**.

---

## 0. Orientation — how the CLI works today

`src/copyroom/cli.py` (945 lines) is an argparse frontend:

- `_build_parser()` builds one parser with subparsers for every command.
- `main(argv)` parses, handles `--version`/no-command, then:
  - **bootstrap** commands (`new`, `adopt`, `templatize`) skip mode detection and run
    directly (`BOOTSTRAP_COMMANDS` in `session/model.py`);
  - everything else calls `_detect_and_report()` → `dispatch()` (mode gating) →
    `COMMAND_FN[cmd](args)`.
- Each command is a thin `_cmd_*(args)` handler taking an `argparse.Namespace` and
  delegating to the real logic in `project/`, `template/`, `workshop/`, etc.
- Mode gating lives entirely in `session/` (`detect_mode`, `dispatch`,
  `COMMAND_MODE_MAP`, `CLISession`, `SessionStatus`, the `*_COMMANDS` frozensets).

The command surface (must be preserved exactly):

```
Global:    --mode {workshop,project}   --version
Project:   update [ref] [--branch] [--trust]
           inspect [--json]            status [--json]
           template-checkout [--from REF]
           template-test  [--from REF] [--check CMD]
           template-preview [--from REF]
           template-discard
Bootstrap: new <source> [target] [--answers FILE] [--trust]
           templatize [--into PATH] [--name NAME] [--id ID]
           adopt <template> [--ref REF] [--answers FILE] [--write] [--force]
Workshop:  registry <list|show <id>|validate|add <id> --source <src> [--scaffold]>
           render <tid> <sid>          test <tid> <sid>
           golden <tid> <sid> [--refresh]
           release-check <tid>
           update-test <tid> <sid> <old> <new>
NEW:       doctor [--json]             (runs anywhere, like bootstrap)
```

---

## 1. Invariants the tests lock in (read before touching anything)

These constrain the migration. **Run the suite first** to capture the green baseline:
`devenv shell -- pytest`.

1. **`_cmd_*(args)` handlers stay importable and accept an attribute-bag.**
   `tests/unit/test_cli_messages.py` does:
   ```python
   from copyroom import cli
   args = argparse.Namespace(template_id="t", scenario_id="s", old_version="v1", new_version="v2")
   cli._cmd_update_test(args)                       # called directly
   monkeypatch.setattr(cli, "run_update_simulation", ...)   # patches module-level name
   ```
   → **Do not** change `_cmd_*` signatures or move their imported names off the `cli`
   module. The Typer command functions must build an attribute-bag and delegate to the
   existing `_cmd_*`. (See §3 "bridge".)

2. **`python -m copyroom …` is the integration entrypoint.**
   `tests/integration/test_cli.py` shells out via
   `subprocess.run([sys.executable, "-m", "copyroom", *args])` and asserts **exit codes
   and message substrings**. So `__main__.py → main()` must remain, `--mode` must work,
   and out-of-mode / error exit codes (currently `1`) and message text must match.

3. **Mode-model tests are independent of the frontend.** `tests/unit/test_dispatcher.py`
   and `tests/unit/test_mode_detection.py` test `session/` directly — they keep passing
   because we reuse `session/` untouched.

4. **Exit codes:** today success `0`, errors `1`. Keep that for migrated commands.
   `doctor` introduces `0` ok / `2` infra (see §4).

5. **`--json` output is plain JSON** (no Rich coloring). Keep `print(json.dumps(...))`.

---

## 2. Dependencies & entrypoint

- `pyproject.toml` → add to `[project].dependencies`:
  ```toml
  "typer>=0.12",
  ```
  (matches gitman/testee.) Typer pulls `click` + `rich`. Nothing is removed.
- Keep the console script and `__main__.py` exactly:
  ```toml
  [project.scripts]
  copyroom = "copyroom.cli:main"
  ```
  `main()` will call the Typer app (`app()`), so both `copyroom` and `python -m copyroom`
  route through the same place.
- `devenv shell -- uv sync` (or the repo's task) after editing pyproject.

---

## 3. Deliverable A — the Typer frontend

### 3.1 App + globals

Replace `_build_parser()`/`main()` plumbing (keep everything else in the file):

```python
import typer
from types import SimpleNamespace

app = typer.Typer(
    name="copyroom",
    help=COPYROOM_DESCRIPTION,          # reuse the existing long description
    add_completion=False,
    no_args_is_help=True,               # `copyroom` with no args → help, exit 0
    rich_markup_mode=None,              # keep help text verbatim (no Rich markup)
)

# Module-global the gating helpers read; set by the callback.
_MODE_OVERRIDE: str | None = None


def _version_callback(value: bool) -> None:
    if value:
        from . import __version__
        typer.echo(f"copyroom {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    mode: str | None = typer.Option(
        None, "--mode",
        help="Force a mode instead of auto-detecting from directory markers",
    ),
    version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True,
        help="Print version and exit",
    ),
) -> None:
    global _MODE_OVERRIDE
    if mode is not None and mode not in ("workshop", "project"):
        typer.echo("Error: --mode must be 'workshop' or 'project'.", err=True)
        raise typer.Exit(code=2)
    _MODE_OVERRIDE = mode
```

> `--mode` was an argparse `choices=[...]`. Typer can do this with an `Enum`, but a
> plain `str` + manual check keeps the existing error surface simple. Use an `Enum` if
> you prefer Typer's auto-validation — just confirm the message text isn't asserted.

### 3.2 The mode-gating helper (replaces per-command `dispatch` in `main`)

Factor the gating that `main()` did into one helper that every **mode-bound** command
calls first. It reuses the existing `session/` functions verbatim:

```python
def _require_mode(command: str) -> None:
    """Detect/resolve mode and gate `command`; print + exit on failure (parity with old main)."""
    session = _detect_and_report(mode_override=_MODE_OVERRIDE)   # exits on unknown mode
    result = dispatch(command, session)
    if result == SessionStatus.command_failed:
        session.advance(SessionStatus.command_failed)
        if session.mode and command in COMMAND_MODE_MAP:
            _print_out_of_mode_error(command, session)   # exits 1
        else:
            _print_unknown_command_error(command)         # exits 1
    session.advance(SessionStatus.command_running)
```

- **Bootstrap** commands (`new`, `adopt`, `templatize`) and **`doctor`** do **not** call
  `_require_mode` — they run anywhere, matching today's `BOOTSTRAP_COMMANDS` bypass.
- `_detect_and_report`, `dispatch`, `_print_out_of_mode_error`,
  `_print_unknown_command_error`, `COMMAND_MODE_MAP`, `SessionStatus` are all reused
  unchanged.

> **Unknown-command note:** with Typer, an *unregistered* command is rejected by Typer
> itself (Click) with its own message and **exit 2**, before `_require_mode` runs. The
> old custom "Unknown command" message (exit 1) only remains reachable for commands
> that are registered but absent from `COMMAND_MODE_MAP` — i.e. effectively dead now.
> Confirm no integration test asserts the old unknown-command text via `python -m
> copyroom <garbage>`; if one does, update it to Typer's behaviour (exit 2). This is the
> one intended behavioural change — call it out in the PR.

### 3.3 The bridge: Typer command → existing `_cmd_*`

To honour invariant #1 (keep `_cmd_*(args)` callable with an attribute-bag), each Typer
command builds a `SimpleNamespace` and delegates. Example for the two trickiest cases —
the `--from` reserved word and a hyphenated name:

```python
@app.command("template-test")
def _typer_template_test(
    from_ref: str | None = typer.Option(None, "--from", help="Base ref for the edit branch"),
    check: str | None = typer.Option(None, "--check", help="Shell command to run against the render"),
) -> None:
    _require_mode("template-test")
    _cmd_template_test(SimpleNamespace(from_ref=from_ref, check=check))
```

```python
@app.command("new")
def _typer_new(
    source: str = typer.Argument(..., help="Template source (local path or git URL)"),
    target: str = typer.Argument(".", help="Target directory"),
    answers_file: str | None = typer.Option(None, "--answers", help="Path to YAML answers file"),
    trust: bool = typer.Option(False, "--trust", help="Execute the template's post-create hooks"),
) -> None:
    # bootstrap: no _require_mode
    _cmd_new(SimpleNamespace(source=source, target=target, answers_file=answers_file, trust=trust))
```

The `SimpleNamespace` attribute names must match exactly what each `_cmd_*` reads (see
the argparse `dest=`/attribute usage in the current handlers). Crib sheet:

| Command | `_cmd_*` reads | Typer params (name → attr) |
|---|---|---|
| `new` | `source, target, answers_file, trust` | arg `source`; arg `target="."`; `--answers`→`answers_file`; `--trust` |
| `update` | `target_ref, branch, trust` | arg `target_ref=None`; `--branch`; `--trust` |
| `inspect` | `json` | `--json`→`json` (use param name `json_`, attr `json`) |
| `status` | `json` | `--json`→`json` |
| `template-checkout` | `from_ref` | `--from`→`from_ref` |
| `template-test` | `from_ref, check` | `--from`→`from_ref`; `--check` |
| `template-preview` | `from_ref` | `--from`→`from_ref` |
| `template-discard` | _(none)_ | — |
| `templatize` | `into, name, id` | `--into`; `--name`; `--id`→`id` |
| `adopt` | `template, ref, answers_file, write, force` | arg `template`; `--ref`; `--answers`→`answers_file`; `--write`; `--force` |
| `render`/`test` | `template_id, scenario_id` | two args |
| `golden` | `template_id, scenario_id, refresh` | two args; `--refresh` |
| `release-check` | `template_id` | one arg |
| `update-test` | `template_id, scenario_id, old_version, new_version` | four args |

> `--json` collides with Python's nothing-in-particular, but the attr the handler reads
> is `args.json`. Name the Typer param `json_output: bool = typer.Option(False, "--json")`
> and pass `SimpleNamespace(json=json_output)`.

### 3.4 The `registry` sub-command

Today `registry` is one command with a positional `action` (`list/show/validate/add`)
plus `args` and `--source/--scaffold`, all handled in `_cmd_registry`. Two options:

- **(Recommended) Typer sub-app** — cleaner and idiomatic, same surface:
  ```python
  registry_app = typer.Typer(help="Inspect the template registry (list/show/validate/add)")
  app.add_typer(registry_app, name="registry")

  @registry_app.command("list")
  def _registry_list() -> None:
      _require_mode("registry"); _cmd_registry(SimpleNamespace(action="list", args=[], source=None, scaffold=False))

  @registry_app.command("show")
  def _registry_show(template_id: str = typer.Argument(...)) -> None:
      _require_mode("registry"); _cmd_registry(SimpleNamespace(action="show", args=[template_id], source=None, scaffold=False))

  @registry_app.command("validate")
  def _registry_validate() -> None:
      _require_mode("registry"); _cmd_registry(SimpleNamespace(action="validate", args=[], source=None, scaffold=False))

  @registry_app.command("add")
  def _registry_add(
      template_id: str = typer.Argument(...),
      source: str = typer.Option(..., "--source", help="Template source (path or URL)"),
      scaffold: bool = typer.Option(False, "--scaffold"),
  ) -> None:
      _require_mode("registry"); _cmd_registry(SimpleNamespace(action="add", args=[template_id], source=source, scaffold=scaffold))
  ```
  Keeps `copyroom registry list|show <id>|validate|add <id> --source ...` identical.
  `_cmd_registry` is reused unchanged (its internal usage-error branches become
  belt-and-suspenders, since Typer now enforces the required args).

- **(Minimal) keep one command** — replicate the positional `action` + variadic `args`
  with `typer.Argument`. More faithful to the old error messages but uglier. Only choose
  this if a test asserts the old `Usage: copyroom registry show <template_id>` string —
  check `tests/integration/test_cli.py` / `test_registry.py`.

### 3.5 New `main()`

```python
def main(argv: Sequence[str] | None = None) -> None:
    app(args=argv)   # Typer/Click reads sys.argv when argv is None
```

Keep the `Sequence[str] | None` signature so any caller passing `argv` still works.

---

## 4. Deliverable B — `copyroom doctor`

### 4.1 New module `src/copyroom/doctor.py`

Environment-only checks (no managed project required), Pydantic-modelled to match the
family style (testee/gitman):

```python
from __future__ import annotations
import os, shutil, subprocess, tempfile
from importlib.metadata import version as _pkg_version
from pathlib import Path
from pydantic import BaseModel

from .template.workspace import _cache_root   # reuse the real resolver

class DoctorCheck(BaseModel):
    name: str
    ok: bool
    detail: str = ""

class DoctorReport(BaseModel):
    checks: list[DoctorCheck]
    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)
    def to_dict(self) -> dict:
        return self.model_dump()

def _check_copier() -> DoctorCheck:
    try:
        import copier  # noqa: F401
        v = _pkg_version("copier")
    except Exception as exc:  # ImportError or metadata missing
        return DoctorCheck(name="copier", ok=False, detail=f"not importable: {exc}")
    # pyproject pins copier>=9.15.1,<10
    major = int(v.split(".")[0])
    ok = 9 <= major < 10
    return DoctorCheck(name="copier", ok=ok, detail=f"{v}" + ("" if ok else " (need >=9.15,<10)"))

def _check_git() -> DoctorCheck:
    if shutil.which("git") is None:
        return DoctorCheck(name="git", ok=False, detail="not found on PATH")
    try:
        out = subprocess.run(["git", "--version"], capture_output=True, text=True, timeout=5)
        return DoctorCheck(name="git", ok=out.returncode == 0, detail=out.stdout.strip())
    except Exception as exc:
        return DoctorCheck(name="git", ok=False, detail=str(exc))

def _check_cache() -> DoctorCheck:
    root = _cache_root()
    try:
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=root, delete=True):
            pass
        return DoctorCheck(name="cache", ok=True, detail=str(root))
    except Exception as exc:
        return DoctorCheck(name="cache", ok=False, detail=f"{root}: {exc}")

def run_doctor() -> DoctorReport:
    return DoctorReport(checks=[_check_copier(), _check_git(), _check_cache()])

def format_doctor_report(report: DoctorReport) -> str:
    lines = []
    for c in report.checks:
        mark = "OK  " if c.ok else "✗   "
        lines.append(f"{mark}{c.name}" + (f" — {c.detail}" if c.detail else ""))
    return "\n".join(lines)
```

> The cache check reuses `template/workspace.py:_cache_root()` (honours
> `COPYROOM_CACHE_DIR` / `XDG_CACHE_HOME`), so doctor and the real cache agree. If you'd
> rather not import a `_underscore` name across modules, promote `_cache_root` to a
> public `cache_root` in a small follow-up and have both call it.

### 4.2 The CLI command (in `cli.py`)

```python
@app.command("doctor")
def _typer_doctor(
    json_output: bool = typer.Option(False, "--json", help="Emit the report as JSON"),
) -> None:
    """Check the CopyRoom environment (Copier, git, cache). Runs anywhere."""
    from .doctor import run_doctor, format_doctor_report
    report = run_doctor()
    if json_output:
        import json
        typer.echo(json.dumps(report.to_dict(), indent=2))
    else:
        typer.echo(format_doctor_report(report))
    raise typer.Exit(code=0 if report.ok else 2)   # 0 ok · 2 infra/config
```

- **No `_require_mode`** — doctor is a precondition check, valid in a bare repo (this is
  the whole reason RepoMan wants it).
- Exit policy: `0` healthy · `2` any failed check (infra/config). This is the family
  `0/1/2/3` contract; doctor never returns `1` (no domain decision) or `3` (Typer
  handles arg-usage errors with its own exit).

---

## 5. Testing plan

1. **Baseline:** `devenv shell -- pytest` green before changes.
2. **Keep green via the bridge:** `tests/unit/test_cli_messages.py` keeps calling
   `_cmd_*` directly — untouched. `test_dispatcher.py` / `test_mode_detection.py`
   untouched.
3. **Integration parity:** re-run `tests/integration/test_cli.py`. Watch for:
   - exit-code deltas (Typer/Click uses `2` for usage errors where argparse used `2`
     too — usually fine; the risk is the *unknown-command* path now exit `2` not `1`).
   - help/`--version` output: `copyroom --version` must still print `copyroom X.Y.Z`.
   Update only the tests that assert the intentionally-changed unknown-command behaviour.
4. **New tests** — `tests/unit/test_doctor.py`:
   - `run_doctor()` all-ok in a healthy env → `report.ok is True`.
   - monkeypatch `shutil.which` → `None` ⇒ git check fails, `report.ok is False`.
   - monkeypatch `_cache_root` to an unwritable path ⇒ cache check fails.
   - format string contains `OK`/`✗`.
   And an integration check: `python -m copyroom doctor` in `tmp_path` exits `0`
   (env is healthy in devenv) and `--json` parses to the expected keys.
5. **Smoke (manual, in devenv):**
   ```bash
   devenv shell -- copyroom --help        # lists doctor + all commands
   devenv shell -- copyroom doctor
   devenv shell -- copyroom doctor --json
   devenv shell -- copyroom --version
   devenv shell -- copyroom status        # still errors cleanly outside a project
   ```

---

## 6. Phased execution (each phase ends green)

- **Phase 0 — setup.** Branch in `copyroom` (`git checkout -b typer-cli-and-doctor`).
  Add `typer` dep; `uv sync`; baseline `pytest`.
- **Phase 1 — frontend swap.** Add the Typer `app`, callback, `_require_mode`, and one
  command (`status`) end-to-end; confirm `python -m copyroom status` works. Then migrate
  the rest using the §3.3 crib sheet. Delete `_build_parser` and the old `main` body;
  keep `COMMAND_FN`/`_cmd_*`/`COPYROOM_DESCRIPTION`/error formatters. `pytest`.
- **Phase 2 — registry sub-app** (§3.4). `pytest`.
- **Phase 3 — doctor** (§4): module + command + tests. `pytest`.
- **Phase 4 — docs.** Update `docs/user/cli-reference.md` (add `doctor`, note the
  framework is Typer); mention `doctor` in `README.md`. The Allium spec
  `.scratch/specs/copyroom.allium` may warrant a `doctor` note (optional).
- **Phase 5 — version + changelog.** Bump `src/copyroom/__init__.py` `__version__` to
  `0.5.0`; note the CLI migration + `doctor` in the changelog/REFACTORING history.
- **Phase 6 — verify.** Full `pytest` + the §5.5 smoke list.

---

## 7. Follow-up in the `repoman` repo (separate, after this ships)

Once `copyroom doctor` exists and a tagged release is available:

1. `src/repoman/registry.py` → change the `copy` entry from `doctor=None` back to the
   default `doctor=["doctor"]` (drop the `doctor=None` line + its comment).
2. Re-run the spike: `tests/consumer-example` → `repoman doctor` should now run
   `copyroom doctor` and aggregate its exit code alongside testee's.
3. Update `repoman/SPIKE.md`'s "managers don't all implement every verb" note to record
   that copyroom now conforms (keep the general principle — the conductor stays tolerant).

---

## 8. Risks & rollback

| Risk | Mitigation |
|---|---|
| Unknown-command exit code changes `1`→`2` (Typer) | Intended; update the asserting test, call out in PR. |
| `--from` is a Python keyword | Use `from_ref: ... = typer.Option(None, "--from")` (shown in §3.3). |
| `_cmd_*` attr mismatch in `SimpleNamespace` | Use the §3.3 crib sheet; the `_cmd_*` bodies are unchanged so attrs are fixed. |
| argparse `nargs="?"` defaults (`target="."`, `target_ref=None`) | Replicate with `typer.Argument` defaults. |
| Rich coloring leaking into `--json` | `--json` paths use plain `json.dumps`; never Rich. |
| `registry` usage-message tests | Prefer the sub-app; if a message is asserted, keep the single-command form (§3.4 minimal). |
| Importing `_cache_root` across modules | Acceptable now; optional public `cache_root` follow-up. |

Rollback is a single-branch revert — no data migrations, no changes outside `cli.py`,
the new `doctor.py`, tests, and `pyproject.toml`/`__init__.py`.
