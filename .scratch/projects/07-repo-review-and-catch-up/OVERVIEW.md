# 07 — CopyRoom: Repo Review & Catch-Up — OVERVIEW

Snapshot of what CopyRoom **is**, where it is **now** (verified against code at
`v0.5.0`), and the remaining gap between the concept and the shipped reality.

> Verified 2026-07-01 against the working tree. `git describe`/tags: **`v0.5.0`**
> is the latest tag and `HEAD` sits on it (`git log v0.5.0..HEAD` is empty; working
> tree clean). `src/copyroom/__init__.py:__version__ = "0.5.0"` and
> `pyproject.toml:version = "0.5.0"` agree. Full `pytest` suite is **green**
> (exit 0, 71% line coverage) via `devenv shell -- pytest`.

---

## 1. What CopyRoom IS (final concept)

CopyRoom is a **mode-aware CLI wrapper around [Copier](https://copier.readthedocs.io/)**
(the project-templating engine that *generates* a project from a template and later
*updates* it via a three-way merge). On top of Copier's low-level operations it adds:

- **Mode-aware command routing** — the tool auto-detects whether it is standing in a
  *project* (`.copier-answers.yml`) or a *workshop* (registry markers) and gates each
  command to the correct mode. Bootstrap commands (`new`, `adopt`, `templatize`) and
  `doctor` run anywhere.
- **Safe lifecycle management** — report-and-exit on one error type (`CopyRoomError`),
  never auto-rollback; git/copier/subprocess work funnels through `_compat/`; git
  helpers fail soft.
- **A template-author's "workshop"** — a registry of templates + scenarios with a
  render/golden/update-test/release-check loop for exercising a template against known
  answers (`render`, `golden`, `test`, `update-test`, `release-check`, `registry`).
- **Agentic template editing** — drive a change *back into* a template from inside a
  generated project and preview the update, all on a throwaway scratch branch
  (`template-checkout` → `template-test` → `template-preview` → `template-discard`).
- **Repo adoption / templatization** — bring an existing hand-written repo under
  management (`adopt`) or extract a fresh template from it (`templatize`). Both are
  report-only; only `--write`/`adopt --write` records the `.copier-answers.yml` link.
- **A trust model** — template-defined `post_project_create` / `post_template_update`
  hooks are *not* run unless `--trust` is passed (remote templates = arbitrary code).
- **Environment readiness checks** — `doctor` verifies Copier/git/cache so RepoMan's
  conductor can drive every manager's `doctor` uniformly.

Family role (per the workspace naming conventions): CopyRoom is the **templating
mechanics engine** the fleet's `new-project` / `adopt-project` skills defer to; it owns
its own agent skills (`copyroom-adopt`, `copyroom-template-edit`, `propagate`).

---

## 2. Where it is NOW (verified command surface)

CLI frontend: `src/copyroom/cli.py` (996 lines) is now a **Typer** app
(`import typer`; `app = typer.Typer(...)`; `main()` at line 984 just calls
`app(args=argv)`). The old `argparse` `_build_parser()` is gone; `argparse` survives
only as the type annotation on the preserved `_cmd_*(args: argparse.Namespace)`
handler-bag bridge (deliberate — see the migration invariants below).

| Group | Commands (verified in `cli.py`) |
|---|---|
| Global | `--mode {workshop,project}`, `--version` |
| Project | `update [ref] [--branch] [--trust]`, `inspect [--json]`, `status [--json]`, `template-checkout [--from]`, `template-test [--from] [--check]`, `template-preview [--from]`, `template-discard` |
| Bootstrap | `new <source> [target] [--answers] [--trust]`, `templatize [--into] [--name] [--id]`, `adopt <template> [--ref] [--answers] [--write] [--force]` |
| Workshop | `registry {list\|show <id>\|validate\|add <id> --source [--scaffold]}`, `render <tid> <sid>`, `test <tid> <sid>`, `golden <tid> <sid> [--refresh]`, `release-check <tid>`, `update-test <tid> <sid> <old> <new>` |
| Env | `doctor [--json]` (runs anywhere; exit `0` ok / `2` infra) |

Source layout (verified `find src`): `project/` (create/update/inspect/config/model),
`template/` (workspace/preview/validate/model), `workshop/`
(registry/render/golden/simulate/edits/model), `manage/` (adopt/templatize/model),
`release/` (check), `session/` (detector/dispatcher/model — the mode state machine),
`doctor.py`, and the `_compat/` shim layer
(conflicts/copier/errors/fsutil/gitutil/refs/semver/shellcmd/state_machine/treediff).

Tests (verified `find tests`): `unit/` (incl. `test_doctor.py`, 71 lines;
`test_cli_messages.py` which still calls `_cmd_*` directly),
`integration/` (`test_cli.py` shells out via `python -m copyroom`), and `spec/`
(allium-invariant tests). `pyproject.toml` runs `pytest -q --cov=copyroom`.

Version / test commands:
- `devenv shell -- pytest` → green (exit 0).
- `devenv shell -- copyroom --version` → `copyroom 0.5.0`.
- `devenv shell -- copyroom doctor` / `... doctor --json` → env report, exit 0 when healthy.

### What LANDED at v0.5.0 (confirmed via `git log` + code)
- **Two review-remediation passes** — `04-v0.3.0-review-remediation` (P1..P3) merged
  (`5501b9a Merge v0.3.0 code-review remediation`), then `05-deep-review-remediation`
  (P1-1..P3-10) landed across `e9879b7..0ed84d5`, version bumped to `0.4.0` (`0b4fc3d`).
- **argparse → Typer migration + `doctor`** — single commit
  `4addb2b feat(cli): migrate CLI to Typer and add doctor command`; version → `0.5.0`;
  tagged `v0.5.0`. `doctor.py` + `tests/unit/test_doctor.py` present.
- Docs updated: `docs/user/cli-reference.md` documents the Typer frontend, the
  `doctor` command, and the `0/2` exit policy.

---

## 3. Concept-vs-reality gap table

The core concept is **fully realized**; CopyRoom is a mature, feature-complete tool at
`v0.5.0`. The remaining gaps are cross-repo follow-ups and small hygiene items that the
`06` guide itself flagged as deferred — not missing features.

| # | Concept / intent (source) | Reality now | Gap | Evidence |
|---|---|---|---|---|
| G1 | After `doctor` ships, RepoMan should drive `copyroom doctor` (06 IMPLEMENTATION_GUIDE §7.1) | `copyroom doctor` exists & works | **Un-landed cross-repo follow-up.** RepoMan still disables it | `repoman/src/repoman/registry.py:60` → `doctor=None,  # copyroom (v0.4) has no doctor verb; inspect/status only` |
| G2 | Update RepoMan's SPIKE note to record copyroom now conforms (06 §7.3) | Note still says the opposite | **Stale doc.** | `repoman/SPIKE.md:142` "copyroom (v0.4) has no `doctor`" + `:131` "no doctor, skipped" |
| G3 | Re-run the N=2 spike so `repoman doctor` aggregates copyroom's exit (06 §7.2) | Not re-run since v0.4 | **Verification debt** (depends on G1). | `repoman/SPIKE.md:120,137` (recorded against v0.4) |
| G4 | Optional: promote `_cache_root` → public `cache_root` so `doctor` doesn't import a private name cross-module (06 §4.1 note, guide §7-adjacent) | Still `_cache_root`, imported by `doctor.py` | **Deferred hygiene** (explicitly optional). | `src/copyroom/template/workspace.py:84 def _cache_root`; `src/copyroom/doctor.py:19 from .template.workspace import _cache_root` |
| G5 | Optional: add a `doctor` note to the Allium spec (06 §4-Phase-4, "optional") | No `doctor` in any `.allium` | **Deferred doc** (spec drives `tests/spec`; doctor is env-only, unmodelled). | `grep doctor .scratch/specs/*.allium` → none |
| G6 | Migration flagged one intended behaviour change: unknown-command exit `1`→`2` (06 §3.2, Risks) | Typer/Click now owns unknown commands (exit 2) | **No gap** — intended; `cli-reference.md:31` documents exit 2. Listed only for completeness. | `docs/user/cli-reference.md:31` |

Bottom line: the biggest genuine outstanding item is **G1/G2/G3 — the RepoMan
integration for `copyroom doctor` was never landed**, so the tool that motivated the
whole `06` effort still can't call it. Everything inside the copyroom repo is complete
and green.
