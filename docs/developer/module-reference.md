# Module Reference

A file-by-file tour of `src/copyroom/`. Each entry says what the module owns and
names the functions/types you'll touch most. See [architecture](architecture.md)
for the layering and [state machines](state-machines.md) for the lifecycle
pattern these modules share.

```
src/copyroom/
├── __init__.py          # __version__ = "0.3.0"
├── __main__.py          # `python -m copyroom` → cli.main()
├── cli.py               # argparse front end, dispatch, output, exit codes
├── session/             # mode detection + command gating
├── project/             # new / update
├── template/            # template-checkout / template-test / template-preview
├── workshop/            # render / test / golden / update-test
├── release/             # release-check
├── manage/              # templatize / adopt (bootstrap)
└── _compat/             # subprocess boundary + shared primitives
```

---

## Top level

### `cli.py`
The only argparse code in the project. Key pieces:
- `COPYROOM_DESCRIPTION` / `NO_MODE_FOUND_MESSAGE` — grouped help and the
  unknown-mode diagnostic.
- `_build_parser()` — the full subparser tree; the single source of truth for
  flags.
- `_detect_and_report(mode_override)` — resolves mode (honoring `--mode`) into a
  `CLISession`; prints the diagnostic and exits on unknown mode.
- `_cmd_*` functions — one thin handler per command: unpack args → call the domain
  workflow → format output → set exit code.
- `COMMAND_FN` — maps command name → handler.
- `main(argv)` — orchestrates parse → bootstrap shortcut → detect → dispatch →
  run, advancing the `CLISession` through its lifecycle.

### `__main__.py`
Enables `python -m copyroom`; just calls `cli.main()`.

---

## `session/` — mode detection & gating

### `session/model.py`
- `CLIMode` (StrEnum) — `workshop`, `project` (template_repo/standalone reserved).
- `SessionStatus` (StrEnum) — `mode_detecting → mode_detected →
  command_running → command_complete | command_failed`, plus `unknown_mode`.
- `VALID_SESSION_TRANSITIONS` — the session state graph.
- `WORKSHOP_COMMANDS`, `PROJECT_COMMANDS`, `BOOTSTRAP_COMMANDS` — the command sets
  per mode (bootstrap commands bypass detection).
- `CLISession` (dataclass) — `status` + optional `mode`, with `advance()` routed
  through a shared `StateMachine`.

### `session/detector.py`
- `is_workshop(path)` — `copyroom.yml` + `registry/` + `scenarios/`.
- `is_project(path)` — `.copier-answers.yml` or `copyroom.project.yml`.
- `detect_mode(cwd)` — walks ancestors; closest marker wins; workshop wins a
  same-directory tie; returns `None` for unknown.
- `detect_workshop_root(cwd)` — finds the workshop root for workshop/release
  commands so they work from any descendant.

### `session/dispatcher.py`
- `COMMAND_MODE_MAP` — command → required mode (built from the command sets).
- `dispatch(command, session)` — returns `command_running` for a valid
  mode/command pair, else `command_failed`. Pure gating; the CLI prints errors.

---

## `project/` — `new` and `update`

### `project/model.py`
- `CreationStatus` + `VALID_CREATION_TRANSITIONS` + `ProjectCreation` dataclass
  (`initiated → target_verified → prompts_collected → copy_executed →
  [post_create_run →] complete | failed`).
- `UpdateStatus` + `VALID_UPDATE_TRANSITIONS` + `TemplateUpdate` dataclass
  (`initiated → config_loaded → worktree_verified → [branch_created →]
  update_executed → [post_update_run →] complete | failed`); carries
  `conflicts`/`rejects` sets.

### `project/create.py` (`copyroom new`)
Rule functions `initiate` → `verify_target` → `collect_prompts` →
`execute_copy` → `detect_post_create_commands` → `run_post_create_commands`, and
the orchestrator `create_project(source, target_dir, answers_file, trust)`.
Refuses non-empty targets; forwards Copier stderr on failure; runs post-create
hooks only under `trust`.

### `project/update.py` (`copyroom update`)
Rule functions `initiate` → `load_config` (the single reader of
`.copier-answers.yml`, extracting `_template`/`_commit`) → `no_update_available`
→ `verify_worktree` (clean-tree gate) → `create_branch` (with `--branch`) →
`execute_update` → `capture_conflicts` → `run_post_update_commands`, and the
orchestrator `update_project(...)`. Captures inline conflict markers and `*.rej`
rejects (deliberately in separate sets to avoid double-counting).

---

## `template/` — the agentic edit loop

### `template/model.py`
- `PreviewResult` / `ValidateResult` value types.
- `CheckoutStatus` + `TemplateCheckout` (`initiated → source_resolved →
  worktree_ready | failed`).
- `PreviewStatus` + `TemplatePreview` (`initiated → sandbox_prepared →
  update_simulated → diffed → complete | failed`).

### `template/workspace.py` (`copyroom template-checkout`)
The shared foundation for all three template commands:
- `resolve_project_root` / `read_answers` — locate the project, read
  `.copier-answers.yml` (also confirms you're in a Copier project).
- `_cache_root` / `_template_cache_dir` — the cache layout
  (`$COPYROOM_CACHE_DIR` or `$XDG_CACHE_HOME/copyroom/templates`).
- `_looks_remote` / `_ensure_local_repo` — clone remote sources into cache; demand
  local sources be git repos.
- `checkout_template(...)` — reads `_src_path`, ensures a local repo, and
  `git worktree add`s `copyroom/edit/<slug>`.

### `template/validate.py` (`copyroom template-test`)
`validate_template(...)` — re-resolves the worktree, commits pending edits onto
the edit branch, `copier copy --vcs-ref <branch>` into a temp dir, runs an
optional `--check` command. Returns a `ValidateResult`.

### `template/preview.py` (`copyroom template-preview`)
`run_preview(...)` — copies the project working tree into a sandbox, retargets the
sandbox's answers at the edit repo, snapshots it, `copier update --vcs-ref
<branch>`, diffs baseline→post-update, scans for inline conflict markers and
`*.rej`, and writes `.copyroom/preview/<timestamp>.patch`. Applies nothing.

---

## `workshop/` — the author's workbench

### `workshop/model.py`
Value types `GoldenDiffResult`, `UpdateSimulationResult`; entities
`ScenarioRender`, `GoldenDiff`, `UpdateSimulation` with their status enums and
transition tables.

### `workshop/registry.py`
The shared registry lookup (consolidated to kill four near-duplicate copies):
- `resolve_template_source(workshop_root, template_id)` — `copyroom.yml`
  (`templates`/`registry`) then `registry/<id>.yml`.
- `load_checks(workshop_root, template_id)` — the template's `checks` list.
- `require_workshop_root(workshop_root)` — default-resolve via
  `detect_workshop_root`, raising if none.

### `workshop/render.py` (`render` / `test`)
`render_scenario(...)` — load scenario answers, `copier copy` into
`generated/<id>/<scenario>/`, run registry checks. `test` is an alias.

### `workshop/golden.py` (`golden` [`--refresh`])
`golden_diff(...)` — render (or `reuse_generated`) then `tree_diff` against
`golden/`. `refresh_golden(...)` — copy `generated/` → `golden/`.

### `workshop/simulate.py` (`update-test`)
`run_update_simulation(...)` — render old version into `.copyroom_sim/`, git
snapshot, apply edits, `copier update --vcs-ref <new>`, capture conflicts/rejects,
run checks. Uses a repo-local git identity so it works without a global one.

### `workshop/edits.py`
The `<scenario>-edits.yml` DSL: `load_edits` / `apply_edits` with `append`,
`set-field` (YAML now, basic TOML), `create`, `patch` actions. `EditsParseError`
on malformed files.

---

## `release/` — the release gate

### `release/check.py` (`release-check`)
- `ReleaseCheck` dataclass + `ReleaseStatus` + transitions
  (`initiated → matrix_run → checked → passed | failed`).
- `run_release_check(...)` — orchestrator: capture worktree state first, discover
  scenarios, run the render+test matrix, run golden diffs (reusing matrix renders),
  resolve pass/fail.
- `format_release_report(check)` — the human report.
- `_check_worktree_clean` / `_is_git_repo` — git status (excluding `generated/`
  and `.copyroom_sim/`) and the git-repo probe used for the `N/A` case.

---

## `manage/` — bootstrap (templatize & adopt)

### `manage/model.py`
- `EXCLUDE_DIRS` — dirs never copied/compared (`.git`, `.copyroom`, `generated`,
  caches, `.venv`, `node_modules`, …), shared by both commands.
- `DriftResult` (adopt) and `Adoption` / `Templatization` entities + statuses.

### `manage/templatize.py` (`copyroom templatize`)
`templatize(...)` — scaffold the sibling template+workshop (`_scaffold`),
verbatim-copy the repo into `template/`, snapshot it into `golden/<id>/default/`.
Implements the verbatim-then-parameterize strategy; leaves a plain (non-git) dir.

### `manage/adopt.py` (`copyroom adopt`)
`adopt(...)` — resolve the template (reusing `template/workspace`'s
clone/cache helpers), `copier copy` with inferred answers into a scratch dir,
`tree_diff` against the repo, write a drift patch under `.copyroom/adopt/`, and
(only with `--write`) copy the rendered `.copier-answers.yml` in. Refuses an
already-managed repo without `--force`.

---

## `_compat/` — the subprocess boundary

See [the `_compat` layer](compat-layer.md) for detail.

| Module | Owns |
|--------|------|
| `copier.py` | `copier_copy` / `copier_update` subprocess wrappers (timeouts, `--quiet --defaults`, `--vcs-ref`). |
| `gitutil.py` | Defensive git helpers: `clone`, `fetch`, `worktree_add`, `snapshot`, `commit_all`, `add_all_and_diff_cached`, `default_branch`, `normalize_source_url`. |
| `shellcmd.py` | `run_hook_commands` — the trust-gated template-hook runner. |
| `treediff.py` | `tree_diff` / `collect_files` — the shared comparison (excludes `.copier-answers*.yml`). |
| `state_machine.py` | `StateMachine[S]` + `InvalidTransitionError`. |
| `errors.py` | `CopyRoomError` (re-exported per workflow module). |
