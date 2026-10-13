# Template-py migration batch B and C

Date: 2026-10-12

Six repos migrated to template-py v0.8.0: flora-qc, inferference, llgym, pyllij, scopeman, and shellij. Each migration passed Testee 4/4 on its final main tree. CopyRoom v0.8.4 reports the v0.8.0 pin, and a second update reports `no-change`. Each local main bookmark matches origin main.

## Results

| Repo | Result | Main commit | Checks |
|---|---|---|---|
| flora-qc | Migrated and pushed | `fa18ad602587c4e2c90f3f6594feb8c109371b5e` | Testee 4/4; CopyRoom pin and no-change verified |
| inferference | Migrated and pushed | `7b9c340bb54d1faea9b6119e6455195d44095005` | Testee 4/4; CopyRoom pin and no-change verified |
| llgym | Migrated and pushed | `c46980c5eb93deb3099231228e7816231e11edce` | Testee 4/4 on main; CopyRoom pin and no-change verified |
| pyllij | Migrated and pushed | `4c6ee82c4eb35dd210e9c9927e6cc9818a19156d` | Testee 4/4 on main; CopyRoom v0.8.4 status reports pin `v0.8.0` at `851a7112f21e`, no pending preview; second update reports `no-change` |
| scopeman | Migrated and pushed | `097b4b1f73889460d0d3e4ae426d858bf163c890` | Testee 4/4 on main; CopyRoom status ok, pin v0.8.0, no-change |
| shellij | Migrated and pushed | `194228ea931f547cfc71345e0c08f8b7cb24fd83` | Testee 4/4 on main; CopyRoom status ok, pin v0.8.0, no-change |

The resolution deleted only `copyroom.project.yml` beyond the template's normal changes. Each repo kept its project-specific checks, tasks, dependencies, and toolchain pins. Shellij's merged `devenv.nix` had two `languages.python` assignments. The migration removed the duplicate and then passed Testee on the final main tree.

## Batch D result: pytuin

pytuin joined template-py directly at v0.8.0. It has no valid template creation ref. Main is `8398ba3886a30d02a12a619b7c71d938a6dfaa84` and matches origin. Testee passed 4/4; CopyRoom status reports pin v0.8.0, and the next update reports `no-change`.

## Additional migration: Linkman

Linkman's default workspace migrated and pushed at `14f5ce2a0d6f49d6e471bc2c6ae828b79f7a2dda`. Testee passed 4/4. CopyRoom reports the v0.8.0 pin, and the next update reports `no-change`. The `v6-linkman` workspace and its side commit `b923040f4b7ad67fb40a1755adba1c91af330d57` remain unchanged.

## Repo not touched

Talkee was not touched, per user direction.

Vendomat was not touched.

## Eventic gate investigation

Eventic was migrated and pushed in batch A. Main is `c1f27c248ff82e2318ba4700ef8bf89fe3e5672c`. CopyRoom 0.8.5 reports the v0.8.0 pin and a second update returns `no-change`. The user waived Testee on the real tree, so no post-migration tests ran there.

The reviewed project configuration installs the `test`, `postgres`, and `migrate` extras, then builds the wheel. It keeps Eventic's existing basedpyright scope (`src/eventic`) and runs pytest with `-W error`. One Ruff-format line changed. The change does not reduce check scope.

The disposable baseline and first migrated Testee results are in [BATCH-A.md](BATCH-A.md). The exact-scope disposable Testee run was canceled under the user's waiver. Do not report a green Testee result for the final Eventic configuration.

## Stale template text

The generated README in scopeman and shellij contains this stale paragraph. The text is in more repos; see [the follow-up](#follow-up-eventic-pin-update-text-scope-and-template-tags):

> This project was created from the `template-py` source. CopyRoom saves a snapshot of that source in `.copyroom-local/`. Pull template updates with:

Its code block says:

```bash
copyroom update                 # preview a three-way merge in a separate workspace
copyroom update --apply PATH    # apply the preview that you reviewed
```

This text does not describe the current update flow. CopyRoom v0.8.4 stores the source in a private Git ref. A project stays pinned until `update --ref` selects a new version.

Proposed replacement:

> This project uses template-py pinned at v0.8.0. Check for newer tags with `copyroom status`. Preview a new version with `copyroom update --ref NEW_REF`, then apply the reviewed preview with `copyroom update --apply PATH`.

The migration did not change this text. A documentation-only template release can carry the replacement after the fleet migration.

## Follow-up: Eventic pin, update text scope, and template tags

Date: 2026-10-12 (later session).

### Eventic pin repaired

The Eventic marker pinned `/tmp/eventic-gate-FMgCga/template-py`. That path was a disposable clone and is gone. CopyRoom could not read the pinned repository from it. Flora had the same fault and got the same repair.

`copyroom update --source /home/andrew/Documents/Projects/template-py/source --ref v0.8.0` made a preview with no conflicts. Only `.copyroom-local.json` changed. The source and render digests stayed equal. Eventic `main` is now `08c05895fc16`, and origin matches. The next update returns `no-change`. No tests ran, as the user directed for Eventic.

### Stale update text: real scope

The paragraph is not only in scopeman and shellij. The `README.md` of 11 repos has it: poddantic, agentman, argentic, flora, flora-core, flora-qc, linkman, llgym, pyllij, scopeman, and shellij. The `AGENTS.md` of 12 repos has the matching "Template updates" bullet: the same 11 plus Eventic. inferference and pytuin have neither text.

### template-py v0.8.1

The commit `cf2ec939f8f1` is on `main` and on origin. It does four things:

- It replaces the stale text in the README template and in `source/static/AGENTS.md`. The new text does not name a version, so it stays true for later tags.
- It fixes the Release note in the template README. CopyRoom does read tags now.
- It bumps `pyproject.toml` and `uv.lock` from 0.7.0 to 0.8.1. The 0.8.0 release left them at 0.7.0.
- It refreshes the `basic` and `probe` goldens. `copyroom release-check py` and `scripts/check_render.py` pass.

The tag `v0.8.1` is published. It is annotated and points to `cf2ec939f8f1`. The user authorized the push after the permission policy first denied it.

### template-py v0.8.1 rollout

Twelve repos moved to `v0.8.1` and are pushed: poddantic, agentman, argentic, Eventic, Flora, flora-core, flora-qc, Linkman, llgym, pyllij, scopeman, and shellij. Each update changed only `.copyroom-local.json`, `AGENTS.md`, and `README.md` (Eventic: no README change). Each repo reports CopyRoom status ok with pin `v0.8.1`, and a second update returns `no-change`. The devman links did not change. No tests ran: the change is documentation only.

| Repo | Main commit |
|---|---|
| poddantic | `9a11378f5754` |
| agentman | `fa2d7baf9fcc` |
| argentic | `fe254979227f` |
| eventic | `a58974b083ee` |
| flora | `55889d4affd7` |
| flora-core | `90e02b0bf525` |
| flora-qc | `474ccfb77fde` |
| linkman | `6c3e2f97e543` |
| llgym | `2d92e9d869d4` |
| pyllij | `70fecebc62b7` |
| scopeman | `d2639d3cc2c4` |
| shellij | `03801bbd2608` |

Three previews had a README conflict:

- Eventic: the whole README is project text. The project side stayed.
- flora-core: the project had edited the paragraph by hand. The template side replaced both hunks.
- Linkman: the project had reworded the first sentence. The template side replaced it, so the text matches the other repos.

inferference and pytuin carry neither stale text and stay at `v0.8.0`.

Two lessons for a later rollout:

- `jj describe` on a change that has a visible twin split each update into two lines with one change ID. Check `divergent()` before you describe, or describe the empty commits before apply.
- Moving `main` to a twin commit with the same tree needs `--allow-backwards`.

agentman and flora-qc still list an old pending preview each (`copyroom status` reports `pending_previews`). Those previews predate this rollout and were left alone.

### template-nix v0.4.0 rollout

The user decided to follow the template and drop the vendomat and shellij inputs. Four clean repos migrated in parallel, one agent per repo. loci.nvim and nix-nvim stay deferred because of unfinished work in their default workspaces.

| Repo | Old tag | Main commit | State |
|---|---|---|---|
| mnemonix | `v0.3.0` | `3fac903655b7` | pushed |
| nix-paseo | `v0.2.2` | `de8b5937b200` | pushed |
| nix-secrets | `v0.2.2` | `83fd48cf9603` | pushed |
| nix-desktop | `v0.2.2` | `04caa2359d7a` | pushed (the user ran the landing after the agent's push was denied) |

Each pushed repo reports CopyRoom status ok with the `base` and `module` layers at `v0.4.0`, and both updates return `no-change`. Every pin points at `/home/andrew/Documents/Projects/template-nix`. No `flake.nix`, `flake.lock`, or module file changed (mnemonix: one stub that `layer add` rendered was deleted). The links are unchanged. No test gate exists for these repos: the template selects no Testee manager.

Flow used for each repo:

1. Build the baseline source from the old tag with `schemas/v0_2.py`, and adopt the base with `--template-only keep`.
2. Drop `.copier-answers.yml` and `copyroom.project.yml`. Release `.repoman/project.toml` in its own commit, so that the new base can render it.
3. Update the base to `v0.4.0` and resolve the conflicts. Apply.
4. Attach the `module` layer directly at `v0.4.0`: back up the three module files, remove them, run `layer add`, and restore the exact bytes.
5. Commit `devenv.lock` as its own change.

Decisions made while the agents ran:

- `project_id` comes from `.devman/project.toml` (hyphen form). The schema default would give `nix_desktop`.
- `.gitignore` takes the template block. The project keeps its own `result`, `result-*`, and `.testee/` rules, because the template does not own them.
- `AGENTS.md` and `README.md` keep the project text. mnemonix `README.md` still names the Vendomat module and is now stale.
- The `devenv.lock` change adds `devman` and switches `repoman` from `git+file` to a `path:` input. Both follow from the template `devenv.yaml`.

Findings for the user:

- **The devman overlays imported V4 vendomat modules.** See "After the rollout" below. The overlay files were cleaned.
- **nix-paseo tracked a 79-byte `.env`.** See "After the rollout" below.
- **template-nix `.gitignore` wrote `.agents/` and `.claude/` with a trailing slash.** Fixed on `main`; see "After the rollout".
- The pilot found that the stub `modules/<name>.nix` can appear for a project that never had one (mnemonix). A later template bump may offer it again.
- The v0.1.0 and v0.1.1 tag changes in nix-secrets were divergent before this work. They were left alone.


Deferred repos:

- loci.nvim (`module_class: none`, so no module layer): the default workspace has an uncommitted `devenv.lock` change and a WIP commit above `main`.
- nix-nvim: the default workspace sits on a conflicted WIP commit (`stray-devenv`) with three modified files.

Settle that work first. Then run the same flow.

### After the rollout

**nix-desktop** is pushed at `04caa2359d7a`. Status is ok, and both updates return `no-change`.

**Overlays.** Eight central overlays in `~/.config/devman/projects/` imported a V4 vendomat consumer module:

- tyo3, nix-paseo, nix-nvim, and nix-desktop pointed at `vendomat/modules/devenv.nix`. That path no longer exists, so `devenv info` failed in the real repos. An untouched `main` failed the same way.
- flora-core, loci.nvim, loci-core, and nix-secrets pointed at the machine-delivered `/run/current-system/sw/share/vendomat/consumer-module.nix` of vendomat 0.5.0. It still resolves today and will not after the machine takes vendomat 0.6.0 or later.

Evidence: vendomat `main` holds V5 only (`663b864`), and its backlog item 4 says to remove the import line and keep the devman link lines. The backlog gates this on RepoMan running managers from `PATH`. RepoMan has not referenced `REPOMAN_TOOLCHAIN_BIN` since at least `v0.12.1`, so the gate is met. The talkee overlay was already cleaned on 2026-10-09 with the same reason.

All eight overlays now import only the devman link module (loci.nvim and tyo3 keep the machine RepoMan import, because their repos declare no `repoman` input). Each evaluated with exit 0 on a scratch copy of its `main`. In the real repos, `devenv info` exits 0 for nix-desktop, nix-paseo, nix-secrets, and mnemonix. The change is one local commit in `~/.config/devman` (that repo has no remote). The `vendomat.toml` files in flora-core, loci.nvim, loci-core, and nix-nvim are now unread. Delete each in its own lane (vendomat backlog item 5).

**Regression found and fixed.** The nix-secrets overlay imported the machine RepoMan module too. The migrated `devenv.yaml` declares the `repoman` input, so the shell failed with `option repoman.enable is already declared`. Checks on a copy without the overlay could not see this. The fix removes the machine RepoMan import from that overlay. Lesson: evaluate a migrated repo with its overlay present.

**nix-paseo `.env`.** The file held one API key. It was added by accident in `c03caa7` (2026-09-22). It is untracked, deleted from disk, and removed from the tree at `22dd17ad809e`. It is still in git history and on origin. Rotate the key. History was not rewritten.

**template-nix `.gitignore`.** `main` is `8d623640dc3e`. The base template and the five goldens now write `.agents` and `.claude` with no trailing slash, with the explanatory comment from template-py. A symlink named `.agents` matches the rule (checked). `scripts/check_render.py` asserted the old slash form and was updated. No tag exists for this fix. `template/.gitignore` in the legacy Copier-era tree is still tracked with the old rule. Nothing reads it. Delete the tree or edit it.

The four migrated repos still carry `.agents/` and `.claude/` with a slash. They reach the fix with `copyroom update --ref v0.4.1` after the tag.

**loci.nvim** (read-only investigation):

- `main` equals origin at `f0cca7c2`. Nothing is unpushed. The WIP commit is empty; its description is stale. The default working copy changes only `devenv.lock`: it removes the unused `shellij` input and node. This is plain lock drift.
- The unreviewed commit `1e6c204b` (already on origin) dropped `cliProvider = "venv"` from `.repoman/project.toml` and `[toolchain] enable = false` from `vendomat.toml`. That moved the repo from the venv toolchain to the store toolchain.
- Predicted migration conflicts: `devenv.nix`, `devenv.yaml`, `.gitignore`, `.repoman/project.toml`. README and `AGENTS.md` merge cleanly. `repoman.lock` is absent and comes from the template. `.copier-answers.yml` must be deleted. The repo has no module layer.
- Decisions for the owner: land or discard the lock prune, confirm the toolchain switch, and say whether `devenv.nix`, `devenv.yaml`, and `.gitignore` keep project text or take the template.
- The remote branch `038-devman-migration` is stale.

**nix-nvim** (read-only investigation):

- `main` equals origin at `edac5777`. The conflicted WIP commit `947aac03` (bookmark `stray-devenv`) is local only. It is a stale, earlier devman migration. Everything in it is already on `main` or outdated. The "uncommitted changes" are only the materialized conflict markers.
- Predicted migration conflicts: `devenv.nix`, `devenv.yaml`, `.gitignore`, `AGENTS.md` (project prose). README, `flake.nix`, and `.repoman/project.toml` merge cleanly. `.copier-answers.yml` and `copyroom.project.yml` must be deleted.
- Recommended: abandon `947aac03`, delete the `stray-devenv` bookmark, then run the migration flow with a `module` layer. The remote branch `038-devman-migration` is stale.
