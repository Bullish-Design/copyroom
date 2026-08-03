# 07 — CopyRoom: Repo Review & Catch-Up — PLAN

Sequenced, numbered plan for the **remaining** work. CopyRoom itself is
feature-complete and green at `v0.5.0`; be honest about that. The genuine remaining
items are almost all the **cross-repo RepoMan follow-up** that the `06` guide
(`.scratch/projects/06-typer-migration-and-doctor/IMPLEMENTATION_GUIDE.md` §7) queued
but never landed, plus two explicitly-optional hygiene items.

Ordering rationale: land the cross-repo integration first (it's the highest-value gap
and the reason `06` existed), then the optional polish, then a close-out.

> Conventions for every step: run in-repo commands via `devenv shell -- …`; route all
> VCS through **gitman** (jj + colocated git), branch/lane first, never raw jj/git;
> **verify (tests green) before commit**; commit in logical groups; no AI-attribution
> trailers. Do not push without an explicit ask.

---

## Step 1 — Land the RepoMan `doctor` integration for copyroom  (repo: `repoman`)

The motivating gap. `copyroom doctor` exists at v0.5.0 but RepoMan still opts it out.

- **Deliverable:** `repoman/src/repoman/registry.py` — change the `copy`/copyroom entry
  from `doctor=None` back to the default `doctor=["doctor"]`; delete the
  `# copyroom (v0.4) has no doctor verb…` comment (currently line ~60-62).
- **Files:** `repoman/src/repoman/registry.py`.
- **Acceptance:** `repoman`'s own suite green via its devenv/testee; `repoman doctor`
  in a repo managing copyroom now dispatches `copyroom doctor` and aggregates its exit
  code (0 healthy). No `doctor=None` remains for copyroom.
- **Risks:** RepoMan may pin a copyroom *version*; ensure the roster points at a build
  that has `doctor` (v0.5.0+). If RepoMan resolves copyroom from a git tag, bump that
  ref. Low blast radius — one registry entry.

## Step 2 — Re-run the RepoMan N=2 spike and refresh SPIKE.md  (repo: `repoman`)

- **Deliverable:** re-execute the spike (`repoman/tests/consumer-example` →
  `repoman doctor`); capture the new transcript showing copyroom's doctor running &
  aggregating. Update `repoman/SPIKE.md` to record that copyroom now conforms — replace
  the "copyroom (v0.4) has no `doctor`" finding (line ~142) and the "no doctor, skipped"
  transcript (line ~131) with the conforming result, **keeping** the general principle
  that the conductor stays tolerant of managers that lack a verb.
- **Files:** `repoman/SPIKE.md` (+ any spike fixture under `repoman/tests/`).
- **Acceptance:** SPIKE.md no longer claims copyroom lacks doctor; the recorded
  aggregated-exit example includes copyroom's check.
- **Risks:** Depends on Step 1. Keep it a doc/transcript refresh — don't rewrite the
  spike's architecture narrative.

## Step 3 — (Optional hygiene) Promote `_cache_root` → public `cache_root`  (repo: `copyroom`)

Removes the cross-module private-name import the `06` guide (§4.1 note) flagged.

- **Deliverable:** add public `cache_root()` in `src/copyroom/template/workspace.py`
  (keep `_cache_root` as a thin alias for internal callers, or migrate them); point
  `src/copyroom/doctor.py:19` at the public name.
- **Files:** `src/copyroom/template/workspace.py`, `src/copyroom/doctor.py`, and any
  other `_cache_root` caller (grep first).
- **Acceptance:** `devenv shell -- pytest` green; `doctor` no longer imports a
  `_underscore` name across modules; `copyroom doctor` still reports the same cache path.
- **Risks:** Minor — a rename touching a public-ish resolver. Preserve behaviour for
  `COPYROOM_CACHE_DIR` / `XDG_CACHE_HOME`. Skip if not worth the churn (it is optional).

## Step 4 — (Optional doc) Add a `doctor` note to the Allium spec  (repo: `copyroom`)

- **Deliverable:** a short note in `.scratch/specs/copyroom.allium` (or a session-adjacent
  spec) recording that `doctor` is an **env-only, mode-independent** verb outside the
  session state machine — so the spec matches the shipped surface. `doctor` has no state
  transitions to model, so this is documentation, not a new invariant test.
- **Files:** `.scratch/specs/copyroom.allium`.
- **Acceptance:** spec mentions `doctor`; `tests/spec` still green (no new invariant that
  the code can't satisfy).
- **Risks:** Don't introduce a spec invariant that forces a `tests/spec` change without a
  matching state-machine edge. Keep it descriptive. Skip if the spec is intentionally
  session-only.

## Step 5 — Fresh code-review pass + close-out  (repo: `copyroom`)

Since the last review was pre-migration, do a light review of the Typer frontend +
`doctor` (the only code that changed since the `05` deep review) to confirm no new
findings, then close the project.

- **Deliverable:** run `/code-review` (or an equivalent read-through) scoped to
  `cli.py` + `doctor.py`; capture any findings in this dir as `CODE_REVIEW_REPORT.md`
  (only if findings exist). Confirm the full ritual: `devenv shell -- pytest` green,
  `copyroom --help` lists every command incl. `doctor`, `copyroom doctor[/ --json]` and
  `copyroom --version` behave.
- **Files:** (optional) `.scratch/projects/07-repo-review-and-catch-up/CODE_REVIEW_REPORT.md`.
- **Acceptance:** either "no findings — v0.5.0 clean" recorded, or a short remediation
  list; suite green; smoke commands pass.
- **Risks:** None material. If findings surface, spin them into a numbered remediation
  sub-plan rather than fixing ad-hoc.

---

## Honesty note

Steps 3–5 are polish/verification, and Steps 1–2 are in a *different* repo (`repoman`),
not copyroom. **Inside the copyroom repo, there is no outstanding feature or bug work at
v0.5.0** — the concept is fully implemented, tests pass, docs are current. If the intent
is strictly "finish copyroom", the honest answer is: it's done; the only real
loose thread is wiring RepoMan to actually call the `doctor` command copyroom now
provides (Steps 1–2).
