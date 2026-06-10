# Projects: `new` and `update`

The project lifecycle is the everyday path: generate a project from a template,
then keep it up to date as the template evolves. Both commands are guarded
wrappers around Copier — see the [Copier overview](../copier/overview.md) for the
engine.

---

## Creating a project — `copyroom new`

```bash
copyroom --mode project new <source> [target] [--answers FILE] [--trust]
```

A fresh target directory has no [markers](concepts.md), so there is nothing for
CopyRoom to detect — pass `--mode project` to make `new` legal there.

### What it does, step by step

`copyroom new` runs a guarded lifecycle
(`initiated → target_verified → prompts_collected → copy_executed →
[post_create_run →] complete`):

1. **Verify the target.** The directory must be empty or non-existent. A
   non-empty target is refused (CopyRoom never overwrites your files).
2. **Collect answers.** With `--answers FILE`, the YAML file is validated and
   passed to Copier. Without it, Copier uses each question's default
   (`--defaults`).
3. **Run `copier copy`.** `copier copy --quiet --defaults [--data-file FILE]
   SOURCE TARGET`. On any Copier failure, its stderr/stdout are forwarded and the
   command exits non-zero.
4. **Post-create hooks (optional).** If the rendered project has a
   `copyroom.project.yml` with `commands.post_project_create`, those run **only
   when you pass `--trust`** — otherwise they're skipped with a warning. See
   [trust & safety](trust-and-safety.md).
5. **Report.** Prints `Project created in <dir>` and suggested next steps.

### Example

```bash
cat > answers.yml <<'YAML'
project_name: Aurora
package_name: aurora
description: A starlight-fast task runner.
author: Ada Lovelace
YAML

copyroom --mode project new gh:org/python-cli-template ./aurora --answers answers.yml

cd aurora
git init && git add -A && git commit -m "Initial generation"
```

That commit matters: a project under version control is the precondition for
clean updates later.

---

## Updating a project — `copyroom update`

```bash
copyroom update [target_ref] [--branch] [--trust]
```

Run from inside the project (or any descendant). `<target_ref>` is the template
version to move to — a tag, branch, or commit.

> **Omit the ref to update to the latest.** With no `target_ref`, CopyRoom reads
> the template source from `.copier-answers.yml` and resolves the **highest
> semver tag** (`vX.Y.Z`) for you — `git tag` for a local source, `git ls-remote
> --tags` for a remote one — then applies that concrete tag. Passing an explicit
> ref (`copyroom update v2.0.0`) stays fully offline; the no-arg path may need
> the network. If the source can't be reached or has no semver tags, the command
> fails with a clear error.

### What it does, step by step

The update lifecycle is
`initiated → config_loaded → worktree_verified → [branch_created →]
update_executed → [post_update_run →] complete`:

1. **Load config.** Reads `.copier-answers.yml` for `_src_path` (the template
   source) and `_commit` (the version you're currently on — the merge base).
2. **Resolve the ref.** If you didn't pass one, pick the latest semver tag from
   the template source.
3. **No-op check.** If `_commit` already equals the target ref, it stops:
   nothing to update (reported as "already at the latest version").
4. **Require a clean worktree.** Runs `git status --porcelain`. A dirty tree is
   **refused**, with the offending files listed — commit or stash first. (If the
   directory isn't a git repo at all, this check is skipped.) This is the safety
   net: the only reliable undo for a bad merge is `git checkout .` on an
   otherwise-clean tree.
5. **Isolation branch (optional).** With `--branch`, CopyRoom creates
   `template-update/<template_id>-<target_ref>` and runs the update there, so the
   merge result is trivially reviewable and discardable.
6. **Run `copier update`.** `copier update --defaults --vcs-ref <target_ref>` — a
   [three-way merge](../copier/overview.md#5-copier-update--the-three-way-merge)
   that applies the template's changes on top of your local edits.
7. **Capture conflicts & rejects.** Inline `<<<<<<<`/`>>>>>>>` conflict markers
   are detected in changed files; `*.rej` reject files are found by scanning the
   tree. Both are reported.
8. **Post-update hooks (optional).** `commands.post_template_update` run only
   with `--trust`.
9. **Report.** Prints `Project updated to <ref>`, the isolation branch (if any),
   and any captured conflicts/rejects.

### Example

```bash
# template author has tagged v2.0.0 upstream
copyroom update v2.0.0
git diff                        # review the merge
git add -A && git commit -m "Update to template v2.0.0"
```

With an isolation branch:

```bash
copyroom update v2.0.0 --branch
# now on template-update/<template>-v2.0.0
git diff main
# merge it back, or discard the branch if the update is bad
```

---

## Checking where you stand — `inspect` and `status`

Two read-only commands answer "what is this project linked to, and is it current?"
Neither touches your tree; both support `--json` for scripting and agents.

```bash
copyroom status            # terse: am I up to date?
copyroom inspect           # full: the whole template link + configured hooks
```

`copyroom status` prints the detected mode, the template and its **current ref**
(`_commit`), the template's **latest** semver tag, whether an **update is
available**, and whether the worktree is clean — a quick "should I run
`copyroom update`?" check:

```text
Mode:             project
Template:         python-cli-template (../python-cli-template)
Current ref:      v1.0.0
Latest ref:       v2.0.0
Update available: yes
Worktree:         clean
```

`copyroom inspect` is the fuller report: project root, template id/source, the
recorded commit, the answers-file path, whether `copyroom.project.yml` is present,
and the configured command/hook lists (read through the validated config model).
Use `--json` to feed either into other tooling.

---

## Handling conflicts

A conflict means the template changed the same place you did. CopyRoom **reports**
conflicts; it does not resolve them for you. Your options:

- **Inline markers** (`<<<<<<<` / `=======` / `>>>>>>>`) appear in the file.
  Open the file, resolve as you would a git merge, and remove the markers.
- **`.rej` files** sit next to the original; apply the rejected hunk by hand and
  delete the `.rej`.

Because you started from a clean tree, you can always abandon the attempt with
`git checkout . && git clean -fd` (and delete the isolation branch if you used
one) and try again.

---

## Tips

- **Always commit between operations.** A clean tree is required for `update` and
  makes every result reviewable.
- **Use `--branch` for risky upgrades** (major version bumps) so the merge lives
  somewhere you can throw away.
- **Want to see the update before running it?** If the change originates from
  *you*, drive it through the [template-edit loop](template-editing.md) and use
  `template-preview` — it simulates the update without touching your tree.

## See also

- [CLI reference](cli-reference.md) — exact flags and exit codes.
- [Copier overview](../copier/overview.md) — copy, update, and the merge model.
- [Trust & safety](trust-and-safety.md) — the `--trust` gate for hook commands.
