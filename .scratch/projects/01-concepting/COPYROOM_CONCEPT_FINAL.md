# CopyRoom: Canonical Concept

**Status:** Final concept — build-ready
**Date:** 2026-05-28
**Purpose:** This is the single authoritative concept document for CopyRoom. It supersedes all prior concept drafts and review documents. Use this document as the foundation for implementation.

---

## What CopyRoom Is

CopyRoom is a two-surface system: a template-maintainer **workshop** and a `uv`-installable **CLI tool**.

```text
CopyRoom workshop repository
  Maintainer workspace.
  Coordinates many independent Copier template repositories and shared
  tooling repositories. Owns registry metadata, scenarios, fixtures,
  golden outputs, policies, skills, agent context, test runners,
  release checks, and generated sandboxes.

copyroom CLI
  uv-installable Python package.
  Runs inside the CopyRoom workshop or inside generated project repositories.
  Provides project inspection, safe Copier copy and update, git workflow helpers,
  context discovery, and agent-facing structured output.

Template repositories
  Independent Git repositories containing actual Copier templates.
  Directly consumable by Copier without requiring CopyRoom.

Shared tooling repositories
  Independent Git repositories containing reusable behavior.
  Examples: shared devenv modules, shared GitHub Actions, shared lint configs,
  reusable pytest plugins, shared docs tooling.

Generated projects
  Normal project repositories created or updated from Copier templates.
  Own local project choices, local overrides, application code, docs, tests,
  fixtures, and release history.
```

The operating rule:

> **CopyRoom coordinates template work. Template repos contain template source. Shared tooling repos contain reusable behavior. Generated projects contain local project choices.**

The project-side extension:

> **The `copyroom` CLI makes the CopyRoom operating model usable from inside any generated project.**

---

## What CopyRoom Is Not

```text
- the canonical source tree for every template
- a replacement for individual template repositories
- a replacement for Copier, git, uv, devenv, pytest, ruff, just, or other tools
- a hidden runtime dependency for generated projects
- a branch-per-template or branch-per-project system
- a large generated script bundle copied into every generated repository
- a general-purpose project introspection tool
- a central place where project-specific behavior is forced back into templates
```

Users of a template can still consume it directly with Copier. A user can run a generated project without knowing CopyRoom exists. The `copyroom` CLI adds structure, guardrails, and agent affordances. It does not obscure the underlying tools.

CopyRoom v1 targets single-template projects. Multi-template composition (layered partial templates) is a future concern.

---

## Architecture

```text
┌────────────────────────────────────────────────────────────────────┐
│ CopyRoom workshop                                                  │
│                                                                    │
│ Maintainer control plane.                                          │
│ Owns registry, scenarios, policies, skills, agents, fixtures,      │
│ generated sandboxes, golden outputs, and release checks.           │
└───────────────┬───────────────────────────────────────┬────────────┘
                │                                       │
                │ manages local clones                  │ shares config model
                │                                       │
┌───────────────▼──────────────────────┐      ┌─────────▼──────────────┐
│ Template repos                       │      │ copyroom CLI/tool      │
│                                      │      │                        │
│ Independent Git repos containing     │      │ uv-installable Python  │
│ Copier templates.                    │      │ tool. Runs in workshop │
│                                      │      │ or generated projects. │
└───────────────┬──────────────────────┘      └─────────┬──────────────┘
                │                                       │
                │ copier copy/update                    │ project-local commands
                │                                       │
┌───────────────▼───────────────────────────────────────▼────────────┐
│ Generated project repository                                       │
│                                                                    │
│ Normal project repo. Contains application code, docs, tests,       │
│ .copier-answers.yml, optional copyroom.project.yml, and local      │
│ project-specific decisions.                                        │
└────────────────────────────────────────────────────────────────────┘
```

---

## Core Goals

### Workshop-side goals

The workshop should answer these questions for every registered template:

```text
1. Can the template render?
2. Does the generated output work?
3. Can an existing generated project be updated safely?
4. Did generated output change intentionally?
5. Is the template ready to release?
6. Which projects or templates consume a shared tooling repo?
7. Which scenarios prove the template's important modes?
8. Which policies apply to this template family?
```

### Project-side goals

Inside a generated project, the CLI should answer these questions:

```text
1. Which template is right for the kind of project I need?
2. How do I safely create a new project from a template?
3. Which template generated this project?
4. Which template revision or version is currently recorded?
5. How should this project receive template updates?
6. What branch naming and tagging workflow should be used?
7. Which files are generated, local, or policy-managed?
8. Which commands should be run after template generation or update?
9. Where should a local agent search for context?
10. What is the safest next step for creating, updating, testing, or releasing?
```

---

## Key Definitions

### Template vs. shared tooling

The boundary is mechanical, not judgmental:

```text
Template
  Generates files into a project at copy-time. Copier does the work.
  After copier copy finishes, the template does not need to exist
  anywhere outside the generated project.

Shared tooling
  Consumed by generated projects at dev-time or runtime.
  Imported, included, fetched, or referenced — not generated.
  After copier copy finishes, this still needs to exist somewhere
  outside the generated project.
```

A template produces files. Shared tooling is consumed by files.

### Template families

CopyRoom classifies templates by role:

```text
1. Project templates — generate full repositories
   python-cli-template, docs-site-template, nvim-plugin-template

2. Partial templates — generate a subsystem inside an existing project
   pytest-harness-template, github-actions-ci-template

3. Structure templates — generate directory layouts
   monorepo-layout-template, test-fixture-layout-template

4. Policy and config templates — generate configuration files
   ruff-config-template, editorconfig-template

5. Shared behavior modules — not Copier templates; reusable behavior
   shared-devenv-python, shared-github-actions
```

Each family has different testing needs. Project templates need full render, generated-project tests, golden comparison, and update simulations. Partial templates need conflict tests and update tests. Structure templates need path validation and tree snapshots. Config templates need syntax validation.

---

## Repository Model

Canonical template and shared tooling repos remain separate Git repositories. CopyRoom checks them out locally under `repos/`. CopyRoom tracks metadata, scenarios, policies, and tests for those repos — not the template source itself.

### Why not a monorepo

```text
- each template should be independently versioned
- each template should be directly consumable by Copier
- shared tooling should be independently versioned
- generated projects should pin or update template/tooling versions intentionally
```

### Why not git submodules

```text
- branch switching is awkward
- local agent edits are cumbersome
- partial checkouts are confusing
- submodule pointers add commit-management overhead
```

The default is plain local clones managed by scripts. A lock file (`copyroom.lock.yml`) is available when reproducible workshop test runs or release validation is needed.

---

## CLI Package Design

### Decision: CLI lives inside the CopyRoom workshop repo 

The CLI source lives in `src/copyroom/` within the CopyRoom workshop repository.

Reasons:
- One fewer repo during the fast-iteration phase
- CLI tests run against real workshop fixtures immediately
- The workshop `justfile` wraps `copyroom` commands naturally
- Extraction to a separate repo is easy later — `src/copyroom/` moves to its own repo with its own `pyproject.toml`

Extract to a separate repo when the CLI is stable enough that generated projects want to pin a specific CLI version independently of workshop changes. That is a v0.5+ concern.

### Decision: One package, mode-gated commands

Ship a single `copyroom` package. Workshop commands import workshop-specific modules lazily. If you are not in a workshop directory, those commands print "not available outside a CopyRoom workshop" and exit. No extras, no plugins, no package splits.

### Package layout

```text
src/copyroom/
├── __init__.py
├── cli.py
├── models.py
├── errors.py
├── discovery.py
├── config_loader.py
├── registry.py
├── project.py
├── git_tools.py
├── copier_tools.py
├── context_tools.py
├── agent_tools.py
├── workshop_tools.py
├── command_runner.py
└── output.py
```

Module responsibilities:

```text
cli.py             Command groups, maps commands to services.
models.py          Pydantic models for all config and structured output.
errors.py          Error types and error reporting.
discovery.py       Detects operating mode from directory context.
config_loader.py   Loads/validates copyroom.yml, copyroom.project.yml,
                   registry files, lock files.
registry.py        Reads template and shared-tooling registry entries.
project.py         Inspects generated projects, .copier-answers.yml,
                   project manifest, local commands, file policies.
git_tools.py       Worktree checks, branch helpers, tagging helpers.
copier_tools.py    Wraps copier copy, copier update, scenario rendering,
                   conflict detection, answer-file inspection.
context_tools.py   Finds and lists context roots from config.
agent_tools.py     Emits structured agent briefs and tool manifests.
workshop_tools.py  Repo sync, render, test, golden diff, update simulation.
command_runner.py   Safe subprocess execution with captured output.
output.py          Human-readable and JSON output formatting.
```

---

## CLI Modes

The CLI detects its operating mode automatically from directory context.

### Workshop mode

Detected when the current directory or an ancestor contains `copyroom.yml` with `registry/` and `scenarios/`.

### Project mode

Detected when the current directory or an ancestor contains `.copier-answers.yml` or `copyroom.project.yml`.

### Template repository mode

Detected when the current directory or an ancestor contains `copier.yml` (and is not inside a workshop).

### Standalone mode

Detected when none of the above markers exist. Provides `init`, `help`, and `version` commands.

`copyroom explain-mode` prints which mode was detected and why. This is the primary debugging tool for mode confusion.

---

## Configuration

### Workshop config: `copyroom.yml`

```yaml
name: CopyRoom
version: 0.1.0

paths:
  repo_dir: repos
  generated_dir: generated
  golden_dir: golden
  scenarios_dir: scenarios
  registry_dir: registry
  fixtures_dir: fixtures
  policies_dir: policies
  skills_dir: skills
  agents_dir: agents

repo_management:
  mode: local-clone
  lock_file: copyroom.lock.yml
  auto_create_missing_repos: false
  allow_dirty_repos_by_default: false

template_engines:
  - copier

policies:
  require_registry_entry: true
  require_scenario_for_template: true
  require_update_test_for_long_lived_templates: true
  require_diff_review_before_release: true
  require_release_notes_for_template_tags: true
  require_clean_template_worktree_before_release: true

agent:
  default_brief_files:
    - agents/base-template-agent.md
    - policies/copier-template-policy.md
    - policies/generated-file-policy.md
    - policies/update-conflict-policy.md
```

### Project config: `copyroom.project.yml`

```yaml
copyroom:
  version: 1

project:
  kind: generated-project
  name: demo-cli
  template_id: python-cli-template
  template_source: git@github.com:Bullish-Design/python-cli-template.git
  template_ref_policy: tagged
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
  docs:
    - README.md
    - docs/
    - ADR/
    - .agents/
  source:
    - src/
    - tests/
  config:
    - pyproject.toml
    - uv.lock
    - .copier-answers.yml
    - copyroom.project.yml

devenv:
  enabled: false

commands:
  check:
    - uv run pytest
  lint:
    - uv run ruff check
  format:
    - uv run ruff format
  typecheck:
    - uv run pyright
  post_project_create:
    - uv run pytest
    - uv run ruff check
  post_template_update:
    - uv run pytest
    - uv run ruff check
```

### Relationship between `.copier-answers.yml` and `copyroom.project.yml`

```text
.copier-answers.yml
  Copier-owned state.
  Records template source, template version/ref, and template answers.
  Used by copier update.
  Should not be manually edited in normal workflows.
  Authoritative for all Copier operations.

copyroom.project.yml
  CopyRoom-owned project metadata.
  Records local workflow preferences, context roots, check commands,
  agent hints, git policy, and environment flags.
  Can be generated by the template and edited locally.
  Advisory workflow metadata — not authoritative for Copier operations.
```

When they disagree, the CLI treats `.copier-answers.yml` as authoritative for Copier operations and `copyroom.project.yml` as advisory.

### Config evolution strategy

Config schemas use additive-only changes:

```text
- Fields in copyroom.project.yml v1 are never removed in future versions
- New fields always have defaults, so v1 configs work with newer CLIs
- The CLI reads any config version it understands (no migration required)
- Templates always generate the latest config version they support
- If a truly breaking change is ever needed, bump to v2 and keep a v1 reader
```

The CLI is responsible for reading older config versions. Templates are responsible for generating current config versions. Users are not responsible for manual config migration.

---

## Template Registry

The registry is the center of the workshop. Each template or shared tooling repo has one registry file.

### Copier template entry

```yaml
id: python-cli-template
kind: copier-template
name: Python CLI Template
status: active

remote: git@github.com:Bullish-Design/python-cli-template.git
local_path: repos/python-cli-template
default_branch: main

template:
  engine: copier
  root: .
  answers_file: .copier-answers.yml
  min_copier_version: "9.0.0"

scenarios_dir: scenarios/python-cli-template
generated_dir: generated/python-cli-template
golden_dir: golden/python-cli-template
fixtures_dir: fixtures/python-cli-template

commands:
  generated_test:
    - uv run pytest
  generated_check:
    - uv run pytest
    - uv run ruff check

checks:
  render: true
  update: true
  golden: true
  generated_tests: true

project_manifest:
  generate: true
  path: copyroom.project.yml
  default_context_roots:
    docs:
      - README.md
      - docs/
    source:
      - src/
      - tests/

release:
  strategy: semver
  tag_prefix: v
  require_matrix: true
  require_clean_worktree: true
```

### Shared tooling entry

```yaml
id: shared-python-devenv
kind: shared-tooling
name: Shared Python Devenv Module
status: active

remote: git@github.com:Bullish-Design/shared-python-devenv.git
local_path: repos/shared-python-devenv
default_branch: main

checks:
  unit_tests: true
  integration_tests: true

consumed_by:
  - python-cli-template
  - python-package-template

release:
  strategy: semver
  tag_prefix: v
```

### Registry kinds

Start with:

```text
copier-template
shared-tooling
```

Add `example-project`, `fixture-repo`, `policy-module` only when needed.

---

## Scenarios

A scenario is a stable set of answers used to render a template.

```yaml
# scenarios/python-cli-template/minimal.yml
project_name: demo-cli
package_name: demo_cli
description: Demo Python CLI
repo_owner: Bullish-Design
license: MIT
include_github_actions: true
include_tests: true
include_pydantic: false
include_sqlmodel: false
```

Scenarios should cover durable risk areas:

```text
minimal          Smallest useful render.
standard         Normal default output.
full             Most optional features enabled.
ci-enabled       Includes CI configuration.
existing-repo-update   Tests update against a customized generated repo.
migration        Tests adoption into a non-template-managed project.
edge-case-names  Tests hyphens, underscores, casing, path templating.
```

Do not create a scenario for every possible prompt combination. Create scenarios for combinations that affect structure, update risk, generated commands, or policy.

---

## Generated Output and Golden Testing

### Generated output

`generated/` is a scratch area. Generated outputs are not committed. They are used for local inspection, testing, update simulations, and diffing against golden outputs.

### Golden output

Golden testing is selective. Snapshot directory trees and key config files, not every generated byte.

Good golden targets:

```text
- rendered directory tree (tree.txt)
- pyproject.toml
- README skeleton
- copyroom.project.yml shape
- .copier-answers.yml shape
- generated CI workflow
- generated starter tests
```

Example:

```text
golden/python-cli-template/minimal/
├── tree.txt
└── important-files/
    ├── pyproject.toml
    ├── README.md
    ├── copyroom.project.yml
    ├── src/demo_cli/__init__.py
    └── tests/test_import.py
```

Golden changes are allowed only when intentional and reviewed.

---

## Update Simulation

Every long-lived template must have update tests.

```text
1. Render from an older template version or fixture.
2. Commit or snapshot the generated output.
3. Apply realistic user edits (README, pyproject.toml, tests, CI).
4. Run copier update to a newer template version.
5. Detect conflicts, rejects, and unexpected churn.
6. Run generated-project checks.
7. Produce a diff report.
```

A template is not release-ready if it works only on initial generation but creates unusable updates.

---

## Fixtures

`fixtures/` contains input projects or local dependencies used by scenarios. They are especially important for update and migration tests.

```text
fixtures/
├── existing-python-package/
├── existing-docs-repo/
├── existing-mature-plugin/
├── local-shared-modules/
└── partially-template-managed-repo/
```

---

## Safe Project Creation Workflow

`copyroom project new` wraps `copier copy` with a guarded workflow:

```text
1. Accept a template source (Git URL, GitHub shorthand, or local path).
2. Present the template's interactive prompts. Accept answers.
3. Verify the target directory does not exist or is empty.
4. Run copier copy with the provided answers.
5. Initialize git if the target is not already a repository.
6. Run post-project-create commands (from the generated copyroom.project.yml).
7. Summarize results.
8. Suggest next steps (cd, git init, copyroom project inspect).
```

Example output:

```text
Project creation summary

Template: python-cli-template
Source: git@github.com:Bullish-Design/python-cli-template.git
Version: v0.4.0
Target: /home/user/projects/demo-cli

Post-create checks:
  uv run pytest       passed
  uv run ruff check   passed

Suggested next steps:
  cd /home/user/projects/demo-cli
  git init && git add . && git commit -m "Initial generation from python-cli-template v0.4.0"
  copyroom project inspect
```

Just like `template update`, the `--json` and `--quiet` flags are supported for agent consumption.

---

## Safe Template Update Workflow

`copyroom template update` wraps `copier update` with a guarded workflow:

```text
1. Detect project root.
2. Load .copier-answers.yml and copyroom.project.yml.
3. Identify current template source and recorded template ref.
4. Resolve target template ref.
5. Verify git worktree is clean (required by default).
6. Create an update branch if requested or required by policy.
7. Run copier update --defaults, optionally with --vcs-ref.
8. Capture changed files, conflicts, rejects, and warnings.
9. Run post-template-update commands.
10. Summarize results.
11. Suggest commit message.
```

Example output:

```text
Template update summary

Project: demo-cli
Template: python-cli-template
Previous ref: v0.3.0
Target ref: v0.4.0
Branch: template-update/python-cli-template-v0.4.0

Changed files:
  modified: pyproject.toml
  modified: README.md
  added: .github/workflows/lint.yml

Conflicts: none

Post-update checks:
  uv run pytest       passed
  uv run ruff check   passed

Suggested commit:
  Update python-cli-template to v0.4.0
```

---

## Git Workflow Policy

CopyRoom provides project-local git helpers. It does not hide git.

### Branch naming

```text
Generated project repos:
  feature/<short-name>
  fix/<short-name>
  template-update/<template-id>-<target-version>
  release/<version>

Template repos:
  main, next, feature/<name>, fix/<name>, release/<version>

CopyRoom workshop:
  main, feature/<name>, policy/<name>, registry/<template-id>
```

### Tag strategy

Template repos, shared tooling repos, and generated project repos each use semver tags independently. Their version numbers do not need to match.

---

## Agent Model

### Agent context files

```text
agents/
├── base-template-agent.md
├── copier-review-agent.md
├── python-template-agent.md
├── docs-template-agent.md
├── directory-template-agent.md
├── test-template-agent.md
├── migration-agent.md
└── release-agent.md
```

### Agent-facing CLI commands

Any command likely to be consumed by an agent supports `--json` and `--quiet`.

`copyroom agent brief` produces a concise project-specific summary:

```text
Project: demo-cli
Mode: generated project
Template: python-cli-template
Template source: git@github.com:Bullish-Design/python-cli-template.git
Recorded template ref: v0.3.0

Git policy:
  Default branch: main
  Template update branches: template-update/<template-id>-<version>
  Clean worktree required: yes

Important context roots:
  README.md, docs/, src/, tests/, pyproject.toml,
  .copier-answers.yml, copyroom.project.yml

Checks after template updates:
  uv run pytest
  uv run ruff check

Notes:
  Do not manually edit .copier-answers.yml.
  Review generated diffs before committing template updates.
```

`copyroom agent tools --json` emits a structured tool manifest for agent consumption.

`copyroom context roots` lists configured context paths. This tells agents where to look. Agents already have file reading, glob, and grep capabilities — they need location guidance, not a custom search layer.

### Deferred agent features

`copyroom context search` and `copyroom context agent-pack` are deferred. `context roots` plus `agent brief` is sufficient for initial agent support.

---

## Skills and Policies

### Skills

`skills/` holds reusable operational procedures:

```text
skills/copier.md       Copy, update, recopy, inspect answers, handle conflicts.
skills/jinja.md        Jinja conventions, path templating, filters, escaping.
skills/golden-tests.md Snapshot, normalize, diff, and refresh golden outputs.
skills/update-tests.md Simulate user edits and validate copier update behavior.
skills/python-packaging.md  pyproject conventions, build checks, test commands.
skills/devenv.md       Shared module conventions, generated devenv files.
```

### Policies

`policies/` defines durable rules across template families:

```text
policies/copier-template-policy.md
policies/prompt-policy.md
policies/generated-file-policy.md
policies/update-conflict-policy.md
policies/git-workflow-policy.md
policies/release-policy.md
```

### Prompt policy

Good prompts: project name, package name, description, repo owner, license, broad feature flags, test runner choice, shared tooling reference, whether to include CopyRoom project manifest.

Avoid prompts for: every dependency, every README section, every config detail, things users can edit after generation.

### Generated file policy

Generated files should be small, readable, local, safe to edit, and low-churn across template releases. Reusable behavior should move into the `copyroom` CLI, shared tooling repos, or shared devenv modules.

---

## Devenv Integration

Devenv is an optional config field in `copyroom.project.yml`, not a command surface.

```yaml
devenv:
  enabled: true
  shell_command: devenv shell
```

No `copyroom devenv *` commands are built. Projects with devenv use the `devenv` CLI directly. CopyRoom records whether devenv is present so agents and inspection commands can report it.

Revisit only if a concrete, recurring pain point emerges that devenv's own CLI cannot solve.

---

## Error Handling

The CLI follows a report-and-exit philosophy:

```text
- Print what happened, what failed, and where state was left.
- Never attempt automatic rollback of file changes or git operations.
- Never silently swallow errors.
- Exit with non-zero status on any failure.
- For wrapped commands (copier copy, copier update, git), print the underlying
  command's stderr.
```

Automatic rollback is more dangerous than a clear error message. The clean-worktree requirement is the safety net. If the worktree was clean before the operation, `git checkout .` is always available as a manual escape hatch.

---

## Security Model

CopyRoom trusts local config files the same way `Makefile`, `justfile`, and `package.json` scripts are trusted. Commands defined in `copyroom.project.yml` are local files under the user's control.

```text
- The CLI never fetches scripts from URLs.
- The CLI never executes commands from remote registry entries.
- Template sources are Git URLs passed to Copier. Copier handles the fetch.
- CopyRoom does not add its own remote fetch or execution layer.
```

---

## CopyRoom Off-Ramp

Removing CopyRoom from a generated project is a non-event:

```text
1. Delete copyroom.project.yml
2. Optionally remove copyroom from dev dependencies
3. Continue using copier update directly
4. .copier-answers.yml is unaffected
5. Your project is a normal Copier-managed project again
```

---

## CLI Testing Strategy

Three tiers:

```text
Tier 1 — Unit tests (fast, no I/O)
  Pydantic model validation, config parsing, mode detection logic,
  output formatting. Fixture data, not real files.

Tier 2 — Integration tests (medium, temp directories)
  Create temp directories with .copier-answers.yml and
  copyroom.project.yml. Run CLI commands. Verify output.
  No real Copier templates, no git repos, no network.

Tier 3 — End-to-end tests (slow, real templates)
  One minimal fixture template in the test suite.
  Run copier copy, then copyroom commands against the result.
  Run in CI, not on every save.
```

Tier 1 and 2 cover >90% of CLI logic. Tier 3 proves Copier integration works.

---

## CLI Versioning

```text
- Semver. No breaking changes within 0.x minor versions.
- 0.1.x: bug fixes only
- 0.2.0: new commands, new config fields (with defaults)
- 0.x to 0.y: may add commands, may deprecate with warnings, never remove
- 1.0.0: first stable release with backward-compat commitment
```

Since `copyroom.project.yml` uses additive-only versioning, CLI upgrades should never break existing project configs. New CLI versions ignore unknown config fields rather than failing.

---

## Release Workflow

### Template release (advisory-only in v0.x)

`copyroom release check <template-id>` runs the matrix, verifies clean worktree, checks for golden diffs, and prints a pass/fail report.

Actual tagging is done by humans: `git tag v0.4.0 && git push --tags`. Automated cross-repo releases are a v1+ concern.

### Generated project creation

```bash
copyroom project new git@github.com:Bullish-Design/python-cli-template.git ./my-project
cd my-project
copyroom project inspect
# review generated files, commit
```

### Generated project update

```bash
copyroom template status
copyroom template update --to v0.4.0
copyroom project run post-template-update
git diff
# review, commit, merge
```

---

## Workshop Repository Structure

```text
CopyRoom/
├── README.md
├── CLAUDE.md
├── copyroom.yml
├── copyroom.lock.yml              # optional
├── pyproject.toml
├── src/copyroom/
│   ├── __init__.py
│   ├── cli.py
│   ├── models.py
│   ├── errors.py
│   ├── discovery.py
│   ├── config_loader.py
│   ├── registry.py
│   ├── project.py
│   ├── git_tools.py
│   ├── copier_tools.py
│   ├── context_tools.py
│   ├── agent_tools.py
│   ├── workshop_tools.py
│   ├── command_runner.py
│   └── output.py
├── docs/
│   ├── architecture.md
│   ├── template-taxonomy.md
│   ├── prompt-design.md
│   ├── generated-file-policy.md
│   ├── update-strategy.md
│   ├── testing-strategy.md
│   ├── release-strategy.md
│   └── template-families/
│       ├── python.md
│       ├── documentation.md
│       ├── directory-structure.md
│       ├── test-harnesses.md
│       ├── neovim.md
│       └── devenv.md
├── agents/
│   ├── base-template-agent.md
│   ├── copier-review-agent.md
│   ├── python-template-agent.md
│   ├── docs-template-agent.md
│   ├── directory-template-agent.md
│   ├── test-template-agent.md
│   ├── migration-agent.md
│   └── release-agent.md
├── skills/
│   ├── copier.md
│   ├── jinja.md
│   ├── golden-tests.md
│   ├── update-tests.md
│   ├── python-packaging.md
│   ├── pydantic.md
│   ├── sqlmodel.md
│   ├── pytest.md
│   ├── documentation.md
│   ├── markdown.md
│   ├── devenv.md
│   └── github-actions.md
├── policies/
│   ├── copier-template-policy.md
│   ├── prompt-policy.md
│   ├── generated-file-policy.md
│   ├── update-conflict-policy.md
│   ├── git-workflow-policy.md
│   └── release-policy.md
├── registry/
│   ├── python-cli-template.yml
│   └── nvim-plugin-template.yml
├── scenarios/
│   ├── python-cli-template/
│   │   └── minimal.yml
│   └── nvim-plugin-template/
│       └── minimal.yml
├── fixtures/
│   └── .gitkeep
├── generated/
│   └── .gitkeep
├── golden/
│   └── .gitkeep
├── repos/
│   └── .gitkeep
├── tests/
│   ├── test_models.py
│   ├── test_discovery.py
│   └── test_project_inspect.py
├── justfile
├── devenv.yaml
└── devenv.nix
```

### `.gitignore`

```gitignore
/repos/*
!/repos/.gitkeep
/generated/*
!/generated/.gitkeep
```

---

## Pydantic Models

```python
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class GitPolicy(BaseModel):
    default_branch: str = "main"
    update_branch_prefix: str = "template-update/"
    feature_branch_prefix: str = "feature/"
    fix_branch_prefix: str = "fix/"
    release_branch_prefix: str = "release/"
    tag_prefix: str = "v"
    require_clean_worktree: bool = True


class ContextConfig(BaseModel):
    docs: list[Path] = Field(default_factory=list)
    source: list[Path] = Field(default_factory=list)
    config: list[Path] = Field(default_factory=list)


class ProjectMetadata(BaseModel):
    kind: Literal["generated-project", "template-repo", "shared-tooling"]
    name: str | None = None
    template_id: str | None = None
    template_source: str | None = None
    template_ref_policy: Literal["tagged", "branch", "commit", "unknown"] = "unknown"
    answers_file: Path = Path(".copier-answers.yml")


class DevenvConfig(BaseModel):
    enabled: bool = False
    shell_command: str = "devenv shell"


class CopyRoomProjectConfig(BaseModel):
    version: int = 1
    project: ProjectMetadata
    git: GitPolicy = Field(default_factory=GitPolicy)
    context: ContextConfig = Field(default_factory=ContextConfig)
    devenv: DevenvConfig = Field(default_factory=DevenvConfig)
    commands: dict[str, list[str]] = Field(default_factory=dict)


class CommandResult(BaseModel):
    command: list[str]
    cwd: Path
    status: Literal["passed", "failed", "skipped"]
    return_code: int | None = None
    stdout: str = ""
    stderr: str = ""


class TemplateUpdateSummary(BaseModel):
    project_name: str | None = None
    template_id: str
    previous_ref: str | None = None
    target_ref: str | None = None
    branch: str | None = None
    changed_files: list[Path] = Field(default_factory=list)
    conflict_files: list[Path] = Field(default_factory=list)
    check_results: list[CommandResult] = Field(default_factory=list)
    suggested_commit_message: str | None = None
```

---

## Command Surface

### v0.1.0 commands (Phase 1)

```bash
copyroom version
copyroom status
copyroom explain-mode
copyroom project inspect
copyroom project inspect --json
copyroom template status
copyroom template status --json
```

All read-only. All safe. These force the full foundation to exist: package skeleton, CLI framework, Pydantic models, config loading, mode detection, `.copier-answers.yml` parsing, git tag inspection, and human + JSON output.

### v0.2.0 commands (Phase 2)

```bash
copyroom project new <template-source> [target-dir]
copyroom project new <template-source> [target-dir] --answers <file>
copyroom project new <template-source> [target-dir] --json
copyroom template update
copyroom template update --to <version>
copyroom template update --branch
copyroom template diff
copyroom project check
copyroom project run <command-name>
```

### v0.3.0 commands (Phase 3)

```bash
copyroom git ensure-clean
copyroom git start-template-update <template-id> <version>
copyroom git start-work <branch-name>
```

### v0.4.0 commands (Phase 4)

```bash
copyroom agent brief
copyroom agent brief --json
copyroom agent tools
copyroom agent tools --json
copyroom context roots
copyroom context roots --json
```

### v0.5.0+ commands (Phase 5+)

```bash
# Workshop operations
copyroom registry validate
copyroom repo sync
copyroom repo status
copyroom render <template-id> <scenario>
copyroom test <template-id> <scenario>
copyroom update-test <template-id> <scenario>
copyroom golden diff <template-id> <scenario>
copyroom golden refresh <template-id> <scenario>
copyroom matrix <template-id>

# Release (advisory only)
copyroom release check <template-id>
```

---

## Build Order

### Phase 1: Foundation (v0.1.0)

```text
Deliver:
  copyroom version, status, explain-mode
  copyroom project inspect (+ --json)
  copyroom template status (+ --json)

Build:
  Python package with CLI entrypoint (click or typer)
  Pydantic models for all config types
  Config loading (copyroom.yml, copyroom.project.yml, .copier-answers.yml)
  Mode detection (workshop, project, template-repo, standalone)
  Human-readable and JSON output
  Unit tests for models, discovery, config loading
  Integration tests with temp directory fixtures
```

### Phase 2: Project creation and template updates (v0.2.0)

```text
Deliver:
  copyroom project new <template-source> [target-dir] (+ --answers, --json)
  copyroom template update (+ --to, --branch)
  copyroom template diff
  copyroom project check
  copyroom project run <command>

Build:
  copier_tools.py — wrap copier copy and copier update with safety checks
  command_runner.py — safe subprocess execution
  Post-create and post-update check runner
  Creation and update summary reporting
```

### Phase 3: Git workflow (v0.3.0)

```text
Deliver:
  copyroom git ensure-clean
  copyroom git start-template-update
  copyroom git start-work

Build:
  git_tools.py — worktree checks, branch creation
  Integration with template update workflow
```

### Phase 4: Agent support (v0.4.0)

```text
Deliver:
  copyroom agent brief (+ --json)
  copyroom agent tools (+ --json)
  copyroom context roots (+ --json)

Build:
  agent_tools.py — brief generation, tool manifest
  context_tools.py — context root listing from config
```

### Phase 5: Workshop operations (v0.5.0+)

```text
Deliver:
  Workshop render, test, update-test, golden diff commands
  Registry validation
  Repo sync and status
  Release checks (advisory only)

Build:
  workshop_tools.py — registry-driven operations
  Port existing shell scripts to CLI commands
```

### Decision: First template integration

Start with `python-cli-template`. It exercises the full config surface (pyproject.toml, src layout, tests, uv, ruff, pytest) and the tooling is familiar since CopyRoom itself is Python. Use `nvim-plugin-template` as the second template to prove generalization.

---

## Workshop Command Surface (justfile)

```just
repos:
    ./scripts/repo-sync

status:
    ./scripts/repo-status

render template scenario:
    ./scripts/render-scenario {{ template }} {{ scenario }}

test template scenario:
    ./scripts/test-generated {{ template }} {{ scenario }}

update-test template scenario:
    ./scripts/test-update {{ template }} {{ scenario }}

golden template scenario:
    ./scripts/diff-golden {{ template }} {{ scenario }}

refresh-golden template scenario:
    ./scripts/refresh-golden {{ template }} {{ scenario }}

matrix template:
    ./scripts/test-matrix {{ template }}

matrix-all:
    ./scripts/test-matrix --all

release-check template:
    ./scripts/release-template {{ template }} --check
```

The command layer should be boring and predictable.

---

## Example Workflows

### Modify a template

```text
1. Read registry/python-cli-template.yml.
2. Confirm repos/python-cli-template exists and is on the intended branch.
3. Read relevant docs, skills, policies, and scenarios.
4. Modify files in repos/python-cli-template.
5. Render scenarios into generated/python-cli-template/.
6. Run generated tests.
7. Run update tests.
8. Compare golden outputs.
9. Review diffs in both the template repo and generated outputs.
10. Prepare release notes if the change is intended for release.
```

### Add a new template

```text
1. Create or identify the canonical template repo.
2. Add a registry entry under registry/.
3. Add at least one scenario under scenarios/<template-id>/.
4. Add a minimal golden tree or important-file snapshot.
5. Add generated test commands to the registry.
6. Run render, test, update-test, and golden checks.
7. Add template-family documentation if this is a new category.

Minimum files:
  registry/new-template.yml
  scenarios/new-template/minimal.yml
  golden/new-template/minimal/tree.txt
```

### Create a new project from a template

```bash
copyroom project new git@github.com:Bullish-Design/python-cli-template.git ./my-new-project
cd my-new-project
copyroom project inspect
# The template's prompts run interactively. Answers are recorded in .copier-answers.yml.
# Post-create commands run automatically.
```

### Update a generated project from its template

```bash
copyroom template status
copyroom template update --to v0.4.0
copyroom project run post-template-update
git diff
# review, commit, merge
```

### Agent workflow inside a generated project

```bash
copyroom agent brief
copyroom agent tools --json
copyroom context roots
# agent reads files from context roots, uses standard tools
```

---

## Anti-Patterns

```text
- making CopyRoom the canonical source of all template code
- copying template source into CopyRoom manually
- committing generated scratch outputs
- snapshotting too much golden output
- relying only on copier copy without update tests
- manually editing .copier-answers.yml
- using one branch per generated project in a template repo
- putting large reusable scripts in every generated project
- making project-specific behavior live in shared tooling
- treating shared tooling and generated project skeletons as the same thing
- hiding template copy or update behavior behind opaque automation
- letting agents operate without context roots and workflow policy
- building context search or devenv wrappers before the core works
- attempting automatic rollback of failed operations
- fetching and executing remote code
```

---

## Summary

CopyRoom is a coordinated ecosystem, not one repository that contains everything.

```text
CopyRoom workshop
  Coordinates, validates, documents, and releases template work.

copyroom CLI
  uv-installable tool for project creation, safe updates,
  git workflow helpers, and agent-facing structured output.

Template repos
  Independent Copier templates, directly consumable, tagged with semver.

Shared tooling repos
  Reusable behavior imported or referenced by generated projects.

Generated projects
  Normal repositories that own local decisions after generation.
```

Build order follows the value curve: mode detection and inspection first, safe project creation and template updates second, git workflow third, agent support fourth, workshop operations fifth. Everything else comes after demonstrated need.
