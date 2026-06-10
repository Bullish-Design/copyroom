# CopyRoom v0.3.0 — Code Review Report

**Branch:** `feat/v0.3.0` · **PR:** #1 · **Base:** `main`
**Scope:** the v0.3.0 change set (latest-ref resolution, validated `copyroom.project.yml`,
`inspect`/`status`, `registry`).
**Method:** 7 finder angles (3 correctness, 3 cleanup, 1 altitude) over `git diff
main...HEAD`, deduped, then each surviving candidate verified by direct inspection of
the current code (line numbers below are from the branch as reviewed).

Gate at review time: ruff clean · 448 tests green · `demo/walkthrough.sh` exits 0.
None of the findings below are caught by the existing suite — they live on inputs the
fixture template doesn't exercise (describe-format `_commit`, schema-invalid configs,
`registry:`-keyed workshops, `~` sources, remote sources offline).

---

## Severity legend

| Tier | Meaning |
|------|---------|
| **P1** | Fix before merge — wrong result or regression on realistic input. |
| **P2** | Fix soon — correctness/contract issue on a reachable but narrower path. |
| **P3** | Cleanup / altitude — no wrong result today, but duplication or a latent trap. |

---

## P1 — fix before merge

### P1-1 · Whole-model config validation aborts `new`/`update` on an invalid *known* field
**Files:** `src/copyroom/project/create.py:226` & `:271`, `src/copyroom/project/update.py:404`
(root cause: `src/copyroom/project/config.py:109` `load_project_config`).

The pre-v0.3.0 hook extractors read only the `commands` key and ignored everything else.
`load_project_config` now validates the **entire** `CopyRoomProjectConfig`, and the
create/update flows translate any `CopyRoomError` into a `failed` transition. So a
`copyroom.project.yml` that is valid YAML and a mapping, but carries an invalid value for
a *known* field, now **aborts project creation / update**:

- `project.kind: library` (not in the `Literal`) → `ValidationError` → `failed`.
- `project.template_ref_policy: pinned` → `failed`.
- any future field value a newer template emits that this CLI's `Literal` doesn't know.

**Why it matters:** this directly contradicts the project's stated **additive /
forward-compat invariant** ("readers ignore unknown fields rather than failing; old
configs keep working"). A future template bumping `kind` would break generation on older
CLIs — exactly the failure mode the invariant exists to prevent. Unknown *fields* are
tolerated (good), but unknown *enum values* and minor type slips on known fields are not.

**Trigger:** generate/update a project whose `copyroom.project.yml` has any
schema-divergent known field (very plausible across CLI/template version skew).

**Fix direction:** (a) the hook-reading paths must not hard-fail the workflow on a
validation error unrelated to hooks — degrade to a minimal `commands` read; and
(b) relax forward-compat-sensitive fields (`kind`, `template_ref_policy`) from `Literal`
to `str` with documented expected values, so unknown values validate. Keep the loader
raising only for unparseable YAML / non-mapping. See guide §2.

---

### P1-2 · `_commit`-vs-tag string comparison breaks no-op and "update available"
**Files:** `src/copyroom/project/update.py:169` (`no_update_available`),
`src/copyroom/project/inspect.py:162` (`project_status`).

Both compare the recorded `_commit` against the resolved bare semver tag with plain
`==` / `!=`. Copier records `_commit` as `git describe` output:

- tag-exact project → `_commit == "v1.0.0"` (works — this is what the test fixture hits),
- project generated at a post-tag commit → `_commit == "v1.0.0-3-gdeadbee"` or a raw SHA.

In the describe-suffix / SHA case `previous_ref != target_ref` is **always** true, so:

- `copyroom update` (no ref) skips the no-op guard and re-runs `copier update` against the
  version the project is effectively already on (needless merge, possible spurious
  conflict capture);
- `copyroom status` reports **"update available: yes"** when the project is current.

**Why it matters:** wrong answer on a realistic input; the two call sites also frame the
same comparison differently (`==` vs `!=`), so they can drift independently.

**Fix direction:** one shared `_compat` helper that compares a recorded ref (tag,
`tag-N-gsha`, or SHA) against a target tag — strip the describe suffix to a base tag and
compare; SHA-only `_commit` (no resolvable tag) stays "not a no-op". Route both call
sites through it. See guide §3.

---

### P1-3 · `registry add` only checks `registry/<id>.yml`, ignoring ids in `copyroom.yml`
**File:** `src/copyroom/workshop/registry.py:196` (`add_template`).

`resolve_template_source` reads `copyroom.yml` **first**, then falls back to
`registry/<id>.yml`. But `add_template`'s collision guard only stats
`registry/<id>.yml`. So `copyroom registry add webapp --source ./local`, when `webapp` is
already defined inline in `copyroom.yml`, **"succeeds"** and writes a
`registry/webapp.yml` that the resolver will never consult — a silently dead, shadowed
entry. The user is told it worked; the new source is ignored.

**Fix direction:** refuse when the id already resolves via `copyroom.yml` (e.g. check
`template_id in _registry_ids(...)`), with a message pointing at the inline definition.
See guide §4.

---

## P2 — fix soon

### P2-4 · `registry add` writes an unquoted `source:` line
**File:** `src/copyroom/workshop/registry.py:206`.

`f"source: {source}\n"` string-formats the value. A source containing ` #` (read as a YAML
comment), or beginning with a flow indicator (`{`, `[`, `@`, `` ` ``), or otherwise needing
quoting, round-trips to a truncated/invalid value on the next `_load_yaml`. The
just-added entry then resolves to the wrong path or `None`.

**Fix direction:** build the entry with `yaml.safe_dump({...}, sort_keys=False)` instead of
hand-formatting. See guide §5.

---

### P2-5 · `load_checks` omits the `registry:`-key fallback that `resolve_template_source` has
**File:** `src/copyroom/workshop/registry.py:59`.

`resolve_template_source` and `_registry_ids` resolve via `cfg.get("templates",
cfg.get("registry"))`, but `load_checks` only reads `(cfg.get("templates") or {})`. For a
workshop whose `copyroom.yml` is keyed `registry:` (a documented alias), `list`/`show`/
`validate` resolve the source and id correctly but report **empty checks** — and
`validate`'s reasoning silently loses them. Pre-existing bug, newly **re-exposed** by the
v0.3.0 `load_entry`/`list`/`show`/`validate` surface.

**Fix direction:** a single `_registry_map(cfg)` helper shared by all three readers; fold
into the single-loader refactor (§7). See guide §6.

---

### P2-6 · `~`-prefixed local source is never expanded
**Files:** `src/copyroom/_compat/gitutil.py:70` (`looks_remote`) → `:225`
(`resolve_latest_ref` local branch); `src/copyroom/workshop/registry.py`
(`_resolve_local_source`).

`looks_remote` classifies `~/templates/foo` as **local** (good) but the path is never
`expanduser()`'d, so `list_tags(Path("~/templates/foo"))` runs on a literal-`~` path that
can't exist → resolves to "no semver tags / unreachable" for a perfectly valid template.
The logic moved verbatim from `template/workspace.py`, where `_src_path` is always an
expanded absolute path — but it is newly reachable now that `resolve_latest_ref` and the
registry accept user-supplied sources.

**Fix direction:** `expanduser()` in local-path resolution; centralize in one helper. See
guide §8.

---

### P2-7 · `capture_conflicts` swallows a config error and silently skips post-update hooks
**File:** `src/copyroom/project/update.py:368` (`except CopyRoomError: pass`).

If `copyroom.project.yml` fails validation, `capture_conflicts` swallows the error, leaves
`has_post_commands=False`, and short-circuits the update to `complete` — so configured
`post_template_update` hooks **never run**, with no warning. Meanwhile
`run_post_update_commands` (`:404`) and the create path treat the same bad config as
`failed`. The three readers of the same file now disagree (silent-skip vs hard-fail).

**Fix direction:** resolve once with P1-1 — read hook commands through one resilient
accessor used by `capture_conflicts` and `run_post_update_commands` alike; never
silently drop configured hooks. See guide §2 + §9.

---

### P2-8 · `resolve_latest_ref` raises without transitioning the entity to `failed`
**File:** `src/copyroom/project/update.py:125` (raises with `state="config_loaded"`);
orchestrator `update_project` does not convert it.

Every other update step sets `update.status = failed` and returns the entity; this one
raises a `CopyRoomError` while the entity is left at `config_loaded`. `_cmd_update`
catches the exception (so the CLI is fine), but any other caller of `update_project` that
inspects `.status` after the call sees a non-terminal entity for a run that didn't
complete — breaking the workflow's "failed is reachable and recorded" contract.

**Fix direction:** before raising (or in the orchestrator), transition `config_loaded →
failed` (a legal edge) so the entity reflects the outcome; keep the clear `CopyRoomError`
message for the CLI. See guide §10.

---

## P3 — cleanup / altitude

### P3-9 · Worktree-clean check now exists in three divergent copies
**Files:** `src/copyroom/project/inspect.py:101` (`_worktree_clean`),
`src/copyroom/project/update.py:186` (`verify_worktree`),
`src/copyroom/release/check.py` (`_check_worktree_clean`).

Three implementations of `git status --porcelain`, already divergent: `release/check`
excludes `generated/` and `.copyroom_sim/`; `inspect` uses `gitutil.run_git` (120s
timeout); `update.verify_worktree` uses **bare `subprocess.run` with no timeout** (a mild
correctness wrinkle of its own — a hung git blocks the update). A fix to one path won't
reach the others.

**Fix direction:** one `gitutil.worktree_clean(path, *, exclude=()) -> bool | None`
(plus a way to surface the dirty-file list `verify_worktree` prints). See guide §11.

---

### P3-10 · Registry helpers re-parse `copyroom.yml` ~4× per entry and decode the storage model in three places
**File:** `src/copyroom/workshop/registry.py` (`list_templates` → `load_entry` →
`_registry_ids` + `resolve_template_source` + `load_checks`).

`load_entry` re-opens `copyroom.yml` through `_registry_ids`, `resolve_template_source`,
and `load_checks` (~4 parses + 2 of `registry/<id>.yml`) per entry; `list_templates`
calls `load_entry` per id, so `validate` on N templates re-parses `copyroom.yml` ~4N times
and re-globs the registry dir N+1 times. The "templates vs registry key" + "copyroom.yml
vs registry/<id>.yml" merge is implemented in three functions (and inconsistently — see
P2-5).

**Fix direction:** one `load_registry(workshop_root) -> dict[str, RegistryEntry]` that
reads each file once and builds normalized entries; `list`/`validate` iterate it, `show`/
`load_entry` look up by key. Subsumes P2-5. See guide §7.

---

## Noted but not separately tracked

- **Pre-release-only repos resolve to `None`.** `select_latest_semver` drops all
  pre-release tags by design (per the original spec). A repo whose only tags are
  `v1.0.0-rc1`/`-rc2` yields "no semver tags," which is correct-by-design but the message
  misleads and the no-arg path can't track an rc line. Consider a future
  `--pre`/`--allow-prerelease` opt-in; out of scope for this remediation.
- **`status` runs a blocking `git ls-remote`.** Documented as fetch-class, but a remote
  `_src_path` while offline hangs `status` up to the 120s git timeout with no cache or
  `--offline`. Consider a short-TTL cache or `--no-fetch` flag later.
- **`copyroom:`-block version folding drops future `copyroom.*` keys.** `load_project_config`
  whitelists top-level keys and only lifts `copyroom.version`; any future `copyroom.<x>`
  metadata is silently dropped. Fine today; revisit if that block grows.
- **`to_dict` is hand-maintained per report dataclass** (`inspect.py`). A new field must be
  added in two places or it silently drops from `--json`. Low risk.

---

## Suggested cut line

Merge-blockers: **P1-1, P1-2, P1-3.** Strongly recommended in the same pass: **P2-4…P2-8**
(small, and P2-7 is the same fix as P1-1). **P3-9/P3-10** are healthy refactors that also
remove the latent traps behind P2-5 and the missing-timeout in §9 — worth doing while the
code is fresh, but they can be a follow-up PR.

See `REFACTORING_GUIDE.md` (same directory) for the ordered remediation plan and
`FIX_PROMPT.md` for a ready-to-run kickoff prompt.
