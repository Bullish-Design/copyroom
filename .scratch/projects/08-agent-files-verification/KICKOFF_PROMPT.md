# Kickoff prompt — verify the agent-files rollout (end-to-end proof + unrun suites + housekeeping)

> Paste everything below the line into a **clean session** opened at the copyroom repo
> root (`/home/andrew/Documents/Projects/copyroom`). It is self-contained: it assumes no
> memory of any earlier conversation. The design is **settled and shipped** — your first
> job is to verify what shipped, not to re-design it.

---

## Who you are / what this is

You are an implementing engineer working in **CopyRoom** (the mode-aware CLI wrapper around
[Copier](https://copier.readthedocs.io/), source in `src/copyroom`), a member of the
**`*man` family** (copyroom, gitman, testee, docman, shellij — orchestrated by repoman).

The family adopted a single **agent-files convention**, and the rollout is **already done
and on `main`** in seven repos. This session has **three jobs**:

1. **Prove it end-to-end** — generate a real project from the published genome
   (template-py), verify every convention artifact, update it, and run `repoman doctor`
   in the generated project. This is the headline deliverable: no test has yet exercised
   the whole loop from the published artifacts.
2. **Run the test suites that were never run** — docman's roundtrip harness, and the
   gitman / testee / shellij suites (the rollout touched only docs/skills/config in those
   repos, but nothing was executed).
3. **Housekeeping** — delete the merged feature branches, mark the follow-ups done,
   fix two doc cross-references, and grep for zero dangling `.claude/skills` references.

The convention itself is **settled** — read the docs below before touching anything, and
do not re-litigate the design.

## State of the world (verify with `git log`/`git tag`, don't assume)

| Repo | Path | main | Tags |
|------|------|------|------|
| copyroom | `~/Documents/Projects/copyroom` | `182cbbf` | `v0.6.0` (agent-files pilot) |
| template-py (the genome) | `~/Documents/Projects/template-py` | `5c0bcc3` | `v0.1.3` (agent-files embed) |
| repoman | `~/Documents/Projects/repoman` | `59d4b11` | — |
| gitman | `~/Documents/Projects/gitman` | `99813da` | — |
| testee | `~/Documents/Projects/testee` | `5d5d1b6` | — |
| docman | `~/Documents/Projects/docman` | `cd4c615` | — |
| shellij | `~/Documents/Projects/shellij` | `f439086` | — |

All working trees should be clean except **testee**, which has two pre-existing
**untracked** scratch dirs (`.scratch/projects/04-fornix-alignment/`,
`.scratch/projects/05-ci-provider-evaluation/`) — **leave them alone**, they are not yours.

## What shipped (read these first, in order — the facts live here, not in your head)

1. `docs/user/agent-files.md` (copyroom) — the convention, the `agent-files export|check`
   commands, the `agent:` project-config section, the overlay contract.
2. `docs/AGENT-FILES.md` (repoman) — the **family decision doc**: `.agents/skills` +
   `AGENTS.md` + `CLAUDE.md` symlink as the one convention, the ownership split
   (tool-shipped / genome / repoman router / overlay), the template requirements
   (`_preserve_symlinks: true`, `_copy_without_render: [".agents/skills/**"]`), and the
   `.agents/` dual-use carve-out.
3. `.scratch/projects/07-agent-files/` (copyroom) — the pilot record: `SPIKE.md` (the
   symlink decision), `README.md` (what shipped), `symlink-spike.sh`.
4. `copier.yml` + `template/` (template-py) — how the genome ships the files
   (`_preserve_symlinks`, `_copy_without_render` for `.agents/skills/**` +
   `.agents/devenv/**`, the canonical copyroom skills, the devenv-literacy layer, the
   genome-authored `AGENTS.md` + `CLAUDE.md` symlink).

## Environment & tooling (every repo pins its own devenv)

- **Always** run commands through each repo's own devenv shell (it pins Python/tools).
  Never bare `uv`/`python`/`pytest`.
  ```
  devenv shell -- uv run pytest -q                 # copyroom / testee / shellij-style repos
  devenv shell -- bash -c 'gitman:lint && gitman:test'   # gitman (devenv tasks)
  devenv shell -- bash -c 'testee:quick'                 # testee
  bash scripts/dev/roundtrip.sh                          # docman (host orchestrator; drives devenv)
  ```
- **Time-budget the nix builds.** A cold `devenv` build can take 10–20 minutes. If a
  build exceeds ~20 minutes, record the exact command as a blocker and move on — never
  burn the whole session on one build.
- If you need an interactive command run, tell the user to type it with a leading `!`.
- Do **not** add AI-attribution trailers to commits.
- Commit per-repo on a branch (e.g. `feat/verify-agent-files`). You may push after the
  step is verified. Never rewrite history.

---

## Order of work

### Workstream A — the end-to-end proof (the headline)

Prove the whole convention works from the **published** genome, in a throwaway dir.

**A1. Publish a small genome update (v0.1.4) so update-convergence is provable.**

- In template-py (`main`), add **one** new genome skill under
  `template/.agents/skills/<name>/SKILL.md` — a realistic devenv-literacy skill with a
  literal `{{ }}` example in the body (so the `_copy_without_render` carve-out is
  exercised). Include a domain boundary + the "see the `repoman` skill" deferral footer.
- Re-render + refresh the golden: `copyroom golden --refresh py basic` (run from
  template-py; copyroom is available via the copyroom repo's devenv, or any devenv with
  copyroom 0.6.0). `copyroom golden py basic` must then be **✅ no diffs**.
- Commit, `git tag v0.1.4` (local tag is enough — the E2E uses the local path).

**A2. Generate a project from the genome.**

```bash
mkdir -p /tmp/afx-e2e
copyroom new /home/andrew/Documents/Projects/template-py /tmp/afx-e2e/proj \
  --answers /home/andrew/Documents/Projects/template-py/scenarios/py/basic.yml
```

(If `new` rejects the answers file, fall back to `--defaults` with
`-d`-style overrides; the answers file is advisory.) Then **assert every artifact** and
record each as a `✓`/`✗` line in the proof table (below):

- `.agents/skills/{copyroom,copyroom-adopt,copyroom-template-edit}/SKILL.md` exist and
  byte-match the copyroom 0.6.0 package assets
  (`src/copyroom/agent/assets/skills/`);
  `copyroom agent-files check --target /tmp/afx-e2e/proj` prints all `✓`.
- The `devenv-*` genome skills + `.agents/devenv/` docs are present (genome-shipped), and
  the new v0.1.4 skill is **not** (it arrives on update — that's the point of A3).
- `AGENTS.md` present; `CLAUDE.md` **is a symlink** to it
  (`stat -c '%F' /tmp/afx-e2e/proj/CLAUDE.md` → `symbolic link`).
- `copyroom.project.yml` carries the `agent:` section (`skills_dir`, `instructions`,
  `claude_symlink`, `overlay`); `copyroom inspect` prints it.
- `.gitignore` has the `.agents/` carve-out.
- `git init` the project and commit; `git ls-files -s CLAUDE.md` shows mode **`120000`**.

**A3. Update convergence.**

- In template-py, the v0.1.4 skill is already committed/tagged (A1).
- From `/tmp/afx-e2e/proj`: `copyroom update v0.1.4` — must complete **cleanly**
  (no conflicts/rejects).
- Assert: the new skill converged (byte-identical to the template, `{{ }}` intact);
  `CLAUDE.md` is still a symlink; `copyroom agent-files check --target /tmp/afx-e2e/proj`
  still all `✓`.

**A4. Overlay contract (cheap, do it).**

- Declare `agent.overlay: [copyroom-adopt]` in `/tmp/afx-e2e/proj/copyroom.project.yml`,
  commit it, then in template-py edit `template/.agents/skills/copyroom-adopt/SKILL.md`
  and tag **v0.1.5**. This changes the rendered tree, so re-render + refresh the golden
  (`copyroom golden --refresh py basic`) and keep it green before tagging.
- `copyroom update v0.1.5` → the overlaid skill must keep the project's local version
  while everything else converges; `copyroom agent-files check` reports it as
  "declared in agent.overlay — divergence expected" and stays `ok`.

**A5. Ownership lint in the generated project.**

- Build the generated project's devenv (it imports repoman/gitman/testee via
  `path:` sources in its rendered `repoman.lock` — this is the slow nix build; time-budget
  it). Install the toolchain + generate the entrypoint:
  `cd /tmp/afx-e2e/proj && devenv shell -- repoman-sync`.
- Then `devenv shell -- repoman doctor` and assert the self-check rows:
  `skill:tool-shipped` **ok** (canonical copyroom skills present) and
  `skill:genome-overlay` **ok** listing the `devenv-*` skills. The `repoman` entrypoint
  skill exists under `.agents/skills/repoman/`.
- If the devenv build exceeds the budget, record the exact blocker + commands instead of
  skipping silently.

**Proof record:** write the full assertion table to
`.scratch/projects/08-agent-files-verification/E2E_PROOF.md` (repo: copyroom). Every
assertion is `✓` or `✗` with the exact command that produced it. `✗` means a real bug —
fix it (on a branch, with tests) before moving on.

### Workstream B — run the never-run suites

The rollout touched only docs/skills/config in these repos (no Python), but nothing was
executed. Close that gap:

1. **docman** — the authoritative check is the CI harness:
   `bash scripts/dev/roundtrip.sh` (run from the docman root; the host needs `devenv` +
   `git`). It drives a throwaway consumer repo that imports docman and asserts the full
   lifecycle — including that `docs-skills-install` links the skill pack into
   `.agents/skills/`. Time-budget the nix builds. **Green roundtrip = the path change is
   proven end-to-end.**
2. **gitman** — `devenv shell -- bash -c 'gitman:lint && gitman:test'`.
3. **testee** — `devenv shell -- bash -c 'testee:quick'` (the fast subset; the full
   detailed run is optional if slow).
4. **shellij** — its check command (read `copyroom.project.yml`; likely
   `devenv shell -- repoman doctor` or pytest).

Any failure here is a regression from the rollout — fix it on a branch in that repo with a
test, don't paper over it.

### Workstream C — housekeeping

1. **Delete the merged `feat/agent-files` branches** on the six remotes
   (copyroom's is already gone): `git push origin --delete feat/agent-files` for
   template-py, repoman, gitman, testee, docman, shellij.
2. **Mark the follow-ups done** in `.scratch/projects/07-agent-files/README.md` — the
   "Follow-ups (scoped out…)" section now ships; rewrite it as "completed" with the
   per-repo main SHAs.
3. **Doc cross-reference** in copyroom `docs/user/agent-files.md`: the template section
   names `_copy_without_render: [".agents/skills/**"]`; add a line that templates shipping
   docs under `.agents/devenv/` should also list `".agents/devenv/**"` (the genome does
   both). Also mention `_preserve_symlinks: true` is required (it is in the SPIKE section
   — make sure it reads as a template requirement, not a suggestion).
4. **Zero-dangling-reference sweep**: `grep -rn "\.claude/skills"` across the seven repos'
   tracked `src/`, `docs/`, `modules/`, `scripts/`, `README*` (exclude `.git/`, `.devenv/`,
   `node_modules/`, and `tests/consumer-example` histories). Historical notes under
   `.scratch/` and in git history are fine; any **live** reference to `.claude/skills`
   (install paths, defaults, docs that tell a user where skills land) is a bug — fix it.
5. **Optional, decide with the user before doing it:** bump repoman `0.3.0 → 0.4.0`
   (feature release) and copyroom's own `docs/user/agent-files.md` mention of the
   follow-up status. Only bump if the user wants a release; otherwise record it as a
   decision.

## Definition of done

- `E2E_PROOF.md` written with every assertion `✓` (or an explicit `✗` that was fixed on a
  branch with a test).
- docman roundtrip green **or** a recorded blocker with the exact command that will finish
  it.
- gitman/testee/shellij suites green (or recorded blockers).
- Merged `feat/agent-files` branches deleted from all six remotes.
- 07 scratch README follow-ups marked done; `docs/user/agent-files.md` cross-references
  fixed.
- Zero live `.claude/skills` references across the seven repos (historical notes exempt).
- All work committed per-repo on branches; `main` untouched unless a fix lands (then on a
  branch + reviewed, and pushed only after the full gate for that repo).

## Guardrails

- Every command through the relevant repo's `devenv shell --`; never bare
  `uv`/`python`/`pytest`/`git` subprocesses from outside a devenv.
- The convention is **settled** — read `docs/user/agent-files.md`, `docs/AGENT-FILES.md`,
  and the 07 scratch `SPIKE.md`/`README.md` before touching anything; do not re-open the
  symlink decision or the ownership split.
- The throwaway E2E project lives in `/tmp/afx-e2e/` — never generate into a real repo.
- Do **not** touch the two pre-existing untracked scratch dirs in testee.
- Time-budget nix builds (~20 min); record blockers, don't burn the session.
- No AI-attribution trailers in commits. Commit on branches; push after verification;
  never rewrite history.
