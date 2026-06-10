# Editing a Template from a Project

This is CopyRoom's signature feature. From **inside a generated project** you can
drive a change *back into the template* and preview exactly what your project
would receive on update — **without touching your working tree and without
pushing anything**.

CopyRoom supplies the mechanical, deterministic primitives. You (or an agent)
do the editing and the orchestration. There is an agent skill,
`copyroom-template-edit`, that runs this loop end to end.

---

## When to use it

Use this when you're working in a generated project and want a change made to the
**template itself** (not just this project), then want to see the resulting
update. Typical triggers:

- "Add X to the template", "change the template so it…", "fix the template's…"
- "What would my project look like if I pulled this template change?"
- "Update the template and show me the diff I'd get."

Do **not** use it for changes scoped to this project only — those are ordinary
edits to the files in front of you.

---

## The three guarantees

1. The template is edited in an **isolated git worktree on a scratch branch**.
   The template's main checkout is never disturbed; nothing is pushed.
2. The preview runs against a **throwaway copy of your project's current working
   tree**. Your real project is never modified.
3. It is **preview only**. You never apply the update here — you do that later
   with `copyroom update <ref>` once the template change is committed/tagged.

---

## The loop

```bash
copyroom template-checkout            # 1. template → editable worktree
# …edit files under the printed worktree path…   2. make the change
copyroom template-test                # 3. confirm it still renders
copyroom template-preview             # 4. see what your project would receive
```

All three are **project-mode** commands; run them from the project directory or
any descendant. They re-resolve the *same* worktree, so your edits persist across
`template-test` and `template-preview` runs.

### 1. `template-checkout` — get an editable template

```bash
copyroom template-checkout [--from REF]
```

CopyRoom reads `_src_path` from your `.copier-answers.yml`, locates the template
(cloning a remote source into the cache if needed), and creates a git worktree on
a scratch branch `copyroom/edit/<project-slug>`. It prints:

```
Template checked out for editing:
  Worktree: /…/.cache/copyroom/templates/<hash>/wt-<slug>
  Branch:   copyroom/edit/<slug>
  Source:   gh:org/your-template
```

- Edit the files **under the Worktree path** — these are the real template
  sources (`copier.yml`, `*.jinja`, etc.).
- `--from <ref>` bases the edit branch on a specific ref. Default is the
  template's current default branch; pass the project's recorded `_commit` to
  scope the preview to *only* your new change (excluding template changes you
  haven't pulled yet).
- The template source must be a **git repository**. A local non-git template is
  rejected with guidance to `git init` it.

### 2. Make the change

Edit the template files in the worktree. For example, add a new generated file:

```bash
cat > "$WORKTREE/CONTRIBUTING.md.jinja" <<'MD'
# Contributing to {{ project_name }}

Thanks for helping make {{ project_name }} better!
MD
```

Remember the [Copier rules](../copier/overview.md): only `.jinja` files are
rendered, and `{{ … }}` expressions reference the template's questions.

### 3. `template-test` — confirm it still renders

```bash
copyroom template-test [--from REF] [--check "pytest -q"]
```

CopyRoom commits your pending edits onto the scratch branch, renders the edited
template **with your project's own answers** into a temp directory, and confirms
it generates cleanly. With `--check CMD`, it also runs that command against the
rendered output (a non-zero exit fails the test). Fix and repeat until it passes.

This catches "the edit broke rendering" early, with a clear message, before the
heavier preview.

### 4. `template-preview` — see the update you'd receive

```bash
copyroom template-preview [--from REF]
```

CopyRoom:

1. commits pending edits to the scratch branch,
2. copies your project's **current working tree** into a sandbox (excluding
   `.git`, `.copyroom`, `generated/`, etc.),
3. runs `copier update --vcs-ref <edit-branch>` in the sandbox,
4. diffs baseline → post-update, and
5. writes a unified diff to `.copyroom/preview/<timestamp>.patch`.

The summary lists **Added / Modified / Removed** files, plus any **Conflicts**
(where your template change collides with your local edits) and **Rejects**.
Nothing is applied to your project.

```
Update preview (project ← edited template on copyroom/edit/<slug>):
  Added:    ['CONTRIBUTING.md']
  Patch: /…/your-project/.copyroom/preview/preview-20260610-101500.patch

Nothing was applied to your project. Review the patch, then once the
template change is committed/tagged, apply it with: copyroom update <ref>
```

---

## After previewing

The preview proved the change is good and showed you the diff. To actually adopt
it:

1. Commit your edit in the **template** repo (you've been editing a worktree of
   it) and tag a release, e.g. `git tag v2.1.0 && git push --tags`.
2. In your project, run `copyroom update v2.1.0`.

> The edit worktree and scratch branch live in CopyRoom's cache and are never
> pushed. They are scratch space for the preview, not the canonical edit — push
> from the template repo as you normally would.

---

## Notes & failure handling

- **`.copier-answers.yml` will appear in the preview diff.** Its recorded
  `_commit` advances on update — that's expected metadata churn, not a content
  change.
- **Conflicts/rejects are information, not failure.** They tell you precisely
  where the template change would clash with your local edits.
- **The commands are idempotent.** Re-running `template-checkout` reuses the same
  worktree/branch, so you can iterate edit → test → preview freely.
- **Remote vs local templates.** Remote sources are cloned (full clone) into
  `$XDG_CACHE_HOME/copyroom` (override with `$COPYROOM_CACHE_DIR`). Local sources
  must already be git repositories.

## See also

- [Projects: update](projects.md) — how the real `copyroom update` works.
- [Copier overview](../copier/overview.md) — the three-way merge being simulated.
- The `copyroom-template-edit` agent skill (`.agents/skills/copyroom-template-edit/`).
