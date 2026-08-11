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
| 8 | Commit + `v0.1.0` tag | ⏳ **the user's** — see Handover |

## Verification

| What | How | Result |
|---|---|---|
| Copier supports per-layer answers files | [`spike-layers.sh`](spike-layers.sh) — 5 questions, synthetic templates | all PASS ([`SPIKE.md`](SPIKE.md)) |
| The real my-ai template on real repos, via the real CLI | [`verify-my-ai-layer.sh`](verify-my-ai-layer.sh) — stages my-ai as a tagged repo, applies it to a copy of **gitman**, bumps it, converges | all PASS |
| The layer feature in isolation | `tests/unit/test_layers.py` + `tests/integration/test_layers.py` (real Copier + git) | **40 pass** |
| No regression | `devenv shell -- uv run pytest -q` | **588 pass**, 2 skipped |
| Lint | `devenv shell -- uv run ruff check src/ tests/` | clean |
| End-to-end demo | `devenv shell -- bash demo/walkthrough.sh` | passes, ACT 6 included |

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

## One design decision changed during implementation

`update --all-layers` was designed to converge every layer in one pass with a
single up-front worktree check. Implementation found that **Copier refuses a
dirty destination**, so layer 2 could never run after layer 1 dirtied the tree.
Resolved by committing each layer's result before the next runs — required by
Copier, and the right history anyway. The guard still runs once for the whole
run; the last layer is left uncommitted; a layer that leaves conflicts stops the
run instead of committing them. Covered by
`test_all_layers_commits_between_layers`.

## Handover

my-ai's changes are on disk and **uncommitted** — the commit and tag are the
user's to make (my-ai is jj-colocated, and gitman owns VCS in this family). The
template is not consumable until it is tagged: Copier resolves a template by tag.

```bash
cd ~/Documents/Projects/my-ai
gitman status                       # review the change
# commit via your normal lane, then:
git tag v0.1.0                      # a Copier template is consumed BY TAG
```

Then roll out, per repo:

```bash
copyroom layer add ~/Documents/Projects/my-ai        # dev; gh:Bullish-Design/my-ai in fleet mode
copyroom layer list                                  # confirm the layers
git status                                           # review, then commit
```

And thereafter:

```bash
copyroom update --layer my-ai                        # converge the personal layer
copyroom update --all-layers                         # converge everything
```

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
