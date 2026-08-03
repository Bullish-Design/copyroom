# E2E proof — the agent-files rollout, verified from the published genome

Project: `.scratch/projects/08-agent-files-verification` · date: 2026-08-03
Generated project: `/tmp/afx-e2e/proj` (throwaway — never a real repo).

**Headline:** the whole convention loop was exercised from the **published**
artifacts — `copyroom new` → assert → `copyroom update` → assert → overlay →
`repoman doctor` in the generated project. Every assertion below is `✓` with the
exact command that produced it.

## Environment

- copyroom `main` at `182cbbf` (tag `v0.6.0`) + kickoff commit `723a1bc`; copyroom
  0.6.0 run via the copyroom repo's devenv.
- template-py branch `feat/verify-agent-files`, tags `v0.1.4` (devenv-lock) and
  `v0.1.5` (copyroom-adopt answers-are-advisory), both local.
- Every command through the relevant repo's `devenv shell --`; no bare
  uv/python/pytest/copier.
- The generated project's devenv build was **warm** (nix store pre-populated by the
  family's other devenvs) — ~2 min, well inside the 20-min budget.

## A1 — genome update published (v0.1.4, then v0.1.5 for the overlay test)

| # | Assertion | Result | Command |
|---|-----------|--------|---------|
| A1.1 | New genome skill `template/.agents/skills/devenv-lock/SKILL.md` — devenv-literacy, literal `{{ }}` (2×), domain boundary, `repoman` deferral footer | ✓ | `git show b4cea3c --stat` |
| A1.2 | Copier renders the **latest tag**, not HEAD (untracked/HEAD-only files excluded) — the tag must exist before the golden refresh | ✓ (finding) | `copier copy …` (no v0.1.4 tag → skill absent; tag `v0.1.4` → present) |
| A1.3 | Render picks up exactly the new skill; byte-identical to the template, `{{ }}` intact (the `_copy_without_render` carve-out) | ✓ | `copyroom golden py basic` → `Added: ['.agents/skills/devenv-lock/SKILL.md']`; `diff template/… generated/…` → empty; `grep -c '{{' …` → 2 |
| A1.4 | `copyroom golden --refresh py basic` snapshots; `copyroom golden py basic` → ✅ no diffs | ✓ | `copyroom golden py basic` → `Golden: py/basic — ✅ OK (no diffs)` |
| A1.5 | Committed on `feat/verify-agent-files`; tag `v0.1.4` at the skill commit | ✓ | `git tag v0.1.4` (local) |
| A1.6 | Same flow for the A4 overlay-test edit (`copyroom-adopt` + "Answers are advisory"), tag `v0.1.5`, golden green | ✓ | `git tag v0.1.5`; `copyroom golden py basic` → ✅ |

## A2 — project generated from the published genome (at v0.1.3)

| # | Assertion | Result | Command |
|---|-----------|--------|---------|
| A2.1 | `copyroom new <template-py> /tmp/afx-e2e/proj --answers scenarios/py/basic.yml` succeeds | ✓ | `copyroom new …` → `Project created in /tmp/afx-e2e/proj` |
| A2.2 | Project records `_commit: v0.1.3` (generation pinned to the last *published* version) | ✓ | `grep _commit .copier-answers.yml` → `_commit: v0.1.3` |
| A2.3 | `.agents/skills/{copyroom,copyroom-adopt,copyroom-template-edit}/SKILL.md` exist and byte-match copyroom 0.6.0 package assets | ✓ | `diff -q <proj>/.agents/skills/<s>/SKILL.md src/copyroom/agent/assets/skills/<s>/SKILL.md` → identical ×3 |
| A2.4 | `copyroom agent-files check --target /tmp/afx-e2e/proj` → all canonical `✓`, extras reported, exit 0 | ✓ | `copyroom agent-files check …` (exit=0) |
| A2.5 | Genome-shipped `devenv-*` skills (8) + `.agents/devenv/` docs present; v0.1.4 skill `devenv-lock` **absent** at v0.1.3 | ✓ | `ls .agents/skills/` (10 entries, no `devenv-lock`); `ls .agents/devenv/` |
| A2.6 | `AGENTS.md` present; `CLAUDE.md` is a symlink → `AGENTS.md` | ✓ | `stat -c '%F' CLAUDE.md` → `symbolic link`; `readlink` → `AGENTS.md` |
| A2.7 | `copyroom.project.yml` carries `agent:` (`skills_dir`, `instructions`, `claude_symlink`, `overlay`) and `copyroom inspect` prints it | ✓ | `copyroom inspect` → `Agent files: skills_dir .agents/skills · instructions AGENTS.md · claude_symlink True · overlay (none)` |
| A2.8 | `.gitignore` has the `.agents/` carve-out | ✓ | `grep -E '^\.agents/|^!\.agents/' .gitignore` → 5 lines |
| A2.9 | `git init` + commit; `CLAUDE.md` tracked as a symlink (mode `120000`) | ✓ | `git ls-files -s CLAUDE.md` → `120000 …` |

## A3 — update convergence (v0.1.3 → v0.1.4)

| # | Assertion | Result | Command |
|---|-----------|--------|---------|
| A3.1 | `copyroom update v0.1.4` completes cleanly (no conflicts/rejects) | ✓ | `copyroom update v0.1.4` → `Project updated to v0.1.4` |
| A3.2 | Only `.copier-answers.yml` modified; new skill added as the only content change | ✓ | `git status --short` → `M .copier-answers.yml` + `?? .agents/skills/devenv-lock/`; `git diff --stat ':(exclude).copier-answers.yml'` → empty |
| A3.3 | `devenv-lock` converged byte-identical to the template, `{{ }}` intact (carve-out survives the three-way merge) | ✓ | `diff template/…/devenv-lock/SKILL.md <proj>/…` → empty; `grep -c '{{'` → 2 |
| A3.4 | `CLAUDE.md` still a symlink | ✓ | `stat -c '%F'` → `symbolic link` → `AGENTS.md` |
| A3.5 | `copyroom agent-files check` still all `✓`; recorded `_commit` advances to v0.1.4 | ✓ | `check` exit=0; `grep _commit` → `_commit: v0.1.4` |

## A4 — overlay contract

| # | Assertion | Result | Command |
|---|-----------|--------|---------|
| A4.1 | `agent.overlay: [copyroom-adopt]` declared in the project's `copyroom.project.yml`, committed | ✓ | `git show 9c83162 -- copyroom.project.yml` |
| A4.2 | Template edit to `copyroom-adopt` shipped as v0.1.5; golden green before tagging | ✓ | `copyroom golden py basic` → ✅ after `--refresh` |
| A4.3 | `copyroom update v0.1.5` → overlaid skill keeps the project's local version (no "Answers are advisory") while everything else converges | ✓ | `grep -c 'Answers are advisory' <proj>/.agents/skills/copyroom-adopt/SKILL.md` → 0; template has it (1); only `.copier-answers.yml` changed |
| A4.4 | `copyroom agent-files check` reports `copyroom-adopt: ⚠️ declared in agent.overlay — divergence expected` and stays exit 0 | ✓ | `copyroom agent-files check …` (exit=0) |
| A4.5 | `devenv-lock` (converged in A3) untouched by the v0.1.5 update | ✓ | `grep -c '{{'` → 2 (unchanged) |

## A5 — ownership lint in the generated project

| # | Assertion | Result | Command |
|---|-----------|--------|---------|
| A5.1 | Generated project's devenv builds (imports repoman/gitman/testee via `path:` in `repoman.lock`) | ✓ | `devenv shell -- repoman-sync` — build ~2 min, no blockers |
| A5.2 | `devenv shell -- repoman-sync` installs the toolchain + writes the entrypoint skill | ✓ | log: `repoman: wrote entrypoint skill → .agents/skills/repoman/SKILL.md` |
| A5.3 | `repoman doctor` self-check `skill:tool-shipped` **OK** (canonical copyroom skills present) | ✓ | `devenv shell -- repoman doctor` → `OK skill:tool-shipped — canonical copyroom skills present` |
| A5.4 | `repoman doctor` self-check `skill:genome-overlay` **OK** listing the `devenv-*` skills | ✓ | → `OK skill:genome-overlay — genome or overlay: devenv-authoring, devenv-inputs, devenv-lock, devenv-module-edits, devenv-processes, devenv-python-venv, devenv-run-commands, devenv-troubleshoot` |
| A5.5 | `skill:entrypoint` OK — `.agents/skills/repoman/SKILL.md` exists | ✓ | `OK skill:entrypoint — …/.agents/skills/repoman/SKILL.md`; `head .agents/skills/repoman/SKILL.md` |
| A5.6 | copyroom doctor in the project: `agent-files — conformant` | ✓ | `OK agent-files — conformant` |
| A5.7 | `skill:copy:defers` OK (canonical skills defer to the repoman router) | ✓ | `OK skill:copy:defers` |

**A5 context notes (not convention failures):**
- `repoman doctor` exits **2** because of `FAIL uv:test` / `FAIL installed:test`
  (testee not declared in `pyproject.toml`) and gitman `XX colocated` / `!! remote`
  / `!! trunk`. Root causes, both external to this rollout: (a) the **concurrent
  project-12 work** advanced repoman `main` past the state this genome was written
  against — repoman-sync is now consumer/machine-mode and testee moved from
  `repoman.lock` to `pyproject.toml [dependency-groups] dev`; (b) the post-create
  hooks (`gitman init --colocate`, `gitman seed`) were never run — the project was
  generated without `--trust` and committed with plain git. Neither touches the
  agent-files convention rows, all of which are OK.
- `WARN lock:orphan` (per-repo `repoman.lock` obsolete) is the same project-12
  skew; the machine toolchain venv at `~/.local/share/repoman/venv` (bootstrapped
  by the user) satisfied the consumer-mode sync.

## Findings & deviations recorded

1. **`copier copy` renders the latest tag of a local source, not HEAD** (copier
   copy / `copyroom new` / `copyroom golden`). Untracked and non-tagged files are
   invisible to a render. Consequences: (a) A1 must tag *before* the golden
   refresh (the v0.1.3 history does the same — tag `v0.1.3` → content commit
   `d52b077`, golden refresh `5c0bcc3` after); (b) the kickoff's A2/A3 sequence
   (generate at v0.1.3, then update to v0.1.4) required the v0.1.4 tag to be
   absent at generation time. Executed: temporarily removed the local tag,
   generated (project at v0.1.3, no `devenv-lock`), restored the tag, then
   `copyroom update v0.1.4` converged the skill. Tag delete/restore is local-only
   and does not rewrite history. This is a sequencing note, not a copyroom bug —
   `new` rendering the latest published version is the intended behavior.
2. **Concurrent project-12 work advanced repoman `main`** (`59d4b11` →
   `fa6d7f5`, 4 commits, ahead of origin, not pushed) mid-session; the working
   tree went from dirty (uncommitted project-12 PRs) to clean as the user
   committed. The generated project's devenv therefore built against the current
   repoman. The manager-roster interface (`repoman.managers = [copy git test]`,
   `vendor.enable`) is intact; the doctor's skill rows (`skill:tool-shipped`,
   `skill:genome-overlay`, `skill:entrypoint`) still exist and are all OK. The
   testee-in-pyproject model is the genome's next follow-up, tracked by project 12.
3. `repoman`'s entrypoint skill, once written by `repoman-sync`, appears in
   `copyroom agent-files check` extras as "template-shipped or overlay — reported,
   not judged" — correct per the two-writer rule.

## Conclusion

All assertions `✓`. The agent-files rollout is proven end-to-end from the
published genome: new projects get the convention byte-for-byte (canonical skills,
genome fleet skills, `AGENTS.md`, `CLAUDE.md` symlink committed at mode `120000`),
updates converge new genome content cleanly with `{{ }}` intact, the overlay
contract keeps a permanently-diverging skill local while everything else updates,
and repoman's ownership lint reports tool-shipped and genome-overlay rows OK in
the generated project.
