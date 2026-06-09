# Implementation Plan: Adopt / templatize an existing repo

**Status:** Build-ready
**Date:** 2026-06-09
**Concept:** see `CONCEPT.md` in this directory.

## The two paths (one skill, `copyroom-adopt`)

```
unmanaged repo R
├── user named template T   → ADOPT(T)
└── no template             → TEMPLATIZE(R) → agent parameterizes to golden no_diffs
                              → git init+tag v0.1.0 → ADOPT(extracted template)
```

Both paths end in the same `adopt` primitive; extraction feeds it a template that
already reproduces R, so the final adoption is near-zero-drift.

### Home A layout produced by `templatize`
```
R/                          # the repo → becomes a managed project after adopt
R-template/                 # NEW (plain dir during the loop; git+tag at finalize)
  copier.yml                # _subdirectory: template  + an initial project_name question
  template/                 # verbatim copy of R's content (agent parameterizes this)
    …repo files…
    .copier-answers.yml.jinja
  copyroom.yml              # workshop registry: <id>.source = <abs path to R-template>
  scenarios/<id>/default.yml   # answers reproducing R (project_name: <R name>)
  scenarios/<id>/probe.yml     # distinct answers — over-parameterization sanity render
  golden/<id>/default/         # snapshot of R (the convergence target)
  .gitignore                   # generated/ .copyroom_sim/
```

**Why verbatim-then-parameterize converges cleanly:** initially `template/` == R, so
rendering with default answers reproduces R exactly (only delta is `.copier-answers.yml`,
which the golden engine already excludes via `_is_copier_answers_file`). As the agent
replaces R's literal name with `{{ project_name }}`, rendering with `project_name=<R
name>` yields the literal again → golden stays `no_diffs`. The loop *introduces*
parameters without breaking the match. `probe.yml` (different name) flushes out
over-broad substitutions for the agent to review (no golden — sanity render only).

**Render-reflects-edits nuance:** Copier renders a git ref, not uncommitted files. So
keep the extracted template a **plain (non-git) directory during the parameterization
loop** (Copier renders a plain dir's working tree directly) and convert it to a git repo
+ tag only at *finalize*, right before adoption. Fallback if Copier needs git for local
templates: commit-per-iteration. **Spike this first.**

## Components

New package `src/copyroom/manage/` (mirrors the per-domain layout in `src/copyroom/`):
- `model.py` — `Adoption` (`initiated → template_resolved → rendered → drifted →
  complete | failed`) and `Templatization` (`initiated → scaffolded → golden_captured →
  complete | failed`) entities + `StateMachine` tables; a `DriftResult` value type
  (added/modified/removed sets, patch_path). Follow `src/copyroom/template/model.py`.
- `templatize.py` — scaffold Home A from the repo: build `copier.yml`
  (`_subdirectory: template` + a `project_name` question defaulting to the repo name),
  copy repo→`template/` and repo→`golden/<id>/default/` (shared exclude set), write
  `copyroom.yml` / `scenarios/<id>/{default,probe}.yml` / `.gitignore` /
  `template/.copier-answers.yml.jinja`.
- `adopt.py` — resolve the template (reuse `template/workspace._ensure_local_repo` +
  `_looks_remote` for clone/cache), `copier_copy` into a scratch dir with the agent's
  answers (`vcs_ref` when given), compute drift vs the repo, and on `--write` copy the
  scratch's `.copier-answers.yml` into the repo. Never modifies other repo files. Refuse
  an already-managed repo (`.copier-answers.yml` present) unless `--force`.
- `__init__.py` — re-export entry points + `CopyRoomError` (match siblings).

### Reuse (do not reinvent)
- `_compat/copier.copier_copy` — already takes `vcs_ref`.
- `_compat/gitutil` — `clone`, `is_git_repo`, `default_branch`, `snapshot`,
  `add_all_and_diff_cached`. Build the drift patch exactly like `template/preview.py`:
  copy repo→sandbox, snapshot S0, overlay the rendered template files, `git add -A` +
  `diff --cached`.
- `template/workspace.py` — `read_answers`, `resolve_project_root`, `_ensure_local_repo`,
  `_looks_remote`, `_cache_root`/`_template_cache_dir` (import; `template` does not import
  `manage`, so no cycle).
- **Tree comparison:** lift `workshop/golden.py`'s `_collect_important_files` +
  `_file_content_differs` + `_is_copier_answers_file` into a shared `tree_diff(a, b) ->
  (added, modified, removed)` helper (e.g. `_compat/treediff.py`) used by both `golden`
  and `adopt`. Refactor `golden.compare_to_golden` to call it (keep its tests green).
- **Convergence loop = existing workshop commands.** The agent runs `copyroom render` /
  `copyroom golden [--refresh]` inside `R-template/`. No new code for the loop.
- Golden snapshot of R: `shutil.copytree(R, golden_dir, ignore=…)` with the shared
  exclude set (`.git`, `.copyroom`, `__pycache__`, `*.pyc`, lockfiles/build dirs). Reuse
  the ignore pattern style from `template/preview.py:_SANDBOX_IGNORE`.

### Wiring: a modeless "bootstrap" command class
`adopt`/`templatize` run in a repo with **no markers** → today `detect_mode()` returns
`None` and `cli._detect_and_report` hard-exits. Add a third class:
- `session/model.py` — `BOOTSTRAP_COMMANDS = frozenset({"adopt", "templatize"})`.
- `cli.py` `main()` — handle bootstrap commands **before** `_detect_and_report` (run the
  handler directly; they resolve their own context from repo/args). Add subparsers,
  `COMMAND_FN` entries, and help text. Keep them **out of** `COMMAND_MODE_MAP`.

Command surface (flat, matches existing style in `cli.py`):
```
copyroom templatize [--into PATH] [--name NAME] [--id ID]
copyroom adopt <template> [--ref REF] --answers FILE [--write] [--force]
```
The agent reads the template's `copier.yml` itself to author the answers file (no
`--show-questions` primitive needed). Finalize (git init+commit+tag v0.1.0 of the
extracted template) is a documented git step in the skill — git is already a hard dep.

### Skill + docs
- `.agents/skills/copyroom-adopt/SKILL.md` — match the frontmatter/style of
  `.agents/skills/copyroom-template-edit/SKILL.md`. Content: trigger (user in an unmanaged
  repo wants it CopyRoom-managed); choose path (named template → adopt; else
  templatize→converge→finalize→adopt); the golden loop; **confirm inferred answers with
  the user**; author + review the probe scenario; report drift; never edit repo files;
  remind that only `.copier-answers.yml` is written.
- `README.md` — add an "Adopting / templatizing an existing repo" section.

## Testing / verification

New `tests/integration/test_manage.py` (+ small `tests/unit/test_manage.py`), reusing
`tests/integration/conftest.py` patterns and `COPYROOM_CACHE_DIR` isolation (see how
`tests/integration/test_template_edit.py` sets it via an autouse fixture):
- **templatize** a tiny repo → Home A layout produced; `render_scenario`/`golden_diff` on
  the scaffold reports `no_diffs` immediately (verbatim template reproduces the repo).
- **parameterize**: introduce `{{ project_name }}` where the repo name appears → golden
  stays `no_diffs`; probe renders the distinct name (repo's literal name absent in probe
  output).
- **finalize + adopt**: git init+tag the extracted template, `adopt` the repo → repo
  gains a valid `.copier-answers.yml`, drift ≈ empty, repo files otherwise untouched;
  afterward `detect_mode()` reports `project`.
- **adopt under a named (fixture) template** with hand-written answers → answers file
  written, drift report lists real differences, repo files unchanged (only the answers
  file added under `--write`).
- **adopt refuses** an already-managed repo without `--force`.
- Unit: model transitions (illegal raise); `tree_diff` add/modify/remove sets; answers
  refusal/parse.
- **SPIKE FIRST:** confirm `copier copy` against a plain (non-git) local dir renders the
  working tree. If not, switch the loop to commit-per-iteration.

Gates: `uv run ruff check src/ tests/` clean; `uv run pytest -q` green (currently 376
passing — keep them green; the `golden.py` refactor to `tree_diff` is the main regression
risk).

Manual smoke:
```
cd some-existing-repo
copyroom templatize --into ../demo-template --name demo
# parameterize ../demo-template/template, looping:
( cd ../demo-template && copyroom golden demo default )      # → no diffs when faithful
( cd ../demo-template && git init -q && git add -A && git commit -qm t && git tag v0.1.0 )
copyroom adopt ../demo-template --ref v0.1.0 --answers answers.yml --write
git status                                                   # only .copier-answers.yml added
```

## Suggested build order
1. Spike: Copier non-git local dir behavior (decide loop strategy).
2. `_compat/treediff.py` + refactor `workshop/golden.py` to use it (keep tests green).
3. `manage/model.py` + `manage/adopt.py` + the modeless command wiring; tests for adopt
   under a fixture template.
4. `manage/templatize.py` + scaffolding tests + the golden-loop convergence test.
5. End-to-end extract→finalize→adopt test.
6. Skill doc + README section.
7. Full `ruff` + `pytest` gate; commit.
