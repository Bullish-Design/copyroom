# A Detailed Overview of Copier

CopyRoom is a thin, opinionated coordination layer on top of
[Copier](https://copier.readthedocs.io/). It never reimplements Copier — it
shells out to the `copier` binary and orchestrates git around it. To understand
CopyRoom you have to understand Copier first. This document is a self-contained,
deep introduction to Copier as CopyRoom uses it.

> **TL;DR** Copier renders a *template* (a directory of Jinja-suffixed files +
> a `copier.yml` questionnaire) into a *project*, records the answers and the
> template version into `.copier-answers.yml`, and can later *update* that
> project to a newer template version using a three-way merge.

---

## 1. What problem Copier solves

A *project template* is a reusable skeleton: a Python package layout, a docs
site, a Neovim plugin, a service scaffold. The naive way to use one is to copy
it once and start editing. That works for the first five minutes and fails
forever after: when the template improves (a new CI workflow, a fixed
`pyproject.toml`, a security patch in a generated file), every project that was
copied from it is now stranded. There is no link back to the source.

Copier keeps that link alive. It:

1. **Generates** a project from a template, asking the template's questions and
   substituting the answers (`copier copy`).
2. **Records** the template source, the exact template version, and every answer
   into a file *inside the generated project* (`.copier-answers.yml`).
3. **Updates** the project later by re-rendering the template at a new version
   and performing a three-way merge against the project's current files
   (`copier update`), preserving the user's local edits where it can.

That third capability — safe, repeatable updates across the lifetime of a
project — is the whole point. It is also the hardest part to get right, which is
why CopyRoom exists: to make `copier update` *testable, previewable, and
gated*.

---

## 2. Anatomy of a Copier template

A Copier template is just a directory (usually a git repository) with two
ingredients.

### 2.1 `copier.yml` — the questionnaire + settings

`copier.yml` (or `copier.yaml`) declares the *questions* a template asks and the
*settings* that control rendering. Questions become variables available to every
template file.

```yaml
# Settings (underscore-prefixed keys are Copier configuration, not questions)
_subdirectory: template          # render only files under template/ (see §2.4)
_answers_file: .copier-answers.yml  # where to record answers in the project
_templates_suffix: .jinja        # which files get rendered (the default)
_min_copier_version: "9.0.0"

# Questions (everything else)
project_name:
  type: str
  default: My Project
  help: Human-readable project name

package_name:
  type: str
  default: "{{ project_name | lower | replace('-', '_') | replace(' ', '_') }}"

license:
  type: str
  default: MIT
  choices:
    - MIT
    - Apache-2.0
    - GPL-3.0

include_ci:
  type: bool
  default: true
```

Key facts CopyRoom relies on:

- **Question types** are `str`, `int`, `float`, `bool`, `yaml`, and `json`.
- **Defaults can themselves be Jinja expressions** that reference earlier
  answers (`package_name` above is derived from `project_name`).
- **`choices`** constrains an answer to a fixed set.
- **Underscore keys are settings, not questions.** `_subdirectory`,
  `_answers_file`, `_templates_suffix`, `_exclude`, `_skip_if_exists`,
  `_min_copier_version`, `_envops`, and others tune the engine.

### 2.2 Template files and the Jinja suffix

By default Copier renders **only files whose name ends in `.jinja`** (the
`_templates_suffix`). The suffix is stripped from the output name and the file
contents are run through Jinja:

| Template file                 | Rendered output       | Processed? |
|-------------------------------|-----------------------|-----------|
| `README.md.jinja`             | `README.md`           | Jinja     |
| `pyproject.toml.jinja`        | `pyproject.toml`      | Jinja     |
| `logo.png`                    | `logo.png`            | copied verbatim |
| `.gitignore`                  | `.gitignore`          | copied verbatim |

This single rule — *only `.jinja` files are rendered, everything else is copied
byte-for-byte* — is the foundation of CopyRoom's `templatize` command (see
[adoption](../user/adoption.md)): a directory copied **verbatim** (no `.jinja`
suffixes) reproduces the source exactly, so you can introduce template variables
one file at a time without ever breaking the match.

### 2.3 Templated *paths*

Jinja runs on file and directory **names**, not just contents. A directory named
`src/{{ package_name }}/` renders to `src/aurora/` when `package_name=aurora`.
This is how a template lays out a tree that depends on the answers.

### 2.4 `_subdirectory` — separating template source from template repo

A template repository often needs files that are *about* the template (a README
for maintainers, tests, CI for the template itself) but must **not** end up in
generated projects. `_subdirectory: template` tells Copier to render only the
contents of `template/`. Everything else in the repo (workshop config, golden
snapshots, the template's own README) stays behind.

CopyRoom's `templatize` uses exactly this layout:

```
my-app-template/            # the template repository
├── copier.yml              # _subdirectory: template
├── template/               # ← the only thing Copier renders
│   ├── README.md.jinja
│   └── src/{{ package_name }}/__init__.py.jinja
├── copyroom.yml            # workshop config (not rendered)
├── scenarios/              # workshop scenarios (not rendered)
└── golden/                 # golden snapshots (not rendered)
```

### 2.5 The answers-file template

To make `copier update` work, the template must write the answers back into the
generated project. Templates include a file like:

```jinja
{# {{ _copier_conf.answers_file }}.jinja  (or  .copier-answers.yml.jinja) #}
# Changes here will be overwritten by Copier; NEVER EDIT MANUALLY
{{ _copier_answers|to_nice_yaml }}
```

`_copier_answers` is a special variable Copier exposes containing all recorded
answers plus the template metadata. The rendered result is the
`.copier-answers.yml` described next.

---

## 3. `.copier-answers.yml` — the link between project and template

After `copier copy`, the generated project contains an answers file. A typical
one looks like:

```yaml
# Changes here will be overwritten by Copier; NEVER EDIT MANUALLY
_commit: v1.2.0
_src_path: gh:org/my-app-template
project_name: Aurora
package_name: aurora
license: MIT
include_ci: true
```

The three "machine" fields matter enormously:

| Field        | Meaning                                                        |
|--------------|---------------------------------------------------------------|
| `_src_path`  | Where the template came from (git URL, `gh:` shorthand, or local path). |
| `_commit`    | The exact template version that was rendered (a tag or commit). This is the **merge base** for the next update. |
| *(answers)*  | Every question's recorded answer, reused as defaults on update. |

This file is **Copier-owned state**. The cardinal rule, repeated throughout
Copier and CopyRoom docs: *never hand-edit `.copier-answers.yml`.* It is
regenerated on every update and is the authority for all Copier operations.

CopyRoom reads this file constantly:

- `copyroom update` reads `_commit` (previous version) and `_template`/`_src_path`.
- `copyroom template-checkout` reads `_src_path` to locate the template and
  `_commit` to scope a preview.
- The presence of `.copier-answers.yml` is one of the two **project-mode**
  markers (see [concepts](../user/concepts.md)).

> Multi-template note: a project managed by more than one template uses
> `.copier-answers.<name>.yml`. CopyRoom v0.x targets single-template projects,
> but its tree-diff helper already excludes `.copier-answers*.yml` from
> comparisons so neither form pollutes a diff.

---

## 4. `copier copy` — generating a project

```bash
copier copy [--vcs-ref REF] [--data-file answers.yml] [--defaults] [--quiet] SOURCE DEST
```

What happens:

1. Copier resolves `SOURCE`. Remote sources (`gh:org/repo`, `https://…`,
   `git@…`) are cloned; local sources are read directly. Git templates render the
   **latest tag** by default unless `--vcs-ref` pins a specific tag/branch/commit.
2. It asks each question in `copier.yml`. `--data-file` supplies answers
   non-interactively; `--defaults` accepts each question's default for anything
   not supplied.
3. It renders every `.jinja` file (and templated path) into `DEST`, copying
   everything else verbatim.
4. It writes `.copier-answers.yml` into `DEST`.

CopyRoom's wrapper (`src/copyroom/_compat/copier.py`) always invokes:

```
copier copy --quiet --defaults [--vcs-ref REF] [--data-file FILE] SOURCE DEST
```

`--quiet --defaults` makes the run non-interactive and machine-friendly; CopyRoom
captures stdout/stderr and forwards them on failure. `--vcs-ref` is critical for
the template-edit workflow: without it Copier renders the latest *tag*, which is
wrong when you want to render an edit *branch*.

---

## 5. `copier update` — the three-way merge

This is Copier's signature feature and the reason its data model looks the way it
does.

```bash
copier update [--vcs-ref REF] [--defaults] DEST
```

To update a project from its current template version to a new one, Copier
performs a **three-way merge**:

```
        old template          (rendered at _commit, the recorded version)
       /            \
  base │             │  →  diff = what the template changed
       \            /
        new template          (rendered at --vcs-ref, the target version)

                +                project's current files
                                 (the user's local edits)
                =
        merged project           (template changes applied, local edits kept)
```

Concretely Copier:

1. Reads `.copier-answers.yml` to learn `_src_path` and `_commit`.
2. Re-renders the template at `_commit` (the **base**) using the recorded
   answers — reconstructing what the project looked like *as generated*, before
   the user touched it.
3. Renders the template at the target `--vcs-ref` (the **new** side) with the
   same answers (re-prompting only for genuinely new questions).
4. Computes the diff between base and new (what the template changed) and applies
   it on top of the project's **current** working tree (the user's edits).
5. Where the template's change and the user's change touch the same lines, it
   produces a **conflict**.

### 5.1 Conflicts and rejects

Copier (modern versions) defaults to **inline conflict markers** — the same
`<<<<<<<` / `=======` / `>>>>>>>` markers git uses — written directly into the
conflicting file. Older behavior / patch-based application can instead leave
`*.rej` reject files next to the originals.

CopyRoom detects **both**:

- It scans changed files for inline conflict markers
  (`<<<<<<<` / `>>>>>>>`) — see `template/preview.py:_scan_conflict_markers`.
- It scans the tree for `*.rej` files — see `project/update.py:capture_conflicts`
  and `workshop/simulate.py:_capture_rejects`.

### 5.2 Why a clean git worktree matters

`copier update` rewrites files in place. If the worktree already has uncommitted
changes, you cannot tell Copier's changes from your own, and you cannot cleanly
back out. Therefore:

- Copier itself works best on a committed tree.
- **CopyRoom requires a clean worktree before `copyroom update`**
  (`project/update.py:verify_worktree`) and refuses otherwise, pointing you at
  `git stash`/`git commit`. The clean tree *is* the undo button:
  `git checkout .` reverts a bad update.

### 5.3 Why the full history must be present

The merge base is rendered at `_commit`. That commit must exist in the local
clone. This is why CopyRoom does **full** clones (no `--depth`) of remote
templates — a shallow clone might not contain the recorded `_commit`, breaking
the three-way merge. See `_compat/gitutil.py:clone`.

---

## 6. Source addressing

Copier accepts several source forms, all of which CopyRoom passes through:

| Form                         | Example                              |
|------------------------------|--------------------------------------|
| GitHub shorthand             | `gh:org/repo`                        |
| GitLab shorthand             | `gl:org/repo`                        |
| Full git URL (https)         | `https://github.com/org/repo.git`    |
| Full git URL (ssh)           | `git@github.com:org/repo.git`        |
| Local path                   | `../my-template` or `/abs/path`      |

CopyRoom's `gitutil.normalize_source_url` expands `gh:`/`gl:` shorthands to
clone-able URLs when it needs to clone for itself (the template-edit and adoption
flows); plain Copier understands the shorthands natively.

---

## 7. Versioning templates

Copier resolves "the version to render" from git:

- **`copier copy`** without `--vcs-ref` renders the **latest git tag**. Templates
  are therefore expected to be **semver-tagged** (`v1.0.0`, `v1.1.0`, …).
- **`copier update`** without `--vcs-ref` updates to the latest tag; with
  `--vcs-ref` it updates to the given tag/branch/commit.

CopyRoom leans on this throughout: the workshop's `update-test` simulates
`v1.0.0 → v2.0.0`; `release-check` is the gate you run before cutting a new tag;
the template-edit flow renders an *edit branch* via `--vcs-ref`. CopyRoom does
**not** yet auto-resolve "latest" — `copyroom update` requires an explicit ref
(see [CLI reference](../user/cli-reference.md)).

---

## 8. Post-generation tasks (and why CopyRoom gates them)

Copier templates can declare `_tasks` / migration hooks that run shell commands
after `copy`/`update`. Because a template is often fetched from a remote source,
running its commands is **arbitrary code execution from an untrusted source**.

CopyRoom takes a deliberate stance here. It **never runs Copier's native
`_tasks` / migrations at all** — not even with `--trust`. CopyRoom does not pass
`--trust` through to Copier, so a template's own `_tasks` are silently a no-op
under CopyRoom (a deliberate limitation, not a bug). Instead, the *project's*
`copyroom.project.yml` may declare `post_project_create` /
`post_template_update` command lists, and CopyRoom runs **those** — and only
those — **when you pass `--trust`** (`_compat/shellcmd.py`). If you maintain a
template that relies on Copier `_tasks`, port that logic into a CopyRoom
post-hook. See [trust and safety](../user/trust-and-safety.md).

---

## 9. How CopyRoom maps onto Copier

Every CopyRoom command ultimately drives one or two Copier invocations plus git.
This table is the Rosetta Stone:

| CopyRoom command        | Underlying Copier / git work |
|-------------------------|------------------------------|
| `copyroom new`          | `copier copy --quiet --defaults` into an empty target; optional trusted post-create hooks. |
| `copyroom update <ref>` | clean-worktree check → optional isolation branch → `copier update --defaults --vcs-ref <ref>` → capture conflicts/rejects → optional trusted post-update hooks. |
| `copyroom template-checkout` | clone template (if remote) → `git worktree add` a scratch edit branch. |
| `copyroom template-test`     | commit edits on the branch → `copier copy --vcs-ref <edit-branch>` into a temp dir → optional check command. |
| `copyroom template-preview`  | copy project to a sandbox → `copier update --vcs-ref <edit-branch>` → diff → write `.patch` (nothing applied). |
| `copyroom render`       | `copier copy` with a scenario's answers into `generated/`. |
| `copyroom golden`       | `render` + tree-diff against `golden/`. |
| `copyroom update-test`  | `copier copy` at old version → apply edits → `copier update --vcs-ref <new>` → run checks. |
| `copyroom release-check`| run the whole scenario matrix (render + golden) + worktree check. |
| `copyroom templatize`   | verbatim copy of the repo into `template/` + golden snapshot (no Copier render yet). |
| `copyroom adopt`        | `copier copy` the template with inferred answers → tree-diff against the repo → optionally write `.copier-answers.yml`. |

---

## 10. Glossary

- **Template** — a directory (usually a git repo) with `copier.yml` and
  Jinja-suffixed source files. Produces files at copy time.
- **Project / generated project** — the output of `copier copy`; contains
  `.copier-answers.yml`.
- **Answers file** (`.copier-answers.yml`) — Copier-owned record of source,
  version (`_commit`), and answers. Never hand-edited.
- **`_commit`** — the template version a project was last rendered/updated at;
  the merge base for the next update.
- **`_src_path`** — where the template lives.
- **`_subdirectory`** — the folder inside a template repo that actually gets
  rendered (CopyRoom uses `template/`).
- **`vcs-ref`** — the git tag/branch/commit to render or update to.
- **Three-way merge** — base (old render) + new render + current project →
  merged result, with conflicts where template and user edits collide.
- **Conflict / reject** — overlapping changes surfaced as inline `<<<<<<<`
  markers or `*.rej` files.

## Further reading

- Official Copier docs: <https://copier.readthedocs.io/>
- CopyRoom [concepts](../user/concepts.md) — modes and the mental model.
- CopyRoom [configuration](../user/configuration.md) — the three config files.
