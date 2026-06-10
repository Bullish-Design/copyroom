# Configuration Files

CopyRoom touches three configuration files. Each has a different **owner** and a
different **authority**. Knowing which is which prevents almost every confusing
situation.

| File | Owner | Authority | Where it lives |
|------|-------|-----------|----------------|
| `.copier-answers.yml` | Copier | **Authoritative** for all Copier operations | every generated project |
| `copyroom.project.yml` | You / the template | **Advisory** workflow metadata | a generated project (optional) |
| `copyroom.yml` | The workshop | Workshop registry | a workshop root |

---

## `.copier-answers.yml` — Copier-owned project state

Written by Copier into every generated project. It records the template source,
the exact template version, and every answer.

```yaml
# Changes here will be overwritten by Copier; NEVER EDIT MANUALLY
_commit: v1.2.0
_src_path: gh:org/aurora-template
project_name: Aurora
package_name: aurora
```

| Field | Meaning |
|-------|---------|
| `_src_path` | Where the template came from. CopyRoom reads this in `template-checkout` to find the template. |
| `_commit` | The template version this project is currently on — the merge base for the next update. CopyRoom reads this in `update`. |
| `_template` | (Some templates) the template identifier. |
| *(answers)* | Every recorded answer, reused as defaults on update. |

**Rules:**
- **Never hand-edit it.** Copier regenerates it on every update; manual edits are
  lost and can corrupt the merge base.
- Its presence is one of the two **project-mode** markers
  ([concepts](concepts.md)).
- CopyRoom excludes `.copier-answers*.yml` from every tree-diff (golden, preview,
  adopt) because its machine-specific fields would create spurious diffs.

See the [Copier overview](../copier/overview.md#3-copier-answersyml--the-link-between-project-and-template)
for the full data model.

---

## `copyroom.project.yml` — CopyRoom's advisory project metadata

**Optional.** A generated project may carry this file (typically emitted by the
template) to declare post-generation hooks and workflow preferences. It is parsed
through a single **validated Pydantic model**, so a malformed file fails fast
with a clear error rather than being silently half-read. Its presence is also a
project-mode marker, and `copyroom inspect`/`status` read through the same model.

```yaml
copyroom:
  version: 1

project:
  kind: generated-project          # recommended: generated-project | template-repo | shared-tooling (free-form)
  name: demo-cli
  template_id: python-cli-template
  template_source: git@github.com:example/python-cli-template.git
  template_ref_policy: tagged      # recommended: tagged | branch | commit | unknown (free-form)
  answers_file: .copier-answers.yml

git:
  default_branch: main
  update_branch_prefix: template-update/
  feature_branch_prefix: feature/
  fix_branch_prefix: fix/
  release_branch_prefix: release/
  tag_prefix: v
  require_clean_worktree: true

context:
  docs: [README.md, docs/]
  source: [src/, tests/]
  config: [pyproject.toml, .copier-answers.yml]

devenv:
  enabled: false
  shell_command: devenv shell

commands:
  check:
    - "uv run pytest"
  post_project_create:
    - "uv run pytest"
    - "uv run ruff check"
  post_template_update:
    - "uv run pytest"
    - "uv run ruff check"
```

### Field reference

| Section | Field | Default | Meaning |
|---------|-------|---------|---------|
| (top) | `copyroom.version` | `1` | Config schema version. |
| `project` | `kind` | `generated-project` | Free-form string; recommended `generated-project`, `template-repo`, or `shared-tooling`. A value this CLI doesn't recognize still loads (see note below). |
| `project` | `name` | `null` | Human project name. |
| `project` | `template_id` | `null` | The template's registry id. |
| `project` | `template_source` | `null` | Where the template came from (advisory; `.copier-answers.yml` is authoritative). |
| `project` | `template_ref_policy` | `unknown` | Free-form string; recommended `tagged`, `branch`, `commit`, or `unknown`. Unknown values load (see note below). |
| `project` | `answers_file` | `.copier-answers.yml` | Path to the Copier answers file. |
| `git` | `default_branch` | `main` | Branch updates land on. |
| `git` | `update_branch_prefix` | `template-update/` | Prefix for `--branch` isolation branches. |
| `git` | `feature_branch_prefix` / `fix_branch_prefix` / `release_branch_prefix` | `feature/` / `fix/` / `release/` | Branch-name conventions. |
| `git` | `tag_prefix` | `v` | Version-tag prefix. |
| `git` | `require_clean_worktree` | `true` | Whether a clean worktree is enforced before updates. |
| `context` | `docs` / `source` / `config` | `[]` | Declared context roots for agents/tooling. |
| `devenv` | `enabled` | `false` | Whether the project uses devenv. |
| `devenv` | `shell_command` | `devenv shell` | How to enter the dev shell. |
| `commands` | `<name>` | `{}` | Named command lists (`check`, `post_project_create`, `post_template_update`, …). |

**Every field is optional and defaulted** — a missing file (or any missing key)
behaves exactly like the all-defaults config, and **unknown fields are ignored**,
so a newer template's config keeps working on an older CLI (additive evolution).

The same forward-compat rule applies to **values**, not just fields: `kind` and
`template_ref_policy` are free-form strings, so a value a newer template emits
that this CLI doesn't recognize is tolerated rather than fatal. A
schema-divergent but readable config **never blocks `new`/`update`** — configured
hooks are still read and run — so version skew between a template and the CLI
can't break generation. Only genuinely unusable input (unparseable YAML, or a
document that isn't a mapping) is an error.

### Hooks

| Key | Used by | When it runs |
|-----|---------|--------------|
| `commands.post_project_create` | `copyroom new` | After `copier copy`, **only with `--trust`**. |
| `commands.post_template_update` | `copyroom update` | After `copier update`, **only with `--trust`**. |

Each command value is a list; a **bare string is also accepted** and normalized
to a one-item list. Because these commands come from a (possibly remote,
untrusted) template, they are **skipped with a warning unless you pass
`--trust`** — see [trust & safety](trust-and-safety.md). Failures of trusted
hooks are reported but never block completion.

---

## `copyroom.yml` — the workshop registry

Lives at a workshop root. Combined with a `registry/` directory and a
`scenarios/` directory, it makes the directory a **workshop**. It maps template
ids to a source and the checks to run against rendered output.

### Inline form (recommended for a single-template workshop)

```yaml
templates:
  aurora:                       # the template id
    source: ../aurora-template  # local path or git URL (anything Copier accepts)
    checks:
      - "test -f README.md"
      - "test -f pyproject.toml"
```

- `source` may be a **string** (the source directly) or a **mapping** with a
  `source:` / `url:` key.
- `registry:` is accepted as an alias for `templates:`.
- `checks` is a list of shell commands run against the rendered output by
  `render` / `test` / `update-test`, and required-green by `release-check`.

### Per-template file form

Instead of inlining, put one file per template at
`registry/<template_id>.yml`:

```yaml
# registry/aurora.yml
source: ../aurora-template
checks:
  - "uv run pytest"
```

CopyRoom looks in `copyroom.yml` first, then falls back to
`registry/<template_id>.yml`.

### What else lives in a workshop

| Path | Role |
|------|------|
| `scenarios/<id>/<name>.yml` | A named set of Copier answers (a scenario). |
| `scenarios/<id>/<name>-edits.yml` | Optional deterministic edits for `update-test`. |
| `golden/<id>/<name>/` | The locked-down expected output tree. |
| `generated/` | Scratch render output — **gitignore this**. |
| `.copyroom_sim/` | Scratch update-simulation output — **gitignore this**. |

A workshop's `.gitignore` should contain at least:

```gitignore
generated/
.copyroom_sim/
```

---

## Caching & environment

CopyRoom clones remote template sources and creates edit worktrees under a cache
directory:

| Variable | Default | Purpose |
|----------|---------|---------|
| `COPYROOM_CACHE_DIR` | — | Overrides the cache root entirely (`<dir>/templates`). |
| `XDG_CACHE_HOME` | `~/.cache` | Standard base; cache lives at `$XDG_CACHE_HOME/copyroom/templates`. |

Set `COPYROOM_CACHE_DIR` to isolate a run (the demo and tests do this).

## See also

- [Concepts](concepts.md) — how markers (these files) drive mode detection.
- [Trust & safety](trust-and-safety.md) — the `--trust` gate for hook commands.
- [Copier overview](../copier/overview.md) — `.copier-answers.yml` in depth.
