# CopyRoom Refactoring Guide

A step-by-step plan to fix every issue from the code review. Work the phases
**in order** — later fixes depend on the shared helpers introduced early, and
the test harness in Phase 0 is what proves the critical fixes actually work.

Conventions used below:
- `path:line` anchors are clickable and reflect the code at review time.
- After **every** phase run the gate: `uv run ruff check src/ && uv run pytest -q`.
- Don't add AI-attribution trailers to commits.

---

## Phase 0 — Baseline & safety net (do first)

The critical bugs (#1, #2, #3) all live in workflow functions that the current
suite never calls. Build the net before swinging.

### 0.1 Make ruff green and wire it into the gate
```bash
uv run ruff check --fix src/        # fixes the 7 import-sort/F401 issues
uv run ruff check src/              # see the remaining 2
```
Remaining after `--fix`:
- `release/check.py:308` — `F841` unused `status`. The last two `status = …`
  assignments in `run_release_check` are dead; delete the `status =` prefix
  (keep the calls: `evaluate(check)` / `resolve(check)`).
- `edits.py:360` — `B007` loop var `i` unused: rename to `_i` (the index is not
  used after the loop). Note: `_validate_edits` *does* use `i` for messages;
  this is the `_set_nested_value` loop — confirm which one ruff flags and rename
  only there.

Also remove the now-unused `import textwrap` (`edits.py:26`) if `--fix` didn't.

### 0.2 Create an integration fixture + harness
This is the highest-leverage change in the whole guide. Add a tiny real Copier
template and a workshop layout under `tests/integration/fixtures/`.

```
tests/integration/
  __init__.py
  conftest.py                     # fixtures below
  fixtures/
    template/                     # a minimal Copier template (git repo, tagged)
      copier.yml                  # one question, e.g. project_name
      {{project_name}}/README.md.jinja
    workshop/
      copyroom.yml                # registry mapping template_id -> template path
      registry/                   # (dir marker)
      scenarios/
        demo/
          basic.yml               # answers: {project_name: demo}
```

`conftest.py` essentials:
```python
import subprocess, shutil
from pathlib import Path
import pytest

@pytest.fixture
def template_repo(tmp_path):
    """Copy the fixture template into a tmp git repo with a v1 tag."""
    src = Path(__file__).parent / "fixtures" / "template"
    dst = tmp_path / "template"
    shutil.copytree(src, dst)
    subprocess.run(["git", "init", "-q"], cwd=dst, check=True)
    subprocess.run(["git", "add", "-A"], cwd=dst, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "v1"], cwd=dst, check=True)
    subprocess.run(["git", "tag", "v1.0.0"], cwd=dst, check=True)
    return dst

@pytest.fixture
def workshop(tmp_path, template_repo):
    """A workshop dir whose copyroom.yml points template 'demo' at template_repo."""
    ws = tmp_path / "workshop"
    shutil.copytree(Path(__file__).parent / "fixtures" / "workshop", ws)
    (ws / "copyroom.yml").write_text(
        f"templates:\n  demo:\n    source: {template_repo}\n"
    )
    return ws
```

These two fixtures unblock real assertions in Phase 2/6. Don't proceed to the
command fixes until `render_scenario(...)` can be called against `workshop`.

**Gate:** `uv run pytest -q` (still green; integration dir may be empty of tests yet).

---

## Phase 1 — Shared foundation (kills the duplication that fixes #4 would otherwise multiply)

Four near-identical `_resolve_template_source` copies and two `_load_checks*`
copies exist (`render.py`, `golden.py`, `simulate.py`, `release/check.py`). Fix
#4 touches all of these, so consolidate **before** editing them four times.

### 1.1 One `CopyRoomError`
Create `src/copyroom/_compat/errors.py`:
```python
from __future__ import annotations

class CopyRoomError(Exception):
    """Base error with structured message (§10.3)."""
    def __init__(self, message: str, state: str | None = None) -> None:
        self.message = message
        self.state = state
        super().__init__(self._format())

    def _format(self) -> str:
        parts = [f"Error: {self.message}"]
        if self.state:
            parts.append(f"State left: {self.state}")
        return "\n".join(parts)
```
Then in each of `project/create.py`, `project/update.py`, `workshop/render.py`,
`workshop/golden.py`, `workshop/simulate.py`, `release/check.py`: delete the
local class and add `from .._compat.errors import CopyRoomError`
(`from ..` depth as appropriate). The `cli.py` imports that alias each module's
`CopyRoomError` (e.g. `CreateError`, `RenderError`) keep working unchanged
because the name is still re-exported from each module.

### 1.2 One registry/checks helper
Create `src/copyroom/workshop/registry.py`:
```python
from __future__ import annotations
from pathlib import Path
import yaml

def _load_yaml(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
    except (yaml.YAMLError, OSError):
        return None
    return data if isinstance(data, dict) else None

def resolve_template_source(workshop_root: Path, template_id: str) -> str | None:
    cfg = _load_yaml(workshop_root / "copyroom.yml")
    if cfg:
        templates = cfg.get("templates", cfg.get("registry")) or {}
        if isinstance(templates, dict):
            src = templates.get(template_id)
            if isinstance(src, str):
                return src
            if isinstance(src, dict):
                return src.get("source", src.get("url"))
    tpl = _load_yaml(workshop_root / "registry" / f"{template_id}.yml")
    if tpl:
        src = tpl.get("source", tpl.get("url"))
        if isinstance(src, str):
            return src
    return None

def load_checks(workshop_root: Path, template_id: str) -> list[str]:
    for cfg, getter in (
        (_load_yaml(workshop_root / "copyroom.yml"),
         lambda c: (c.get("templates") or {}).get(template_id)),
        (_load_yaml(workshop_root / "registry" / f"{template_id}.yml"),
         lambda c: c),
    ):
        if not cfg:
            continue
        tpl = getter(cfg)
        if isinstance(tpl, dict):
            raw = tpl.get("checks", [])
            if isinstance(raw, list):
                return [str(c) for c in raw]
    return []
```
Replace the four `_resolve_template_source` bodies and the two `_load_checks*`
bodies with imports of these. Delete the dead local copies (and the stray
`import yaml as _yaml` inside `golden.py:298`).

**Gate:** `uv run ruff check src/ && uv run pytest -q`. (Tests should still pass —
these are internal helpers; `test_release.py`/`test_workshop.py` don't import them
directly. If any do, update the import path.)

---

## Phase 2 — Critical command fixes

### 2.1 (#1) `golden --refresh` crashes with `TypeError`
**Cause:** `cli.py:259` passes `workshop_root=None`; `refresh_golden`
(`golden.py:190`) requires a `Path` and immediately does `None / "generated"`.

**Fix** — give it the same default + cwd fallback as its siblings:
```python
# golden.py
def refresh_golden(
    template_id: str,
    scenario_id: str,
    workshop_root: Path | None = None,
) -> None:
    if workshop_root is None:
        workshop_root = Path.cwd()   # (replaced in 3.1 with detect_workshop_root)
    ...
```
**Note:** `refresh_golden` requires `generated/<t>/<s>/` to already exist (it
copies it to `golden/`). That's by design (you render, eyeball, then refresh) —
keep the existing `CopyRoomError` that tells the user to run `render` first
(`golden.py:204`). Just make sure it's *that* error and not a `TypeError`.

**Test (integration):**
```python
def test_golden_refresh_creates_snapshot(workshop):
    from copyroom.workshop.render import render_scenario
    from copyroom.workshop.golden import refresh_golden, golden_diff
    from copyroom.workshop.model import GoldenStatus
    render_scenario("demo", "basic", workshop_root=workshop)
    refresh_golden("demo", "basic", workshop_root=workshop)        # was TypeError
    assert (workshop / "golden" / "demo" / "basic").is_dir()
    assert golden_diff("demo", "basic", workshop_root=workshop).status == GoldenStatus.no_diffs
```

### 2.2 (#2) `update-test` crashes (no edits) and never applies the update
**Two bugs, one path.** When `scenarios/<t>/<s>-edits.yml` is absent:
1. `apply_user_edits` (`simulate.py:179`) does `old_rendered → update_applied`,
   which is not a legal transition → uncaught `InvalidTransitionError`.
2. Even if it were legal, `run_update_simulation` (`simulate.py:398`) only calls
   `apply_update` when `status == user_edited`, so the actual `copier update`
   would be skipped.

**Spec-faithful fix** (`copyroom-workshop.allium:80-87` has *no*
`old_rendered → update_applied` edge; reaching `old_rendered` always advances to
`user_edited`). Treat "no edits file" as **zero edits applied**, still passing
through `user_edited`. No model/spec/test changes needed.

In `simulate.py` `apply_user_edits` (the no-edits branch ~L177-183):
```python
    if not edits_path.is_file():
        # No edits file: user made zero edits, but the edit step still ran.
        # Spec: old_rendered -> user_edited (never old_rendered -> update_applied).
        sim.status = _sim_sm.transition(SimStatus.old_rendered, SimStatus.user_edited)
        return sim.status
```

In `run_update_simulation` (`simulate.py:393-402`), remove the conditional so the
update **always** runs after the edit step:
```python
    # 3. ApplyUserEdits (always advances to user_edited, even with zero edits)
    status = apply_user_edits(sim, workshop_root)
    if status == SimStatus.failed:
        return sim

    # 4. ApplyUpdate (always runs)
    status = apply_update(sim, workshop_root)
    if status == SimStatus.failed:
        return sim
```
`apply_update` uses `from_state = sim.status` (`simulate.py:218`) which is now
always `user_edited` → `update_applied` (legal). Leave it as-is.

**Tests (integration):** cover both paths.
```python
def test_update_test_without_edits_runs_update(workshop, template_repo):
    # tag a v2 on the template first (add a file, commit, tag v2.0.0)
    from copyroom.workshop.simulate import run_update_simulation
    from copyroom.workshop.model import SimStatus
    sim = run_update_simulation("demo", "basic", "v1.0.0", "v2.0.0",
                                workshop_root=workshop)
    assert sim.status == SimStatus.complete          # no longer raises
    assert sim.result is not None                    # update actually ran
```
Add a second test with a `basic-edits.yml` present to cover the `user_edited`
branch with real edits.

### 2.3 (#3) `--no-detect` makes every command unrunnable
**Cause:** `_detect_and_report` returns a session still in `mode_detecting`
(`cli.py:99-100`); `dispatch` rejects anything not in `mode_detected`
(`dispatcher.py:41`), so all commands fall through to "Unknown command".

**Decide the intended semantics, then implement one:**

- **Option A (recommended): replace `--no-detect` with `--mode {workshop,project}`.**
  An explicit override is genuinely useful (CI, ambiguous dirs) and removes a
  flag that can only ever fail.
  ```python
  # _build_parser
  parser.add_argument("--mode", choices=["workshop", "project"], default=None,
                      help="Force a mode instead of auto-detecting")
  # _detect_and_report(mode_override: str | None)
  if mode_override is not None:
      session.mode = CLIMode(mode_override)
      session.status = SessionStatus.mode_detected
      return session
  ```
  Update `main` to pass `args.mode`. Update the demo and any help text.

- **Option B (minimal): keep `--no-detect` but make it advance state.** On
  `--no-detect`, set `session.status = SessionStatus.mode_detected` and infer the
  mode from the command via `COMMAND_MODE_MAP[cmd]` so dispatch passes:
  ```python
  if no_detect:
      session.status = SessionStatus.mode_detected
      session.mode = COMMAND_MODE_MAP.get(command)   # requires passing command in
      return session
  ```
  This needs `_detect_and_report` to know the command (reorder so detection runs
  after `args.command` is known, which it already is at the call site).

Pick A unless you have a reason to preserve the flag name. **Test:** assert a
valid command reaches its handler under the override (e.g. `--mode workshop render`
gets to the registry lookup, not "Unknown command").

**Gate after Phase 2:** `uv run ruff check src/ && uv run pytest -q` — all green,
with the three new integration tests passing.

---

## Phase 3 — Architectural fixes

### 3.1 (#4) Workshop commands only work from the exact root
`render`, `test`, `golden` (+`--refresh`), `update-test` default
`workshop_root` to `Path.cwd()`; `release-check` correctly uses
`detect_workshop_root()`. From a workshop *subdirectory* the command dispatches
(mode detection walks ancestors) but then can't find `scenarios/`/`registry/`.

**Fix:** make the default resolve the root, in every workshop entry point.
Replace each `if workshop_root is None: workshop_root = Path.cwd()` in
`render_scenario` (`render.py:286`), `golden_diff` (`golden.py:237`),
`refresh_golden` (added in 2.1), and `run_update_simulation` (`simulate.py:367`)
with:
```python
    if workshop_root is None:
        workshop_root = detect_workshop_root()
        if workshop_root is None:
            raise CopyRoomError(
                "No CopyRoom workshop found here. Run this from a workshop "
                "directory or any descendant.",
                state="not_started",
            )
```
Add `from ..session.detector import detect_workshop_root` to each module. This
mirrors `release/check.py:271` exactly — consider lifting the
"resolve-or-raise" into a small `_require_workshop_root()` helper in
`workshop/registry.py` to avoid the fourth copy.

**Test:** call `render_scenario("demo","basic")` with `cwd` set to
`workshop/scenarios/demo` (use `monkeypatch.chdir`) and assert it succeeds.

### 3.2 (#5) `release-check` reports `Worktree: DIRTY` because it created the output
`run_matrix` renders into `<workshop>/generated/...` and then runs
`git status --porcelain` (`check.py:198`) — the freshly written render output
makes the tree dirty unless `generated/` is gitignored.

**Fix (do both):**
1. **Order:** capture the worktree state **before** any rendering. Move the
   `check.worktree_clean = _check_worktree_clean(workshop_root)` call to the top
   of `run_matrix` (before scenario discovery/rendering).
2. **Scope:** make `_check_worktree_clean` ignore CopyRoom's own scratch output
   so re-runs are stable. Use a pathspec exclude:
   ```python
   result = subprocess.run(
       ["git", "status", "--porcelain", "--",
        ".", ":(exclude)generated", ":(exclude).copyroom_sim"],
       cwd=str(repo_root), capture_output=True, text=True, timeout=30,
   )
   ```
   Also document (README + a generated `.gitignore` entry, or a note in
   `copyroom.yml` docs) that `generated/` and `.copyroom_sim/` should be
   gitignored in a workshop.

**Test:** in a git-initialised workshop with a committed clean tree, run
`run_release_check("demo")` and assert `check.worktree_clean is True` after a
render has happened.

**Gate after Phase 3:** full suite + the new subdir/worktree tests green.

---

## Phase 4 — Medium correctness & robustness

### 4.1 Enforce the session lifecycle (or stop pretending to)
`VALID_SESSION_TRANSITIONS` (`session/model.py:37`) is never used; `cli.py`
assigns `session.status` by hand (`cli.py:489,493`). Two acceptable resolutions:
- **Enforce:** instantiate a `StateMachine(VALID_SESSION_TRANSITIONS, "CLISession")`
  and route the `command_running`/`command_complete`/`command_failed`
  assignments through `.transition(...)`, matching the other entities.
- **Demote:** if the session truly isn't a guarded lifecycle, delete the table
  and the `mode_detecting` ceremony to avoid implying a guarantee.
Prefer enforcing for consistency with the rest of the architecture.

### 4.2 Delete the duplicate `InvalidTransitionError`
`session/model.py:75` defines a second `InvalidTransitionError` with a *different*
constructor `(status, target)` than the real one in `state_machine.py:14`
`(entity_name, from, to)`. It's never raised. Delete the `session/model.py`
copy; if anything imports it, repoint to `_compat.state_machine`.

### 4.3 Make the shell-execution trust model explicit
`post_project_create` / `post_template_update` / registry `checks` run with
`shell=True` from template- or workshop-controlled YAML (`create.py:300`,
`update.py:431`, `render.py:209`, `simulate.py:291`). A fetched template can thus
execute arbitrary code.
- At minimum: document this in the README and **delete** the misleading
  "no remote execution" claim from `demo/__init__.py:195`.
- Recommended: gate command execution behind an explicit opt-in
  (`--trust` flag / `COPYROOM_TRUST=1`), defaulting to **skip + warn**:
  ```python
  if not trust:
      print(f"Skipping post-create command (use --trust to run): {cmd}", file=sys.stderr)
      continue
  ```
  Thread `trust` from the CLI down through `create_project` / `update_project` /
  `render_scenario` / `run_update_simulation`.

### 4.4 Add timeouts to the Copier subprocess calls
`copier_copy`/`copier_update` (`_compat/copier.py:34,54`) have no `timeout`,
unlike every other `subprocess.run` here. Add `timeout=300` (copier can be
slow on first clone) and handle `subprocess.TimeoutExpired` at the call sites
(`execute_copy`, `execute_render`, `execute_update`, `render_old_version`,
`apply_update`) by transitioning to `failed` with a clear message.

### 4.5 Stop double-counting rejects/conflicts in `update`
`update.py` records `.rej` files both via the regex in
`_capture_conflicts_from_output` (`update.py:556`, into `conflicts`) and via
`rglob` in `capture_conflicts` (`update.py:373`, into `rejects`). Decide one
home: keep filesystem `.rej` scanning → `rejects`, and restrict
`_capture_conflicts_from_output` to genuine conflict-marker lines only (drop the
`".rej" in line` clause at `update.py:552` and the `\.rej` regex at L556).

### 4.6 Friendlier bare `copyroom update`
`resolve_latest_ref` is a stub that routes a missing ref straight to `failed`
(`update.py:117`), so bare `copyroom update` dies with a generic
"Update failed at state: failed". Special-case it in `_cmd_update`/`update_project`
to print: *"Auto-resolving the latest version isn't supported yet; pass an
explicit ref: `copyroom update <tag>`."*

### 4.7 Drop the redundant answers read
`initiate` reads `.copier-answers.yml` (`update.py:82`) and `load_config` reads
the same file again (`update.py:151`) to set the same two fields. Have `initiate`
not parse it (just construct the entity) and let `load_config` be the single
reader, or have `load_config` reuse the values `initiate` already set.

**Gate after Phase 4:** full suite green; add a unit test for 4.5 (one `.rej`
appears in exactly one set) and 4.3 (skip-without-trust).

---

## Phase 5 — Hygiene / low

- **5.1** Remove dead `check_copier_version()` (`_compat/copier.py:57`) — defined,
  never called. (Or wire it into a real preflight if you want the version gate.)
- **5.2** Replace the hard-coded `"Tests: 326 all passing"` in
  `demo/__init__.py:197` with a computed count or drop the literal.
- **5.3** Add a one-line comment at `detector.py:63` noting that within a single
  directory `is_workshop` wins over `is_project` (proximity holds *across* levels,
  type-priority breaks ties *within* a level).
- **5.4** Confirm ruff is clean and consider adding it to the devenv test task /
  pre-commit so it stays clean.

---

## Phase 6 — Lock it in with workflow tests

The root cause of #1/#2/#4 is that the suite tested models, not workflows. Add an
`tests/integration/test_workflows.py` that drives the **public entry points**
end-to-end against the Phase 0 fixture:

- `render_scenario` → `complete`, output exists, runs configured checks.
- `golden_diff` → `no_diffs` after `refresh_golden`; `has_diffs` after mutating
  the template.
- `refresh_golden` happy path + the "render first" error (regression for #1).
- `run_update_simulation` v1→v2 **with and without** an edits file (regression
  for #2); assert `apply_update` actually ran (e.g. a v2-only file is present).
- `run_release_check` on a clean committed workshop → `passed`; worktree stays
  clean across re-runs (regression for #5).
- Each workshop command from a **subdirectory** via `monkeypatch.chdir`
  (regression for #4).
- `main(["--mode","workshop","render","demo","basic"])` reaches the handler
  (regression for #3).

Target: every bug above has at least one test that **fails before** the fix and
**passes after**. Write the test first where practical.

---

## Final verification checklist

```bash
uv run ruff check src/                 # 0 errors
uv run pytest -q                       # all green, incl. new integration tests
uv run pytest --cov=copyroom --cov-report=term-missing   # workflow fns now covered
uv run demo                            # end-to-end smoke (fix the 326 literal first)
```

Manual smoke (in a throwaway workshop dir with a tagged template):
```bash
copyroom render demo basic
copyroom golden demo basic
copyroom golden --refresh demo basic   # was TypeError (#1)
copyroom update-test demo basic v1.0.0 v2.0.0   # was crash/no-op (#2)
cd scenarios/demo && copyroom render demo basic # was "not in registry" (#4)
copyroom --mode workshop render demo basic      # was "Unknown command" (#3)
copyroom release-check demo                      # Worktree: CLEAN on re-run (#5)
```

## Suggested commit sequence
1. `chore: ruff clean + integration fixture/harness` (Phase 0)
2. `refactor: shared CopyRoomError + registry helpers` (Phase 1)
3. `fix: golden --refresh crash on default workshop root` (#1)
4. `fix: update-test runs update and survives missing edits file` (#2)
5. `fix: make --mode override usable (replaces broken --no-detect)` (#3)
6. `fix: resolve workshop root from any descendant` (#4)
7. `fix: release-check worktree check ignores generated output` (#5)
8. `refactor: enforce session lifecycle; dedupe InvalidTransitionError` (4.1/4.2)
9. `feat: gate post-hook shell execution behind --trust` (4.3)
10. `fix: copier subprocess timeouts; reject double-count; update UX` (4.4–4.7)
11. `chore: remove dead code, fix demo literal, comments` (Phase 5)
12. `test: end-to-end workflow coverage` (Phase 6)
