# Project lifecycle

The local workflow has two histories: project commits and render commits.
CopyRoom keeps them in one jj repository and uses separate workspaces for
proposed changes.

## Create

`copyroom new` validates the source and answers before it creates the target. It
then writes the base render, stores a source snapshot, writes the local marker,
and verifies the render head.

## Preview and apply

`copyroom update` builds a new render as a child of the current render head. It
merges that render with the project head in a separate workspace. The preview
records both parent IDs and the reviewed tree digest.

`copyroom apply` checks that the project head, project tree, marker, and render
head still match the preview. It also checks that no conflict remains. It then
publishes the preview head with one `pyjutsu publish-if` call and verifies the
exact tree. The guard rejects before `@` moves when another writer changed the
project, and the journal returns to `prepared`. With `--publish-unguarded`,
CopyRoom runs `jj new` and detects a foreign writer afterward: it saves the jj
operation before `jj new` and checks which operation moved `@`.

## Recovery

`copyroom preview list --project DIR` lists saved previews. `copyroom discard --preview PATH`
removes one preview. A conflict remains in its preview workspace for review.
The project stays unchanged until apply succeeds.

## Layers

Each layer has one owner manifest and one render head. A layer update advances
only that render head. The workflow checks path ownership before it makes a new
layer visible.

## Tests

Tests use disposable jj repositories to check parent relationships, preserved
project edits, exact preview apply, conflict resolution, stale-state refusal,
and independent layer history. See [testing](testing.md) for the test gate.
