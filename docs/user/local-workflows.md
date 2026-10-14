# Local Workflows

CopyRoom uses local Templateer sources and jj. It does not fetch project
templates. Each managed project tracks its answers, a render head for each
layer, and a `.copyroom-local.json` marker. The project tree holds no copy of
the template source.

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
locator. A source can also be pinned to a Git ref; see
[Versioned sources](#versioned-sources). The private source store of the
project holds the saved input used to replay that render.

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
copyroom update --omit-path .devman/project.toml --out ../app-update-1
```

Use `--omit-path PATH` when a rendered path belongs to the repository. You can
repeat the option. CopyRoom records each path in that layer's `omissions` list,
removes it from layer ownership, and restores its current tracked content from
the active project into the preview. This keeps the repository file unchanged
while the layer updates. The omission remains for later updates.

The preview workspace must be outside the project. If `--out` is inside the
project, `copyroom update` exits with code `2` and prints `preview must be
outside the project`. CopyRoom creates the parent directory of `--out`.

Review files in the preview workspace. Apply the exact reviewed preview with:

```bash
copyroom update --apply ../app-update-1
```

The apply uses the omission recorded in that preview. Do not pass omission
options with `--apply`; create and review a new preview to change layer inputs.

The active project does not change during preview. If the project changes after
preview, CopyRoom refuses the apply. A jj conflict remains in the preview
workspace. Resolve the file there, inspect the result, then apply it. Discard a
preview with `copyroom discard --preview PATH`. Discard removes the workspace
and abandons the preview commits, so none stays in `jj log`.

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

## Versioned sources

A source can follow a version. Without `--ref`, the marker records the source
path and the digest. An update reads whatever is at that path. Use this for
template development.

With `--ref REF`, CopyRoom pins the source to a commit. SOURCE stays a path to
the source directory. `REF` is a tag, a branch, or a commit of the Git
repository that holds SOURCE. CopyRoom reads only the local repository. It never
fetches. `--ref` works on `new`, `adopt`, `layer add`, `update`, and
`preview create`.

```bash
copyroom new ~/src/template-py/source ./app --answers answers.json --ref v0.8.0
copyroom adopt ~/src/template-py/source --answers answers.json --ref v0.8.0 --write
copyroom layer add --source ~/src/docs/source --as docs --answers docs.json --ref v1.2.0
```

CopyRoom finds the repository root with `git rev-parse --show-toplevel`. Jj
repositories that are colocated with Git work the same way. It resolves `REF` to
a commit and reads that commit's subdirectory from the Git object store. It
does not use the working tree, `.gitattributes`, or line-ending filters.
Executable bits and symlinks stay as the commit holds them. A source symlink is
refused, as for a path source.

The marker records these fields for each pinned layer, in `pin`:

| Field | Meaning |
|---|---|
| `repo` | Absolute path of the repository root |
| `subdir` | Source directory inside the repository (empty at the root) |
| `ref` | The ref as you gave it |
| `commit` | The commit that the ref named at that time |

The `source` field holds `repo/subdir`. The digest stays as before.

Updates follow these rules:

- `copyroom update` with no `--source` and no `--ref` renders the pinned commit
  again. Only the answers can change it. A moving branch, new commits, and
  working-tree edits have no effect. CopyRoom reads the pinned commit first.
  When the repository or the commit is gone, it reads the private source store,
  so the update still works.
- `copyroom update --ref NEW` moves the layer to a new ref of the same
  repository.
- `copyroom update --source PATH --ref REF` switches to another repository or
  subdirectory. It also moves a path-source project onto a versioned source.
- `copyroom update --source PATH` without `--ref` switches the layer to a path
  source and drops the pin.
- `--layer NAME` selects the layer, as before. A pin belongs to one layer.

A missing ref makes CopyRoom exit with code `2`: `ref v0.9.0 not found in
/path; fetch it first`. Run `git fetch` in the repository, then retry. A SOURCE
outside a Git repository, with `--ref`, also exits `2`. A ref that starts with
`-` exits `3`.

`copyroom status` and `copyroom layer list` show the source kind (`path` or
`ref`), the ref, and the commit for each layer. When the pinned ref is a version
tag, `status` lists newer version tags of the repository as `updates_available`
and prints `update available: ...` on stderr. A version tag looks like `v1`,
`v1.2`, or `v1.2.3`. Pre-release tags do not count. A newer tag is information.
It does not change the exit code. If CopyRoom cannot read the repository, the
layer shows `updates_error` and `status` still finishes.

The workshop is unchanged. It renders the working source, so template authors
see their edits.

### The private source store

A project keeps no copy of its source in the working tree. Lint, type check, and
packaging tools see only project files. CopyRoom stores each source it renders
in the Git object database of the project. It writes the source tree as Git
objects and points one private ref at the tree:

```text
refs/copyroom/sources/<source_digest>
```

The ref name is the source digest from the marker. CopyRoom keeps modes 644 and
755 and symlinks. Git holds only the executable bit, so the digest of a source
ignores all other mode bits. `new`, `adopt --write`, `layer add`, and every
`update` preview write the ref. A ref never changes: the same digest names the
same tree. A new source digest gets a new ref. Old refs stay.

CopyRoom reads a source in this order:

1. A pinned layer reads the pinned commit from the template repository. The
   tree must match the recorded digest.
2. When the repository, the commit, or the match is missing, CopyRoom writes the
   tree of the private ref to a temporary directory. It checks the digest again
   and removes the directory when the command ends.
3. A path layer reads its recorded path while that directory exists. A changed
   path is a new template, and the update converges to it. When the path is
   gone, CopyRoom reads the private ref.

When no source matches the recorded digest, CopyRoom exits with code `2`. The
message says what to do: fetch the template repository, or run
`copyroom update --source PATH` (with `--ref REF` for a pinned layer).

The private ref belongs to one machine:

- A clone does not fetch it. `git clone`, `git fetch`, `git push`, and
  `jj git push` ignore `refs/copyroom/`. Only `git push --mirror` sends it.
- jj does not import it as a bookmark. `jj bookmark list --all` does not show it.
- `git gc` and `jj util gc` keep it. A ref keeps its objects alive.
- A fresh clone has no ref. It relies on the pin. Keep the template repository
  and its tags reachable.
- `copyroom status` shows `ref_reachable` for each layer. It is true when the
  private ref holds a tree that matches the digest.

#### Projects from an older CopyRoom

Before 0.8.4, CopyRoom committed a source copy at `.copyroom-local/sources/`.
CopyRoom no longer reads it. The next `copyroom update` removes that directory
in its preview, so you review the removal and apply it with the update. It
counts as a change, so `update` does not answer `no-change` while the directory
is tracked. `layer add` removes the directory in the same way. The update needs
the pinned repository or the path, because the old copy is not a source for the
new store. If the source is gone, the update exits with code `2`. Run
`copyroom update --source PATH` then.

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

A source can be a subdirectory of a jj repository. Then `template-checkout`
makes the candidate a workspace of that repository. Edit the files in
`candidate_source`, which is the candidate path plus the subdirectory. If the
repository is Git-only, the command exits `2`. Run `jj git init --colocate`
at its root first.

`copyroom update-test` exits `0` and reports `no-change` when the candidate
renders the same tree as the project. That result means the update path was not
exercised. It exits `1` when the update preview has conflicts.
