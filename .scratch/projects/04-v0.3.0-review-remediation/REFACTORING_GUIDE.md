# CopyRoom v0.3.0 Review — Refactoring Guide

Companion to `CODE_REVIEW_REPORT.md`. This is the ordered plan to remediate the review
findings on `feat/v0.3.0`. It is written to be executed top-to-bottom: shared primitives
first (they unblock several fixes), then per-finding correctness fixes, then the two
cleanups, then tests/docs/verification.

> **Conventions (non-negotiable — same as the rest of the repo).**
> - Run everything via `devenv shell --` (pins Python 3.13). Never ambient `uv`/`python`.
> - Gate green **before and after every change**: `uv run ruff check src/ tests/` and
>   `uv run pytest -q`.
> - Workflows are guarded state machines: transition only via `StateMachine.transition`,
>   never assign `entity.status =`. Pure reads may return a result dataclass (no machine).
> - All subprocess/git/copier work goes through `_compat/`. Git helpers fail soft
>   (`None`/`False`) on a missing binary.
> - One error type: `CopyRoomError` (re-exported per module). Report-and-exit; forward the
>   tool's stderr; never auto-roll-back.
> - Config evolution stays **additive**: new fields default; unknown fields tolerated.
> - Keep `.scratch/specs/*.allium` and `docs/` accurate for any behavior change.
> - **No AI-attribution trailers** anywhere (commits, PRs, code, docs).

Branch: keep working on `feat/v0.3.0` (or a child branch off it). The package stays at
**0.3.0** — these are pre-release fixes to an unmerged branch, not a new version.

---

## Phase 0 — Baseline

```
devenv shell -- uv run ruff check src/ tests/
devenv shell -- uv run pytest -q          # expect 448 passing
```

Read, in order: `CODE_REVIEW_REPORT.md` (this dir), then `docs/developer/architecture.md`,
`state-machines.md`, `compat-layer.md`, and the existing `project/`, `workshop/`, `_compat/`
modules named below. Add a regression test for each finding **first** (it should fail),
then fix.

---

## Phase 1 — Shared primitives (do these first)

### §1. `_compat` helpers the fixes will reuse

Add to `src/copyroom/_compat/gitutil.py`:

- **`worktree_clean(path, *, exclude=()) -> bool | None`** — `git status --porcelain`
  via the existing `run_git` (so it inherits the 120s timeout and fail-soft). `None` when
  `path` isn't a git repo; otherwise `True`/`False`. `exclude` filters porcelain lines by
  path prefix (for `release-check`'s `generated/`, `.copyroom_sim/`). Used by §11.
- **`worktree_status(path) -> list[str]`** (or have `verify_worktree` keep its own
  `run_git` call) so `update.verify_worktree` can still print the dirty-file list. Pick the
  smaller change: a `worktree_clean` boolean for `inspect`, and a shared porcelain reader
  for the two that need the lines.
- **`local_path(source) -> Path`** — `Path(source).expanduser()`. One place that turns a
  local source string into a real path (fixes §8). For the registry, resolve relative to
  the workshop root: `(_resolve_local_source` should call `local_path` then join base).

Add a tiny ref-comparison helper (new file `src/copyroom/_compat/refs.py`, or alongside
`semver.py`):

- **`same_version(recorded_ref, target_tag) -> bool`** — `True` when a project's recorded
  `_commit` (`recorded_ref`) is effectively the same version as `target_tag`. Handle the
  three `git describe` shapes: exact tag (`v1.2.3`), describe suffix (`v1.2.3-3-gabc123`),
  and bare SHA. Implementation: equal if `recorded == target`, or if `recorded` strips to
  the base tag `recorded.rsplit("-", 2)[0] == target` when it matches the
  `^<tag>-<n>-g<sha>$` shape. A SHA-only `recorded` (no tag) → `False` (can't prove
  same → treat as "not a no-op", preserving today's behavior). Unit-test this directly.

### §7 (do here, it unblocks §6). Single registry loader

In `src/copyroom/workshop/registry.py`, add:

- **`_registry_map(cfg) -> dict`** — the one definition of "where templates are declared":
  `cfg.get("templates", cfg.get("registry")) or {}` (returns `{}` if not a dict).
- **`load_registry(workshop_root) -> dict[str, RegistryEntry]`** — read `copyroom.yml`
  **once** and each `registry/*.yml` **once**; merge into normalized `RegistryEntry`
  objects keyed by id. `copyroom.yml` wins for source precedence (matching today's
  resolver); checks come from whichever file declares them, using `_registry_map` for the
  inline case (this is the fix for **P2-5**).

Then re-express the public helpers as thin views over the map:

- `list_templates` → `list(load_registry(root).values())`.
- `load_entry(root, id)` → `load_registry(root)[id]` (raise `CopyRoomError` on `KeyError`).
- `resolve_template_source` / `load_checks` → keep the names (other code imports them) but
  back them with `load_registry` (or the parsed `_registry_map`), so `copyroom.yml` is
  parsed once per call instead of 2–4×. This is the fix for **P3-10**.

> Keep the public function signatures stable — `cli.py`, `render.py`, `golden.py`,
> `simulate.py`, `release/check.py`, and tests import them.

---

## Phase 2 — Correctness fixes

### §2. P1-1 + P2-7: config validation must not block generation/update

Two coordinated changes:

1. **Relax forward-compat-sensitive fields** in `src/copyroom/project/config.py`:
   change `ProjectMetadata.kind` and `template_ref_policy` from `Literal[...]` to `str`
   (keep the defaults; document the expected values in the docstring + `configuration.md`).
   Rationale: the additive-config invariant requires a newer template's enum value to load,
   not crash, on an older CLI. The loader should still raise on **unparseable YAML** and
   **non-mapping** (those tests stay green).

2. **Make hook reads resilient.** Add one accessor used by every hook path:
   ```python
   def load_hook_commands(project_yml: Path, key: str) -> list[str]:
       """Return commands[key]; [] if the file is missing or can't be validated."""
   ```
   It calls `load_project_config` and returns `cfg.commands.get(key, [])`, but on
   `CopyRoomError` (a config that fails to validate for any reason) it falls back to a
   minimal direct read of just `commands[key]` (tolerant of bare strings), so an unrelated
   schema problem never blocks `new`/`update`. Use it in:
   - `create.py:detect_post_create_commands` and `run_post_create_commands`
     (`post_project_create`),
   - `update.py:capture_conflicts` and `run_post_update_commands`
     (`post_template_update`) — and **remove the silent `except: pass`** in
     `capture_conflicts` (P2-7); both update-path readers now use the same accessor and
     agree.

   Keep `failed` only for the cases that genuinely can't proceed (e.g. the file vanished
   mid-run and even the minimal read raises `OSError`). Net effect: a schema-divergent but
   readable config no longer aborts a generation; truly broken YAML still does.

> Decision already made by this guide: **forward-compat wins over strict validation in the
> generation paths.** `inspect`/`status` may still surface a validation error verbatim
> (that's a diagnostic surface, not a gate), but they should not crash either — prefer
> showing what loaded.

### §3. P1-2: route version comparisons through `same_version`

- `update.py:no_update_available` → replace `update.previous_ref == update.target_ref`
  with `same_version(update.previous_ref, update.target_ref)` (guard `None`s).
- `inspect.py:project_status` → `update_available = latest_ref is not None and not
  same_version(current_ref, latest_ref)`.

Both now share one definition; a describe-suffix `_commit` correctly reads as a no-op when
it's the same version.

### §4. P1-3: `registry add` must not shadow a `copyroom.yml` entry

In `add_template`, before writing, also refuse when the id already exists in the registry
map:
```python
if template_id in load_registry(workshop_root):
    raise CopyRoomError(f"Template '{template_id}' is already registered (in copyroom.yml "
                        f"or registry/). Edit the existing entry instead.")
```
Keep the existing `registry/<id>.yml` existence check too (clear message either way).

### §5. P2-4: write the registry entry with the YAML library

In `add_template`, replace the f-string with:
```python
import yaml
target.write_text(yaml.safe_dump(
    {"id": template_id, "source": source, "checks": []}, sort_keys=False))
```
So special characters in `source` round-trip correctly.

### §6. P2-5: checks load from a `registry:`-keyed workshop

Resolved by §7's `load_registry` + `_registry_map`. Add a regression test for a workshop
whose `copyroom.yml` uses `registry:` (not `templates:`) and asserts `load_entry(...).checks`
is populated.

### §8. P2-6: expand `~` in local sources

- `gitutil.resolve_latest_ref` local branch → `list_tags(local_path(source))`.
- `registry._resolve_local_source` → use `local_path(source)` then join the workshop root
  for relative paths.
- Consider applying `local_path` in `template/workspace._ensure_local_repo` too for
  consistency (low risk; `_src_path` is already absolute, so no behavior change there).

### §10. P2-8: record `failed` when latest-ref resolution fails

In `update.py:resolve_latest_ref`, before each `raise CopyRoomError(...)`, set
`update.status = _update_sm.transition(UpdateStatus.config_loaded, UpdateStatus.failed)`
(a legal edge). Keep raising so `_cmd_update` prints the message; the entity now reflects
the outcome for non-CLI callers. (Alternatively, convert it to a rule that returns
`UpdateStatus` and have `update_project` short-circuit on `failed`; either is fine, but the
set-then-raise change is the smaller one.)

---

## Phase 3 — Cleanup

### §11. P3-9: collapse the worktree-clean check

- `inspect._worktree_clean` → call `gitutil.worktree_clean(path)`.
- `update.verify_worktree` → use the shared porcelain reader (so it gains the 120s timeout)
  while keeping its dirty-file listing on stderr.
- `release/check._check_worktree_clean` → `gitutil.worktree_clean(root,
  exclude=("generated/", ".copyroom_sim/"))`, preserving its exclusions.

Delete the now-dead private copies.

### §7 wiring (finish). Ensure all registry readers go through `load_registry`

Confirm `cli._cmd_registry`, `render`, `golden`, `simulate`, `release/check` still pass
through the (now-thin) public helpers and that `copyroom.yml` is parsed once per command.

> **Altitude note (optional):** the review also flagged that `_cmd_registry` holds ~80
> lines of dispatch/validation/formatting in `cli.py`. If you touch it, consider moving the
> action validation and human formatting into `workshop/registry.py` thin functions
> (mirroring the `_cmd_*` split elsewhere). Not required for correctness.

---

## Phase 4 — Tests (add the failing test first, per finding)

- **`tests/unit/test_refs.py`** (new): `same_version` — exact tag, `tag-N-gsha` suffix,
  SHA-only, mismatched versions, `None` inputs.
- **`tests/unit/test_project_config.py`**: a config with `project.kind: <future-value>`
  now **loads** (forward-compat) rather than raising; a non-mapping / bad-YAML still raises.
- **`tests/unit/test_semver.py`**: unchanged (pre-release exclusion is intended).
- **`tests/integration/test_workflows.py`**:
  - generate a project at a **post-tag commit** (so `_commit` is `vX.Y.Z-N-gsha`), then a
    no-arg `update` to the same latest tag is a **clean no-op** (P1-2);
  - `new`/`update` with a `copyroom.project.yml` that has an invalid known field **still
    completes** and still runs/skips hooks correctly (P1-1, P2-7).
- **`tests/integration/test_registry.py`**:
  - `add` **refuses** an id already in `copyroom.yml` (P1-3);
  - `add` with a source containing ` #` or `{` round-trips correctly via `validate`/`show`
    (P2-4);
  - a `registry:`-keyed workshop reports non-empty `checks` (P2-5);
  - a `~`-prefixed local source validates/resolves (P2-6).
- **`tests/integration/test_inspect_status.py`**: `status` reports
  `update_available: false` for a describe-suffix `_commit` at the latest tag (P1-2).
- **State-machine:** assert `update_project(..., target_ref=None)` on a project with no
  `_src_path` returns an entity in `failed` (P2-8).

Conftest note: `tests/integration/conftest.py` currently tags `v1.0.0` at HEAD (so
`_commit == "v1.0.0"`). For the P1-2 tests, add a fixture variant that commits **after** the
tag before generating, so Copier records a describe-suffixed `_commit`.

---

## Phase 5 — Specs & docs

- `.scratch/specs/copyroom-project.allium`: note that `ResolveLatestRef` failure transitions
  the entity to `failed` (P2-8); no graph change needed (`config_loaded → failed` already
  exists).
- `docs/user/configuration.md`: document `kind`/`template_ref_policy` as free-form strings
  with recommended values (P1-1), and that a schema-divergent config is tolerated (hooks
  still read; generation isn't blocked).
- `docs/user/cli-reference.md` / `workshop.md`: note `registry add` refuses an id already in
  `copyroom.yml` (P1-3).
- `project/config.py` docstring: reflect the forward-compat relaxation.

---

## Phase 6 — Verification ritual

```
devenv shell -- uv run ruff check src/ tests/
devenv shell -- uv run pytest -q          # all green, new regression tests included
devenv shell -- bash demo/walkthrough.sh  # exits 0
```

Commit in logical groups (suggested): (1) `_compat` primitives + `same_version`; (2) the
two registry fixes + single loader; (3) the config-resilience + version-comparison fixes;
(4) worktree-clean consolidation; (5) docs/specs. Keep the gate green per commit where
practical. No version bump (stays 0.3.0). No AI-attribution trailers.

---

## Quick reference — finding → section

| Finding | Fix section(s) |
|---------|----------------|
| P1-1 config aborts generation | §2 |
| P1-2 `_commit` vs tag | §1 (`same_version`), §3 |
| P1-3 registry add shadowing | §1/§7 (`load_registry`), §4 |
| P2-4 unquoted source | §5 |
| P2-5 checks `registry:` fallback | §7, §6 |
| P2-6 `~` not expanded | §1 (`local_path`), §8 |
| P2-7 capture_conflicts swallow | §2 |
| P2-8 no `failed` transition | §10 |
| P3-9 worktree-clean ×3 | §1, §11 |
| P3-10 registry O(4N) reads | §7 |
