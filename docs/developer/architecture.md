# Architecture

CopyRoom composes trusted local Templateer sources and uses jj to manage project
history. It keeps each rendered source revision as a render commit. Project
updates merge a new render into a separate preview workspace. The user reviews
that exact tree before CopyRoom applies it.

## Data flow

```text
local source + JSON answers
          │
          ▼
TemplateRegistry + local composer
          │ validate schema, paths, bytes, modes, links
          ▼
immutable render plan ─── private source ref
          │
          ├── new ──► project render T0 ──► project marker
          │
          └── update ──► render T1 ──► isolated jj merge preview
                                             │
                                             ▼
                                     reviewed tree apply
```

Normal render and update commands do not call a model provider. The explicit
`generate` and `refresh` commands use Templateer generation. CopyRoom saves the
validated artifact bytes so later updates replay the saved result.

## Package areas

- `local/composer.py` validates the source and builds an immutable tree plan.
- `local/source.py` reads and writes project markers and finds the Git
  directory of a project.
- `local/store.py` writes a source tree as Git objects behind the private ref
  `refs/copyroom/sources/<digest>`. It reads the tree back.
- `local/pinned.py` pins a source to a commit of its local Git repository and
  reads that commit into a temporary directory.
- `local/jj.py` runs jj commands and holds project write locks. It spawns jj by
  absolute path (`COPYROOM_JJ`, or `PATH` resolved once).
- `local/guard.py` finds and probes the pyjutsu executable, and runs
  `pyjutsu publish-if` and `pyjutsu recover`.
- `local/workflow.py` implements project creation, preview, apply, recovery,
  status, and layer ownership.
- `local/generation.py` calls Templateer only after an explicit request and
  stores generated artifacts for replay.
- `local/manage.py` implements report-only adoption, explicit adoption, and
  source extraction.
- `local/workshop.py` implements local registry, scenario, golden, candidate,
  and update-test workflows.
- `cli.py` is the single public Typer dispatch path.

## Project state

`.copyroom-local.json` records the project ID, source locator, source digest,
Templateer and composer digests, normalized answers, output digest, owners, and
render revision. The project tree holds no source copy. The Git object database
of the project stores each source behind the private ref
`refs/copyroom/sources/<digest>`.
Each layer has its own render line. The base layer uses the reserved name
`base`.

jj commits record both project state and render history. CopyRoom does not use a
lock file as the source revision. It records the source tree digest. A pinned
layer reads its commit. The private ref lets a project update after its source
path or repository moves.

## Update safety

CopyRoom renders before it changes a project. It checks output ownership and
path collisions before it creates a preview. The preview records the active
project head, tree digest, render head, new source digest, merge parents, and
preview tree digest.

Apply checks those values again while holding a process lock. It rejects a
stale project or unresolved conflict. A user can resolve a conflict in the
preview workspace. CopyRoom applies the reviewed tree and verifies the result.

The full state contract is in [local workflows](../user/local-workflows.md).
