# State Machines — the Guarded-Lifecycle Pattern

Every workflow in CopyRoom is a **guarded state machine**. This is the single most
important pattern to internalize before changing any workflow code: it's how the
codebase stays predictable, spec-faithful, and honest about failure.

---

## 1. The primitive

`_compat/state_machine.py` provides a tiny generic machine:

```python
class StateMachine[S]:
    def __init__(self, transitions: dict[S, set[S]], entity_name: str = "Entity"): ...
    def transition(self, from_state: S, to_state: S) -> S:   # raises if illegal
    def can_transition(self, from_state: S, to_state: S) -> bool:
    def is_terminal(self, state: S) -> bool:
```

`transition` validates the move against the declared table and **raises
`InvalidTransitionError`** if the edge doesn't exist. It returns the target state
so call sites read naturally:

```python
entity.status = sm.transition(Status.a, Status.b)
```

That raise is intentional. An illegal transition is a *programming* error (a
workflow tried to skip or reorder a step), and the machine surfaces it loudly
rather than letting state drift silently.

---

## 2. The three parts of a lifecycle

Each domain `model.py` declares a lifecycle in three coordinated pieces:

```python
# 1. the states
class CreationStatus(StrEnum):
    initiated = "initiated"
    target_verified = "target_verified"
    prompts_collected = "prompts_collected"
    copy_executed = "copy_executed"
    post_create_run = "post_create_run"
    complete = "complete"          # terminal
    failed = "failed"              # terminal

# 2. the transition table (the graph)
VALID_CREATION_TRANSITIONS = {
    CreationStatus.initiated: {CreationStatus.target_verified, CreationStatus.failed},
    CreationStatus.target_verified: {CreationStatus.prompts_collected, CreationStatus.failed},
    # …
    CreationStatus.complete: set(),   # terminal: no outbound edges
    CreationStatus.failed: set(),
}

# 3. the entity carrying the status
@dataclass
class ProjectCreation:
    template_source: str
    status: CreationStatus = CreationStatus.initiated
    # …workflow-specific fields…
```

Conventions that hold across every package:

- States are a **`StrEnum`** (string-comparable, JSON-friendly, readable in logs).
- **`failed`** is reachable from every non-terminal state.
- Terminal states map to the **empty set** (`is_terminal` checks this).
- The entity is a plain `@dataclass`, not a Pydantic model — these are internal
  workflow state, not validated config.

---

## 3. Rule functions

A workflow module turns the graph into code as a series of **rule functions**, one
per spec rule. Each function does one step and performs exactly the transition(s)
that step allows:

```python
_creation_sm = StateMachine(VALID_CREATION_TRANSITIONS, entity_name="ProjectCreation")

def verify_target(creation: ProjectCreation) -> CreationStatus:
    target = Path(creation.target_dir).resolve()
    if target.exists() and any(target.iterdir()):
        creation.status = _creation_sm.transition(
            CreationStatus.initiated, CreationStatus.failed,   # ← legal edge
        )
        creation.result_suggestions = ["Target directory is not empty. …"]
        return creation.status
    creation.status = _creation_sm.transition(
        CreationStatus.initiated, CreationStatus.target_verified,
    )
    return creation.status
```

Each rule function carries a comment naming the spec rule it implements
(`# Rule: VerifyTargetDirectory (spec L87-L94)`), so the code and the Allium spec
stay traceable to each other.

---

## 4. The orchestrator

A high-level function chains the rules and short-circuits on `failed` (and on any
legal early-complete edge). It returns the entity in its **terminal** state — the
CLI handler then turns that into output and an exit code.

```python
def create_project(source, target_dir=".", answers_file=None, trust=False):
    creation = initiate(source, target_dir, answers_file)

    if verify_target(creation) == CreationStatus.failed:
        return creation
    if collect_prompts(creation, answers_file) == CreationStatus.failed:
        return creation
    if execute_copy(creation, answers_file) == CreationStatus.failed:
        return creation

    status = detect_post_create_commands(creation)   # may short-circuit to complete
    if status in (CreationStatus.failed, CreationStatus.complete):
        return creation

    run_post_create_commands(creation, trust=trust)
    return creation
```

**The orchestrator is the public entry point** the CLI and the tests call. Tests
drive these directly and assert on the terminal `status` — no argparse needed.

---

## 5. "Short-circuit" and "pruned" edges

Two patterns recur and are worth recognizing:

- **Short-circuit to `complete`.** When an optional step has nothing to do (no
  post-create hooks, no checks configured), the graph allows jumping straight to
  the terminal state. E.g. `copy_executed → complete` skips `post_create_run`.
  The transition table explicitly lists both `copy_executed → post_create_run`
  *and* `copy_executed → complete`.

- **Pruned (always-traversed) edges.** A step may always advance even when it
  does no work, because the spec graph only allows that one outbound edge. In
  `update-test`, `old_rendered → user_edited` is the *only* legal move, so a
  missing edits file still passes through `user_edited` (zero edits applied)
  rather than illegally jumping to `update_applied`. This faithfulness to the
  spec graph is deliberate — see `workshop/simulate.py:apply_user_edits`.

---

## 6. The entity catalogue

| Entity | Module | Lifecycle (happy path) |
|--------|--------|------------------------|
| `CLISession` | `session/model.py` | `mode_detecting → mode_detected → command_running → command_complete` |
| `ProjectCreation` | `project/model.py` | `initiated → target_verified → prompts_collected → copy_executed → [post_create_run →] complete` |
| `TemplateUpdate` | `project/model.py` | `initiated → config_loaded → worktree_verified → [branch_created →] update_executed → [post_update_run →] complete` |
| `TemplateCheckout` | `template/model.py` | `initiated → source_resolved → worktree_ready` |
| `TemplatePreview` | `template/model.py` | `initiated → sandbox_prepared → update_simulated → diffed → complete` |
| `ScenarioRender` | `workshop/model.py` | `initiated → rendered → [tested →] complete` |
| `GoldenDiff` | `workshop/model.py` | `initiated → rendered → compared → has_diffs \| no_diffs` |
| `UpdateSimulation` | `workshop/model.py` | `initiated → old_rendered → user_edited → update_applied → checks_run → complete` |
| `ReleaseCheck` | `release/check.py` | `initiated → matrix_run → checked → passed \| failed` |
| `Adoption` | `manage/model.py` | `initiated → template_resolved → rendered → drifted → complete` |
| `Templatization` | `manage/model.py` | `initiated → scaffolded → golden_captured → complete` |

All have a `failed` (or `has_diffs`/`no_diffs`/`passed`/`failed`) terminal set.

---

## 7. Adding or changing a lifecycle

1. **Update the spec** in `.scratch/specs/` first — it's the source of truth.
2. **Edit `model.py`**: add states to the `StrEnum` and the corresponding edges to
   `VALID_*_TRANSITIONS`. Remember `failed` reachability and terminal = empty set.
3. **Add/adjust rule functions** that perform the new transitions, each annotated
   with its spec rule.
4. **Wire them into the orchestrator** with proper short-circuit handling.
5. **Add spec-tier tests** that the new transitions are legal and old illegal ones
   still raise; add an integration test driving the orchestrator end to end. See
   [testing](testing.md).

> Pitfall: never assign `entity.status = SomeStatus.x` directly inside a workflow.
> Always go through `sm.transition(...)`. The one historical exception
> (`session/model.py`'s old hand-assignment) was reworked precisely to route
> through the machine.

## See also

- [Architecture](architecture.md) — where lifecycles sit in the layering.
- [Module reference](module-reference.md) — each entity's home.
