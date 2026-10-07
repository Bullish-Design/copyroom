# Research report — adopt an existing jj project

Date: 2026-10-07 UTC

## Target and method

Test whether an existing project can enter a local render lineage without
changing its file bytes. Then test a later template update and a conflict.
Run [spike.py](spike.py) in spike 12's nested devenv shell:

```sh
cd .scratch/projects/12-jj-render-merge
devenv shell -- bash -c 'export PATH="$DEVENV_PROFILE/bin"; python3 ../17-jj-adopt/spike.py'
```

The environment supplies jj 0.45.1 and Python 3.13.14. The script creates
disposable colocated jj repositories. It does not use jj in the CopyRoom
repository. The [check results](evidence/2026-10-07-results.txt) and
[command transcript](evidence/2026-10-07-transcript.txt) record the run.
All 31 checks passed.

## Findings

The script first compared project and template files outside jj. The drift
report named changed, project-only, and template-only paths. This read-only
step left the project's current commit and file fingerprint unchanged.

The script rendered T0 in a separate workspace from `root()`. It then made an
adoption commit with project P0 and T0 as parents. `jj restore --from P0`
made that merge commit's tree byte-identical to the original project. The
script checked both parent IDs, every path and byte, and the tree fingerprint.
It did this for a clean case and a case where the project had changed a
template-owned line.

The script made T1 as a child of T0. The merge base of the adopted project
and T1 was T0. The clean case accepted the template change and kept the
project-only file. The changed-line case recorded a conflict with both the
project and template values. Both cases kept the project's earlier deletion
of a template-only file. Adoption can therefore preserve existing project
content while giving later updates a valid render base.

The [jj revset reference](https://docs.jj-vcs.dev/latest/revsets/) defines
the ancestor and `heads` expressions used to check the merge base. The
[jj conflict guide](https://docs.jj-vcs.dev/latest/conflicts/) describes how
jj records merge conflicts. The byte and tree results above come from this
local jj 0.45.1 run.

## Implementation guidance

Report drift before changing the project. Make the T0 render in a separate
workspace. Create an adoption merge with P0 and T0 as parents. Restore the
project tree from P0 in that merge. Verify the tree and both parents before
recording the adoption. A later update can follow the usual T0 to T1 merge.

The drift report must make template-only paths clear. This spike kept those
paths absent after adoption. A user who wants them added must make that
choice during adoption. The script did not test file modes, symlinks,
untracked ignores, or multiple layers. It also did not test adoption of a
project without an existing jj repository.
