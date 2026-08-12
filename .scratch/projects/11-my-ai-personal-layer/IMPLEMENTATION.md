# Implementation — state and verification

Everything below is **done and verified** unless marked otherwise. The one
remaining step is the user's to take (see [Handover](#handover)).

## CopyRoom — the layer concept

| # | Change | State |
|---|--------|-------|
| 1 | `project/layers.py` — `Layer`, `discover_layers`, `resolve_layer`, `answers_filename`, `template_default_layer` | ✅ |
| 2 | `_compat/copier.py` — real `answers_file` (`-a`) on copy + update; the misnamed old param renamed `data_file` (it was `--data-file` all along) | ✅ |
| 3 | `project/update.py` — `update_project(..., layer=)`, layer-scoped `load_config`/`execute_update`, layer-qualified branch names, `update_all_layers` | ✅ |
| 4 | `manage/layer.py` — `add_layer` / `list_layers` | ✅ |
| 5 | `manage/adopt.py` — `--layer`; per-layer refusal; drift scoped for a partial template | ✅ |
| 6 | `session/detector.py` — an overlay-only repo is a project | ✅ |
| 7 | `template/workspace.py` — `read_answers(root, answers_file=…)` | ✅ |
| 8 | `project/inspect.py` — `inspect`/`status` report every layer; `status.update_available` means *any* layer is behind | ✅ |
| 9 | `cli.py` + `session/model.py` — `copyroom layer add|list`; `--layer`/`--all-layers` on `update`; `--layer` on `adopt` | ✅ |
| 10 | Docs — new `docs/user/layers.md`; updates to `agent-files`, `adoption`, `projects`, `configuration`, `cli-reference`, `docs/README`, `developer/module-reference`, root `AGENTS.md` | ✅ |
| 11 | Canonical skill asset `copyroom/SKILL.md` — layers in the law + the routing table | ✅ |
| 12 | `demo/walkthrough.sh` — ACT 6 drives `layer add` → `layer list` → `update --layer` | ✅ |

**Deliberately not done:** `doctor` does not report layers. It reports
*environment* health; the layer set is a project fact already reported three ways
(`layer list`, `inspect`, `status`).

## my-ai — the personal layer

| # | Change | State |
|---|--------|-------|
| 1 | `copier.yml` — `_subdirectory`, `_answers_file`, `_preserve_symlinks`, `_copy_without_render`, `_skip_if_exists: [AGENTS.md]`, no questions | ✅ |
| 2 | `template/.copier-answers.my-ai.yml.jinja` | ✅ |
| 3 | `template/.agents/skills/my-ai/SKILL.md` — the personal law (the cross-repo material that was stranded in my-ai's `AGENTS.md`) | ✅ |
| 4 | `template/AGENTS.md` + `template/CLAUDE.md -> AGENTS.md` — seed + symlink | ✅ |
| 5 | Stopped shipping copies of `copyroom*`, `gitman`, `repoman` skills (the two-writer fix) | ✅ |
| 6 | `scripts/my-ai-sync.py` deleted; `devenv.nix` script + `enterShell` rewritten | ✅ |
| 7 | `AGENTS.md` / `README.md` / `pyproject.toml` rewritten for the layer model | ✅ |
| 8 | Commit + `v0.1.0` tag | ✅ `796107c`, tag `v0.1.0` |
| 9 | my-ai applies its own layer to itself (dogfood) | ✅ `b071e36` |

## Verification

| What | How | Result |
|---|---|---|
| Copier supports per-layer answers files | [`spike-layers.sh`](spike-layers.sh) — 5 questions, synthetic templates | all PASS ([`SPIKE.md`](SPIKE.md)) |
| The real my-ai template on real repos, via the real CLI | [`verify-my-ai-layer.sh`](verify-my-ai-layer.sh) — stages my-ai as a tagged repo, applies it to a copy of **gitman**, bumps it, converges | all PASS |
| The layer feature in isolation | `tests/unit/test_layers.py` + `tests/integration/test_layers.py` (real Copier + git) | **40 pass** |
| No regression | `devenv shell -- uv run pytest -q` | **588 pass**, 2 skipped |
| Lint | `devenv shell -- uv run ruff check src/ tests/` | clean |
| End-to-end demo | `devenv shell -- bash demo/walkthrough.sh` | passes, ACT 6 included |
| **The real two-layer case** | [`verify-two-real-layers.sh`](verify-two-real-layers.sh) — the real my-ai layer on a copy of **argentic**, whose base layer is the real genome (`gh:Bullish-Design/template-py` @ v0.1.2) | all PASS |
| The new command is live machine-wide | `~/.local/share/repoman/venv/bin/copyroom layer --help` | works (editable install picked it up; no `repoman-sync` needed) |

What `verify-my-ai-layer.sh` proves against a *real* repo (gitman, which has its
own `AGENTS.md`, `CLAUDE.md`, and `.agents/skills/gitman/`):

- the personal skill lands; the layer link is recorded in `.copier-answers.my-ai.yml`;
- gitman's `AGENTS.md` is **byte-identical** after `layer add` **and** after
  `update --layer my-ai` (the `_skip_if_exists` contract, on both paths);
- gitman's own skill is untouched (the two-writer rule holds);
- `CLAUDE.md` stays a symlink through both;
- re-running `layer add` changes nothing (idempotent);
- a v0.2.0 bump converges: edited skill updated, new skill added, ref recorded;
- on a repo with **no** `AGENTS.md`, the seed and symlink are created.

## Three things dogfooding found that design and the first verification missed

### 1. `layer add` must pass `--overwrite` (fixed — `4d727f3`)

Applying the layer to my-ai itself failed outright:

    Interactive session required: Consider using `--overwrite`

A layer lands in a repo that already has files, so Copier prompts per conflicting
file and then fails when stdin isn't a terminal — every agent and CI invocation.
The first verification missed it because the conflict only arises when a
layer-owned file already exists with **different** content; those targets either
lacked the layer's skills entirely or had a byte-identical `CLAUDE.md`. my-ai
already had a `.agents/skills/my-ai/SKILL.md`, which is exactly the shape of any
repo an older distribution mechanism has touched.

Fixed, regression-tested, and documented: `layer add` *applies* (a copy —
replaces), `update --layer` *converges* (three-way merges).

### 2. Rollout order matters, because two layers ship `AGENTS.md` (documented)

Verifying against a real template-py repo (argentic, 6 genome versions behind, no
`AGENTS.md`) showed the genome's own update conflicting on `AGENTS.md`. A control
run without the personal layer isolated the cause:

| Conflicts on `copyroom update` (v0.1.2 → v0.1.8) | control | with the layer |
|---|---|---|
| `devenv.nix`, `devenv.yaml`, `.gitignore`, `pyproject.toml`, `.agents/devenv/*` | yes | yes |
| **`AGENTS.md`** | **no** | **yes** |

template-py ships an `AGENTS.md` too. `_skip_if_exists` makes this safe — nobody
overwrites — but it means **whoever seeds it first wins**, so applying the
personal layer to a repo that is behind on its genome creates one avoidable
merge. Not a code bug; a rollout-order fact. Fix is the order:

    copyroom update && git add -A && git commit    # genome first
    copyroom layer add <my-ai>                     # then the personal layer

Documented in `docs/user/layers.md` §"Rollout order", my-ai's `AGENTS.md`, and
its `README.md`. Irrelevant for a repo already current on its genome, or one with
no genome.

### 3. `layer add` recorded the local clone as `_src_path` (fixed — `11a9a76`)

Caught by running the `gh:` form against the **real published** template rather
than assuming it behaved like the local-path case. `layer add` resolves the
template to a local clone so it can read `copier.yml` and derive the layer name,
then handed *that clone* to Copier as the source. Copier records its source
verbatim, so the result was:

    _src_path: /home/andrew/.cache/copyroom/templates/3f3c79a7e880b956/repo

`_src_path` is what every future `update --layer` resolves against. Rolling out
across the fleet would have pinned every repo to a machine-local cache directory
— unresolvable on another machine or in CI, broken by a cache prune — and since
answers files are never to be hand-edited, the fix would have been re-adopting
each repo. (`eventic` already carries this shape on its *base* layer:
`_src_path: /home/andrew/Documents/Projects/template-py`.)

`copyroom new` has always passed the caller's original string, which is why
generated repos correctly record `gh:Bullish-Design/template-py`. `layer add` now
does the same; the clone stays, but only to read `copier.yml`. Verified against
the published template:

    _src_path: gh:Bullish-Design/my-ai

## One design decision changed during implementation

`update --all-layers` was designed to converge every layer in one pass with a
single up-front worktree check. Implementation found that **Copier refuses a
dirty destination**, so layer 2 could never run after layer 1 dirtied the tree.
Resolved by committing each layer's result before the next runs — required by
Copier, and the right history anyway. The guard still runs once for the whole
run; the last layer is left uncommitted; a layer that leaves conflicts stops the
run instead of committing them. Covered by
`test_all_layers_commits_between_layers`.

## Shipped

| Repo | State |
|---|---|
| copyroom | `main` @ `11a9a76`, tagged **v0.7.2**, **pushed** |
| my-ai | `main` @ `effb8e9`, tagged **v0.1.0**, **pushed** |
| machine toolchain | `copyroom layer` live — the venv installs copyroom editable from the main checkout, so merging to `main` was enough |

Tag history, stated accurately:

| Tag | Published | Status |
|---|---|---|
| v0.7.0 | no | `layer add` missing `--overwrite` — never left this machine |
| v0.7.1 | **yes** | pushed before finding 3; `layer add` records a machine-local `_src_path` |
| v0.7.2 | yes | **use this one** |

v0.7.1 was pushed before the `_src_path` bug was found. It is left on the remote
rather than deleted — rewriting a published tag is worse than a superseded one,
and nothing consumes it (`repoman.lock` pins copyroom by `path:`). Consumers want
**>= 0.7.2**; anything that applied a layer with 0.7.1 should check its
`.copier-answers.<layer>.yml` for a `~/.cache/copyroom` path.

**my-ai is jj-colocated with a detached git HEAD**, so the commits landed off the
`main` branch and local `main` still pointed at the old tip. It was advanced with
`git branch -f main` (verified a clean fast-forward first) before pushing. Run any
`jj` command in that repo to re-import the refs into jj's view.

## Rollout — not started

No production repo has the layer yet. Per repo, in this order:

```bash
copyroom update && git add -A && git commit          # 1. genome first (see above)
copyroom layer add gh:Bullish-Design/my-ai           # 2. the PORTABLE form — see finding 3
copyroom layer list && git status                    #    review, then commit
```

And thereafter:

```bash
copyroom update --layer my-ai                        # converge the personal layer
copyroom update --all-layers                         # converge everything
```

Most repos are several genome versions behind (argentic was 6), so step 1 will
produce real conflicts from its own drift — unrelated to the personal layer, but
worth doing one repo at a time rather than fanning out.

## Follow-ups for other repos (out of scope here)

1. **`gitman`'s skill has no owner-side materializer.** gitman ships it only in
   its own repo; `repoman install-skills` writes only the generated router;
   `copyroom agent-files export` writes only copyroom's set. my-ai was informally
   papering over this by carrying a copy — removing the copy makes the gap
   visible rather than creating it. It belongs to gitman/repoman: either a
   `gitman agent-files export`, or repoman installing each wired manager's
   tool-shipped skill.
2. **repoman's `docs/AGENT-FILES.md`** should gain the *personal* row in its
   ownership split, so the family decision record matches
   `copyroom/docs/user/agent-files.md`.
3. **`template-py`** could stop shipping copies of copyroom's canonical skills
   (`template/.agents/skills/copyroom*/`) for the same two-writer reason — a
   separate call, since the genome shipping them means a freshly generated repo
   has them before `agent-files export` ever runs.
