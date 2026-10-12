# 31 — Agent skill ownership: design note

Date: 2026-10-12. Status: proposal, not approved.
Origin: fleet convergence investigation
(`.scratch/projects/30-fleet-convergence-investigation/REPORT.md`, issue #3).

Labels for facts about today: **V** = verified (file or command), **I** =
inferred, **U** = unknown. The design sections state proposals, not facts.

## 1. Problem

Agent files reach a project from several places, and nobody states one owner
per file. Issue #3 is the visible failure. template-py renders
`.agents/devenv/**` into a directory that devman links from its central store.
Copier refuses that write. CopyRoom 0.7.x then wrote the files through the
link, and devman's central store now tracks 234 per-project copies (V).

The same missing rule causes quieter drift:

- devman tracks real copies of `docman-*` skills that lag the docman repo
  (Zensical 0.0.45 against 0.0.67) (V).
- `devenv-lock` still says `gitman land` and explains Copier's
  `_copy_without_render` (V).
- People link each project's skill set by hand. poddantic has roster
  `copy, git, test` but no `testee` skill link, so RepoMan's doctor warns (V/I).
- `.devman/project.toml` has `groups`, which looks like a content selector.
  It selects only Dagu workflows (V).

## 2. Principle

Separate the **source** of each agent file from the **view** that an agent
reads.

- A source has exactly one owner. The owner is whoever changes the content.
- The view is assembled, machine-local, gitignored, and never edited by hand.
- One component assembles the view: devman.
- Templates select skills. They do not ship skill content.

## 3. Today (summary of the survey)

| Item | Today | Label |
|---|---|---|
| `.agents` in a project | one whole-directory symlink to `~/.config/devman/projects/NAME/agents` | V |
| `.claude/skills` | symlink to the same central `agents/skills` | V |
| Per-project skill set | hand-made relative links into `~/.config/devman/skills/` | V |
| Skill pool | `~/.config/devman/skills/`: copyroom (3), devenv-* (7), gitman, testee, writing | V |
| Tool repos | only docman tracks its skills (`skills/`); copyroom, gitman, testee track none | V |
| Version coupling | none; pool skills are hand-synced commits | V |
| Tool versions | the host Nix profile puts copyroom, gitman, docman, testee on PATH; repos pin only RepoMan and the testee module | V |
| Selection policy | RepoMan `check.py:48-69`: `writing` plus one skill per enabled manager plus two copyroom sub-skills; missing links only warn | V |
| RepoMan router | `repoman install-skills` generates `.agents/skills/repoman/SKILL.md` per project | V |
| Template agent files | `AGENTS.md`, `CLAUDE.md -> AGENTS.md`, `.agents/devenv/**` (13 files), `.devman/project.toml` | V |
| Link declarations | `links.yaml` and `devenv.local.nix` both declare the same links | V |

## 4. Ownership model

Four kinds of agent file. Each has one owner and one source location.

| Kind | Examples | Owner | Source |
|---|---|---|---|
| Tool skill | copyroom, gitman, testee, docman | the tool's repo | tracked `skills/<name>/` in the tool repo, shipped in the tool package |
| Fleet skill | writing, devenv-* (devenv literacy) | you, through devman | `~/.config/devman/skills/<name>/` |
| Project skill | this repo's own workflows | the project | tracked `skills/<name>/` in the project repo |
| Project instructions | `AGENTS.md`, `CLAUDE.md -> AGENTS.md` | the project; the template seeds and converges them | tracked files at the repo root |

Rules:

1. One convention for every repo: **a repo's tracked `skills/` directory
   holds the skills that the repo owns.** docman already follows it (V).
2. A tool package installs its skills to `share/agent-skills/<name>/` in its
   Nix output. The skill then always matches the tool binary on PATH. This
   ends the hand-sync commits.
3. Devenv literacy (`.agents/devenv/**`) moves into the devman pool. The
   pool already has 7 `devenv-*` skills (V). Fold the 13 docs into those
   skills as reference files, or into one `devenv` skill. Delete the
   per-project copies from the central store.
4. Templates render no file under `.agents/` or `.claude/`. They may render
   project skill stubs into `skills/`. After birth, the project owns those
   stubs.

## 5. The view

devman assembles `.agents/` in each project as a **real gitignored
directory of per-entry symlinks**. It stops using one symlink for the whole
directory.

```
<repo>/.agents/skills/copyroom  -> <profile>/share/agent-skills/copyroom
<repo>/.agents/skills/gitman    -> <profile>/share/agent-skills/gitman
<repo>/.agents/skills/writing   -> ~/.config/devman/skills/writing
<repo>/.agents/skills/devenv    -> ~/.config/devman/skills/devenv
<repo>/.agents/skills/release   -> ../../skills/release      (project skill)
<repo>/.claude/skills           -> ../.agents/skills
```

Why per-entry links:

- A stray write into `.agents/` creates a local file. It cannot write into
  central storage, so the issue #3 class of bug disappears.
- Project skills join the view by a relative link inside the repo. Your
  `<repo>/.agents/usage/` idea needs this, because a tracked path cannot sit
  under a whole-directory symlink.
- The central store holds only what devman owns. It no longer holds
  per-project copies.

## 6. Selection

The skill set of a project is computed, not curated:

```
view = universal  ∪  tools(roster)  ∪  project.extra  ∪  project.owned
```

- `universal`: fleet skills every project gets (`writing`, `devenv`).
- `tools(roster)`: one skill per enabled RepoMan manager, plus declared
  sub-skills (copyroom-adopt, copyroom-template-edit). RepoMan already
  encodes this mapping in `check.py:57-69` (V). Move it to one shared
  place, so that devman builds the view from it and RepoMan's doctor checks
  against the same data.
- `project.extra`: an optional `skills = [...]` list in
  `.devman/project.toml` for fleet skills outside the roster.
- `project.owned`: every directory under the repo's tracked `skills/`.

The template's selection role is therefore its existing `managers` answer,
plus an optional `skills` list. Both are tracked project files that
CopyRoom converges.

`devman-link reconcile` already runs on shell entry (V). It becomes the
only writer of the view: it adds missing links and removes stale ones.

## 7. Consequences for CopyRoom

1. Add `.agents` and `.claude` to the composer's reserved paths
   (`src/copyroom/local/composer.py`, `RESERVED`). A source that renders
   there is refused with a clear message (exit 1). This encodes the
   boundary in one rule.
2. Lane 1 (project view = jj tracked tree) already makes the gitignored view
   invisible to adopt and preflight.
3. CopyRoom's own skills move back into the CopyRoom repo as tracked
   `skills/copyroom*/`. The Nix package installs them to
   `share/agent-skills/`. This reverses the September 2026 removal
   (`3a05e7f`, `f5c57db`) for a better reason: the tool owns its skill, and
   devman still owns the view.

## 8. Migration order

1. **devman:** support per-entry view assembly and the selection formula.
   Keep the whole-directory link as a fallback until step 6.
2. **Tool repos** (copyroom, gitman, testee, docman): track `skills/` and
   install to `share/agent-skills/` in the Nix package. Move the pool copies
   there, then delete them from the pool.
3. **Fleet skills:** fold `.agents/devenv/**` into the devman `devenv`
   skill. Fix the stale `devenv-lock` text.
4. **RepoMan:** share the roster-to-skill mapping. Decide where the router
   comes from (open question 3). Fix the "Copier" comments.
5. **Templates:** render nothing under `.agents/` or `.claude/`. This is part
   of the template conversion in project 30.
6. **Fleet:** run `devman-link reconcile` per project. Delete
   `projects/NAME/agents/` from the central store once each view is
   per-entry.
7. **CopyRoom:** reserve `.agents` and `.claude`.

Step 5 and step 7 do not depend on the others. They can land with the
project 30 work.

## 9. Open questions

1. Name of the project-owned skill directory: `skills/` (matches docman), or
   a less generic name such as `agent-skills/` to avoid clashes with code
   directories?
2. Where do fleet skills that belong to no tool live in the long term: the
   devman pool, or a dedicated repo (the old "my-ai" layer)?
3. The RepoMan router (`repoman/SKILL.md`) is generated per project. Should
   devman generate it during view assembly, or should RepoMan ship one
   static router skill that reads the roster at run time?
4. Which declaration is authoritative, `links.yaml` or `devenv.local.nix`?
   One should generate the other.
5. Should `.devman/project.toml` `groups` also select fleet skills, or stay
   workflow-only with a separate `skills` key? Separate keys are clearer.
