# Local Workflows

CopyRoom uses local Templateer sources and jj. It does not fetch project
templates. Each managed project stores a source snapshot, its answers, a render
head for each layer, and a `.copyroom-local.json` marker.

## Source format

A source has a `manifest.json` file and a `templates/` directory. Each named
template is a Templateer artifact with `metadata.yml`, `schema.py`, and
`template.j2` files.

```json
{
  "templates": ["readme", "config"],
  "executable": ["scripts/setup.sh"],
  "static": [
    {"path": "assets/logo.bin", "source": "assets/logo.bin"}
  ],
  "symlinks": [
    {"path": "docs/current", "target": "../README.md"}
  ]
}
```

All templates in one source use the same Pydantic schema. Templateer validates
the model and each rendered artifact before CopyRoom writes a tree. Static
files retain their bytes. Executable files retain their mode. Symlinks must be
relative and must point to a path in the output tree.

Answers are JSON files that match the shared schema. The source path is a
locator. The project snapshot under `.copyroom-local/sources/<digest>` is the
saved input used to replay that render.

## Create and update

```bash
copyroom new app-template ./app --answers app-template/answers.json
cd app
copyroom status
copyroom update
```

`copyroom update` prints a JSON preview state. Its `path` field names the
preview workspace. With no `--out`, CopyRoom creates a unique path beside the
project, in `.copyroom-previews/`. Set the path with `--out`:

```bash
copyroom update --out ../app-update-1
```

The preview workspace must be outside the project. If `--out` is inside the
project, `copyroom update` exits with code `2` and prints `preview must be
outside the project`. CopyRoom creates the parent directory of `--out`.

Review files in the preview workspace. Apply the exact reviewed preview with:

```bash
copyroom update --apply ../app-update-1
```

The active project does not change during preview. If the project changes after
preview, CopyRoom refuses the apply. A jj conflict remains in the preview
workspace. Resolve the file there, inspect the result, then apply it. Discard a
preview with `copyroom discard --preview PATH`.

The preview contains the next marker and the full prepared project tree. Its
state records the active head, source digest, render head, and tracked-tree
digest. CopyRoom publishes that prepared tree. It does not rerender during apply.

If the source and answers produce no change, `copyroom update` returns
`no-change` and exits `0`. It does not create a preview workspace.

If CopyRoom stops during an apply or layer add, inspect and reconcile the saved
state with:

```bash
copyroom recover
```

Transaction journals live in `.copyroom-local/journal/`. Each journal has one
of three states:

- `prepared`: CopyRoom built a result. Publication has not started.
- `publishing`: CopyRoom started publication. Recovery must check the result.
- `published`: publication passed its checks. Cleanup may still be pending.

`recover` keeps a prepared update preview for review. Apply it or discard it.
For layer add, recovery publishes a complete prepared layer when the active
head still matches. If another writer moved the head, keep the result and
retry the layer add or prune the dead result.

`recover` exits `0` when it has no pending recovery, damaged journal, or
unpruned finding. A prepared update is pending review. It does not make
`recover` exit `1`. The report separates `pending_review` from
`pending_recovery`. Exit `1` reports a finding. Exit `2` reports an error.

Before it runs `jj new`, CopyRoom saves the current jj operation in the
journal as `publish_from_operation`. After publication, CopyRoom checks that the
first operation after it put the prepared head under `@`. Any other operation
means a foreign writer ran during publication. `apply` and `layer add` then exit
`1`, keep the journal and the preview, and name the operation. `status` and
`recover` keep reporting `published but unverified` until you resolve it.
A journal without `publish_from_operation` gets the same result, because
CopyRoom cannot prove where its publication started.

## Publication guard

`copyroom update --apply` and `copyroom layer add` publish through the pyjutsu
guard. CopyRoom runs one `pyjutsu publish-if --expect-wc ACTIVE_HEAD --onto
PREPARED_HEAD` call. The guard rejects the publication before `@` moves when
another writer committed, edited a tracked file, or moved the jj operation
heads. CopyRoom then exits `1`, changes nothing, keeps the preview or the
prepared layer, and names the observed head. Run `update` again to build a new
preview.

CopyRoom finds `pyjutsu` from `COPYROOM_PYJUTSU` or from `PATH`. It stores the
absolute path, and it probes the executable before it publishes. The probe calls
`publish-if` on a repository that does not exist and expects the answer
`result=error reason=repo-not-found`. A version number alone is not proof.
`COPYROOM_JJ` names the jj executable in the same way.

If CopyRoom finds no guard, `apply` and `layer add` exit `2` and name the fix.
Pass `--publish-unguarded`, or set `COPYROOM_PUBLISH_UNGUARDED=1`, to publish
without the guard. That path runs `jj new`. It cannot reject a foreign writer.
It checks the result afterward and reports the writer as a finding. The journal
records `publish_mode` for every publication: `{"guard": false}` without the
guard, or the guard path and version with it. The prebuilt pyjutsu wheel runs on
Linux x86-64 with glibc 2.39 or later. Other platforms build it from source with
Rust 1.89 or later.

Without the guard, CopyRoom saves the current jj operation in the journal as
`publish_from_operation` before it runs `jj new`. After publication, it checks
that the first operation after it put the prepared head under `@`. Any other
operation means a foreign writer ran during publication. `apply` and `layer add`
then exit `1`, keep the journal and the preview, and name the operation.
`status` and `recover` keep reporting `published but unverified` until you
resolve it. A journal without `publish_from_operation` gets the same result,
because CopyRoom cannot prove where its publication started. The foreign commit
stays in the repository but leaves the active line. To resolve it, run `jj op
log`, move the foreign work back onto the active line, and apply or discard the
preview. Do not run `jj op restore`; it hides the foreign work.

The guard does not remove five limits:

1. A direct file write that lands during the checkout can be lost when the file
   is one that the checkout rewrites. A new file and a file the checkout does not
   touch survive.
2. A writer that loaded the previous jj operation and publishes later forks the
   operation log. Its content stays visible. Its `@` move does not.
3. Power loss. jj does not fsync the operation head file or any directory.
4. A raw `git` write in a colocated repository. `git` does not take jj's lock.
5. A colocated child workspace, with a pyjutsu build that embeds jj-lib older than
   0.45. See the next section.

### Colocated child workspaces

`gitman work` makes a colocated child workspace: a jj workspace that is also a Git
worktree. Its root holds a `.git` file that reads `gitdir: .../.git/worktrees/NAME`.
Since jj 0.45, jj records one Git HEAD for each workspace. A pyjutsu build with
jj-lib older than 0.45 drops the Git HEAD of every workspace except `default`
when it writes an operation. It also skips the Git HEAD sync in a child workspace.
The next jj command in the child imports the old Git HEAD. That moves `@` off the
published commit. jj prints no message, because it treats the dropped Git HEAD as
a first checkout.

CopyRoom checks this before it changes anything. If the project root is a
colocated child workspace and the guard is too old, `apply` and `layer add` exit
`2`, change nothing, and keep the preview. The error names the pyjutsu and jj-lib
versions. Choose one of these:

1. Run the command from the `default` workspace. Other colocated child workspaces
   of the same repository can still lose their Git HEAD. jj imports it again on
   the next command in that workspace. The parent stays, and `@` gets a new change
   ID.
2. Pass `--publish-unguarded`. This path runs `jj new` with the jj CLI. The jj 0.46
   CLI writes the Git HEAD of every workspace, so `@` stays on the published
   commit. The path loses the guard's rejection of a foreign writer.

CopyRoom reads the jj-lib version from `pyjutsu --version`. pyjutsu 0.24.0 and later
print `pyjutsu 0.24.0 (jj-lib 0.46.0)`. Older builds have no such flag. For them,
CopyRoom reads `pyjutsu.JJ_VERSION` through the interpreter of the `pyjutsu` script.
The build is safe at jj-lib 0.45 or later. The pyjutsu version alone proves nothing.
If CopyRoom reads no jj-lib version, it treats the build as old and refuses. The
refusal lifts by itself when a safe pyjutsu is installed. `copyroom doctor` reports
`guard_jj_lib` and `guard_child_workspace` (`ok` or `refused`).

A rejected guard call can leave unreferenced jj operations and Git objects. Run
`jj util gc` to remove them. They are not damage.

`recover` reports orphan workspaces, layer directories, and JSON write
temporaries. An orphan is a workspace or temporary that no journal protects.
Use `copyroom recover --prune` to remove safe orphans and temporaries. This
command also untracks CopyRoom local state when needed.

`layer add` stages its render under the system temporary directory. Its path
starts with `copyroom-layer-`. Recovery tracks this path through the journal.

`status` exits `1` when it finds a marker/render mismatch, a pending
publication, a conflict, or another unhealthy project state. It prints a
line for each finding to stderr. `inspect` reports the same mismatch data, but a
mismatch does not change its exit code. Both commands can emit JSON with
`--json`.

The inspection report includes `marker_render_mismatches`,
`pending_transactions`, and `pending_previews`. The status report adds
`has_pending_publication`. The recovery report includes `pending_review`,
`pending_recovery`, `damaged`, and `repaired`.

Tree checks use paths that jj tracks. jj can refuse new files above its
`snapshot.max-new-file-size` limit, which defaults to 1 MiB. The setting
`snapshot.auto-track = none()` can also hide new files. CopyRoom prints jj's
"Refused to snapshot some files" warning to stderr. A tree check cannot include
a new file that jj did not track.

Recovery also reports tracked preview, journal, lock, and write-temporary paths.
Use `copyroom recover --prune` to untrack those paths. It keeps their files on
disk.

## Layers

Each layer owns a separate set of paths and a separate jj render head. The
base layer is created by `new`. Add an overlay with a local Templateer source
and answers file:

```bash
copyroom layer add --source ../docs-template --as docs \
  --answers ../docs-template/docs-answers.json
copyroom layer list --json
copyroom update --layer docs --out ../docs-2
```

CopyRoom rejects exact, prefix, case-folded, and project-owned path collisions
before it changes the active tree.

## Explicit generation

`generate` and `refresh` are the only CopyRoom commands that call a model.
Each saves the request, model name, validated model, Templateer source digest,
and exact artifact bytes. A normal update replays those bytes without a provider
call.

```bash
copyroom generate --source ../app-template --template config \
  --request "Add a local test command" --model openai:gpt-4.1-mini
copyroom refresh --layer gen-config --out ../config-preview \
  --request "Add a coverage command"
```

The `refresh` preview is also outside the project. Review it, then apply it
with `copyroom update --apply PATH`.

## Adopt and templatize

`adopt` reports changed, project-only, and template-only paths. It does not
write unless `--write` is present. The report exits with code `1` when the
project differs from the source. Use `--template-only keep` to save explicit
omissions for paths that should remain outside template ownership.

`adopt --write` requires an existing jj repository to be colocated with its
Git directory. A non-colocated repository makes CopyRoom exit with code `2`.
Run `jj git init --colocate`, then retry adoption.

CopyRoom sees a project as jj does. A path that the repository ignores is not
part of the project. Adoption, `templatize`, and collision checks skip ignored
paths, such as links that devman adds. If adoption fails, CopyRoom removes
what it created, and the project looks untouched.

A render path under a symlinked project directory makes CopyRoom exit with code
`1`. CopyRoom never writes through a link. Remove the path from the source.

A source never renders at `.agents` or `.claude`. devman owns both paths. A
source with an artifact, static file, or symlink there makes CopyRoom exit with
code `2`. `adopt` and `templatize` leave both paths out of the project tree.

If a project has a Copier answers file, CopyRoom exits with code `1` and names
the steps. Convert the template to a local Templateer source, write a JSON
answers file, then run `copyroom adopt SOURCE --answers FILE.json --write`.

Run these commands from the directory that holds the project and the source.
Name the project with `--project`.

```bash
copyroom adopt app-template --project app --answers app-template/answers.json
copyroom adopt app-template --project app --answers app-template/answers.json \
  --template-only keep --write
```

`templatize` extracts files, modes, binary files, and safe relative symlinks.
Selected paths can use `project_name`; the command checks the extracted source
against the original tree and then renders a changed probe answer.

Run `templatize` from the directory that holds the project. The `--target`
source must be outside the project. With `--parameterize`, `--name` must equal
the project directory name.

```bash
copyroom templatize --project app --target app-template --name app \
  --parameterize README.md
```

Copier answer files are not migrated automatically. Extract a local source,
then adopt it with an explicit answers file.

## Workshop

A workshop has `copyroom.yml`, `registry/`, and `scenarios/`. Each registry
source is a local Templateer source. A scenario is a YAML mapping that matches
the source schema.

```yaml
templates:
  app:
    source: ../app-template
```

Render and compare a scenario against `goldens/<id>/<scenario>/`:

```bash
copyroom render app basic
copyroom golden app basic
copyroom golden app basic --refresh
copyroom test app basic
copyroom release-check app
```

Run `copyroom golden ID SCENARIO --refresh` first to create a golden. Without a
golden, `copyroom golden` exits with code `1`.

Golden comparison checks paths, bytes, modes, and symlink targets. Refresh is
explicit and runs Templateer's authoring audit first. `test` and
`release-check` run `devenv test` in the generated scenario and preserve the
output in `.copyroom-workshop/logs/`.

Use a separate jj workspace for template edits:

```bash
copyroom template-checkout app
# Edit files in the candidate path printed by the command.
copyroom template-test app
copyroom update-test app basic
copyroom template-preview app --project ../app --out ../app-preview
copyroom template-discard app
```

The active source remains unchanged while the candidate is edited. The project
preview is separate from the active project. Apply a reviewed project preview
from that project's directory.

`copyroom update-test` exits `0` and reports `no-change` when the candidate
renders the same tree as the project. That result means the update path was not
exercised. It exits `1` when the update preview has conflicts.
