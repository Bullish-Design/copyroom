# Research report — jj render workspace

Date: 2026-10-07 UTC

## Target and method

Test render, preview, conflict, failure recovery, and local source relocation.
Run [spike.py](spike.py) from the nested devenv shell in spike 12:

```sh
cd .scratch/projects/12-jj-render-merge
devenv shell -- bash -c 'export PATH="$DEVENV_PROFILE/bin"; python3 ../15-jj-workspace/spike.py'
```

The environment supplies jj 0.45.1 and Python 3.13.14. The spike uses
disposable colocated jj repositories. It does not use the active CopyRoom
repository for jj operations. The [command transcript](evidence/2026-10-07-transcript.txt)
and [check results](evidence/2026-10-07-results.txt) record the run.
All 78 checks passed.

## Findings

`jj workspace add --revision T0` creates a separate working copy. The spike
rendered T1 in that workspace. It then merged T1 with project P0 in the same
workspace for preview. The active project's `@` commit and file fingerprint
stayed equal to their initial values at every step. `jj diff --from P0 --to @`
showed the update. The preview kept a project-only file. A same-line edit
produced a jj conflict that held both versions of the line.

The spike injected failures before render and after the T1 commit. In each
case, `jj workspace forget` and directory removal left the active project
unchanged. It also injected a failure after applying a merge and committing a
new marker in the active workspace. Restoring the operation ID captured before
the active merge returned the active commit and files to their initial state.
This verifies recovery from these controlled failures. It does not test a
process kill between an on-disk write and jj's working-copy update.

The current prototype saves an absolute template path. After the spike moved
both the project and template, a normal `update` failed with exit code 2. An
explicit `--template` path let the same project update successfully. A
relative sibling path survived the pair move in a separate locator check.
Moving the project alone did not provide its template. Source lookup therefore
needs an explicit relocation rule. A saved local path also does not identify
immutable template bytes; the implementation needs a template revision or
snapshot if it must audit or reproduce the source of a render.

## Implementation guidance

Render and preview in a named workspace. Record the current operation ID just
before changing the active workspace. On a controlled failure after apply,
restore that operation. Forget and remove the render workspace after preview.
Provide an explicit source override for a moved project. If project and
template move as a pair, a relative path can serve as the default locator.

The [jj workspace reference](https://docs.jj-vcs.dev/latest/working-copy/)
describes separate working copies and workspace cleanup. The
[jj command reference](https://docs.jj-vcs.dev/latest/cli-reference/) describes
`workspace add`, `workspace forget`, and `op restore`. The behavior above comes
from this local run under jj 0.45.1.

## Limits

The script uses a small text fixture, not a full Templateer render. It does
not test concurrent changes to both workspaces, crashes, remote clones,
symlinks, or permission errors. `op restore` changes repository operation
state, so an implementation must define what to do if another actor changes
the repository after the saved operation ID. The test did not make concurrent
changes.
