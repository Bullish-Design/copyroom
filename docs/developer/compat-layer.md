# The `_compat` Layer

`src/copyroom/_compat/` is the **boundary** between CopyRoom's pure-Python
workflows and the outside world: the `copier` and `git` binaries, the trust gate
for untrusted commands, and the handful of primitives every workflow shares. If a
function runs a subprocess or is used by more than one package, it belongs here.

The name signals intent: a thin compatibility/isolation seam around tools CopyRoom
*delegates to* rather than reimplements. Keeping it isolated means Copier/git
error handling, timeouts, and stderr forwarding live in exactly one place.

---

## `copier.py` — the Copier subprocess wrapper

CopyRoom drives Copier via `subprocess.run`, **not** its Python API. The reasons:
clean error isolation, trivial stderr forwarding, and no coupling to Copier
internals across the `>=9.15.1,<10` range.

```python
def copier_copy(source, destination, answers_file=None, vcs_ref=None, timeout=300)
def copier_update(destination, vcs_ref=None, timeout=300)
```

Both return a `subprocess.CompletedProcess[str]` (callers inspect `.returncode`,
`.stdout`, `.stderr`). Key behaviors:

- **`copier copy`** always runs `copier copy --quiet --defaults [--vcs-ref REF]
  [--data-file FILE] SOURCE DEST`. `--quiet --defaults` makes it non-interactive.
- **`--vcs-ref` matters.** Without it Copier renders the latest *tag*; the
  template-edit and adopt flows must render an *edit branch* or a specific ref, so
  they pass `vcs_ref` explicitly.
- **`copier update`** runs `copier update --defaults [--vcs-ref REF] DEST`.
- **Timeouts.** Default 300s (Copier may clone on first use). A timeout raises
  `subprocess.TimeoutExpired`, which call sites catch via their `except Exception`
  guards and turn into a `failed` transition.

Callers never build Copier command lines themselves — they call these two
functions.

---

## `gitutil.py` — defensive git helpers

Every git interaction goes through here. The defining trait: **a missing `git`
binary or a timeout returns `None` (or `False`) rather than raising**, so each
call site decides what failure means in its context (often "treat as not a git
repo" or "git is required → fail").

```python
run_git(*args, cwd=None, timeout=120)   # → CompletedProcess | None
normalize_source_url(source)            # expand gh:/gl: → clone-able URL
is_git_repo(path) -> bool
default_branch(repo) -> str | None      # current branch name
clone(source, dest) -> bool             # FULL clone (no --depth) — see below
fetch(repo) -> None                     # best-effort refresh of a cached clone
branch_exists(repo, branch) -> bool
worktree_add(repo, worktree_dir, branch, base) -> bool   # idempotent reuse
snapshot(work_dir, message) -> bool     # init-if-needed + commit -A --allow-empty
commit_all(repo, message) -> bool       # stage + commit pending edits
add_all_and_diff_cached(repo) -> str    # staged unified diff (includes new files)
```

Notes worth internalizing:

- **Full clones only.** `clone` never uses `--depth`: the project's recorded
  `_commit` must remain in history for Copier's three-way merge to find its base.
  A shallow clone would break updates.
- **Repo-local identity.** `snapshot`/`commit_all` configure
  `user.email`/`user.name` (and disable gpg signing) on the throwaway repo so
  commits succeed even when the user has no global git identity.
- **`add_all_and_diff_cached`** stages everything and diffs `--cached`, so **new
  files show up** in the patch (a plain `git diff` would omit them). This is how
  preview/adopt build their `baseline → updated` patches.
- **`worktree_add` is idempotent**: if the edit branch already exists it attaches
  to it, so re-running `template-checkout` reuses the same worktree.

---

## `shellcmd.py` — the trust gate

The one place template-supplied commands are executed, and the enforcement point
for the [trust model](../user/trust-and-safety.md).

```python
def run_hook_commands(commands, cwd, *, trust: bool, label: str, timeout=120) -> None
```

- When `trust=False`, each command is **skipped with a warning** to stderr.
- When `trust=True`, each runs with `shell=True` in `cwd`; a non-zero exit or
  timeout is **reported but never raises** — post-hooks are advisory and must not
  block create/update completion.
- Used only by `project/create.py` (post-create) and `project/update.py`
  (post-update). Workshop registry `checks` deliberately **do not** route through
  here — they're the author's own commands and run unconditionally in
  `render`/`simulate`.

---

## `treediff.py` — the shared tree comparison

One answer to "which files were added, modified, or removed between two
directories?", used by both golden testing and adoption.

```python
def collect_files(directory, *, relative_to=None, ignore_dirs=frozenset()) -> set[str]
def tree_diff(a, b, *, ignore_dirs=frozenset()) -> tuple[added, modified, removed]
```

- `tree_diff(a, b)` describes how to get from baseline `a` to target `b`:
  `added` = in `b` not `a`; `removed` = in `a` not `b`; `modified` = in both with
  differing bytes.
- **`.copier-answers*.yml` is always excluded** (`_is_copier_answers_file`) — its
  machine-specific `_src_path`/`_commit` would create spurious diffs.
- `ignore_dirs` skips whole subtrees (golden passes nothing; adopt passes
  `EXCLUDE_DIRS` so `.git`, caches, etc. don't count as drift).

---

## `state_machine.py` — the lifecycle primitive

`StateMachine[S]` + `InvalidTransitionError`, the engine behind every workflow.
Full treatment in [state machines](state-machines.md). The essentials:

```python
sm = StateMachine(VALID_X_TRANSITIONS, entity_name="X")
entity.status = sm.transition(from_state, to_state)   # raises if the edge is undeclared
sm.is_terminal(state)                                 # outbound set is empty
```

---

## `errors.py` — the single error type

```python
class CopyRoomError(Exception):
    def __init__(self, message: str, state: str | None = None): ...
```

- One error type for the whole project. Its formatted message starts with
  `Error:` and, when a `state` is given, appends `State left: <state>` — so the
  user sees *what* failed and *where the lifecycle stopped*.
- **Re-exported per workflow module** (`from .._compat.errors import CopyRoomError`)
  so `cli.py`'s aliased imports — `CreateError`, `UpdateError`, `RenderError`,
  `GoldenError`, `SimError`, `ReleaseError`, `TemplateError`, `ManageError` — all
  resolve to this one class. Catching any of them in `cli.py` is catching
  `CopyRoomError`.

---

## Rules for working in `_compat`

1. **All subprocess work lives here.** No `subprocess.run("copier"/"git", …)`
   anywhere above this layer.
2. **Fail soft on tooling absence.** Git helpers return `None`/`False` on a
   missing binary; let callers decide. Don't raise for "git isn't installed."
3. **Always set a timeout** on `subprocess.run`. Copier gets 300s; git gets 120s.
4. **Keep it dependency-light and stateless.** These are leaf utilities; they must
   not import from the domain packages (that would invert the layering).

## See also

- [Architecture](architecture.md) — why this is the bottom layer.
- [Trust & safety](../user/trust-and-safety.md) — the policy `shellcmd` enforces.
- [Copier overview](../copier/overview.md) — the engine `copier.py` drives.
