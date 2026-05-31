# CopyRoom: Generic Copier Template Workshop Concept

**Status:** Refined concept and architecture proposal  
**Audience:** Maintainers of multiple Copier templates, shared development modules, generated project skeletons, and agent-assisted template workflows  
**Date:** 2026-05-26  
**Primary decision:** Use **CopyRoom** as a generic template workshop that coordinates many independent Git-hosted Copier template repositories through local checkouts, registry metadata, scenarios, tests, golden outputs, policies, and agent context.

---

## Executive Summary

CopyRoom is a template operations workspace.

It is not itself the canonical source of every template. Instead, it is a dedicated repository that helps create, inspect, modify, test, update, validate, and release many separate Copier template repositories.

The model is:

```text
CopyRoom
  Generic template workshop and control plane.
  Owns docs, policies, agents, registry, scenarios, fixtures, tests,
  golden outputs, generated sandboxes, and release workflows.

Template repositories
  Independent Git repositories containing actual Copier templates.
  Examples: python-cli-template, docs-site-template, nvim-plugin-template.

Shared tooling repositories
  Independent Git repositories containing reusable behavior or infrastructure.
  Examples: shared devenv modules, shared CI actions, shared lint configs.

Generated projects
  Output repositories or directory trees produced by Copier templates.
  They own their local project-specific choices.
```

The practical rule is:

> **CopyRoom coordinates template work. Template repos contain template source. Shared tooling repos contain reusable behavior. Generated projects contain local project choices.**

This keeps CopyRoom generic enough to manage Python templates, documentation templates, directory structure templates, test harness templates, Neovim/devenv templates, and future template families without making CopyRoom itself a monolithic template repo.

---

## Core Goals

CopyRoom should answer five questions for every registered template:

```text
1. Can the template render?
2. Does the generated output work?
3. Can existing generated projects be updated safely?
4. Did the generated output change intentionally?
5. Is the template ready to release?
```

It should also give agents enough persistent context to make useful changes without rediscovering the template architecture every time.

The goal is not only to store templates. The goal is to create a repeatable operating environment for template development.

---

## Non-Goals

CopyRoom should not become:

```text
- the canonical source tree for every template
- a replacement for individual template repositories
- a dumping ground for generated project code
- a branch-per-template or branch-per-project system
- a place where generated project-specific behavior is centralized
- a hidden layer required by users who only want to run copier copy
```

Users of a template should still be able to consume the actual template repo directly with Copier.

CopyRoom is for maintainers and agents, not required runtime infrastructure for generated projects.

---

## Option C Repository Model

The selected model is a hybrid workspace:

```text
Canonical GitHub repos remain separate.
CopyRoom checks them out locally under repos/.
CopyRoom tracks metadata, scenarios, policies, and tests for those repos.
```

Example external canonical repos:

```text
CopyRoom
python-package-template
python-cli-template
python-fastapi-service-template
python-sqlmodel-app-template
docs-site-template
markdown-docset-template
directory-skeleton-template
pytest-harness-template
nvim-plugin-template
nvim-plugin-devenv
shared-python-devenv
shared-github-actions
```

Example local workspace:

```text
CopyRoom/
├── registry/
├── scenarios/
├── agents/
├── skills/
├── policies/
├── tests/
├── generated/
├── golden/
└── repos/
    ├── python-package-template/
    ├── python-cli-template/
    ├── docs-site-template/
    ├── directory-skeleton-template/
    ├── pytest-harness-template/
    ├── nvim-plugin-template/
    └── nvim-plugin-devenv/
```

`repos/` contains local Git clones, not source files tracked directly by CopyRoom.

Recommended `.gitignore`:

```gitignore
/repos/*
!/repos/.gitkeep
/generated/*
!/generated/.gitkeep
```

CopyRoom tracks the registry entry for `python-cli-template`, not the full source of `python-cli-template`.

---

## Why Not a Monorepo?

A monorepo can be convenient during early experiments, but it weakens important separations:

```text
- each template should be independently versioned
- each template should be directly consumable by Copier
- shared tooling should be independently versioned
- generated projects should pin or update template/tooling versions intentionally
```

Keeping canonical template repositories separate also makes it easier to release, tag, deprecate, or replace templates independently.

CopyRoom still gives you a unified local operating environment without forcing all template source into one repository.

---

## Why Not Git Submodules by Default?

Git submodules can work, but they add operational friction:

```text
- branch switching is more awkward
- local agent edits are more cumbersome
- partial checkouts are easier to confuse
- submodule pointers add another commit-management layer
```

The default should be plain local clones managed by scripts.

Submodules can be added later if you want CopyRoom commits to pin exact template commits. A lighter-weight alternative is a generated lock file.

---

## Workspace Locking

CopyRoom can optionally support a lock file:

```text
copyroom.lock.yml
```

Example:

```yaml
repos:
  python-cli-template:
    remote: git@github.com:Bullish-Design/python-cli-template.git
    branch: main
    commit: abc1234

  nvim-plugin-template:
    remote: git@github.com:Bullish-Design/nvim-plugin-template.git
    branch: main
    commit: def5678
```

Use the lock file when you want reproducible workshop test runs or release validation.

The lock file should not be required for normal local experimentation.

---

## Recommended CopyRoom Repository Structure

```text
CopyRoom/
├── README.md
├── copyroom.yml
├── copyroom.lock.yml              # optional, generated or manually refreshed
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
│   └── release-policy.md
├── registry/
│   ├── python-package-template.yml
│   ├── python-cli-template.yml
│   ├── python-service-template.yml
│   ├── docs-site-template.yml
│   ├── directory-skeleton-template.yml
│   ├── pytest-harness-template.yml
│   ├── nvim-plugin-template.yml
│   └── nvim-plugin-devenv.yml
├── scenarios/
│   ├── python-cli-template/
│   │   ├── minimal.yml
│   │   ├── pydantic.yml
│   │   ├── sqlmodel.yml
│   │   └── ci-enabled.yml
│   ├── docs-site-template/
│   │   ├── minimal.yml
│   │   ├── mkdocs.yml
│   │   └── adr-enabled.yml
│   ├── directory-skeleton-template/
│   │   ├── minimal.yml
│   │   └── monorepo.yml
│   └── nvim-plugin-template/
│       ├── minimal.yml
│       ├── mini-test.yml
│       └── busted.yml
├── fixtures/
│   ├── existing-python-package/
│   ├── existing-docs-repo/
│   ├── existing-mature-plugin/
│   └── local-shared-modules/
├── generated/
│   └── .gitkeep
├── golden/
│   ├── python-cli-template/
│   ├── docs-site-template/
│   ├── directory-skeleton-template/
│   └── nvim-plugin-template/
├── repos/
│   └── .gitkeep
├── scripts/
│   ├── copyroom
│   ├── repo-sync
│   ├── repo-status
│   ├── render-scenario
│   ├── test-generated
│   ├── test-update
│   ├── diff-golden
│   ├── refresh-golden
│   ├── test-matrix
│   └── release-template
├── tests/
│   ├── test_registry.py
│   ├── test_render.py
│   ├── test_update.py
│   ├── test_golden.py
│   └── test_policy.py
├── justfile
├── devenv.yaml
└── devenv.nix
```

---

## Top-Level `copyroom.yml`

`copyroom.yml` defines workspace-level defaults.

```yaml
name: CopyRoom
version: 0.1.0

defaults:
  repo_dir: repos
  generated_dir: generated
  golden_dir: golden
  scenarios_dir: scenarios
  registry_dir: registry
  fixtures_dir: fixtures

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
```

This file should stay small. Detailed behavior belongs in scripts, policy docs, and registry entries.

---

## Template Registry

The registry is the center of CopyRoom.

Each template or shared tooling repo should have one registry file.

### Copier Template Entry

Example:

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
    - python -m pytest
    - python -m compileall src
  generated_check:
    - python -m pytest

checks:
  render: true
  update: true
  golden: true
  generated_tests: true

release:
  strategy: semver
  tag_prefix: v
  require_matrix: true
  require_clean_worktree: true
```

### Shared Tooling Entry

Example:

```yaml
id: nvim-plugin-devenv
kind: shared-tooling
name: Neovim Plugin Devenv Module
status: active

remote: git@github.com:Bullish-Design/nvim-plugin-devenv.git
local_path: repos/nvim-plugin-devenv
default_branch: main

checks:
  unit_tests: true
  integration_tests: true

consumed_by:
  - nvim-plugin-template

release:
  strategy: semver
  tag_prefix: v
```

### Registry Kinds

Supported initial kinds:

```text
copier-template
shared-tooling
policy-module
example-project
fixture-repo
```

Start with `copier-template` and `shared-tooling`. Add the others only when needed.

---

## Template Families

CopyRoom should classify templates by role.

### 1. Project Templates

These generate full repositories.

Examples:

```text
python-package-template
python-cli-template
python-fastapi-service-template
python-sqlmodel-app-template
neovim-plugin-template
docs-site-template
```

They need full render, generated-project tests, CI checks, golden comparison, and update simulations.

### 2. Partial Templates

These generate a subsystem inside an existing project.

Examples:

```text
pytest-harness-template
docs-directory-template
adr-directory-template
github-actions-ci-template
sqlmodel-module-template
```

They need conflict tests and update tests more than full repository tests.

### 3. Structure Templates

These generate directory layouts.

Examples:

```text
project-docs-tree-template
monorepo-layout-template
feature-module-layout-template
test-fixture-layout-template
```

They need path validation, naming-policy checks, and tree snapshots.

### 4. Policy and Config Templates

These generate configuration files.

Examples:

```text
ruff-config-template
mypy-config-template
pytest-config-template
editorconfig-template
pre-commit-config-template
mkdocs-config-template
```

They need syntax validation and compatibility tests.

### 5. Shared Behavior Modules

These are not always Copier templates.

Examples:

```text
shared-devenv-python
shared-devenv-neovim
shared-github-actions
shared-pytest-plugin
shared-docs-tooling
```

They should be tested independently and then tested again through consuming templates.

---

## Scenario Files

A scenario file is a stable set of answers or inputs used to render a template.

Example:

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

Scenarios should cover meaningful template modes:

```text
minimal
  Smallest useful render.

standard
  Normal default output.

full
  Most optional features enabled.

ci-enabled
  Includes CI configuration.

existing-repo-update
  Tests update behavior against a customized generated repo.

migration
  Tests adoption into a non-template-managed project.

edge-case-names
  Tests hyphens, underscores, package names, module names, and odd casing.
```

Do not create scenarios for every possible prompt combination. Scenarios should represent durable risk areas.

---

## Generated Output Area

`generated/` is a scratch area for rendered outputs.

Example:

```text
generated/
├── python-cli-template/
│   ├── minimal/
│   ├── pydantic/
│   └── ci-enabled/
└── nvim-plugin-template/
    ├── minimal/
    ├── mini-test/
    └── busted/
```

Generated outputs should generally not be committed.

They are used for:

```text
- local inspection
- generated-project testing
- update simulations
- diffing against golden outputs
- agent review
```

---

## Golden Outputs

`golden/` stores expected output snapshots.

Golden testing should be selective. Do not snapshot everything blindly if that makes template maintenance brittle.

Good golden targets:

```text
- rendered directory tree
- key config files
- expected README skeleton
- expected pyproject.toml
- expected copier answers shape
- expected CI workflow
- expected generated test file
```

A practical structure:

```text
golden/python-cli-template/minimal/
├── tree.txt
└── important-files/
    ├── pyproject.toml
    ├── README.md
    ├── src/demo_cli/__init__.py
    └── tests/test_import.py
```

This gives useful regression detection without freezing every generated byte.

---

## Fixtures

`fixtures/` contains input projects or local dependencies used by scenarios.

Examples:

```text
fixtures/
├── existing-python-package/
├── existing-docs-repo/
├── existing-mature-plugin/
├── local-shared-modules/
└── partially-template-managed-repo/
```

Fixtures are especially important for update and migration tests.

For example, an update test can:

```text
1. Copy fixture into generated scratch area.
2. Apply Copier template or run copier update.
3. Assert expected conflicts or clean updates.
4. Run generated-project checks.
```

---

## Update Simulation

Every long-lived template should have update tests.

Recommended flow:

```text
1. Render from the template.
2. Commit or snapshot the generated output.
3. Simulate realistic user edits.
4. Run copier update with previous answers.
5. Detect conflicts or rejected patches.
6. Run generated-project tests.
7. Produce a diff report.
```

This matters because `copier copy` success is not enough. Long-lived templates must be maintainable after generated projects diverge.

A template should not be considered release-ready if it works only on initial generation but creates unusable updates.

---

## Agent Model

CopyRoom should provide durable context for agents.

Recommended files:

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

### Base Template Agent

The base agent should define universal rules:

```text
- keep generated files small
- avoid over-prompting
- prefer durable identity prompts over implementation-detail prompts
- test both copy and update
- do not manually edit .copier-answers.yml in generated projects
- review generated diffs before release
- keep reusable behavior out of generated skeletons when practical
- version templates with tags
- do not create one branch per generated project
```

### Domain Agents

Domain agents add specific expectations.

Python template agent:

```text
- pyproject.toml conventions
- src layout
- pytest layout
- pydantic conventions
- sqlmodel conventions
- type-checking conventions
- packaging checks
```

Documentation template agent:

```text
- README structure
- docs index structure
- ADR policy
- markdown linting
- link checking
- publishing assumptions
```

Test template agent:

```text
- fixture layout
- test naming
- CI matrix
- fast versus slow tests
- smoke tests
- generated test ergonomics
```

Neovim/devenv template agent:

```text
- shared devenv logic stays in shared tooling repos
- plugin-specific setup stays in generated plugin repos
- runtime dependency setup remains simple
- generated devenv.nix files stay small
```

---

## Skills

`skills/` should hold reusable operational procedures.

Examples:

```text
skills/copier.md
  How to copy, update, recopy, inspect answers, handle conflicts.

skills/jinja.md
  Jinja conventions, path templating, filters, escaping, conditionals.

skills/golden-tests.md
  How to snapshot, normalize, diff, and refresh golden outputs.

skills/update-tests.md
  How to simulate user edits and validate copier update behavior.

skills/python-packaging.md
  pyproject conventions, build checks, package imports, test commands.

skills/devenv.md
  Shared module conventions, generated local devenv files, lock strategy.
```

Skills should be concrete enough for an agent or maintainer to apply, but not so template-specific that they duplicate registry entries.

---

## Policies

Policies define durable rules across template families.

Recommended initial policies:

```text
policies/copier-template-policy.md
policies/prompt-policy.md
policies/generated-file-policy.md
policies/update-conflict-policy.md
policies/release-policy.md
```

### Prompt Policy

Good prompts:

```text
- project name
- package or module name
- description
- repository owner
- license
- broad feature inclusion
- test runner choice
- shared tooling reference
```

Avoid prompts for:

```text
- every possible dependency
- every future README section
- every optional config detail
- things that should be edited locally after generation
```

### Generated File Policy

Generated files should be small and understandable.

Prefer:

```text
- small local config files
- small starter tests
- minimal README skeletons
- delegation to shared tooling where appropriate
```

Avoid:

```text
- large duplicated scripts in every generated repo
- overgenerated application logic
- hidden behavior that users cannot easily modify
- generated files that churn heavily across template releases
```

---

## Shared Tooling Repositories

Some reusable behavior should live outside Copier templates.

Examples:

```text
shared-devenv-python
shared-devenv-neovim
shared-github-actions
shared-docs-tooling
shared-pytest-tools
```

Use shared tooling when logic is:

```text
- reusable across many generated projects
- likely to improve independently
- too large to duplicate in generated repos
- better versioned separately
```

Use generated template files when content is:

```text
- identity-specific
- intentionally local
- expected to diverge
- small enough for users to understand and edit
```

This generalizes the Neovim model where the Copier template generates a small local project skeleton, while reusable development behavior lives in a separate shared devenv module.

---

## Command Surface

Use consistent commands across all template families.

Example `justfile`:

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

release template version:
    ./scripts/release-template {{ template }} {{ version }}
```

The command layer should be boring and predictable. Agents should not need to invent one-off commands for every template.

---

## Example Workflow: Modify a Python CLI Template

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

Example commands:

```bash
just status
just render python-cli-template minimal
just test python-cli-template minimal
just update-test python-cli-template minimal
just golden python-cli-template minimal
just matrix python-cli-template
```

---

## Example Workflow: Add a New Template

```text
1. Create or identify the canonical template repo.
2. Add a registry entry under registry/.
3. Add at least one scenario under scenarios/<template-id>/.
4. Add a minimal golden tree or important-file snapshot.
5. Add generated test commands to the registry.
6. Run render, test, update-test, and golden checks.
7. Add template-family documentation if this is a new category.
```

Minimum files:

```text
registry/new-template.yml
scenarios/new-template/minimal.yml
golden/new-template/minimal/tree.txt
```

---

## Example Workflow: Release a Template

```text
1. Confirm target template repo is clean or has only intended changes.
2. Run the template matrix.
3. Run update tests.
4. Review golden diffs.
5. Update template changelog.
6. Tag the template repo.
7. Optionally refresh CopyRoom lock file.
8. Commit CopyRoom scenario, policy, or golden updates if needed.
```

Release should happen in the canonical template repo, not inside CopyRoom unless CopyRoom itself changed.

---

## Initial MVP

Start with a small CopyRoom.

```text
CopyRoom/
├── README.md
├── copyroom.yml
├── registry/
│   ├── python-cli-template.yml
│   └── nvim-plugin-template.yml
├── scenarios/
│   ├── python-cli-template/
│   │   └── minimal.yml
│   └── nvim-plugin-template/
│       └── minimal.yml
├── agents/
│   ├── base-template-agent.md
│   └── copier-template-agent.md
├── scripts/
│   ├── repo-sync
│   ├── repo-status
│   ├── render-scenario
│   ├── test-generated
│   └── test-update
├── repos/
│   └── .gitkeep
├── generated/
│   └── .gitkeep
├── golden/
│   └── .gitkeep
└── justfile
```

Then add:

```text
- fixtures/
- tests/
- policies/
- skills/
- release automation
- copyroom.lock.yml
- more template families
```

---

## Recommended Build Order

### Step 1: Create CopyRoom Skeleton

Create the repo structure, `copyroom.yml`, `.gitignore`, and base `justfile`.

Minimum directories:

```text
registry/
scenarios/
agents/
scripts/
repos/
generated/
golden/
```

### Step 2: Register One Real Template

Start with one active template, such as `nvim-plugin-template` or `python-cli-template`.

Add:

```text
registry/<template-id>.yml
scenarios/<template-id>/minimal.yml
```

### Step 3: Implement Repo Sync and Status

Implement enough scripts to clone or validate local repos:

```text
repo-sync
repo-status
```

### Step 4: Implement Render Scenario

Render a scenario into `generated/<template-id>/<scenario>/`.

### Step 5: Implement Generated Tests

Run the commands defined by the registry entry.

### Step 6: Add Update Tests

Simulate `copier update` behavior for at least one template.

### Step 7: Add Golden Diffs

Start with tree snapshots and selected important files.

### Step 8: Add More Templates

Once the pattern works for one template, add Python, docs, directory, and test harness templates.

---

## Anti-Patterns

Avoid:

```text
- making CopyRoom the canonical source of every template
- copying template source into CopyRoom manually
- relying only on copier copy without copier update tests
- committing generated scratch outputs
- snapshotting too much golden output
- creating one branch per generated project
- over-prompting in copier.yml
- putting large reusable behavior into generated repos
- treating shared tooling and generated project skeletons as the same thing
- hiding template behavior in scripts that generated project users cannot inspect
```

---

## Final Concept

CopyRoom is a generic template workshop for a family of Copier templates and template-adjacent shared tooling.

It provides:

```text
- a registry of template and shared tooling repos
- local checkout orchestration
- durable agent context
- reusable template skills
- prompt and generated-file policies
- render scenarios
- generated-project tests
- update simulations
- golden output comparisons
- release checks
```

It deliberately keeps canonical template source in independent Git repositories.

The durable operating model is:

```text
CopyRoom
  Coordinates, validates, documents, and releases template work.

Template repos
  Contain Copier template source and are consumed directly by users.

Shared tooling repos
  Contain reusable behavior imported or referenced by generated projects.

Generated projects
  Own local project-specific decisions after generation.
```

This gives you a scalable way to manage Neovim/devenv templates, Python templates, documentation templates, directory structure templates, test harness templates, and future template families from one coherent workshop without collapsing all template source into one repository.
