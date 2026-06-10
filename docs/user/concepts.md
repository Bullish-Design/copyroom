# Concepts & Mental Model

CopyRoom has one defining idea: **it is mode-aware**. Before it runs any command,
it figures out *what kind of directory you are standing in* and only allows the
commands that make sense there. Everything else in CopyRoom follows from that.

This page explains the surfaces, the modes, the markers, and the safety
philosophy. If you understand this page, the rest of the CLI is just details.

---

## 1. The four surfaces

CopyRoom coordinates four kinds of things. Only two of them are *modes* the CLI
runs in; the other two are objects the modes act on.

```
┌─────────────────┐   copier copy / update   ┌──────────────────────┐
│ TEMPLATE repo   │ ───────────────────────▶ │ generated PROJECT    │
│ copier.yml +    │                          │ .copier-answers.yml  │
│ template/*.jinja│ ◀─────────────────────── │ (+ copyroom.project) │
└─────────────────┘   template-edit / adopt  └──────────────────────┘
        ▲
        │ registry / scenarios / golden
        │
┌─────────────────┐
│ WORKSHOP        │   the template author's workbench:
│ copyroom.yml +  │   render · golden · update-test · release-check
│ registry/ +     │
│ scenarios/      │
└─────────────────┘
```

- **Template** — a Copier template (a `copier.yml` plus Jinja-suffixed source).
  Directly consumable by plain Copier; CopyRoom is not required to *use* one.
- **Project** — a repo generated from a template. It remembers its origin in
  `.copier-answers.yml` and can receive updates.
- **Workshop** — the template author's control plane: a registry of templates, a
  matrix of scenarios, and golden snapshots that lock down output.
- **Unmanaged repo** — an ordinary, hand-written repo that predates CopyRoom and
  has *no* markers. The bootstrap commands (`templatize`, `adopt`) bring it in.

---

## 2. The two modes

CopyRoom dispatches in exactly two modes in v0.x:

### Project mode
Detected when the current directory **or any ancestor** contains:
- `.copier-answers.yml`, **or**
- `copyroom.project.yml`

Project commands: `new`, `update`, `inspect`, `status`, `template-checkout`,
`template-test`, `template-preview`.

### Workshop mode
Detected when the current directory **or any ancestor** contains **all** of:
- `copyroom.yml`, **and**
- a `registry/` directory, **and**
- a `scenarios/` directory

Workshop commands: `registry`, `render`, `test`, `golden`, `release-check`,
`update-test`.

> `template_repo` and `standalone` modes exist in the type system but are held in
> reserve for future versions; they are not dispatchable today.

---

## 3. How detection works (the marker walk)

Detection walks from your current directory **up through every ancestor to the
filesystem root**, stopping at the first directory that has any marker
(`src/copyroom/session/detector.py`):

1. Start at the cwd, then each parent in turn.
2. At each level, check **workshop markers first**, then project markers.
3. The **closest ancestor** with any marker wins — proximity beats mode type
   *across* levels.
4. Within a *single* directory that somehow has both marker sets, **workshop
   wins** the tie.
5. If no ancestor has any marker → **unknown mode** → CopyRoom prints a clear
   diagnostic listing the markers it looked for, and exits non-zero.

This is why workshop commands work from a workshop **subdirectory** (e.g. from
inside `scenarios/my-template/`) and project commands work from anywhere inside a
generated project.

### Forcing a mode

`--mode {project,workshop}` skips detection entirely. This is useful for:
- **`copyroom new`** in an *empty* target directory (there is no marker yet, so
  you pass `--mode project`).
- CI or ambiguous directories where you want to be explicit.

```bash
copyroom --mode project new gh:org/template ./my-new-project
```

### Bootstrap commands skip detection

`templatize` and `adopt` are **bootstrap commands**: they are designed to run in
an *unmanaged* repo that has no markers at all. They bypass mode detection and
dispatch entirely and resolve their own context from arguments and the repo. They
are the only commands that work in an unmanaged repo.

### Why so strict?

Mode awareness is the core safety property. A "workshop" command (`render`) run
by accident inside a generated "project" — or a "project" command (`new`) run
inside a workshop — is almost always a mistake. CopyRoom refuses **loudly and
non-zero** rather than guessing and doing something surprising. The mode *is the
contract*.

---

## 4. The configuration files

Three files, three owners. Full detail in [configuration](configuration.md); the
one-line version:

| File | Owner | Role |
|------|-------|------|
| `.copier-answers.yml` | Copier | Authoritative: template source, version, answers. Never hand-edit. |
| `copyroom.project.yml` | You / the template | Advisory: post-create/update hooks, workflow prefs. Optional. |
| `copyroom.yml` | The workshop | Workshop registry: which templates exist and their checks. |

When the two project files disagree, `.copier-answers.yml` is authoritative for
anything Copier does; `copyroom.project.yml` is advisory metadata.

---

## 5. The safety philosophy

CopyRoom is built to be **boring and reversible**. Five rules run through the
whole codebase:

1. **Detect, don't guess.** No marker → refuse with a diagnostic, never a silent
   fallback.
2. **Preview over apply.** `template-preview` and `adopt` *report* what would
   change and write a patch; they never modify your working tree (adopt writes at
   most a single `.copier-answers.yml`, only with `--write`).
3. **Clean worktree is the undo button.** `copyroom update` refuses a dirty tree;
   a clean tree means `git checkout .` always backs out a bad update. CopyRoom
   never attempts automatic rollback.
4. **Untrusted code stays untrusted.** Template-supplied hook commands don't run
   unless you pass `--trust`. See [trust & safety](trust-and-safety.md).
5. **Isolated scratch space.** Template edits happen in a git worktree on a
   scratch branch (never pushed); previews and simulations run on throwaway
   copies in temp dirs or a cache (`$XDG_CACHE_HOME/copyroom`, override with
   `$COPYROOM_CACHE_DIR`).

---

## 6. The off-ramp

CopyRoom is not a lock-in. A generated project is a normal Copier project; you
can stop using CopyRoom at any time:

1. Delete `copyroom.project.yml` (if present).
2. Optionally drop `copyroom` from your dev dependencies.
3. Keep using `copier update` directly — `.copier-answers.yml` is untouched and
   still works.

Your project remains a perfectly normal Copier-managed repository.

---

## Where to go next

- [Getting started](getting-started.md) — install and run your first commands.
- [CLI reference](cli-reference.md) — the exhaustive command list.
- [Copier overview](../copier/overview.md) — the engine all of this rides on.
