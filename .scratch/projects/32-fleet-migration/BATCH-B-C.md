# Template-py migration batch B and C

Date: 2026-10-12

All six repos migrated to template-py v0.8.0. Each migration passed Testee
4/4 on its final main tree. CopyRoom reports the v0.8.0 pin, and a second
update reports `no-change`. Each main bookmark matches its remote.

## Results

| Repo | Result | Main commit | Checks |
|---|---|---|---|
| flora-qc | Migrated and pushed | `fa18ad602587c4e2c90f3f6594feb8c109371b5e` | Testee 4/4; CopyRoom pin and no-change verified |
| inferference | Migrated and pushed | `7b9c340bb54d1faea9b6119e6455195d44095005` | Testee 4/4; CopyRoom pin and no-change verified |
| llgym | Migrated and pushed | `c46980c5eb93deb3099231228e7816231e11edce` | Testee 4/4 on main; CopyRoom pin and no-change verified |
| pytuin | Already adopted; verified and pushed | `8398ba3886a30d02a12a619b7c71d938a6dfaa84` | Testee 4/4; CopyRoom pin and no-change verified |
| scopeman | Migrated and pushed | `097b4b1f73889460d0d3e4ae426d858bf163c890` | Testee 4/4 on main; CopyRoom status ok, pin v0.8.0, no-change |
| shellij | Migrated and pushed | `194228ea931f547cfc71345e0c08f8b7cb24fd83` | Testee 4/4 on main; CopyRoom status ok, pin v0.8.0, no-change |

The resolution deleted only `copyroom.project.yml` beyond the template's
normal file changes. Each repo kept its project-specific checks, tasks,
dependencies, and toolchain pins. Shellij's merged `devenv.nix` had two
`languages.python` assignments. The migration removed the duplicate and then
passed Testee on the final main tree.

No files changed in linkman or talkee. Vendomat was not touched. An unrelated
Testee worker for vendomat remained active during this batch.

## Stale template text

The generated README in scopeman and shellij contains this stale paragraph:

> This project was created from the `template-py` source. CopyRoom saves a snapshot of that source in `.copyroom-local/`. Pull template updates with:

Its code block says:

```bash
copyroom update                 # preview a three-way merge in a separate workspace
copyroom update --apply PATH    # apply the preview that you reviewed
```

This text does not describe the current update flow. CopyRoom v0.8.4 stores the
source in a private Git ref. A project stays pinned until `update --ref` selects
a new version.

Proposed replacement:

> This project uses template-py pinned at v0.8.0. Check for newer tags with `copyroom status`. Preview a new version with `copyroom update --ref NEW_REF`, then apply the reviewed preview with `copyroom update --apply PATH`.

The migration did not change this text. A documentation-only template release
can carry the replacement after the fleet migration.
