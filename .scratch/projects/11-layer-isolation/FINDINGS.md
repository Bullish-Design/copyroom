# Findings — cross-repo agent-file distribution

The study examined a repoman-managed repository with three commits:
`951110a` (initial), `e21bb4e` (canonical agent configuration), and `d12ee10`
(the sync script as a PEP 723 script). The source repository is now archived.

## What the repository contained

Its tracked payload included:

```text
AGENTS.md                                  # shared agent instructions
CLAUDE.md -> AGENTS.md
.agents/skills/copyroom/SKILL.md           # copy of a package asset
.agents/skills/copyroom-adopt/SKILL.md     # copy of a package asset
.agents/skills/copyroom-template-edit/…    # copy of a package asset
.agents/skills/gitman/SKILL.md             # copy of the Gitman skill
.agents/skills/repoman/SKILL.md            # copy of a generated router
.agents/skills/<project>/SKILL.md          # repository-specific skill
scripts/                                   # file distribution script
devenv.nix / devenv.yaml / pyproject.toml / gitman.toml
```

The script walked `.agents/skills/**/SKILL.md` and copied each file into a
target repo. It wrote `AGENTS.md` when absent or when called with `--force`, and
it repaired the symlink.

## Four problems

### 1. It duplicated CopyRoom's distribution role

The file-copy script had no version record, three-way merge, conflict report,
or answer to “which repos are behind?”. CopyRoom already handled template
convergence through Copier. Independent layers reused that path.

### 2. It crossed file ownership boundaries

The family ownership decision assigned each file set to its source:

| File set | Owner | Materialized by |
|---|---|---|
| CopyRoom skills | CopyRoom package | `copyroom agent-files export` |
| Genome skills and docs | template repository | `copyroom update` |
| Generated manager router | repo manager roster | `repoman install-skills` |
| Gitman skill | Gitman | Gitman's own sync |
| Repository-specific skill | source repository | repository workflow |

The copied router was the clearest mismatch. Its content depends on each repo's
manager roster, so one generated snapshot cannot be correct in every repo.

### 3. `AGENTS.md` belongs to each repo

The family decision assigns `AGENTS.md` to the repo. Each file can describe
project-specific behavior. A forced whole-file copy would destroy local content.
Without force, the old script could not update the file. A layer template with
`_skip_if_exists` supplied a third option: seed a missing file and keep an
existing one.

Some shared material from the source instructions still had value, but it did
not belong in each repo's canonical `AGENTS.md`. The ownership review assigned
those skills to their source tools.

### 4. Nothing checked the copies

The source repository had no `tests/`, although its project configuration named
that test path. It had no golden render. CopyRoom's doctor did not report drift
in the copied files.

## The blocker on the first design

Applying a second template was blocked because CopyRoom read one fixed answers
file in four places:

- `project/update.py` loaded `.copier-answers.yml`.
- `manage/adopt.py` used it for the managed-repo refusal.
- `template/workspace.py` read it for reports.
- `session/detector.py` used it as a project marker.

That assumption allowed one template per repo. The spike showed that Copier
supports several answers files. The layer feature removed the CopyRoom limit.

## Adjacent gap

Gitman's skill had no owner-side materializer. Gitman shipped its skill in its
own repo, repoman installed only its generated router, and CopyRoom exported
only its own package set. A copied skill had hidden that ownership gap. The
study assigned the gap to Gitman and repoman, not to CopyRoom layers.
