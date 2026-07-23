# Kickoff Prompt — CopyRoom Repo Review & Catch-Up

> Paste everything below the line into a **clean session** opened at the CopyRoom repo
> root (`/home/andrew/Documents/Projects/copyroom`). It is self-contained: it assumes no
> memory of the review conversation. Your first job is to read the two planning docs,
> not to start editing.

---

## Who you are / what this is

You are an implementing engineer picking up **CopyRoom**, a mode-aware CLI wrapper around
[Copier](https://copier.readthedocs.io/) (the project-templating engine that *generates*
a project from a template and later *updates* it via a three-way merge). CopyRoom adds
mode-aware command routing, safe lifecycle management, a template-author's "workshop"
(render / golden / update-test / release-check), agentic template editing
(`template-checkout` → `template-test` → `template-preview` → `template-discard`), repo
adoption/templatization (`adopt` / `templatize`), a `--trust` gate for template hooks,
and an environment `doctor`. It owns its own agent skills (`copyroom-adopt`,
`copyroom-template-edit`, `propagate`). Source is in `src/copyroom/`.

## Current state (as of the review)

- **CopyRoom is mature and feature-complete at `v0.5.0`** (tagged; `HEAD` is on it; tree
  clean). `pyproject.toml` + `src/copyroom/__init__.py` both read `0.5.0`. The full
  `pytest` suite is **green**.
- Recently landed: two review-remediation passes (through `0.4.0`) and the
  **argparse → Typer** CLI migration plus a new **`doctor`** command (→ `v0.5.0`,
  commit `4addb2b`). `src/copyroom/cli.py` is now a Typer app; `doctor.py` and
  `tests/unit/test_doctor.py` exist; docs are current.
- **The one real loose thread is cross-repo:** `copyroom doctor` exists, but **RepoMan
  still opts it out** — `repoman/src/repoman/registry.py:60` has
  `doctor=None,  # copyroom (v0.4) has no doctor verb…`, and `repoman/SPIKE.md:142`
  still records that copyroom lacks doctor. This was queued in
  `.scratch/projects/06-typer-migration-and-doctor/IMPLEMENTATION_GUIDE.md` §7 but never
  landed.

## Read these first (in order), before touching any code

1. `.scratch/projects/07-repo-review-and-catch-up/OVERVIEW.md` — what CopyRoom is, the
   verified current command surface, and the concept-vs-reality gap table.
2. `.scratch/projects/07-repo-review-and-catch-up/PLAN.md` — the sequenced, numbered
   remaining-work plan (per-step deliverables / files / acceptance / risks).
3. For background on the migration: `.scratch/projects/06-typer-migration-and-doctor/`
   (README + IMPLEMENTATION_GUIDE — note §7 is the un-landed RepoMan follow-up).

## Your first task

**Step 1 of PLAN.md — land the RepoMan `doctor` integration** (in the *`repoman`* repo,
a sibling: `/home/andrew/Documents/Projects/repoman`). Change the copyroom entry in
`repoman/src/repoman/registry.py` from `doctor=None` back to the default
`doctor=["doctor"]` and drop the stale comment, so `repoman doctor` dispatches
`copyroom doctor` and aggregates its exit code. Then Step 2 refreshes `repoman/SPIKE.md`.
Verify RepoMan's own suite is green before committing. Confirm copyroom's roster ref
points at a build that actually has `doctor` (v0.5.0+).

If asked to keep work strictly inside copyroom, the honest report is: **copyroom itself
has no outstanding feature/bug work at v0.5.0** — proceed instead to PLAN Steps 3–5
(optional `_cache_root`→`cache_root` promotion, an Allium `doctor` note, and a fresh
scoped code-review of `cli.py`+`doctor.py`).

## Conventions (non-negotiable)

- **devenv for every in-repo command.** Run tests/lint/build/scripts via
  `devenv shell -- <cmd>` (e.g. `devenv shell -- pytest`). Never invoke bare
  `uv`/`python`/`pytest` — the ambient shell lacks the project's pinned env.
- **VCS through gitman** (jj + colocated git); never raw jj/git. **Branch/lane first**
  when on the default branch. Commit in logical groups as you work. **Do not push**
  without an explicit ask.
- **Verify before you commit** — the test suite must be green (`devenv shell -- pytest`,
  in whichever repo you're editing) before any commit. Never bury a command's failure.
- **No AI-attribution trailers** in commits, PRs, code, or docs.
- Work happens in **two repos**: Steps 1–2 in `repoman`, Steps 3–5 in `copyroom`. `cd`
  into the right repo before doing git work; each is its own repo with its own devenv.

When done, report: which steps landed, the tests you ran and their result, and anything
you intentionally deferred (e.g. the optional Steps 3–4).
