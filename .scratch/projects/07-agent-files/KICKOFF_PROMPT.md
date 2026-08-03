# Kickoff prompt — the agent-files convention (`.agents/skills` + `AGENTS.md` + `CLAUDE.md` symlink)

> Paste everything below the line into a **clean session** opened at the repo root
> (`/home/andrew/Documents/Projects/copyroom`). It is self-contained: it assumes no memory of
> any earlier conversation. The design is settled and written down below — your first job is to
> read it, not to start editing.

---

## Who you are / what this is

You are an implementing engineer working in **CopyRoom**, a mode-aware CLI wrapper around
[Copier](https://copier.readthedocs.io/) (the templating engine that generates a project from a
template and later *updates* it via a three-way merge). CopyRoom adds workflow, safety, a
template-author's testing workshop, and repo-adoption bootstrapping on top of Copier. Source
lives in `src/copyroom`.

CopyRoom is a member of the **`*man` family** (copyroom, gitman, testee, docman — orchestrated
by repoman). The family has adopted a single **agent-files convention** that every repo follows:

- **Skills** live at `.agents/skills/<name>/SKILL.md` (the emerging tool-agnostic standard,
  not `.claude/skills/`).
- **Repo instructions** live in a root **`AGENTS.md`** — the canonical file.
- **`CLAUDE.md`** is a **symlink to `AGENTS.md`** — one source, every tool reads it.
- Skills are **content**: the fleet-wide set is managed by CopyRoom (the convergence engine) —
  templates carry them, `copyroom new` renders them, `copyroom update` converges them, and a
  repo can **overlay** its own additions/modifications on top.

**Your task: make CopyRoom the reference implementation of this convention** — adopt it in
CopyRoom's own repo, ship the canonical skill set as package assets, give CopyRoom a command to
materialize/verify the files, and document the template + overlay story. This is the pilot;
the other `*man` repos and the canonical template follow it later (out of scope — see the end).

- **Repo:** `/home/andrew/Documents/Projects/copyroom`
- **Current branch:** `main` · **Current version:** `0.5.0`
- **Work branch:** create `feat/agent-files` off `main`. Do **not** commit to `main`.

## Design context (settled — do not re-litigate)

1. **Convention (fixed):** `.agents/skills/<name>/SKILL.md`; root `AGENTS.md` is canonical;
   `CLAUDE.md` is a symlink → `AGENTS.md`.
2. **Ownership split (fixed):** version-locked tool skills ship with their tool (installed by
   the tool's own sync — repoman-sync today); fleet/genome skills live in the template and are
   converged by CopyRoom; per-repo divergence is an **overlay**. Repoman's generated entrypoint
   *router* skill stays generated at sync time (it depends on the runtime manager roster) — not
   your problem here.
3. **Overlay contract (fixed), three cases:**
   - *Add* — a local file under `.agents/skills/`; `copyroom update` never touches it.
   - *Edit* — a local edit to a template-managed file; the next update three-way-merges it
     (Copier behavior, `docs/copier/overview.md` §5); a conflict means both sides changed —
     resolved deliberately.
   - *Permanently diverge* — declared in config (`agent.overlay`), mapping to a Copier
     `_exclude` pattern so the template stops managing that skill. Declared divergence instead
     of chronic conflicts.
4. **Two-writer rule:** CopyRoom owns the *canonical set* (package assets + `agent-files`
   command). It must never fight another writer over the same files — the skills it ships are
   the ones under its `assets/`; everything else in `.agents/skills/` belongs to the template or
   the repo.
5. **Layer discipline (family law):** skills are imperative + short, docs are the detailed
   source of truth; skills link to docs, never repeat them. Every skill carries a domain
   boundary and a deferral footer pointing to the entry skill (see repoman's `docs/SKILLS.md`
   contract, linked below).

## Read these first (in order), before touching any code

1. `docs/user/configuration.md` — the three config files and their owners; you'll extend
   `copyroom.project.yml` (advisory, validated, unknown fields ignored — preserve that).
2. `docs/user/adoption.md` and `docs/user/template-editing.md` — the two agent workflows whose
   skills (`copyroom-adopt`, `copyroom-template-edit`) are **referenced in the docs today but do
   not exist as files** — you will write them and fix the references.
3. `docs/copier/overview.md` §5 (the three-way-merge update) and the `_exclude` /
   `_templates_suffix` / `_copy_without_render` sections — the mechanics the overlay contract
   depends on.
4. `docs/developer/architecture.md` (skim) — how commands, modes, and reports are wired.
5. `src/copyroom/cli.py` (the Typer frontend), `src/copyroom/doctor.py` (the check pattern:
   `DoctorCheck(name, ok, detail)` + `format_doctor_report`), `src/copyroom/project/config.py`
   + `project/model.py` (the validated project config you'll extend), `src/copyroom/manage/`
   (adopt/templatize) and `src/copyroom/template/` (the checkout/test/preview loop).
6. repoman's `docs/SKILLS.md` — the skill trigger/deferral discipline (read-only reference).
7. `.scratch/projects/06-typer-migration-and-doctor/` — the most recent project; match its
   conventions for tests and doctor checks.

## Environment & tooling (this repo pins Python via devenv)

- **Always** run commands through the devenv shell, which pins Python 3.13. **Never** use
  ambient `uv`/`python`/`pytest`:
  ```
  devenv shell -- uv run ruff check src/ tests/
  devenv shell -- uv run pytest -q
  devenv shell -- bash demo/walkthrough.sh
  ```
- If you need an interactive command run, tell me to type it with a leading `!`.
- Do **not** add AI-attribution trailers to commits.
- Commit on `feat/agent-files`; don't push unless asked.

## Baseline gate (must be green before you start)

```
devenv shell -- uv run pytest -q
devenv shell -- uv run ruff check src/ tests/
```

## Order of work

### 1. Self-adoption — CopyRoom's own repo follows the convention

- Write a root **`AGENTS.md`** for this repo (concise, ~40-60 lines): what CopyRoom is, the
  `*man` family contract (run inside `devenv shell`; the shared exit-code/report conventions),
  how to work here (`devenv shell -- …`, `uv run pytest`/`ruff`, `demo/walkthrough.sh`), where
  things live (`src/copyroom/`, `docs/` tracks, `.scratch/`), the mode system, and a "start at
  `.agents/skills/copyroom/SKILL.md`" pointer.
- Add **`CLAUDE.md`** as a symlink → `AGENTS.md` (`ln -s AGENTS.md CLAUDE.md`; verify
  `git ls-files -s CLAUDE.md` shows mode `120000`).
- **`.gitignore`:** `.agents/**` and `.pi/**` are currently ignored wholesale. Carve out the
  convention files so they're tracked: keep `.agents/pi/` (and any other platform runtime
  state) ignored, but un-ignore `.agents/skills/`, `AGENTS.md`, `CLAUDE.md`. Note the
  dual-use of `.agents/` in a comment — `.agents/skills/` is the convention; the rest is
  tool state.

### 2. Canonical skill set + the `agent-files` command

- New package module **`src/copyroom/agent/`** with assets under
  `src/copyroom/agent/assets/skills/` (package data, like repoman's `devman/assets/` — ensure
  hatchling ships them: check `pyproject.toml` `[tool.hatch.build.targets.wheel]` and verify
  with `devenv shell -- uv run python -c "import importlib.resources..."` or a built wheel).
- The canonical set (three skills — write them from the docs, imperative + short, each with
  domain boundary + the *"see the `copyroom` skill"* deferral footer):
  - `copyroom/SKILL.md` — the entry/router skill: triggers on copyroom-domain keywords
    ("scaffold a repo", "template drift", "template update", "adopt a repo"…), states the law
    (run in `devenv shell`; mode awareness; never hand-edit `.copier-answers.yml`; the
    template-edit loop is preview-only), routes to the two sub-skills.
  - `copyroom-adopt/SKILL.md` — the adopt/templatize arc (source: `docs/user/adoption.md`).
  - `copyroom-template-edit/SKILL.md` — the `template-checkout` → edit → `template-test` →
    `template-preview` → `template-discard` loop (source: `docs/user/template-editing.md`).
- New Typer command group **`copyroom agent-files`** with:
  - **`agent-files export [--target DIR]`** (default: repo root / `DEVENV_ROOT` / cwd) —
    idempotently materialize the canonical skills into `<target>/.agents/skills/`, write a
    **blueprint `AGENTS.md` only if absent** (never clobber), and ensure `CLAUDE.md` is a
    symlink → `AGENTS.md` (recreate if missing; never replace a real file). Mode-aware: works
    in a project, a template repo, or an unmanaged dir — the natural call is
    `copyroom agent-files export` inside a template's `template/` subdir to seed it.
  - **`agent-files check`** — conformance report: `AGENTS.md` present, `CLAUDE.md` is a symlink
    to it (a regular file is a WARN: it may be a genuine local divergence — flag, don't fix),
    `.agents/skills/` contains the canonical set at the current CopyRoom version, and any
    extra files there are legal (template-shipped or overlay — can't distinguish statically;
    just report them as present).
  - Both print a short structured report (match the existing plain-text report style) and
    conform to the family exit-code contract.

### 3. Config + `doctor`

- Extend the validated `copyroom.project.yml` model with an `agent:` section — all fields
  defaulted, unknown fields still ignored (the config's documented additive contract):
  ```yaml
  agent:
    skills_dir: .agents/skills   # default
    instructions: AGENTS.md       # default
    claude_symlink: true          # default; CLAUDE.md -> AGENTS.md
    overlay: []                   # skills this repo permanently diverges on (→ _exclude)
  ```
  Wire it through `project/config.py`/`project/model.py` and `copyroom inspect`/`status` so it
  round-trips.
- Add an **`agent-files` check to `copyroom doctor`** (warn-level, non-fatal — same precedent
  as repoman's devman checks): presence of `AGENTS.md`, correct `CLAUDE.md` symlink, canonical
  skills present + current. Reuse the `agent-files check` implementation.

### 4. Symlink spike — a hard decision, record it

- In a scratch fixture, verify: does **Copier preserve a `CLAUDE.md → AGENTS.md` symlink**
  through `new` **and** through `update`? (Check the fixture template in `tests/` and
  `demo/walkthrough.sh`'s approach for a faithful test.)
- **Decision required, documented in `.scratch/projects/07-agent-files/`:** if Copier preserves
  the symlink, templates ship it directly and `agent-files export` just ensures it. If not,
  CopyRoom's `new`/`update`/`adopt` get an idempotent **finalize step** that recreates the
  `CLAUDE.md` symlink (prefer a CopyRoom-owned finalize over Copier `_tasks` — adopt has no
  template render, so `_tasks` can't cover it).
- **Jinja gotcha (document regardless):** skill content contains literal `{{ }}` examples.
  Templates must declare `.agents/skills/**` in `_copy_without_render` (or equivalent) so
  skills aren't rendered/destroyed by Copier. State this in the template-authoring doc.

### 5. Docs

- New **`docs/user/agent-files.md`**: the convention; how templates ship the files (skills +
  `AGENTS.md` + `CLAUDE.md` symlink, the `_copy_without_render` gotcha, seeding via
  `copyroom agent-files export`); how `copyroom update` converges them (cite overview §5); the
  overlay contract (add / edit / permanently-diverge via `agent.overlay` → `_exclude`); the
  `.agents/` dual-use carve-out.
- **Fix the broken skill references** in `README.md`, `docs/user/adoption.md`,
  `docs/user/template-editing.md`, and `docs/developer/decisions/0001-cli-command-structure.md`
  — they already point at `.agents/skills/copyroom-*`; make them point at real, committed files
  and link the new doc.
- Add `agent-files.md` to the `docs/user/` index track.

### 6. Tests + verification

- **Unit:** config model parses the `agent:` section (defaults, unknown-ignored); `export` is
  idempotent and never clobbers an existing `AGENTS.md`; `check`/doctor passes after export and
  WARNs when a canonical skill is deleted or `CLAUDE.md` is a regular file.
- **Integration (fixture template):** `copyroom new` from a fixture that ships agent files →
  `.agents/skills/*/SKILL.md` + `AGENTS.md` + `CLAUDE.md` symlink present and correct;
  `copyroom update` to a ref that adds a skill → converges cleanly; `agent.overlay` on a skill
  → the next update stops managing it.
- `devenv shell -- uv run pytest -q` green; `ruff` clean; `demo/walkthrough.sh` still passes.

## Definition of done

- CopyRoom's repo has committed `AGENTS.md`, `CLAUDE.md` (mode `120000` symlink), and
  `.agents/skills/{copyroom,copyroom-adopt,copyroom-template-edit}/SKILL.md`; `.gitignore`
  carve-out in place; zero remaining references to `.agents/skills/copyroom-*` that point at
  nonexistent files.
- `copyroom agent-files export|check` and the `doctor` `agent-files` check exist, tested, and
  documented; `copyroom.project.yml` `agent:` section round-trips through `inspect`/`status`.
- Symlink-spike decision recorded in `.scratch/projects/07-agent-files/`.
- `docs/user/agent-files.md` written and linked; template-authoring gotcha (`_copy_without_render`)
  documented.
- New skills follow the family discipline (domain boundary + deferral footer) and contain no
  fact that the linked doc doesn't own.

## Guardrails

- Every command through `devenv shell --`; never bare `uv`/`python`/`pytest`.
- The canonical skills are **package assets under `src/copyroom/agent/assets/`** — one source
  of truth; the repo's own `.agents/skills/` is materialized from them by `agent-files export`
  and must not be hand-maintained as a second copy.
- `agent-files check`/`doctor` are warn-level only; flipping to fail is a later decision.
- Preserve the additive config contract (unknown fields ignored) and the plain-text report
  style; don't add a new binary or change mode detection.
- Reuse existing seams: `DoctorCheck`, the `_cmd_*`/Typer command pattern, the validated
  config model. Don't fork the CLI into a second frontend.
- Don't touch repoman / gitman / testee / docman / shellij / template-py in this project — see
  follow-ups.

## Out of scope — named follow-ups (do NOT implement here)

- **`gh:Bullish-Design/template-py` (the genome):** embed the canonical set (via
  `copyroom agent-files export`), an `AGENTS.md` blueprint, and the `CLAUDE.md` symlink; add the
  `_copy_without_render` for `.agents/skills/**`.
- **repoman:** default `skillsDir` `.claude/skills` → `.agents/skills`; migrate devman's
  literacy skills/docs into the genome; shrink `install-skills` to the generated entrypoint
  router only; doctor lints skill *ownership* (tool-shipped / genome / overlay) instead of
  installing static copies; retire the `.devman-source` manifest.
- **gitman / testee / docman / shellij:** self-adopt the convention (AGENTS.md + CLAUDE.md
  symlink + their own skills under `.agents/skills/`).
- **A family-wide decision doc** (in repoman or shared): `.agents/skills` + `AGENTS.md` +
  `CLAUDE.md` symlink as the one convention, with the `.agents/` dual-use carve-out.
