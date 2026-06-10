# CopyRoom Deep-Review — Refactoring Guide

Companion to `CODE_REVIEW_REPORT.md`. The ordered plan to remediate every finding from the
deep review. Written to be executed top-to-bottom: shared primitives first (they unblock
several fixes), then the two P1 behavior fixes, then the P2 correctness work, then the P3
cleanups, then docs/specs/tests/verification.

> **Conventions (non-negotiable — same as the rest of the repo).**
> - Run everything via `devenv shell --` (pins Python 3.13). Never ambient `uv`/`python`.
> - Gate green **before and after every change**: `uv run ruff check src/ tests/` and
>   `uv run pytest -q`.
> - Workflows are guarded state machines: transition only via `StateMachine.transition`,
>   never assign `entity.status =` ad-hoc. Pure reads may return a result dataclass.
> - All subprocess/git/copier work goes through `_compat/`. Git helpers fail soft
>   (`None`/`False`) on a missing binary.
> - One error type: `CopyRoomError` (re-exported per module). Report-and-exit; forward the
>   tool's stderr; never auto-roll-back.
> - Config evolution stays **additive**: new fields default; unknown fields tolerated.
> - Keep `.scratch/specs/*.allium` and `docs/` accurate for any behavior change.
> - **No AI-attribution trailers** anywhere (commits, PRs, code, docs).

**Branch & version.** Work on a child branch off `feat/v0.3.0` (e.g.
`feat/deep-review-remediation`). P1-1, P1-2 and the new `template-discard` command change
observable CLI behavior, so this is a **minor bump to `0.4.0`** (maintainer's call — note it
in `pyproject.toml` + `__init__.py` as the final step, not mid-stream).

---

## Phase 0 — Baseline

```
devenv shell -- uv run ruff check src/ tests/
devenv shell -- uv run pytest -q            # expect 419 passing
devenv shell -- bash demo/walkthrough.sh    # exits 0
```

Read, in order: `CODE_REVIEW_REPORT.md` (this dir), then `docs/developer/architecture.md`,
`state-machines.md`, `compat-layer.md`, and the modules named below. **Add the regression
test for each finding first** (it should fail), then fix.

---

## Phase 1 — Shared primitives (do these first; they unblock §4, §6, §8)

### §1. `_compat` helpers the fixes will reuse

**a) Shared conflict/reject scanning** — new file `src/copyroom/_compat/conflicts.py`.
Lift the logic that currently lives only in `template/preview.py`:

```python
"""Detect merge conflicts left by `copier update`.

Copier's default (inline) conflict mode writes git-style <<<<<<< / >>>>>>> markers into
files rather than `.rej` siblings, so a clash shows up as marker text inside an
otherwise-modified file. `.rej` files are also collected for templates configured with the
reject strategy. Shared by project/update, template/preview, and workshop/simulate so all
three report conflicts identically (was: a fragile stdout grep in update.py — P2-1).
"""
from __future__ import annotations
from pathlib import Path

_CONFLICT_MARKERS = ("<<<<<<<", ">>>>>>>")

def scan_conflict_markers(root: Path, candidates: set[str]) -> set[str]:
    """Return the subset of *candidates* (repo-relative paths) that contain markers."""
    found: set[str] = set()
    for rel in candidates:
        try:
            text = (root / rel).read_text(errors="ignore")
        except OSError:
            continue
        if any(m in text for m in _CONFLICT_MARKERS):
            found.add(rel)
    return found

def scan_rejects(root: Path) -> set[str]:
    """Return all `*.rej` paths under *root* (repo-relative)."""
    return {str(p.relative_to(root)) for p in root.rglob("*.rej")}
```

Then make `template/preview.py` import `scan_conflict_markers`/`scan_rejects` instead of its
private `_scan_conflict_markers` + inline rglob, and `workshop/simulate.py:_capture_rejects`
use `scan_rejects`. (Behavior-preserving for those two; the win is `update.py` can now reuse
the same code in §4.)

**b) git branch + worktree helpers** — add to `src/copyroom/_compat/gitutil.py`:

```python
def checkout_new_branch(repo: Path, name: str) -> subprocess.CompletedProcess[str] | None:
    """`git checkout -b <name>` in *repo*. Returns the result (so callers can forward
    stderr) or None if git is unavailable."""
    return run_git("checkout", "-b", name, cwd=repo)

def commits_ahead(repo: Path, branch: str, base: str) -> int | None:
    """Number of commits on *branch* not on *base* (`git rev-list --count base..branch`),
    or None when undeterminable. Used to warn about a reused, non-empty edit branch."""
    result = run_git("rev-list", "--count", f"{base}..{branch}", cwd=repo)
    if result is None or result.returncode != 0:
        return None
    try:
        return int(result.stdout.strip())
    except ValueError:
        return None

def worktree_remove(repo: Path, worktree_dir: Path) -> bool:
    """`git worktree remove --force <dir>`. False on failure / missing git."""
    result = run_git("worktree", "remove", "--force", str(worktree_dir), cwd=repo)
    return result is not None and result.returncode == 0

def delete_branch(repo: Path, branch: str) -> bool:
    """`git branch -D <branch>`. False on failure / missing git."""
    result = run_git("branch", "-D", branch, cwd=repo)
    return result is not None and result.returncode == 0
```

**c) atomic write** (used by §13) — add to `src/copyroom/_compat/__init__.py` or a small
`_compat/fsutil.py`:

```python
import os, tempfile
from pathlib import Path

def atomic_write_text(path: Path, text: str) -> None:
    """Write *text* to *path* via a temp file + os.replace (no torn writes on crash)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)
```

---

## Phase 2 — P1 behavior fixes

### §2. P1-1: make `new` a bootstrap command (runs anywhere)

In `src/copyroom/session/model.py`:

- Remove `"new"` from `PROJECT_COMMANDS`.
- Add `"new"` to `BOOTSTRAP_COMMANDS` → `frozenset({"adopt", "templatize", "new"})`.

That's the whole behavioral change: `cli.main()` already runs `BOOTSTRAP_COMMANDS` before
mode detection (`cli.py:881`), so `copyroom new <src> <target>` now works in any directory.
`COMMAND_MODE_MAP` is derived from the command sets, so `new` correctly drops out of the
mode gate. The empty-target check in `project/create.verify_target` remains the real guard.

Follow-ups:
- `cli.py` `COPYROOM_DESCRIPTION`: move `new` under the "Bootstrap commands (no markers
  needed)" group, or annotate it "(runs anywhere)". Keep the usage line.
- `--mode project` passed to `new` is now a harmless no-op (bootstrap returns before
  detection) — existing tests stay green; **add** a test that `new` works *without* `--mode`.
- Spec: in `.scratch/specs/copyroom-session.allium`, move `new` from the project-dispatch
  rules to the bootstrap set (mirrors `adopt`/`templatize`).

> **Conservative alternative** (if you'd rather keep `new` grouped as a project command):
> in `_detect_and_report`, when `mode_override is None` and `detect_mode()` returns `None`
> *and* the command is `new`, default `session.mode = CLIMode.project` instead of exiting.
> Smaller blast radius, but it special-cases one command in the detector — the bootstrap
> move is cleaner and matches the existing concept.

### §3. P1-2: a no-op `update` is success, not failure

Add an `up_to_date` terminal state so the lifecycle can express "nothing to do."

In `src/copyroom/project/model.py`:

```python
class UpdateStatus(StrEnum):
    ...
    up_to_date = "up_to_date"   # new: no-op terminal (already at target version)
    ...

VALID_UPDATE_TRANSITIONS = {
    ...
    UpdateStatus.config_loaded: {
        UpdateStatus.worktree_verified,
        UpdateStatus.up_to_date,     # new edge
        UpdateStatus.failed,
    },
    ...
    UpdateStatus.up_to_date: set(),  # terminal
    ...
}
```

In `src/copyroom/project/update.py:no_update_available`: transition to `up_to_date` instead
of `failed`:

```python
if same_version(update.previous_ref, update.target_ref):
    update.status = _update_sm.transition(UpdateStatus.config_loaded, UpdateStatus.up_to_date)
    return update.status
```

In `update_project`, short-circuit on it:

```python
status = no_update_available(update)
if status in (UpdateStatus.up_to_date, UpdateStatus.failed):
    return update
```

In `src/copyroom/cli.py:_cmd_update`, handle the no-op as **exit 0** before the failure
block:

```python
if update.status == UpdateStatus.up_to_date:
    if update.resolved_latest:
        print(f"Already at the latest version ({update.target_ref}); nothing to update.")
    else:
        print(f"Already at version {update.target_ref}; nothing to update.")
    return   # exit 0
```

Then delete the now-dead "Already at…" branch inside the `== UpdateStatus.failed` block
(`cli.py:229-236`). Import `UpdateStatus` is already present.

Spec: add the `up_to_date` node + `config_loaded → up_to_date` edge to
`.scratch/specs/copyroom-project.allium` (note it is a success terminal).

---

## Phase 3 — P2 correctness

### §4. P2-1: unify conflict detection on the real `update` path

In `src/copyroom/project/update.py`:

- Delete `_capture_conflicts_from_output` and its call in `execute_update`.
- In `capture_conflicts`, after the `.rej` scan, derive the changed-file set from the
  post-update worktree (it was verified clean before the update, so the dirty files *are*
  the update's output) and scan them for markers:

```python
from .._compat.conflicts import scan_conflict_markers, scan_rejects
...
update.rejects.update(scan_rejects(update.project_root))
changed = {
    gitutil._porcelain_path(ln)
    for ln in (gitutil.worktree_status(update.project_root) or [])
}
update.conflicts.update(scan_conflict_markers(update.project_root, changed))
```

(If you prefer not to reach for the private `_porcelain_path`, promote it to a public
`gitutil.changed_paths(path) -> set[str]` helper and use that here and in preview.) Now
`update`, `preview`, and `simulate` all detect conflicts the same way.

### §5. P2-2: harden the edits DSL (and test it)

`src/copyroom/workshop/edits.py`:

1. **Patch failures are fatal, dependency is checked.** In `_apply_patch`, before running,
   guard the binary; on non-zero exit, raise instead of warn:
   ```python
   import shutil as _sh
   if _sh.which("patch") is None:
       raise EditsParseError("the 'patch' binary is required to apply a 'patch' edit but "
                             "was not found on PATH.")
   ...
   if result.returncode != 0:
       raise EditsParseError(f"patch failed for {file_path}: "
                             f"{result.stderr.strip() or 'no output'}")
   ```
   `apply_user_edits` (`simulate.py:191`) already wraps `apply_edits` in `try/except
   Exception → failed`, so a raised `EditsParseError` now correctly fails the simulation
   instead of silently mis-simulating.

2. **TOML editing — pick one:**
   - **Recommended:** add `tomlkit>=0.13` to `dependencies` in `pyproject.toml` and rewrite
     `_set_field_toml` to parse → set nested key → dump (preserves comments/formatting).
     Delete `_set_toml_key` / `_set_toml_table_key` / `_toml_value_str`.
   - **No-new-dep fallback:** keep the string writer but make it *refuse* what it can't do
     safely — raise `EditsParseError` for inline tables, arrays-of-tables, or quoted/dotted
     keys it can't locate — so a botched edit fails loudly rather than mangling.

3. **Tests** (`tests/unit/test_edits.py`, new — this is the coverage fix): one case per
   action — `append` (existing + missing file), `create` (+ `mode: x` → 0o755), `set-field`
   on `.yml` (nested + list index) and `.toml`, `patch` (success + failure raises), plus
   `load_edits` validation errors (missing `file`/`action`, unknown action, non-mapping).

### §6. P2-3: fix `check_passed` semantics + the mislabeled "clean" message

`src/copyroom/workshop/model.py`:

```python
@dataclass
class UpdateSimulationResult:
    conflicts: set[str] = field(default_factory=set)
    rejects: set[str] = field(default_factory=set)
    check_passed: bool = True          # was False — checks "pass" until one fails

    @property
    def clean(self) -> bool:
        """The update applied with no conflicts, no rejects, and all checks green."""
        return self.check_passed and not self.conflicts and not self.rejects
```

`src/copyroom/workshop/simulate.py`: now that the default is `True`, delete the manual flips
and the result-rebuilding in `run_checks` (`:284-299`) and `_complete` (`:345-349`).
Construct `sim.result` once (in `_capture_conflicts`/`_capture_rejects`) and only ever set
`check_passed = False` when a check fails. `_complete` just re-scans rejects and transitions.

`src/copyroom/cli.py:_cmd_update_test`: gate the clean message on the new property:

```python
if result and result.clean:
    print("  ✅ Update applied cleanly — no conflicts")
elif result:
    print("  ⚠️  Update had issues:")
    ...
```

### §7. P2-4: surface and allow discarding stale edit branches

**Warn on reuse** — `src/copyroom/template/workspace.py:checkout_template`, in the branch
where the worktree already exists:

```python
ahead = gitutil.commits_ahead(repo, branch, base)
if ahead:
    checkout.reused_commits = ahead   # add this int field to TemplateCheckout (default 0)
```
Then in `cli.py:_cmd_template_checkout`, if `checkout.reused_commits`, print a notice:
"Reusing an existing edit branch with N pending commit(s). Run `copyroom template-discard`
to start fresh."

**Add `copyroom template-discard`** (project mode):
- `session/model.py`: add `"template-discard"` to `PROJECT_COMMANDS`.
- `template/workspace.py`: new `discard_template_edit(project_root=None) -> Path` that
  resolves the same `repo`/`worktree_dir`/`branch` (reuse the slug/cache logic — factor the
  path computation out of `checkout_template` into a small `_edit_paths(root, source)`
  helper so both share it), then `gitutil.worktree_remove(repo, worktree_dir)` +
  `gitutil.delete_branch(repo, branch)`; return the worktree path for the message. Missing
  worktree → friendly no-op message, not an error.
- `cli.py`: `_cmd_template_discard` handler + `subparsers.add_parser("template-discard", ...)`
  + entry in `COMMAND_FN`. Add the line to `COPYROOM_DESCRIPTION` under the template-edit
  group.
- Docs: `docs/user/template-editing.md` — document the loop reset and the reuse warning.

> **Minimal variant** (if you want to land P2-4 small): ship only the reuse **warning** and
> defer `template-discard`. The warning alone removes the silent-resurfacing surprise.

---

## Phase 4 — P3 cleanups

### §8. P3-1: route `create_branch` through `_compat`

`src/copyroom/project/update.py:create_branch`: replace the inline `subprocess.run([...])`
with the new `gitutil.checkout_new_branch(update.project_root, branch_name)`. Keep the
`None` → `failed` and non-zero → `failed` (+ forward `result.stderr`) handling; the helper
returns the `CompletedProcess` so stderr forwarding is unchanged. Drop the now-unused
`import subprocess` if nothing else in the module needs it (it does not after this).

### §9. P3-2: portable workshop sources (fixes the latent relative-source bug too)

The copier-facing callers pass the registry `source` straight to `copier copy`, so a
relative source breaks unless `cwd == workshop root`. Fix both the symptom and the cause:

- `src/copyroom/workshop/registry.py`: add
  ```python
  def resolve_source_for_copier(workshop_root: Path, source: str) -> str:
      """Absolute path for a *local* source (relative paths joined to the workshop root);
      remote sources pass through unchanged."""
      if gitutil.looks_remote(source):
          return source
      return str(_resolve_local_source(workshop_root, source))
  ```
- Apply it where the source is handed to Copier: `render.execute_render`,
  `golden.render_for_golden` (via `render_scenario`), `simulate.render_old_version`,
  `release/check.run_matrix`. (Simplest: have `render_scenario`/`golden_diff`/
  `run_update_simulation`/`run_release_check` resolve the source with this helper right
  after `resolve_template_source(...)`.)
- `src/copyroom/manage/templatize.py:_scaffold`: now write a **relative** source so the repo
  is relocatable:
  ```python
  (home / "copyroom.yml").write_text(f"templates:\n  {tid}:\n    source: .\n")
  ```
  `.` resolves to the workshop root for both validation (`_resolve_local_source`) and Copier
  (via `resolve_source_for_copier`).
- Tests: `tests/integration/test_registry.py` — a workshop with a relative `source: .`
  renders/validates correctly when invoked from a **descendant** directory.

### §10. P3-3: delete dead branches in `cli.main()`

`src/copyroom/cli.py:889-907`: after `result = dispatch(cmd, session)`:
- Remove the `if session.status == SessionStatus.unknown_mode: sys.exit(1)` check — that
  state already exited inside `_detect_and_report`.
- The `handler = COMMAND_FN.get(cmd)` / `if handler is not None` guard can collapse to
  `COMMAND_FN[cmd](args)` — dispatch returning `command_running` proves the command is in
  `COMMAND_MODE_MAP`, every member of which has a `COMMAND_FN` entry.

Keep the `session.advance(...)` calls so the lifecycle stays honest. This is pure
simplification — confirm `tests/unit/test_dispatcher.py` + `test_cli.py` stay green.

---

## Phase 5 — docs, specs & the documentation-only findings

### §11. Documentation fixes (P2-5, P3-4, P3-5, P3-7)

- **P2-5** `docs/user/trust-and-safety.md`: add a section stating that **workshop registry
  `checks` run unconditionally** (no `--trust` gate) with `shell=True`, because they are the
  workshop author's own commands — so you must trust any workshop you `cd` into and run
  `render`/`test`/`golden`/`release-check` in. Contrast explicitly with template `post_*`
  hooks, which *are* gated.
- **P3-4** `docs/copier/overview.md` (or `configuration.md`): note CopyRoom does **not** run
  Copier's own `_tasks`/migrations — it has its own `post_project_create`/
  `post_template_update` hooks instead. (Optional code change in §12.)
- **P3-5** `src/copyroom/project/update.py:verify_worktree`: add a one-line comment that,
  unlike `release-check`, it intentionally excludes nothing because Copier's 3-way update
  requires a fully clean tree. No behavior change.
- **P3-7** `cli.py` help text + `docs/user/cli-reference.md`: state that `test` runs the
  configured checks against a fresh render (equivalent to `render` when checks exist) and
  does **not** run golden — use `golden` for snapshot comparison.

### §12. (Optional) forward `--trust` to Copier

If you want `copyroom new --trust` / `update --trust` to also let Copier run its own
`_tasks`, thread a `trust: bool` into `_compat/copier.copier_copy`/`copier_update` and append
`--trust` when set. Purely additive; gate it behind the same `--trust` flag so the
no-trust default still runs nothing unexpected. Skip if CopyRoom-hooks-only is the intended
contract (then §11/P3-4 doc is the whole fix).

---

## Phase 6 — atomic writes (P3-6)

### §13. Route in-place config writes through `atomic_write_text`

Use the §1c helper in:
- `workshop/registry.py:add_template` (the `target.write_text(yaml.safe_dump(...))`).
- `workshop/edits.py:_set_field_yaml` and the TOML writer (or tomlkit dump) — write the
  serialized doc atomically.
- `template/preview.py:_retarget_answers` and `_write_patch` are scratch/sandbox writes;
  leave them (no durability requirement).

Low risk, no behavior change; protects user-facing files from torn writes.

---

## Phase 7 — Tests (write the failing test first, per finding)

- `tests/unit/test_refs.py` / `test_semver.py`: unchanged (still green).
- **P1-1** `tests/integration/test_cli.py`: `new <template> <target>` succeeds **without**
  `--mode` from an unmanaged dir; assert the project is created.
- **P1-2** `tests/integration/test_workflows.py` (or `test_cli.py`): a no-arg `update` on a
  project already at the latest tag exits **0** and prints "Already at…"; entity status is
  `up_to_date`. `tests/spec/` assertion: `config_loaded → up_to_date` is a legal edge and
  `up_to_date` is terminal.
- **P2-1** `tests/integration/`: an `update` that produces an inline-marker conflict reports
  it in `update.conflicts` (was missed by the stdout grep).
- **P2-2** `tests/unit/test_edits.py` (new): per-action coverage incl. patch-failure raises
  and `patch`-missing raises; brings `edits.py` well above its current 27%.
- **P2-3** `tests/`: an `update-test` with conflicts but passing checks reports
  `result.clean is False` and the CLI does **not** print "applied cleanly"; a truly clean
  run reports `clean is True`.
- **P2-4** `tests/integration/test_template_edit.py`: a second `template-checkout` after a
  committed edit warns (`reused_commits > 0`); `template-discard` removes the worktree +
  branch and a subsequent checkout starts at 0 ahead.
- **P3-2** `tests/integration/test_registry.py`: relative `source: .` resolves from a
  descendant dir (render + validate).
- **P3-3** `tests/unit/test_dispatcher.py` / `test_cli.py`: unchanged behavior after the
  `main()` simplification.

> Conftest note: several P-fixtures need a project generated at a **post-tag commit** so
> `_commit` is a `vX.Y.Z-N-gsha` describe string (the `same_version` no-op path). Reuse /
> extend the fixture pattern in `tests/integration/conftest.py`.

---

## Phase 8 — Verification ritual

```
devenv shell -- uv run ruff check src/ tests/
devenv shell -- uv run pytest -q             # all green incl. new regression tests
devenv shell -- bash demo/walkthrough.sh     # exits 0
```

Update the demo to drop `--mode project` from the `new` invocation (P1-1) and, if you added
it, exercise `template-discard` once in the agentic act.

Bump the version to **0.4.0** in `pyproject.toml` and `src/copyroom/__init__.py` as the last
commit.

Suggested commit grouping (gate green per commit where practical):
1. `_compat` primitives (`conflicts.py`, gitutil branch/worktree helpers, `atomic_write_text`).
2. P1-1 `new` bootstrap + P1-2 `up_to_date` (+ spec edits).
3. P2-1 unified conflict detection.
4. P2-2 edits DSL hardening + tests.
5. P2-3 `check_passed`/`clean` cleanup.
6. P2-4 reuse warning + `template-discard`.
7. P3 cleanups (§8 layering, §9 sources, §10 dead code, §13 atomic writes).
8. Docs/specs (§11) + version bump.

No AI-attribution trailers.

---

## Quick reference — finding → section

| Finding | Fix section(s) |
|---------|----------------|
| P1-1 `new` can't bootstrap | §2 |
| P1-2 no-op `update` exits non-zero | §3 |
| P2-1 fragile conflict detection | §1, §4 |
| P2-2 edits DSL fragile + untested | §5 |
| P2-3 `check_passed` footgun + mislabeled clean | §6 |
| P2-4 stale edit-branch resurfacing | §7 |
| P2-5 workshop checks untrusted (doc) | §11 |
| P3-1 `create_branch` bypasses `_compat` | §8 |
| P3-2 absolute/relative registry source | §9 |
| P3-3 dead branches in `main()` | §10 |
| P3-4 `--trust` not forwarded to Copier | §11, §12 |
| P3-5 worktree-clean exclusion disagreement | §11 |
| P3-6 non-atomic config writes | §1, §13 |
| P3-7 `test` aliases `render` | §11 |
