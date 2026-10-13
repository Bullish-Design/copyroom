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
| nix-desktop | `v0.2.2` | `f3d36d76bf14` (unchanged) | migrated tip `04caa2359d7a` is local; the push was denied by the permission policy |

To land nix-desktop, run from the repo: `jj bookmark set main -r potslvwtswyk && jj git push --bookmark main`.

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

- **The devman overlay imports a missing path.** `~/.config/devman/projects/<repo>/devenv.local.nix` imports `/home/andrew/Documents/Projects/vendomat/modules/devenv.nix`, and that path does not exist. `devenv info` fails inside nix-desktop, nix-paseo, and nix-secrets (nix-desktop failed the same way on an untouched `main`). The tracked tree evaluates with exit 0 without the overlay, before and after the migration. The migration did not edit the overlay files. Remove the vendomat import from each central overlay.
- **nix-paseo tracks a 79-byte `.env`** that its `.gitignore` also lists. It predates the migration and was left alone. Check what it holds.
- **template-nix `.gitignore` writes `.agents/` and `.claude/` with a trailing slash.** That form does not match a symlink. template-py writes the names with no slash for this reason. The links stay ignored here only because each repo lists them in `.git/info/exclude`. A `v0.4.1` fix is small.
- The pilot found that the stub `modules/<name>.nix` can appear for a project that never had one (mnemonix). A later template bump may offer it again.
- The v0.1.0 and v0.1.1 tag changes in nix-secrets were divergent before this work. They were left alone.


Deferred repos:

- loci.nvim (`module_class: none`, so no module layer): the default workspace has an uncommitted `devenv.lock` change and a WIP commit above `main`.
- nix-nvim: the default workspace sits on a conflicted WIP commit (`stray-devenv`) with three modified files.

Settle that work first. Then run the same flow.
