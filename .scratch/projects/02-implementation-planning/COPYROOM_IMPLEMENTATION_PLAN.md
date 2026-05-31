# CopyRoom Implementation Plan

> Derived from Allium specifications in `.scratch/specs/`
> Companion tests in `tests/spec/`
> Allium CLI v3.2.3
> Copier pinned to >=9.15.1,<10 (latest stable only; no backward compat)

---

## Table of Contents

1. [Overview](#1-overview)
2. [Project Structure](#2-project-structure)
3. [Phase 0: Project Setup](#3-phase-0-project-setup)
4. [Phase 1: Core Session & Mode Detection](#4-phase-1-core-session--mode-detection)
5. [Phase 2: Project Operations](#5-phase-2-project-operations)
6. [Phase 3: Workshop Operations](#6-phase-3-workshop-operations)
7. [Phase 4: Release Checks](#7-phase-4-release-checks)
8. [Phase 5: Spec Triage & Polish](#8-phase-5-spec-triage--polish)
9. [Testing Strategy](#9-testing-strategy)
10. [Key Design Decisions](#10-key-design-decisions)
11. [Spec Diagnostics Action Plan](#11-spec-diagnostics-action-plan)
12. [Milestones & Timeline](#12-milestones--timeline)
13. [Deferred Features](#13-deferred-features)

---

## 1. Overview

CopyRoom is a Python CLI tool that coordinates **template-driven project workflows** using [Copier](https://copier.readthedocs.io/) under the hood. It lives on top of Copier's lower-level operations, providing mode-aware command routing, safe lifecycle management, workshop testing, and release readiness checks.

### What CopyRoom Is

- A **mode-detecting CLI** that adapts its command set to the directory context: `workshop` mode (template author's workbench) and `project` mode (end-user's generated project). Everything else gets an explicit "no CopyRoom project or workshop found here" error.
- A **project lifecycle manager** for safe `copier copy` and `copier update` operations
- A **workshop test harness** for template authors to validate and golden-test templates
- A **release readiness checker** that runs the full workshop matrix before tagging

### What CopyRoom Is Not

- NOT a template engine — Copier handles rendering
- NOT a package manager — `uv`/`pip` handle dependencies
- NOT a CI system — release checks are advisory; tagging is manual
- NOT a remote code executor — see `invariant NoRemoteExecution`
- NOT a general-purpose tool — it only operates in `workshop` or `project` contexts. Any other directory produces a clear error, not fallback behaviour.

### Architecture

```
User (CLI)
  │
  ▼
copyroom <command>     ← CLI entrypoint via [project.scripts]
  │
  ▼
Session Layer          ← Mode detection, command dispatch (Phase 1)
  │
  ├── Project Module   ← copyroom project new, copyroom project update (Phase 2)
  ├── Workshop Module  ← copyroom render, golden, update-test (Phase 3)
  └── Release Module   ← copyroom release check (Phase 4)
        │
        ▼
    Copier (external)  ← All rendering delegated to Copier
```

---

## 2. Project Structure

```
copyroom/
├── pyproject.toml              ← Package metadata, scripts entrypoint
├── devenv.nix                  ← Dev environment (Python 3.13, uv)
├── devenv.yaml                 ← Dev environment inputs
│
├── src/
│   └── copyroom/
│       ├── __init__.py
│       ├── __main__.py         ← python -m copyroom support
│       ├── cli.py              ← CLI frontend (argparse/typer)
│       │
│       ├── session/            ← Phase 1: Session & Mode Detection
│       │   ├── __init__.py
│       │   ├── model.py        ← CLISession, CLIMode
│       │   ├── detector.py     ← Mode detection logic
│       │   └── dispatcher.py   ← Command routing
│       │
│       ├── project/            ← Phase 2: Project Operations
│       │   ├── __init__.py
│       │   ├── model.py        ← ProjectCreation, TemplateUpdate
│       │   ├── create.py       ← copyroom project new
│       │   └── update.py       ← copyroom project update
│       │
│       ├── workshop/           ← Phase 3: Workshop Operations
│       │   ├── __init__.py
│       │   ├── model.py        ← ScenarioRender, GoldenDiff, UpdateSimulation
│       │   ├── render.py       ← copyroom render
│       │   ├── golden.py       ← copyroom golden
│       │   └── simulate.py     ← copyroom update-test
│       │
│       ├── release/            ← Phase 4: Release Checks
│       │   ├── __init__.py
│       │   └── check.py        ← copyroom release check
│       │
│       └── _compat/            ← Compatibility helpers
│           ├── __init__.py
│           └── copier.py       ← Copier subprocess wrapper
│
├── tests/
│   ├── spec/                   ← Spec-derived tests (already exist)
│   │   ├── __init__.py
│   │   ├── conftest.py         ← Shared fixtures, enums, transition maps
│   │   ├── test_session_lifecycle.py
│   │   ├── test_project.py
│   │   ├── test_workshop.py
│   │   ├── test_release.py
│   │   └── test_invariants.py
│   │
│   ├── unit/                   ← Unit tests for internal modules
│   │   ├── __init__.py
│   │   ├── test_mode_detection.py
│   │   ├── test_project_create.py
│   │   └── ...
│   │
│   └── integration/            ← Integration tests (require fixtures)
│       ├── __init__.py
│       └── test_full_workflows.py
│
└── .scratch/
    └── specs/                  ← Allium specification files
        ├── copyroom.allium
        ├── copyroom-session.allium
        ├── copyroom-project.allium
        ├── copyroom-workshop.allium
        └── copyroom-release.allium
```

---

## 3. Phase 0: Project Setup

**Goal**: Configure the package so `copyroom` can be installed and invoked as a CLI.

### Tasks

#### 3.1 Rename the package

The `pyproject.toml` currently names the package `template-py`. Rename to `copyroom`:

- `[project] name = "copyroom"`
- `[tool.hatch.build.targets.wheel] packages = ["src/copyroom"]`
- `[tool.mypy] packages = ["src/copyroom"]`
- `[tool.ruff] src = ["src"]`

#### 3.2 Add CLI entrypoint

```toml
[project.scripts]
copyroom = "copyroom.cli:main"
```

#### 3.3 Add core dependencies

```toml
dependencies = [
    "pydantic>=2.12.5",
    "pyyaml>=6.0",
    "copier>=9.15.1,<10",
]
```

The existing `pydantic` dependency stays. Add `pyyaml` for `.copier-answers.yml` and `copyroom.project.yml` parsing, and `copier` (pinned to the latest stable 9.x with no backward compatibility) as the rendering engine. At startup, CopyRoom checks that the installed Copier version satisfies the pin and exits with a clear message if not.

#### 3.4 Create scaffolding

- `mkdir -p src/copyroom/session src/copyroom/project src/copyroom/workshop src/copyroom/release src/copyroom/_compat`
- Add `__init__.py` to each
- Create `src/copyroom/__main__.py` with `from .cli import main; main()`

#### 3.5 Update test dependencies

```toml
[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "pytest-cov>=4.1",
    "mypy>=1.10",
    "ruff>=0.5.0",
    "hypothesis>=6.0",  # for property-based tests
]
```

#### 3.6 Fix pytest config

Currently points at `--cov=embeddify` — change to `--cov=copyroom`.

#### 3.7 Verify setup

```bash
uv sync
cp src/copyroom/cli.py ...  # minimal stub that prints "hello"
copyroom --help             # verify CLI entrypoint works
pytest tests/spec/ -v       # verify existing tests still pass
```

---

## 4. Phase 1: Core Session & Mode Detection

**Spec**: `copyroom-session.allium`
**Domain**: CLI entrypoint, mode detection, command dispatch
**CLI surface**: `StartCLI()`, `DetectMode(session)`, `RunCommand(session, command)`

### 4.1 Objective

Build the CLI frontend that:
1. Starts a session
2. Detects which mode the current directory is in
3. Routes commands to the correct handler
4. Rejects commands that don't belong in the current mode

### 4.2 Module: `src/copyroom/session/model.py`

**Domain types** from spec:

```python
from enum import Enum
from dataclasses import dataclass, field

class CLIMode(str, Enum):
    workshop = "workshop"
    project = "project"
    # Note: template_repo and standalone modes from the spec are intentionally
    # collapsed for v0.x. Detection produces an UnknownMode error rather than
    # a dispatchable mode when neither workshop nor project markers exist.
    # See §10.4 for the rationale.

class SessionStatus(str, Enum):
    mode_detecting = "mode_detecting"
    mode_detected = "mode_detected"
    command_running = "command_running"
    command_complete = "command_complete"
    command_failed = "command_failed"
    unknown_mode = "unknown_mode"        # terminal: no workshop or project markers found

@dataclass
class CLISession:
    status: SessionStatus = SessionStatus.mode_detecting
    mode: CLIMode | None = None
```

The `unknown_mode` status is the terminal state when detection finds no workshop or project markers. It produces a clear error message ("No CopyRoom project or workshop found here") and exits non-zero, rather than silently succeeding with nothing to do.

**Transition map** (from spec L22-L33):

```python
VALID_SESSION_TRANSITIONS: dict[SessionStatus, set[SessionStatus]] = {
    SessionStatus.mode_detecting: {SessionStatus.mode_detected},
    SessionStatus.mode_detected: {SessionStatus.command_running, SessionStatus.command_failed},
    SessionStatus.command_running: {SessionStatus.command_complete, SessionStatus.command_failed},
    SessionStatus.command_complete: set(),    # terminal
    SessionStatus.command_failed: set(),      # terminal
}

WORKSHOP_COMMANDS = {"registry", "render", "test", "golden", "release-check", "update-test"}
PROJECT_COMMANDS = {"new", "update"}
```

`inspect` and `status` are deferred to v0.3.0 — they have no spec coverage and no implementation target. See §13 Deferred Features.

### 4.3 Module: `src/copyroom/session/detector.py`

**Mode detection rules** (L38-L84):

Detection walks up ancestors from CWD to root, checking for markers at each level. At each ancestor, workshop markers are checked first, then project markers. The **closest ancestor** that matches wins. If no ancestor matches, detection returns `None` and the session enters `unknown_mode`.

Workshop markers: ancestor contains `copyroom.yml` AND subdirectory `registry/` AND subdirectory `scenarios/`.

Project markers: ancestor contains `.copier-answers.yml` OR `copyroom.project.yml`.

```python
def detect_mode(cwd: Path = Path.cwd()) -> CLIMode | None:
    """Walk up ancestors to detect the mode. Returns CLIMode or None.

    Priority at each level: workshop > project.
    Closest ancestor wins (proximity over mode type).
    """
    for ancestor in [cwd] + list(cwd.parents):
        if is_workshop(ancestor):
            return CLIMode.workshop
        if is_project(ancestor):
            return CLIMode.project
    return None  # → unknown_mode
```

**Why proximity over mode type?** Consider a workshop repo that contains a demo project:
```
workshop-registry/copyroom.yml, registry/, scenarios/
workshop-registry/demo-project/.copier-answers.yml
```
When the user is in `demo-project/`, the closest ancestor with markers is `demo-project/` itself (project markers). If we used mode-type priority, the workshop markers at the parent would take precedence, which is surprising — the user would expect project mode from within a project directory. Proximity gives the intuitive result.

### 4.4 Module: `src/copyroom/session/dispatcher.py`

**Dispatch rules** (L88-L117):

```python
COMMAND_MODE_MAP: dict[str, CLIMode] = {
    # Workshop commands
    "registry": CLIMode.workshop,
    "render": CLIMode.workshop,
    "test": CLIMode.workshop,
    "golden": CLIMode.workshop,
    "release-check": CLIMode.workshop,
    "update-test": CLIMode.workshop,
    # Project commands
    "new": CLIMode.project,
    "update": CLIMode.project,
}

def dispatch(command: str, session: CLISession) -> SessionStatus:
    """Route command based on session mode. Returns new status."""
    if session.status == SessionStatus.unknown_mode:
        return SessionStatus.command_failed  # no mode: reject everything
    if session.status != SessionStatus.mode_detected:
        return SessionStatus.command_failed

    expected_mode = COMMAND_MODE_MAP.get(command)
    if expected_mode is None:
        return SessionStatus.command_failed  # unknown command
    if session.mode != expected_mode:
        return SessionStatus.command_failed  # out-of-mode

    return SessionStatus.command_running
```

### 4.5 Module: `src/copyroom/cli.py`

**CLI frontend** using `argparse` (lightweight, no extra dependency):

```
copyroom [--no-detect] <command> [args...]

Modes are auto-detected unless --no-detect is passed.
If neither workshop nor project markers are found, exits with a clear error.

Commands:
  # Project mode
  new       <source> [target] [--answers FILE]        Create a new project
  update    [target_ref] [--branch]                   Update an existing project

  # Workshop mode
  registry      <action> [args...]                    Manage template registry
  render        <template_id> <scenario_id>           Render a scenario
  test          <template_id> <scenario_id>           Test rendered output
  golden        <template_id> <scenario_id>           Golden test a scenario
  release-check <template_id>                         Run release checks
  update-test   <template_id> <scenario_id> <old> <new>  Simulate template update
```

`inspect` and `status` are deferred (v0.3.0). `release-check` is a single flat command (not `release check` subcommand) to match the single-operation-per-surface contract pattern.

### 4.6 Existing Tests That Must Pass

- `tests/spec/test_session_lifecycle.py` — all tests (structural & transition)
- `tests/spec/test_invariants.py` — `TestCrossSpecInvariants` (mode exclusivity)

### 4.7 State Machine: CLISession Lifecycle

```
StartCLI ──► mode_detecting ──► DetectMode ──► mode_detected
                     │                │              │
                     │                └──────────────┤
                     │                               │
                     │              (no markers)      │
                     │                │               │
                     ▼                ▼               ▼
               unknown_mode    unknown_mode    RunCommand
               [terminal]      [terminal]     (valid mode)
                     │                               │
                     │                        ┌──────┴──────┐
                     ▼                        │             │
              "No CopyRoom                    ▼             ▼
               project or              command_running  command_failed
               workshop found"              │
               exit 1                 ┌─────┴─────┐
                                      │           │
                                      ▼           ▼
                              command_complete  command_failed
                                [terminal]       [terminal]
```

---

## 5. Phase 2: Project Operations

**Spec**: `copyroom-project.allium`
**Domain**: Safe project creation and template update
**CLI surface**: `CreateProject(source, target_dir?, answer_file?)`, `UpdateTemplate(project_root, target_ref?, use_branch?)`

### 5.1 Objective

Implement `copyroom project new` and `copyroom project update` as state-machine-driven workflows that wrap `copier copy` and `copier update`.

### 5.2 Module: `src/copyroom/project/update.py` — Rule Implementation

**Rule implementations for TemplateUpdate:**

| Rule (spec line) | Trigger | Transition | Key behaviour |
|---|---|---|---|
| `InitiateTemplateUpdate` (L154) | `UpdateTemplate(project_root, target_ref, use_branch)` | → initiated | Requires `target_ref != null`, infers `previous_ref` from `.copier-answers.yml` |
| `ResolveLatestRef` (L166) | status becomes `initiated` with `target_ref = null` | — | Resolves to latest semver tag from remote |
| `LoadUpdateConfig` (L172) | status becomes `initiated` | → config_loaded | Loads `.copier-answers.yml` (authoritative) and `copyroom.project.yml` (advisory) |
| `NoUpdateAvailable` (L179) | status becomes `config_loaded` with `previous_ref = target_ref` | → failed | Already at target; nothing to do |
| `VerifyCleanWorktree` (L185) | status becomes `config_loaded` with `previous_ref != target_ref` | → worktree_verified | `git status --porcelain` must be empty |
| `RejectDirtyWorktree` (L194) | status becomes `config_loaded` with worktree not clean | → failed | Error message with remediation steps |
| `CreateUpdateBranch` (L201) | status becomes `worktree_verified` when `--branch` passed | → branch_created | Creates `template-update/<template_id>-<target_ref>` |
| `ExecuteCopierUpdate` (L211) | status becomes `worktree_verified` (no `--branch`) | → update_executed | Runs `copier update --defaults` |
| `ExecuteCopierUpdateFromBranch` (L218) | status becomes `branch_created` | → update_executed | Runs `copier update --defaults` on isolation branch |
| `CaptureUpdateConflicts` (L228) | status becomes `update_executed` | → post_update_run | Captures conflicts and `.rej` files from Copier output |
| `RunPostUpdateCommands` (L236) | status becomes `post_update_run` | → complete | Runs post-template-update commands; failures reported but don't block |

### 5.3 Module: `src/copyroom/project/model.py`

```python
class CreationStatus(str, Enum):
    initiated = "initiated"
    target_verified = "target_verified"
    prompts_collected = "prompts_collected"
    copy_executed = "copy_executed"
    post_create_run = "post_create_run"
    complete = "complete"
    failed = "failed"

@dataclass
class ProjectCreation:
    template_source: str
    target_dir: str = "."
    uses_answer_file: bool = False
    status: CreationStatus = CreationStatus.initiated
    result_suggestions: list[str] = field(default_factory=list)
```

### 5.4 Module: `src/copyroom/project/create.py`

**State machine** (spec L26-L39):

```
initiated ──► target_verified ──► prompts_collected ──► copy_executed
    │                │                   │                    │
    ▼                ▼                   ▼              ┌─────┴─────┐
  failed           failed              failed           │           │
                                                       ▼           ▼
                                               post_create_run   complete
                                                       │
                                                   ┌───┴───┐
                                                   ▼       ▼
                                               complete  failed
```

**Rule implementations:**

| Rule (spec line) | Trigger | Transition | Key behaviour |
|---|---|---|---|
| `InitiateProjectCreation` (L76) | `CreateProject(source, target_dir, answer_file)` | → initiated | Validates `source != ""`, creates entity |
| `VerifyTargetDirectory` (L87) | status becomes `initiated` | → target_verified | Checks target is empty or non-existent |
| `RejectNonEmptyTarget` (L96) | `TargetDirectoryNotEmpty` stimulus | → failed | Sets error suggestion |
| `CollectPrompts` (L102) | status becomes `target_verified` | → prompts_collected | Loads --answers or runs interactive |
| `ExecuteCopierCopy` (L109) | status becomes `prompts_collected` | → copy_executed | Runs `copier copy` |
| `CopierCopyFailed` (L118) | `CopierCopyFailed` stimulus | → failed | Sets error suggestions |
| `DetectPostCreateCommands` (L127) | status becomes `copy_executed` | → post_create_run / complete | Checks `copyroom.project.yml` for commands |
| `RunPostCreateCommands` (L135) | status becomes `post_create_run` | → complete | Executes each command |
| `CompleteProjectCreation` (L141) | status becomes `complete` | → (terminal) | Sets result_suggestions with next-steps |

### 5.5 Module: `src/copyroom/project/update.py` (continued)

**State machine** (spec L58-L72):

```
initiated ──► config_loaded ──► worktree_verified ──► update_executed ──► post_update_run ──► complete
    │              │                   │                    │                   │
    ▼              ▼              ┌────┴────┐               ▼                   ▼
  failed         failed           │         │            failed              failed
                                  ▼         ▼
                           branch_created  update_executed
                                  │
                                  ▼
                              update_executed
```

**Key safety measures:**
- Verifies worktree is clean before any destructive operation
- Creates an isolation branch when `--branch` is passed
- Captures conflicts and `.rej` files for review
- Runs post-update commands (tests, lint) without blocking completion

### 5.6 Copier Integration

```python
# src/copyroom/_compat/copier.py

import subprocess
from pathlib import Path

def copier_copy(source: str, destination: Path, answers_file: Path | None = None) -> subprocess.CompletedProcess:
    """Run copier copy and return the result."""
    cmd = ["copier", "copy", "--quiet"]
    if answers_file:
        cmd.extend(["--answers-file", str(answers_file)])
    cmd.extend([source, str(destination)])
    return subprocess.run(cmd, capture_output=True, text=True)

def copier_update(destination: Path, vcs_ref: str | None = None) -> subprocess.CompletedProcess:
    """Run copier update and return the result."""
    cmd = ["copier", "update", "--defaults"]
    if vcs_ref:
        cmd.extend(["--vcs-ref", vcs_ref])
    cmd.append(str(destination))
    return subprocess.run(cmd, capture_output=True, text=True)
```

### 5.7 Existing Tests That Must Pass

- `tests/spec/test_project.py` — all tests (entity, transition, rule, invariant, surface)
- Transition validation for both `ProjectCreation` and `TemplateUpdate` state machines

---

## 6. Phase 3: Workshop Operations

**Spec**: `copyroom-workshop.allium`
**Domain**: Scenario rendering, golden testing, update simulation
**CLI surface**: `RenderCommand`, `GoldenDiffCommand`, `GoldenRefreshCommand`, `UpdateTestCommand`

### 6.1 Objective

Implement the template author's workshop workbench — tools for rendering scenarios, comparing against golden snapshots, and simulating template updates to catch regressions.

### 6.2 Module: `src/copyroom/workshop/model.py`

**Value types:**

```python
@dataclass
class GoldenDiffResult:
    added: set[str] = field(default_factory=set)
    removed: set[str] = field(default_factory=set)
    modified: set[str] = field(default_factory=set)

    @property
    def has_changes(self) -> bool:
        return bool(self.modified or self.added or self.removed)

@dataclass
class UpdateSimulationResult:
    conflicts: set[str] = field(default_factory=set)
    rejects: set[str] = field(default_factory=set)
    check_passed: bool = False
```

**Entity enums:**

```python
class RenderStatus(str, Enum):
    initiated = "initiated"
    rendered = "rendered"
    tested = "tested"
    complete = "complete"
    failed = "failed"

class GoldenStatus(str, Enum):
    initiated = "initiated"
    rendered = "rendered"
    compared = "compared"
    has_diffs = "has_diffs"
    no_diffs = "no_diffs"

class SimStatus(str, Enum):
    initiated = "initiated"
    old_rendered = "old_rendered"
    user_edited = "user_edited"
    update_applied = "update_applied"
    checks_run = "checks_run"
    complete = "complete"
    failed = "failed"
```

### 6.3 Module: `src/copyroom/workshop/render.py`

**State machine** (spec L33-L38):

```
initiated ──► rendered ──► tested ──► complete
    │            │            │
    ▼            ▼            ▼
  failed       failed       failed
```

Short-circuit: `rendered → complete` when no tests configured.

**Key behaviour:**
- `copier copy` with scenario answers into `generated/<template_id>/<scenario_id>/`
- Scenario answers from `scenarios/<template_id>/<scenario_id>.yml`
- Run checks from registry entry's `checks` list against rendered output

### 6.4 Module: `src/copyroom/workshop/golden.py`

**State machine** (spec L47-L52):

```
initiated ──► rendered ──► compared ──► has_diffs
    │            │                     └──► no_diffs
    ▼            ▼
  failed       failed
```

**Key behaviour:**
- Renders current output, compares against `golden/<template_id>/<scenario_id>/`
- Golden targets: `tree.txt`, `important-files/` (pyproject.toml, README, CI config)
- `GoldenRefreshCommand` overwrites golden snapshot after review

### 6.5 Module: `src/copyroom/workshop/simulate.py`

**State machine** (spec L65-L72):

```
initiated ──► old_rendered ──► user_edited ──► update_applied ──► checks_run ──► complete
    │             │                │                  │                │
    ▼             ▼                ▼                  ▼                ▼
  failed        failed           failed             failed           failed
```

**Key behaviour:**
- Render template at `old_version` to produce a base project
- Apply deterministic user edits from `scenarios/<template_id>/<scenario_id>-edits.yml`
- Run `copier update --defaults` from old to new version
- Capture conflicts and rejects
- Run checks against updated output

#### Deterministic Edit Strategy for `user_edited`

The `ApplyUserEdits` transition (spec L171) must produce consistent results across runs. The strategy:

1. **Edit files live alongside scenario answers**: `scenarios/<template_id>/<scenario_id>-edits.yml`
2. **Edit file format** — a simple YAML DSL of file-level operations:
   ```yaml
   # scenarios/my-template/default-edits.yml
   edits:
     - file: "README.md"
       action: append
       content: |
         ## Custom Section
         This was added by the user after generation.
     - file: "pyproject.toml"
       action: set-field
       path: ["project", "dependencies"]
       value:
         - "requests>=2.31"
     - file: "tests/test_app.py"
       action: create
       content: |
         def test_custom_feature():
             assert True
   ```
3. **Supported actions**: `append` (append to end of file), `set-field` (modify a TOML/YAML field by path), `create` (create a new file), `patch` (unified diff application)
4. **No edits file → no edits applied**: the simulation skips from `old_rendered` directly to `update_applied` when no edits file exists, pruning the `user_edited` state
5. **Template family defaults**: each template family ships a `default-edits.yml` that applies realistic-but-generic modifications. Template authors can add scenario-specific edits for targeted regression testing

### 6.6 Existing Tests That Must Pass

- `tests/spec/test_workshop.py` — all tests (value types, entities, transitions, rules, invariants, scenarios)
- Golden diff result derivations (has_changes logic)
- Update simulation completion conditions

---

## 7. Phase 4: Release Checks

**Spec**: `copyroom-release.allium`
**Domain**: Release readiness matrix testing
**CLI surface**: `ReleaseCheckCommand(template_id)`

### 7.1 Objective

Implement `copyroom release check <template_id>` that runs the full workshop matrix and reports pass/fail for release readiness.

### 7.2 Module: `src/copyroom/release/check.py`

**CLI command**: `copyroom release-check <template_id>` (flat command, not `release check` subcommand). This matches the single-operation-per-surface contract pattern — `ReleaseSurface` provides one operation, `ReleaseCheckCommand`, and the CLI command maps 1:1 to it.

**State machine** (spec L18-L22):

```
initiated ──► matrix_run ──► checked ──► passed
    │             │             │
    ▼             ▼             ▼
  failed        failed        failed
```

**Key behaviour:**

| Rule (spec line) | Trigger | Transition | Condition |
|---|---|---|---|
| `RunReleaseCheck` (L29) | `ReleaseCheckCommand` | → initiated | Creates entity |
| `RunMatrix` (L39) | status becomes `initiated` | → matrix_run | Runs all scenarios |
| `EvaluateReleaseReadiness` (L45) | status becomes `matrix_run` | → checked | Evaluates results |
| `ReleaseCheckPassed` (L49) | status becomes `checked` | → passed | `matrix_passed AND worktree_clean AND golden_ok` |
| `ReleaseCheckFailed` (L56) | status becomes `checked` | → failed | Any one false |

### 7.3 Release Check Output

```text
$ copyroom release-check my-template

Release Check: my-template
  Matrix:     ✅ PASSED (5/5 scenarios rendered, tested)
  Worktree:   ✅ CLEAN
  Golden:     ✅ OK (3/3 scenarios match golden)
  Result:     🟢 PASSED

Note: Release checks are advisory in v0.x.
Tagging is manual: git tag v0.4.0 && git push --tags
```

### 7.4 Existing Tests That Must Pass

- `tests/spec/test_release.py` — all tests (entity, transitions, rules, condition combinations, scenarios)
- All 8 condition combinations for `ReleaseCheckPassed` vs `ReleaseCheckFailed`

---

## 8. Phase 5: Spec Triage & Polish

**Goal**: Resolve the Allium CLI diagnostics identified during validation.

### 8.1 Priority Fixes

| Category | Count | Action |
|---|---|---|
| `status.noExit` | 19 | These are expected — the specs describe declarative lifecycles where each rule advances one step. **Accept as-is** — the transitions are valid, the "no exit" just means the rules form a linear chain. |
| `status.unreachableValue` (failed) | 3 | Add rules that assign `failed` status via error-handling stimuli (see below). |
| `rule.unreachableTrigger` | 4 | Connect error stimuli via surfaces or internal emissions (see below). |
| `surface.unusedBinding` (`viewer`) | 3 | Remove `viewer` bindings from surfaces that don't use them (cosmetic). |
| `field.unused` | 13 | These are identity/descriptive fields. **Accept as-is** — they document the entity schema. |
| `deferred.missingLocationHint` | 4 | Add `@location(...)` hints to the 4 deferred specs. |

### 8.2 Fixing `status.unreachableValue` (failed) and `rule.unreachableTrigger`

The `failed` states and error-handling triggers exist in the specs but aren't connected in a way the CLI can verify. The fix follows the Allium **trigger emission** pattern (see the language reference, `ensures` clause forms): detection rules emit internal events that error-handling rules subscribe to.

**`copyroom-project.allium` — `VerifyTargetDirectory` should emit `TargetDirectoryNotEmpty`:**
```allium
rule VerifyTargetDirectory {
    when: creation: ProjectCreation.status becomes initiated
    ensures: creation.status = target_verified
    ensures:
        if target_is_non_empty:
            TargetDirectoryNotEmpty(creation)   -- internal trigger emission
}
```
`RejectNonEmptyTarget` then works as-is with its `when: TargetDirectoryNotEmpty(creation)` trigger.

**`copyroom-project.allium` — `ExecuteCopierCopy` should emit `CopierCopyFailed`:**
```allium
rule ExecuteCopierCopy {
    when: creation: ProjectCreation.status becomes prompts_collected
    ensures: creation.status = copy_executed
    ensures:
        if copier_copy_failed:
            CopierCopyFailed(creation)
}
```

**`copyroom-project.allium` — `VerifyCleanWorktree` should emit `WorktreeNotClean`:**
```allium
rule VerifyCleanWorktree {
    when: update: TemplateUpdate.status becomes config_loaded
    requires: update.previous_ref != update.target_ref
    ensures: update.status = worktree_verified
    ensures:
        if worktree_not_clean:
            WorktreeNotClean(update)
}
```

**`copyroom-workshop.allium` — `TestRenderedOutput` should emit `RenderTestsFailed`:**
```allium
rule TestRenderedOutput {
    when: render: ScenarioRender.status becomes rendered
    ensures: render.status = tested
    ensures:
        if tests_failed:
            RenderTestsFailed(render)
}
```

This pattern preserves the separation of detection and reaction (consistent with the Allium Patterns doc — see `LoginFailure` in Pattern 1, which shares a trigger with `LoginSuccess` but has different `requires`). The detection rule discovers the condition; the reaction rule handles the error path.

### 8.3 Fixing `surface.unusedBinding`

Remove `viewer` binding from surfaces that don't reference it, and add `update-test` to the workshop dispatch set:

**Remove unused `viewer` bindings:**
```
surface CLISurface {
-    facing viewer: CLIUser
+    facing CLIUser
```

**Add `update-test` to `DispatchWorkshopCommand`:**
```allium
rule DispatchWorkshopCommand {
    when: RunCommand(session, command)
    requires: session.status = mode_detected
        and session.mode = workshop
-       and command in {"registry", "render", "test", "golden", "release"}
+       and command in {"registry", "render", "test", "golden", "release-check", "update-test"}
    ensures: session.status = command_running
}
```

This was missing from the original spec — `update-test` appears in the workshop surface and the plan's CLI but was never added to the dispatch rule.

### 8.4 Adding `@location` hints

```
deferred TemplateAuthoring @location "copyroom-workshop.allium"
deferred MultiTemplateComposition @location "copyroom-project.allium"
deferred CrossRepoReleaseAutomation @location "copyroom-release.allium"
deferred AgentSupport @location "copyroom-session.allium"
```

### 8.5 Post-Polish Validation

```bash
cd copyroom
allium check .scratch/specs         # No errors, minimal warnings
allium analyse .scratch/specs       # No deadlocks after fixes
allium model .scratch/specs/copyroom-session.allium       # Entities visible
allium plan .scratch/specs/copyroom-session.allium        # Obligations generated
```

---

## 9. Testing Strategy

### 9.1 Test Tiers

| Tier | Location | What | Runner |
|---|---|---|---|
| **Structural** | `tests/spec/` | Transition validity, enum completeness, field presence | `pytest tests/spec/ -v` |
| **Unit** | `tests/unit/` | Individual rules, mode detection, dispatch logic | `pytest tests/unit/ -v` |
| **Integration** | `tests/integration/` | Full workflows with temp directory fixtures | `pytest tests/integration/ -v` |
| **Property-based** | `tests/spec/` | Invariant verification with Hypothesis | `pytest tests/spec/ --hypothesis-show-statistics` |

### 9.2 Migration Path for `pass # Integration` Tests

Many generated tests are marked `pass  # Integration`. As each phase is implemented, fill these in according to the following criteria. After each phase, run `pytest tests/spec/ -v` — all structural tests must pass and all integration stubs for the current phase must be either implemented or explicitly deferred.

**Per-phase acceptance criteria:**

| Phase | Tests to fill | Acceptance criteria |
|---|---|---|
| **Phase 1** | `test_session_lifecycle.py`: `TestModeDetection` (5 stubs), `TestCLISurface` (3 stubs), `TestSessionHappyPath` (2 scenarios) | Mode detection works against temp directory fixtures with markers; `unknown_mode` produces the expected error. |
| **Phase 2** | `test_project.py`: `TestInitiateProjectCreation` (3 stubs), `TestRejectNonEmptyTarget`, `TestCopierCopyFailed`, `TestCompleteProjectCreation`, `TestInitiateTemplateUpdate` (2 stubs), `TestResolveLatestRef`, `TestNoUpdateAvailable`, `TestRejectDirtyWorktree`, `TestCreateUpdateBranch`, `TestProjectInvariants` (3 stubs), `TestProjectSurface` (2 stubs) | Full happy-path and error-path flows work with temp directories + mocked Copier subprocess. |
| **Phase 3** | `test_workshop.py`: `TestRenderScenario`, `TestGoldenDiff`, `TestRefreshGolden`, `TestRunUpdateSimulation`, `TestUpdateSimulationComplete`, `TestWorkshopSurface` (4 stubs), `TestWorkshopInvariants` (2 stubs) | Render + golden + update-test flows work with workshop fixture structure. Edit files must be parsed and applied deterministically. |
| **Phase 4** | `test_release.py`: `TestRunReleaseCheck`, `TestRunMatrix`, `TestReleaseSurface` | All 8 boolean condition combinations produce correct pass/fail. |
| **Phase 5** | `test_invariants.py`: all `TestErrorHandlingConsistent` (7 stubs), `TestNoRemoteExecution` (3 stubs), `TestOperatingModelBoundary` (3 stubs), `TestCopierAnswersAuthoritative` (2 stubs), `TestOffRampAlwaysAvailable` (3 stubs) | Cross-cutting invariants verified against real workflows. |

**Rules for stubs:**
- Stubs that cannot be filled because the feature is deferred must be marked with `pytest.skip("Deferred: <version>")` and a reason linking to the deferred feature table (§13).
- Stubs that cannot be filled because they need infrastructure not yet available (e.g., a real Git remote for `ResolveLatestRef`) must be marked with `pytest.skip("Needs: <infrastructure>")`.
- A phase is complete when all its stubs are either implemented (passing) or explicitly skipped with a tracked reason.

### 9.3 Hypothesis Properties to Add

```python
from hypothesis import given, strategies as st

@given(st.lists(st.sampled_from(list(SessionStatus)), min_size=2, max_size=10))
def test_session_never_invalid_transition(path):
    """Random walks through the state machine never use invalid edges."""
    for i in range(len(path) - 1):
        source, target = path[i], path[i+1]
        assert target in VALID_SESSION_TRANSITIONS[source], \
            f"Invalid transition: {source} -> {target}"
```

Note: the original stub used `pytest.skip` on invalid transitions, which would silently pass on bugs. The correct approach is `assert` — Hypothesis generates random paths and every step must be a valid transition. If any step is invalid, the test fails.

---

## 10. Key Design Decisions

### 10.1 State Machines over Conditionals

Each entity's lifecycle is modelled as an explicit state machine with validated transitions. This mirrors the Allium spec directly and makes error paths visible. Implementation uses a simple `state_machine.py` utility:

```python
class StateMachine:
    """Lightweight state machine with validated transitions."""
    def __init__(self, transitions: dict[str, set[str]]):
        self._transitions = transitions

    def transition(self, entity, from_state, to_state):
        valid = self._transitions.get(from_state, set())
        if to_state not in valid:
            raise InvalidTransition(from_state, to_state)
        return to_state
```

### 10.2 Copier as Subprocess

Use `subprocess.run()` rather than Copier's Python API. This:
- Isolates Copier errors cleanly
- Makes stderr forwarding to the user trivial
- Avoids coupling to Copier's internal API
- Allows easy substitution in tests (`unittest.mock.patch("subprocess.run")`)

### 10.3 Error Handling Pattern

Consistent with `invariant ErrorHandlingConsistent`:

```python
class CopyRoomError(Exception):
    """Base error with structured message."""
    def __init__(self, message: str, state: str | None = None):
        self.message = message
        self.state = state
        super().__init__(self._format())

    def _format(self) -> str:
        parts = [f"Error: {self.message}"]
        if self.state:
            parts.append(f"State left: {self.state}")
        return "\n".join(parts)
```

Every error path prints:
- What operation was being performed
- What specifically failed
- Where state was left
- Never auto-rollbacks
- Non-zero exit

### 10.4 Mode Detection: Two Modes + Explicit Error

CopyRoom v0.x detects exactly two dispatchable modes: `workshop` and `project`. The `template_repo` and `standalone` values defined in the spec are intentionally held in reserve for future feature gates (see §13). Detection that finds neither workshop nor project markers produces `unknown_mode` with a clear error message, not a silent fallback.

**Rationale**: A CLI that says "I don't know what to do here" is more honest and less surprising than one that accepts commands but does nothing, or one that tries to guess at intent in an unsupported directory. When future features add commands to those modes, detection will plug them in without breaking existing behaviour.

**Search order**: start at CWD, walk up ancestors. At each ancestor, check workshop markers first, then project markers. The **closest ancestor with any marker wins** (proximity over mode-type priority).

This resolves the spec's `open question "Mode precedence"` in favour of proximity: when a project directory lives inside a workshop repo, the user gets project mode (the nearest context). If they want workshop mode, they run `copyroom` from the workshop root.

**Marker definitions:**
- **Workshop**: `copyroom.yml` exists AND `registry/` subdirectory exists AND `scenarios/` subdirectory exists
- **Project**: `.copier-answers.yml` exists OR `copyroom.project.yml` exists
- **Neither**: `unknown_mode` — print "No CopyRoom project or workshop found here" and exit 1

### 10.5 Command Sets Are Disjoint

```python
WORKSHOP_COMMANDS = {"registry", "render", "test", "golden", "release-check", "update-test"}
PROJECT_COMMANDS = {"new", "update"}
assert WORKSHOP_COMMANDS.isdisjoint(PROJECT_COMMANDS)  # invariant
```

### 10.6 Pipeline Architecture

Each phase's CLI command follows a consistent pattern:

```
CLI parses args ──► Session layer validates mode ──► Phase handler creates entity ──►
State machine advances ──► Copier subprocess (if needed) ──► State machine completes ──► Report output
```

---

## 11. Spec Diagnostics Action Plan

Current diagnostics from `allium check .scratch/specs` and `allium analyse .scratch/specs`:

### 11.1 Addressable Before Implementation

| Diagnostic | Severity | File | Fix |
|---|---|---|---|
| `missingLocationHint` | warning | `copyroom.allium` L70-79 | Add `@location` hints to deferred specs |
| `surface.unusedBinding` | warning | all surface files | Remove unused `viewer` bindings |
| `rule.unreachableTrigger` (update-test) | info | `copyroom-session.allium` L88-92 | Add `update-test` to workshop command set (was missing from dispatch rule) |

### 11.2 Addressable During Implementation

| Diagnostic | Severity | File | Details |
|---|---|---|---|
| `status.unreachableValue` | warning | `copyroom-project.allium:26` | `ProjectCreation.failed` — detection rules will emit internal triggers (see §8.2) |
| `status.unreachableValue` | warning | `copyroom-workshop.allium:38` | `ScenarioRender.failed` — ditto |
| `status.unreachableValue` | warning | `copyroom-workshop.allium:77` | `UpdateSimulation.failed` — ditto |
| `rule.unreachableTrigger` | info | `copyroom-project.allium:109,133,219` | Detection rules will emit `CopierCopyFailed`/`TargetDirectoryNotEmpty`/`WorktreeNotClean` as internal triggers |
| `rule.unreachableTrigger` | info | `copyroom-workshop.allium:129` | `TestRenderedOutput` will emit `RenderTestsFailed` |

### 11.3 Accept As-Is

| Diagnostic | Severity | Reason |
|---|---|---|
| `status.noExit` (19 instances) | warning | Intentional — linear chain state machines; each rule advances one step |
| `field.unused` (13 instances) | info | Identity/descriptive fields documenting the entity schema |
| `status.unreachableValue` (`CLIMode.template_repo`, `CLIMode.standalone`) | warning | Held in reserve for future feature gates (see §13). v0.x collapses to 2 modes + `unknown_mode`. |

### 11.4 Deadlock (Analyse Only)

| Finding | Entity | Details |
|---|---|---|
| `deadlock` | `CLISession` | `mode_detecting` has no achievable path to terminal state per the static analyser |

**Fix**: The `mode_detecting → mode_detected` transition is declared in the graph and the `Detect*` rules set `session.mode`, causing `ModeDetected` to fire. The static analyser can't trace the event chain from `StartCLI` → `DetectMode` → `ModeDetected`, but the chain works at runtime. **Accept as-is** — this is a static analysis limitation, not a spec bug. The `unknown_mode` status added above also provides a terminal exit path when no markers are found.

---

## 12. Milestones & Timeline

### Milestone 1: Skeleton CLI (Phase 0)
- [ ] Package renamed to `copyroom`
- [ ] Copier pinned to `>=9.15.1,<10` with startup version check
- [ ] CLI entrypoint echoes its mode
- [ ] `copyroom --help` works
- [ ] Existing tests pass (updated for 2-mode model)
- **Estimated effort**: 1 session

### Milestone 2: Mode Detection (Phase 1)
- [ ] Directory markers detected correctly (workshop / project / neither)
- [ ] `copyroom` in a project dir shows project commands (new, update)
- [ ] `copyroom` in a workshop dir shows workshop commands (registry, render, test, golden, release-check, update-test)
- [ ] No markers → clear error "No CopyRoom project or workshop found here"
- [ ] Out-of-mode commands rejected with clear error
- [ ] Spec-derived structural tests pass
- **Estimated effort**: 2 sessions

### Milestone 3: Project Create & Update (Phase 2)
- [ ] `copyroom new <source>` creates a project
- [ ] `copyroom update [ref]` updates an existing project
- [ ] Worktree safety checks enforced
- [ ] Post-create/update commands run
- [ ] All error paths clean
- **Estimated effort**: 3-4 sessions

### Milestone 4: Workshop Tools (Phase 3)
- [ ] `copyroom render <template> <scenario>` renders a scenario
- [ ] `copyroom golden <template> <scenario>` compares to golden
- [ ] `copyroom update-test <template> <scenario> <old> <new>` simulates updates with deterministic edits
- [ ] Golden refresh works
- [ ] Edit file DSL parser implemented (`-edits.yml`)
- **Estimated effort**: 3-4 sessions

### Milestone 5: Release Checks (Phase 4)
- [ ] `copyroom release-check <template>` runs the full matrix
- [ ] Pass/fail logic correct for all 8 boolean combinations
- [ ] Advisory reporting with manual tagging guidance
- **Estimated effort**: 1-2 sessions

### Milestone 6: Polish & Weed (Phase 5)
- [ ] All spec diagnostics addressed (trigger emissions, unused bindings, missing dispatch entry)
- [ ] `allium check` exits 0 with minimal warnings
- [ ] `allium analyse` no findings
- [ ] Integration tests filled in per §9.2 criteria
- [ ] `weed` check confirms spec-code alignment
- **Estimated effort**: 1 session

---

## 13. Deferred Features

From `copyroom.allium` deferred section and implementation scoping:

| Feature | Spec | Target Version | Notes |
|---|---|---|---|
| **Template Authoring** | `copyroom-workshop.allium` | Future | How maintainers create/modify Copier templates |
| **Multi-Template Composition** | `copyroom-project.allium` | v1.0+ | Layered partial templates |
| **Cross-Repo Release Automation** | `copyroom-release.allium` | Future | Automated cross-repo releases |
| **Agent Support** | `copyroom-session.allium` | v0.4.0 | Agent brief, context roots, tool manifests |
| **`copyroom inspect`** | — | v0.3.0 | Show project info (template source, version, answers). No spec coverage yet. |
| **`copyroom status`** | — | v0.3.0 | Show project status (update available, worktree dirty?). No spec coverage yet. |
| **`template_repo` mode** | `copyroom-session.allium` | v0.5.0 | Detection returns `unknown_mode` for now. Future: `copyroom validate-template`, template linting. |
| **`standalone` mode** | `copyroom-session.allium` | v0.5.0 | Detection returns `unknown_mode` for now. Future: `copyroom init` to bootstrap a new project/workshop. |

These are explicitly deferred — do not implement in v0.x. The `template_repo` and `standalone` `CLIMode` values are defined in the spec but held in reserve; the implementation uses a 2-mode dispatch model with `unknown_mode` as the terminal state when neither workshop nor project markers are found.

---

## Appendix A: State Machine Reference

All transition graphs across all entities:

```
CLISession:
  mode_detecting → mode_detected | unknown_mode
  mode_detected → command_running | command_failed
  command_running → command_complete | command_failed
  [terminal: command_complete, command_failed, unknown_mode]

ProjectCreation:
  initiated → target_verified | failed
  target_verified → prompts_collected | failed
  prompts_collected → copy_executed | failed
  copy_executed → post_create_run | complete | failed
  post_create_run → complete | failed
  [terminal: complete, failed]

TemplateUpdate:
  initiated → config_loaded | failed
  config_loaded → worktree_verified | failed
  worktree_verified → branch_created | update_executed | failed
  branch_created → update_executed | failed
  update_executed → post_update_run | complete | failed
  post_update_run → complete | failed
  [terminal: complete, failed]

ScenarioRender:
  initiated → rendered | failed
  rendered → tested | complete | failed
  tested → complete | failed
  [terminal: complete, failed]

GoldenDiff:
  initiated → rendered | failed
  rendered → compared | failed
  compared → has_diffs | no_diffs
  [terminal: has_diffs, no_diffs]

UpdateSimulation:
  initiated → old_rendered | failed
  old_rendered → user_edited | failed
  user_edited → update_applied | failed
  update_applied → checks_run | failed
  checks_run → complete | failed
  [terminal: complete, failed]

ReleaseCheck:
  initiated → matrix_run | failed
  matrix_run → checked | failed
  checked → passed | failed
  [terminal: passed, failed]
```

## Appendix B: Surface-to-Command Mapping

| CLI Command | Allium Surface | Allium Rule | Phase |
|---|---|---|---|
| `copyroom [no args]` | `CLISurface.StartCLI` | `InitializeCLISession` | 1 |
| `copyroom new <source>` | `ProjectSurface.CreateProject` | `InitiateProjectCreation` | 2 |
| `copyroom update [ref]` | `ProjectSurface.UpdateTemplate` | `InitiateTemplateUpdate` | 2 |
| `copyroom render <t> <s>` | `WorkshopSurface.RenderCommand` | `RenderScenario` | 3 |
| `copyroom golden <t> <s>` | `WorkshopSurface.GoldenDiffCommand` | `DiffGolden` | 3 |
| `copyroom golden refresh <t> <s>` | `WorkshopSurface.GoldenRefreshCommand` | `RefreshGolden` | 3 |
| `copyroom update-test <t> <s> <o> <n>` | `WorkshopSurface.UpdateTestCommand` | `RunUpdateSimulation` | 3 |
| `copyroom release-check <t>` | `ReleaseSurface.ReleaseCheckCommand` | `RunReleaseCheck` | 4 |

## Appendix C: File Manifest

Files to create:
- `src/copyroom/__init__.py`
- `src/copyroom/__main__.py`
- `src/copyroom/cli.py`
- `src/copyroom/session/__init__.py`
- `src/copyroom/session/model.py`
- `src/copyroom/session/detector.py`
- `src/copyroom/session/dispatcher.py`
- `src/copyroom/project/__init__.py`
- `src/copyroom/project/model.py`
- `src/copyroom/project/create.py`
- `src/copyroom/project/update.py`
- `src/copyroom/workshop/__init__.py`
- `src/copyroom/workshop/model.py`
- `src/copyroom/workshop/render.py`
- `src/copyroom/workshop/golden.py`
- `src/copyroom/workshop/simulate.py`
- `src/copyroom/workshop/edits.py`          ← Edit file parser for `-edits.yml` DSL
- `src/copyroom/release/__init__.py`
- `src/copyroom/release/check.py`
- `src/copyroom/_compat/__init__.py`
- `src/copyroom/_compat/copier.py`

Files to modify:
- `pyproject.toml` — rename package, add entrypoint, pin copier, add deps
- `.scratch/specs/copyroom-session.allium` — add `update-test` to `DispatchWorkshopCommand`, add `unknown_mode` status to `CLISession`
- `.scratch/specs/copyroom-project.allium` — add trigger emissions to detection rules (see §8.2)
- `.scratch/specs/copyroom-workshop.allium` — add `RenderTestsFailed` trigger emission to `TestRenderedOutput`
- `.scratch/specs/copyroom.allium` — add `@location` hints to deferred specs
- `tests/spec/conftest.py` — update `CLIMode` to 2-value enum, add `unknown_mode` to transitions
