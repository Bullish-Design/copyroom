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

**The tag `v0.8.1` is not pushed.** The permission policy denied the tag push. Run this to publish it:

```bash
git -C /home/andrew/Documents/Projects/template-py tag -a v0.8.1 -m 'template-py 0.8.1' cf2ec939f8f1
git -C /home/andrew/Documents/Projects/template-py push origin v0.8.1
```

After the tag exists, update each repo above with `copyroom update --ref v0.8.1`. The change is documentation only, so each update should merge with no conflict.

### template-nix migration: pilot only

template-nix `main` is `7d977175f9d0` and has no release tag after `v0.3.0`. The six consumers pin `v0.2.2` (loci.nvim, nix-desktop, nix-nvim, nix-paseo, nix-secrets) or `v0.3.0` (mnemonix). A migration needs a pushed tag, so no real repo changed. The pilot ran in a disposable clone of nix-desktop with a local tag and was then deleted.

What the pilot proved:

- The baseline source builds from `v0.2.2` with `schemas/v0_2.py`. `adopt --template-only keep` succeeds. Only `repoman.lock` is template-only.
- The `module` layer attaches after the project removes `flake.nix` and the module files and restores them. Only `flake.nix` differed from the baseline in nix-desktop.
- The base update fails with `output path collision: .repoman/project.toml`. The target base renders that file, and the baseline does not. Remove the file, run the update, and restore the project bytes. In four repos the file equals the template file. loci.nvim and nix-secrets carry a stale vendomat comment header.
- The answers file has no `project_id`. The schema then derives `nix_desktop`, but `.devman/project.toml` says `nix-desktop`. Set `project_id` from `.devman/project.toml` in the target answers for every repo.
- The base preview has four conflicts in nix-desktop: `.gitignore`, `AGENTS.md`, `devenv.nix`, and `devenv.yaml`. Each needs a decision. The project keeps vendomat and shellij inputs that the template dropped. `AGENTS.md` is project text, so the project side stays.

Open states to settle before a real run:

- loci.nvim: the default workspace has an uncommitted `devenv.lock` change and a WIP commit above `main`.
- nix-nvim: the default workspace sits on a conflicted WIP commit (`stray-devenv`) with three modified files.
- mnemonix: `main` and the `memprojects` bookmark share one commit. The repo has an untracked `.agents.devman-promoted` directory.
- nix-desktop, nix-paseo, and nix-secrets are clean.
