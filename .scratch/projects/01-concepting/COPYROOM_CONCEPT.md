# CopyRoom: Workshop + Installable Agent Toolkit Concept

**Status:** Detailed architecture concept  
**Audience:** Maintainers of Copier templates, generated project repositories, shared tooling repositories, and local LLM-agent workflows  
**Date:** 2026-05-28  
**Primary decision:** Build CopyRoom as both a template-maintainer workshop and a `uv`-installable project-side CLI/toolkit that helps humans and LLM agents create, update, inspect, test, and release Copier-managed projects.

---

## Executive Summary

CopyRoom should become a two-surface system built around one shared operating model.

```text
CopyRoom workshop repository
  Maintainer workspace.
  Coordinates many independent Copier template repositories and shared tooling repositories.
  Owns registry metadata, scenarios, fixtures, golden outputs, policies, skills,
  agent context, test runners, release checks, and generated sandboxes.

copyroom installable tool
  uv-installable Python CLI.
  Can run inside the CopyRoom workshop or inside generated project repositories.
  Provides project inspection, safe Copier updates, git workflow helpers,
  context discovery, devenv-aware lookup, and local agent tools.

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

The main rule remains:

> **CopyRoom coordinates template work. Template repositories contain template source. Shared tooling repositories contain reusable behavior. Generated projects contain local project choices.**

The new extension is:

> **The `copyroom` CLI makes the CopyRoom operating model usable from inside any generated project.**

This gives maintainers a single workshop for template operations, while giving project-local agents a stable tool surface for understanding and safely updating the project.

---

## Core Problem

The original CopyRoom concept solves the maintainer-side problem:

```text
How do we manage many independent Copier templates without turning them into
one monolithic repository or letting them drift without tests, policy, or
release discipline?
```

The expanded requirement adds a project-side problem:

```text
How can generated projects carry enough local metadata and tooling so that
humans and LLM agents can safely update from their templates, follow the
intended git workflow, find relevant context, inspect dependencies, and use
shared environment capabilities?
```

The answer is not to make generated projects depend on the CopyRoom workshop repository. That would make CopyRoom a hidden runtime dependency.

The answer is to create a small, installable tool that understands the same concepts:

```text
registry
project manifest
Copier answers
template identity
shared tooling
context roots
git workflow policy
generated-file policy
local check commands
agent briefing
```

---

## Design Goals

CopyRoom should support both maintainers and generated-project users.

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

Inside a generated project, the installable tool should answer these questions:

```text
1. Which template generated this project?
2. Which template revision or version is currently recorded?
3. How should this project receive template updates?
4. What branch naming and tagging workflow should be used?
5. Which files are generated, local, policy-managed, or intentionally divergent?
6. Which commands should be run after a template update?
7. Where should a local agent search for context?
8. How can an agent inspect the development environment and dependencies?
9. What local tools are available to the agent?
10. What is the safest next step for updating, testing, or releasing?
```

---

## Non-Goals

CopyRoom should not become:

```text
- the canonical source tree for every template
- a replacement for individual template repositories
- a replacement for Copier
- a replacement for git
- a replacement for uv, devenv, pytest, ruff, just, or other project tools
- a hidden runtime dependency for generated projects
- a branch-per-template or branch-per-project system
- a large generated script bundle copied into every generated repository
- a central place where project-specific behavior is forced back into templates
```

Generated projects should still be usable as normal repositories.

A user should still be able to run a project without knowing CopyRoom exists.

A user should still be able to consume a template directly with Copier.

The `copyroom` CLI should add structure, guardrails, and agent affordances. It should not obscure the underlying tools.

---

## Final Mental Model

```text
┌────────────────────────────────────────────────────────────────────┐
│ CopyRoom workshop                                                   │
│                                                                    │
│ Maintainer control plane.                                          │
│ Owns registry, scenarios, policies, skills, agents, fixtures,      │
│ generated sandboxes, golden outputs, and release checks.           │
└───────────────┬───────────────────────────────────────┬────────────┘
                │                                       │
                │ manages local clones                   │ shares config model
                │                                       │
┌───────────────▼──────────────────────┐      ┌─────────▼─────────────┐
│ Template repos                         │      │ copyroom CLI/tool      │
│                                      │      │                       │
│ Independent Git repos containing      │      │ uv-installable Python  │
│ Copier templates.                     │      │ tool. Runs in workshop │
│                                      │      │ or generated projects. │
└───────────────┬──────────────────────┘      └─────────┬─────────────┘
                │                                       │
                │ copier copy/update                     │ project-local commands
                │                                       │
┌───────────────▼───────────────────────────────────────▼────────────┐
│ Generated project repository                                        │
│                                                                    │
│ Normal project repo. Contains application code, docs, tests,       │
│ .copier-answers.yml, optional copyroom.project.yml, and local       │
│ project-specific decisions.                                        │
└────────────────────────────────────────────────────────────────────┘
```

CopyRoom is not one repository that contains everything. It is a coordinated ecosystem.

---

## Repository Architecture

### 1. CopyRoom workshop repository

Recommended structure:

```text
CopyRoom/
├── README.md
├── copyroom.yml
├── copyroom.lock.yml              # optional generated lock file
├── pyproject.toml                 # optional, if the CLI lives in this repo
├── src/
│   └── copyroom/                  # optional, if the CLI lives in this repo
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
│   ├── agent-tool-policy.md
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

### 2. `copyroom` installable tool repository

There are two viable options.

#### Option A: CLI lives inside CopyRoom

```text
CopyRoom/
├── pyproject.toml
├── src/copyroom/
└── ...workshop files...
```

Use this when the tool and workshop will evolve together early on.

Benefits:

```text
- fewer repositories at the beginning
- simple local development
- CLI can be tested against real workshop files
- easier agent context
```

Costs:

```text
- the workshop repo also becomes a Python package repo
- release cadence for the CLI and workshop may become coupled
```

#### Option B: CLI lives in a separate `copyroom-tool` repo

```text
copyroom-tool/
├── pyproject.toml
├── src/copyroom/
└── tests/

CopyRoom/
├── copyroom.yml
├── registry/
├── scenarios/
└── ...workshop files...
```

Use this once the tool is stable enough to be reused across many projects.

Benefits:

```text
- clean package release boundary
- generated projects install only the tool, not the whole workshop
- independent versioning
- smaller dependency surface
```

Costs:

```text
- one more repository
- needs compatibility tests between tool versions and workshop config versions
```

Recommended path:

```text
Start with Option A if convenient.
Extract to Option B once the command model stabilizes.
```

### 3. Template repositories

Template repositories remain independent Git repos.

Examples:

```text
python-cli-template/
├── copier.yml
├── template/
└── README.md

docs-site-template/
├── copier.yml
├── template/
└── README.md

nvim-plugin-template/
├── copier.yml
├── template/
└── README.md
```

They should still be directly usable:

```bash
copier copy gh:Bullish-Design/python-cli-template my-project
```

CopyRoom should improve maintenance, validation, release, and project-side updates. It should not make templates unusable without the workshop.

### 4. Shared tooling repositories

Shared tooling repositories are also independent.

Examples:

```text
shared-python-devenv/
shared-neovim-devenv/
shared-github-actions/
shared-pytest-tools/
shared-docs-tooling/
```

Use shared tooling when reusable behavior is:

```text
- large enough that copying it into every generated project would create drift
- reused across many templates or projects
- versioned independently
- easier to test as a standalone module
```

Use generated template files when content is:

```text
- identity-specific
- intentionally local
- expected to diverge
- small enough to read and edit directly
```

---

## `copyroom` CLI Architecture

The `copyroom` CLI should be a Python package with a clear internal module structure.

Recommended package layout:

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
├── devenv_tools.py
├── agent_tools.py
├── workshop_tools.py
├── command_runner.py
└── output.py
```

### Responsibilities

```text
cli.py
  Defines command groups and maps commands to application services.

models.py
  Pydantic models for workshop config, registry entries, project manifests,
  git policies, context roots, command results, and agent tool descriptions.

discovery.py
  Detects whether the current directory is a CopyRoom workshop,
  generated project, template repo, shared tooling repo, or standalone directory.

config_loader.py
  Loads and validates copyroom.yml, copyroom.project.yml, registry files,
  lock files, and local overrides.

registry.py
  Reads template and shared-tooling registry entries.

project.py
  Inspects generated projects, .copier-answers.yml, project manifest,
  local commands, and local file policies.

git_tools.py
  Provides clean worktree checks, branch helpers, tagging helpers,
  changelog helpers, and comparison helpers.

copier_tools.py
  Wraps copier copy, copier update, scenario rendering, update simulation,
  conflict detection, and answer-file inspection.

context_tools.py
  Finds, indexes, searches, and packages local context for humans and agents.

devenv_tools.py
  Detects devenv availability, reads devenv files, runs configured commands,
  and helps locate tools or dependency source from inside a devenv project.

agent_tools.py
  Emits structured agent briefs, tool manifests, workflow summaries,
  risk notes, and context bundles.

workshop_tools.py
  Runs repo sync, repo status, render scenarios, generated tests,
  golden diffs, update tests, and release checks in workshop mode.

command_runner.py
  Provides safe subprocess execution with captured output, cwd handling,
  environment control, and structured results.

output.py
  Handles human-readable output and JSON output consistently.
```

---

## CLI Modes

The CLI should detect its operating mode automatically.

### 1. Workshop mode

Detected when the current directory or an ancestor contains:

```text
copyroom.yml
registry/
scenarios/
```

Workshop mode enables:

```text
copyroom repo sync
copyroom repo status
copyroom registry validate
copyroom render <template-id> <scenario>
copyroom test <template-id> <scenario>
copyroom update-test <template-id> <scenario>
copyroom golden diff <template-id> <scenario>
copyroom golden refresh <template-id> <scenario>
copyroom matrix <template-id>
copyroom release check <template-id>
copyroom release tag <template-id> <version>
```

### 2. Project mode

Detected when the current directory or an ancestor contains:

```text
.copier-answers.yml
copyroom.project.yml
```

Project mode enables:

```text
copyroom project inspect
copyroom project check
copyroom template status
copyroom template update
copyroom template diff
copyroom git ensure-clean
copyroom git start-template-update
copyroom context roots
copyroom context search
copyroom devenv status
copyroom agent brief
copyroom agent tools
```

### 3. Template repository mode

Detected when the current directory or an ancestor contains:

```text
copier.yml
```

Template repository mode enables:

```text
copyroom template inspect-source
copyroom template validate-source
copyroom template render-local
copyroom template release-check-local
```

This mode is useful when a maintainer or agent is working directly inside a template repo outside the full CopyRoom workshop.

### 4. Shared tooling repository mode

Detected by a local manifest such as:

```text
copyroom.tooling.yml
```

Shared tooling mode enables:

```text
copyroom tooling inspect
copyroom tooling consumers
copyroom tooling release-check
```

### 5. Standalone mode

Detected when none of the above exists.

Standalone mode should provide limited commands:

```text
copyroom init project-manifest
copyroom init workshop
copyroom help workflows
copyroom version
```

---

## Workshop Configuration: `copyroom.yml`

The workshop-level config should stay small.

Example:

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

The workshop config defines defaults. Template-specific detail belongs in registry entries.

---

## Project Configuration: `copyroom.project.yml`

Generated projects should optionally include a small local manifest.

This manifest should not duplicate the entire workshop registry. It should provide enough local metadata for the CLI and local agents.

Example:

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
  generated_policy:
    - .copier-answers.yml
    - copyroom.project.yml

devenv:
  enabled: false
  shell_command: devenv shell
  dependency_lookup:
    python_packages: true
    nix_store: false
    local_sources: true

commands:
  check:
    - uv run pytest
  lint:
    - uv run ruff check
  format:
    - uv run ruff format
  typecheck:
    - uv run pyright
  post_template_update:
    - uv run pytest
    - uv run ruff check
```

For a Neovim/devenv project:

```yaml
copyroom:
  version: 1

project:
  kind: generated-project
  name: tasknotes.nvim
  template_id: nvim-plugin-template
  template_source: git@github.com:Bullish-Design/nvim-plugin-template.git
  template_ref_policy: tagged
  answers_file: .copier-answers.yml

git:
  default_branch: main
  update_branch_prefix: template-update/
  release_branch_prefix: release/
  tag_prefix: v
  require_clean_worktree: true

context:
  docs:
    - README.md
    - docs/
    - .agents/
  source:
    - lua/
    - plugin/
    - tests/
    - dev/
  config:
    - devenv.yaml
    - devenv.nix
    - devenv.lock
    - stylua.toml
    - selene.toml
    - .copier-answers.yml
    - copyroom.project.yml

devenv:
  enabled: true
  shell_command: devenv shell
  dependency_lookup:
    nix_store: true
    local_sources: true
    neovim_runtime: true

commands:
  check:
    - nvim-dev-check
  test:
    - nvim-dev-test
  format:
    - nvim-dev-format
  bootstrap:
    - nvim-dev-bootstrap
  post_template_update:
    - nvim-dev-test
    - nvim-dev-check
```

---

## Relationship to `.copier-answers.yml`

Generated projects should keep `.copier-answers.yml` as the authoritative Copier state file.

`copyroom.project.yml` should not replace it.

Use the two files for different purposes:

```text
.copier-answers.yml
  Copier-owned state.
  Records template source, template version/ref, and template answers.
  Used by copier update.
  Should not be manually edited in normal workflows.

copyroom.project.yml
  CopyRoom-owned project metadata.
  Records local workflow preferences, context roots, check commands,
  agent hints, git policy, and environment integration.
  Can be generated by the template and edited locally when needed.
```

The CLI should read both.

When they disagree, the CLI should treat `.copier-answers.yml` as authoritative for Copier operations and `copyroom.project.yml` as advisory workflow metadata.

---

## Template Registry

The registry remains the center of workshop-side metadata.

### Copier template registry entry

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

### Shared tooling registry entry

Example:

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
  - python-service-template

release:
  strategy: semver
  tag_prefix: v
```

### Registry kinds

Initial kinds:

```text
copier-template
shared-tooling
example-project
fixture-repo
policy-module
```

Start with only:

```text
copier-template
shared-tooling
```

Add others only when they become useful.

---

## Command Surface

The command surface should be boring, predictable, and friendly to both humans and agents.

### Global commands

```bash
copyroom version
copyroom status
copyroom doctor
copyroom explain-mode
```

### Workshop commands

```bash
copyroom registry validate
copyroom repo sync
copyroom repo status
copyroom render <template-id> <scenario>
copyroom test <template-id> <scenario>
copyroom update-test <template-id> <scenario>
copyroom golden diff <template-id> <scenario>
copyroom golden refresh <template-id> <scenario>
copyroom matrix <template-id>
copyroom matrix --all
copyroom release check <template-id>
copyroom release tag <template-id> <version>
```

### Project commands

```bash
copyroom project inspect
copyroom project inspect --json
copyroom project check
copyroom project run check
copyroom project run post-template-update
```

### Template update commands

```bash
copyroom template status
copyroom template status --json
copyroom template update
copyroom template update --to v0.4.0
copyroom template update --branch
copyroom template diff
copyroom template conflicts
copyroom template explain
```

### Git workflow commands

```bash
copyroom git status
copyroom git ensure-clean
copyroom git start-work feature/add-auth-template
copyroom git start-template-update python-cli-template v0.4.0
copyroom git release-branch v1.2.0
copyroom git tag-release v1.2.0
copyroom git changelog-since v1.1.0
copyroom git compare v1.1.0..v1.2.0
```

### Context commands

```bash
copyroom context roots
copyroom context files
copyroom context search "dependency injection"
copyroom context grep "copier update"
copyroom context summarize
copyroom context agent-pack
```

### Devenv commands

```bash
copyroom devenv status
copyroom devenv shell-info
copyroom devenv run nvim-dev-test
copyroom devenv locate-bin lua-language-server
copyroom devenv dependency-source pydantic
copyroom devenv neovim-runtime
```

### Agent commands

```bash
copyroom agent brief
copyroom agent brief --json
copyroom agent tools
copyroom agent tools --json
copyroom agent workflow update-template
copyroom agent workflow release
copyroom agent risks
copyroom agent context-pack
```

---

## Safe Copier Update Workflow

Raw `copier update` is useful but easy to run too casually.

`copyroom template update` should wrap it with a safe workflow.

Recommended flow:

```text
1. Detect project root.
2. Load .copier-answers.yml.
3. Load copyroom.project.yml if present.
4. Identify current template source and recorded template ref.
5. Resolve target template ref.
6. Verify the git worktree is clean unless overridden.
7. Create an update branch if requested or required by policy.
8. Run copier update --defaults, optionally with --vcs-ref.
9. Capture changed files, conflicts, rejects, and warnings.
10. Run post-template-update commands.
11. Summarize results.
12. Suggest commit message.
```

Example command:

```bash
copyroom template update --to v0.4.0
```

Example branch:

```text
template-update/python-cli-template-v0.4.0
```

Example result summary:

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

Conflicts:
  none

Post-update checks:
  uv run pytest       passed
  uv run ruff check   passed

Suggested commit:
  Update python-cli-template to v0.4.0
```

If conflicts exist:

```text
Template update summary

Conflicts detected:
  README.md
  pyproject.toml

Recommended next steps:
  1. Review conflict markers or .rej files.
  2. Resolve local intent versus generated template changes.
  3. Run copyroom project run post-template-update.
  4. Commit only after reviewing the full diff.
```

---

## Git Workflow Policy

CopyRoom should provide project-local git helpers, not hide git.

### Recommended branch names

For generated project repos:

```text
feature/<short-name>
fix/<short-name>
template-update/<template-id>-<target-version>
release/<version>
```

For template repos:

```text
main
next
feature/<short-name>
fix/<short-name>
release/<version>
```

For the CopyRoom workshop:

```text
main
feature/<short-name>
policy/<short-name>
registry/<template-id>
golden/<template-id>-<scenario>
```

### Recommended tag strategy

Template repos:

```text
v0.1.0
v0.2.0
v0.3.0
```

Shared tooling repos:

```text
v0.1.0
v0.2.0
v0.3.0
```

Generated project repos:

```text
v1.0.0
v1.1.0
v2.0.0
```

Template versions, shared tooling versions, and generated project versions should remain separate concerns.

A generated project might use:

```text
python-cli-template v0.4.0
shared-python-devenv v0.2.1
project version v1.7.0
```

Those numbers do not need to match.

---

## Context Discovery

Local agents need a reliable way to know what to read.

`copyroom context` should discover context roots from:

```text
1. copyroom.project.yml
2. copyroom.yml and registry entries in workshop mode
3. conventional project paths
4. template-family defaults
5. explicit CLI arguments
```

### Python project default context

```text
README.md
docs/
ADR/
pyproject.toml
uv.lock
src/
tests/
.env.example
.agents/
.copier-answers.yml
copyroom.project.yml
```

### Documentation project default context

```text
README.md
docs/
mkdocs.yml
src/
content/
adr/
.agents/
.copier-answers.yml
copyroom.project.yml
```

### Neovim plugin default context

```text
README.md
docs/
lua/
plugin/
tests/
dev/
dev/deps.txt
devenv.yaml
devenv.nix
devenv.lock
stylua.toml
selene.toml
.agents/
.copier-answers.yml
copyroom.project.yml
```

### CopyRoom workshop default context

```text
copyroom.yml
registry/
scenarios/
agents/
skills/
policies/
fixtures/
golden/
repos/<template-id>/
generated/<template-id>/
```

### Agent context pack

`copyroom context agent-pack` should generate a compact local bundle:

```text
.copyroom/agent-context/
├── project-summary.md
├── template-summary.md
├── git-workflow.md
├── available-commands.json
├── context-roots.json
├── generated-file-policy.md
├── update-policy.md
└── risks.md
```

This gives local agents a stable starting point without requiring long-term memory.

---

## Agent Tooling Model

The CLI should expose structured commands that are easy for agents to call.

Any command likely to be consumed by an agent should support:

```text
--json
--quiet
--cwd <path>
```

Example:

```bash
copyroom agent tools --json
```

Example output:

```json
{
  "mode": "project",
  "project_root": "/work/demo-cli",
  "tools": [
    {
      "name": "inspect_project",
      "command": "copyroom project inspect --json",
      "purpose": "Summarize template identity, commands, context roots, and git policy."
    },
    {
      "name": "safe_template_update",
      "command": "copyroom template update --to <version>",
      "purpose": "Run a guarded Copier update with branch and check handling."
    },
    {
      "name": "context_search",
      "command": "copyroom context search <query> --json",
      "purpose": "Search configured context roots."
    }
  ]
}
```

`copyroom agent brief` should produce a concise project-specific briefing:

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
  README.md
  docs/
  src/
  tests/
  pyproject.toml
  .copier-answers.yml
  copyroom.project.yml

Checks after template updates:
  uv run pytest
  uv run ruff check

Operational notes:
  Do not manually edit .copier-answers.yml.
  Review generated diffs before committing template updates.
```

---

## Devenv Integration

CopyRoom should treat devenv as an optional backend.

It should not replace devenv.

For projects with devenv, the CLI should detect:

```text
devenv.yaml
devenv.nix
devenv.lock
```

It should expose useful inspection commands:

```bash
copyroom devenv status
copyroom devenv shell-info
copyroom devenv run <command>
copyroom devenv locate-bin <tool>
copyroom devenv dependency-source <name>
```

For Neovim plugin projects, the CLI can understand common shared commands:

```text
nvim-dev-bootstrap
nvim-dev-open
nvim-dev-test
nvim-dev-smoke
nvim-dev-check
nvim-dev-format
nvim-dev-clean
```

For Python projects, the CLI can understand common commands:

```text
uv run pytest
uv run ruff check
uv run ruff format
uv run pyright
uv run mypy
```

The goal is not to create a universal dependency graph tool. The goal is to give agents a reliable first layer of environment-aware context.

---

## Generated Project Integration

Generated projects should keep their CopyRoom integration thin.

Recommended generated files:

```text
.copier-answers.yml
copyroom.project.yml
optional .agents/README.md
optional justfile wrappers
optional README section
```

Do not generate large, duplicated helper scripts into every project if they can live in the installable tool or shared tooling repositories.

Example generated `justfile`:

```just
template-status:
    copyroom template status

template-update VERSION:
    copyroom template update --to {{ VERSION }}

agent-brief:
    copyroom agent brief

context QUERY:
    copyroom context search "{{ QUERY }}"

check:
    copyroom project run check
```

This gives users convenient project-local commands without hiding the canonical `copyroom` command surface.

---

## Python Package Design

The installable tool should use Pydantic models for configuration and structured output.

Example models:

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
    generated_policy: list[Path] = Field(default_factory=list)


class DevenvDependencyLookup(BaseModel):
    python_packages: bool = False
    nix_store: bool = False
    local_sources: bool = False
    neovim_runtime: bool = False


class DevenvConfig(BaseModel):
    enabled: bool = False
    shell_command: str = "devenv shell"
    dependency_lookup: DevenvDependencyLookup = Field(default_factory=DevenvDependencyLookup)


class ProjectMetadata(BaseModel):
    kind: Literal["generated-project", "template-repo", "shared-tooling"]
    name: str | None = None
    template_id: str | None = None
    template_source: str | None = None
    template_ref_policy: Literal["tagged", "branch", "commit", "unknown"] = "unknown"
    answers_file: Path = Path(".copier-answers.yml")


class CopyRoomProjectConfig(BaseModel):
    version: int = 1
    project: ProjectMetadata
    git: GitPolicy = Field(default_factory=GitPolicy)
    context: ContextConfig = Field(default_factory=ContextConfig)
    devenv: DevenvConfig = Field(default_factory=DevenvConfig)
    commands: dict[str, list[str]] = Field(default_factory=dict)
```

Structured command result:

```python
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


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

## Workshop Scenario Model

A scenario is a stable set of answers used to render a template.

Example:

```yaml
project_name: demo-cli
package_name: demo_cli
description: Demo Python CLI
repo_owner: Bullish-Design
license: MIT
include_github_actions: true
include_tests: true
include_pydantic: true
include_sqlmodel: false
```

Scenarios should cover durable risk areas:

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
  Tests hyphens, underscores, package names, module names, casing,
  and path templating.
```

Do not create a scenario for every possible prompt combination.

Create scenarios for combinations that affect structure, update risk, generated commands, or policy.

---

## Golden Output Strategy

Golden testing should be selective.

Do not snapshot every generated byte unless the template is small and stable.

Good golden targets:

```text
- rendered directory tree
- key config files
- pyproject.toml
- README skeleton
- .copier-answers.yml shape
- copyroom.project.yml shape
- generated CI workflow
- generated starter tests
- generated devenv files
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

The CLI should support:

```bash
copyroom golden diff python-cli-template minimal
copyroom golden refresh python-cli-template minimal
```

The policy should be:

```text
Golden changes are allowed only when intentional and reviewed.
```

---

## Update Simulation

Every long-lived template should have update tests.

Recommended simulation:

```text
1. Render from an older template version or fixture.
2. Commit or snapshot the generated output.
3. Apply realistic user edits.
4. Run copier update to a newer template version.
5. Detect conflicts, rejects, and unexpected churn.
6. Run generated-project checks.
7. Produce a diff report.
```

Useful simulated edits:

```text
- README modified by user
- pyproject.toml customized
- generated test expanded
- generated CI workflow locally edited
- project manifest customized
- local package source added
- docs added
```

This is essential because initial render success does not prove long-term maintainability.

---

## Release Workflow

Template release workflow:

```text
1. Confirm template repo has intended changes only.
2. Run CopyRoom matrix for the template.
3. Run update tests.
4. Review golden diffs.
5. Update template changelog.
6. Commit changes in the template repo.
7. Tag the template repo.
8. Optionally update CopyRoom lock file.
9. Commit CopyRoom registry, scenario, or golden updates if changed.
```

Command form:

```bash
copyroom release check python-cli-template
copyroom release tag python-cli-template v0.4.0
```

Generated project update workflow:

```text
1. Run copyroom template status.
2. Start a template-update branch.
3. Run copyroom template update --to <version>.
4. Resolve conflicts if any.
5. Run project checks.
6. Review diff.
7. Commit template update.
8. Merge according to local project policy.
```

Command form:

```bash
copyroom template status
copyroom template update --to v0.4.0
copyroom project run post-template-update
git diff
```

---

## MVP Build Plan

### Phase 1: Core package and detection

Deliver:

```text
copyroom version
copyroom explain-mode
copyroom status
copyroom project inspect
copyroom registry validate
```

Implementation targets:

```text
- Python package with CLI entrypoint
- Pydantic models
- config loading
- mode detection
- human output
- JSON output
```

### Phase 2: Project-side template update wrapper

Deliver:

```text
copyroom template status
copyroom template update
copyroom template diff
copyroom git ensure-clean
copyroom git start-template-update
```

Implementation targets:

```text
- read .copier-answers.yml
- load copyroom.project.yml
- verify git status
- create update branch
- call copier update
- collect changed files
- run post-update checks
```

### Phase 3: Context and agent support

Deliver:

```text
copyroom context roots
copyroom context files
copyroom context search
copyroom context agent-pack
copyroom agent brief
copyroom agent tools --json
```

Implementation targets:

```text
- context root expansion
- file filtering
- basic grep/search
- structured agent tool manifest
- project-specific agent summary
```

### Phase 4: Workshop operations

Deliver:

```text
copyroom repo sync
copyroom repo status
copyroom render <template-id> <scenario>
copyroom test <template-id> <scenario>
copyroom update-test <template-id> <scenario>
copyroom golden diff <template-id> <scenario>
copyroom matrix <template-id>
```

Implementation targets:

```text
- registry-driven repo lookup
- scenario rendering
- generated output directories
- command execution from registry
- golden tree comparison
- update simulation harness
```

### Phase 5: Release automation

Deliver:

```text
copyroom release check <template-id>
copyroom release tag <template-id> <version>
copyroom git changelog-since <version>
copyroom tooling consumers <shared-tooling-id>
```

Implementation targets:

```text
- clean worktree checks
- matrix requirement checks
- changelog checks
- tag creation helper
- shared tooling consumer mapping
```

---

## Recommended Initial File Set

For the first implementation, start small.

```text
CopyRoom/
├── README.md
├── copyroom.yml
├── pyproject.toml
├── src/copyroom/
│   ├── __init__.py
│   ├── cli.py
│   ├── models.py
│   ├── discovery.py
│   ├── config_loader.py
│   ├── project.py
│   ├── git_tools.py
│   ├── copier_tools.py
│   └── output.py
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
├── policies/
│   ├── generated-file-policy.md
│   └── update-conflict-policy.md
├── repos/
│   └── .gitkeep
├── generated/
│   └── .gitkeep
├── golden/
│   └── .gitkeep
├── tests/
│   ├── test_models.py
│   ├── test_discovery.py
│   └── test_project_inspect.py
└── justfile
```

First generated project integration:

```text
.copier-answers.yml
copyroom.project.yml
justfile wrappers
```

---

## Template Authoring Guidance

Templates that want to support CopyRoom project-side workflows should generate:

```text
copyroom.project.yml
```

They may also generate:

```text
.agents/README.md
.agents/project-context.md
.agents/update-policy.md
```

But keep these files small.

Good prompts for templates:

```text
- project name
- package or module name
- description
- repository owner
- license
- broad feature inclusion
- test runner choice
- shared tooling reference
- whether to include CopyRoom project manifest
```

Avoid prompts for:

```text
- every future dependency
- every possible README section
- every optional local command
- every internal agent instruction
- every file that users can simply edit later
```

Generated files should be:

```text
small
readable
local
safe to edit
low-churn across template releases
```

Reusable behavior should move into:

```text
copyroom CLI
shared tooling repos
shared devenv modules
shared GitHub Actions
shared pytest plugins
```

---

## Risk Areas

### 1. The CLI becomes too magical

Mitigation:

```text
- print underlying commands before running them when useful
- support dry-run modes
- keep generated project files understandable
- do not hide Copier or git concepts
```

### 2. Generated project manifests drift from Copier answers

Mitigation:

```text
- treat .copier-answers.yml as authoritative for Copier state
- treat copyroom.project.yml as workflow metadata
- warn when template identity differs
```

### 3. Workshop and CLI config versions diverge

Mitigation:

```text
- version config schemas
- validate with Pydantic
- keep backward-compatible readers where practical
- add migration commands later if needed
```

### 4. Context search becomes too broad

Mitigation:

```text
- use explicit context roots
- ignore generated scratch output by default
- ignore virtual environments and large dependency caches by default
- support include/exclude patterns
```

### 5. Agents over-trust generated output

Mitigation:

```text
- agent brief should state which files are generated or policy-managed
- template update commands should always recommend diff review
- release checks should require clean worktrees and passing checks
```

### 6. CopyRoom becomes required for template users

Mitigation:

```text
- templates remain direct Copier templates
- generated project manifests are optional
- direct copier copy/update remains possible
- CopyRoom adds workflow support but does not own runtime behavior
```

---

## Anti-Patterns

Avoid:

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
- making shared tooling and generated project skeletons the same thing
- hiding template update behavior behind opaque automation
- letting agents operate without context roots and workflow policy
```

---

## Final Architecture

Use this architecture:

```text
CopyRoom workshop
  Maintainer workspace and control plane.
  Owns registry, scenarios, policies, skills, agents, fixtures,
  generated sandboxes, golden outputs, and release checks.

copyroom CLI
  uv-installable Python package.
  Runs in workshop mode, project mode, template repo mode,
  shared tooling mode, or standalone mode.
  Provides safe update workflows, git helpers, context discovery,
  devenv-aware inspection, and agent-facing structured output.

Template repos
  Independent Git repositories containing Copier templates.
  Directly consumable by Copier.
  Versioned with tags.

Shared tooling repos
  Independent Git repositories containing reusable behavior.
  Versioned separately from templates and generated projects.

Generated projects
  Normal repositories produced by Copier.
  Own local application code, docs, tests, fixtures, and decisions.
  May include copyroom.project.yml for better local workflow and agent support.
```

The practical result:

```bash
# Maintainer workflow inside CopyRoom
copyroom repo sync
copyroom matrix python-cli-template
copyroom release check python-cli-template

# Project workflow inside a generated repo
copyroom project inspect
copyroom template status
copyroom template update --to v0.4.0
copyroom project run post-template-update

# Agent workflow inside a generated repo
copyroom agent brief
copyroom agent tools --json
copyroom context search "how template updates should be handled"
```

This preserves the original CopyRoom concept while adding a project-side operating layer that is useful to both humans and LLM agents.
