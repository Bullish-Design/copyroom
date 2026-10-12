# 32 — Fleet migration pilot 2: poddantic, Copier to CopyRoom 0.8.4

Date: 2026-10-12. Scope: throwaway directories only. No real checkout changed. No push, no remote tag.
Template under test: template-py `main` `851a7112f21e`, local tag `v0.8.0` (never pushed).
Tools: `copyroom 0.8.4` (from `git+https://github.com/Bullish-Design/copyroom.git@v0.8.4`), templateer 0.5.0,
pyjutsu 0.23.0, jj 0.46.0, testee 0.6.1, copier 9.19.0 (proofs only).
Labels: **V** = verified by command output. **I** = inferred.

## 1. Summary

GO for the tag (section 7). The template re-proves under templateer 0.5.0: all conversion proofs are
identical, both goldens match, `release-check` is ready, `check_render` is ok. The pilot works end to end
with the same 7 conflicts as pilot 1 and the same resolution recipe. The 0.8.4 changes all help:
no source copy in the tree, so `testee verify` is GREEN 4/4 **without** any ruff or ty exclude (gap G1 is gone);
`discard` leaves no conflicted head.

## 2. Command log

All commands ran in the CopyRoom devenv shell, with `$T/cr/bin` first on PATH. `$T` = a `mktemp -d` directory.

| # | Command (short) | Exit | Result |
|---|---|---|---|
| 1 | `uv venv $T/cr`; `uv pip install "copyroom @ git+...@v0.8.4"` | 0 | `copyroom --version` prints `copyroom 0.8.4`; templateer 0.5.0 installed (V) |
| 2 | `git clone git@github.com:Bullish-Design/template-py.git` | 0 | HEAD `851a7112f21e6980797f5db6b39219c90241fbc4` (V) |
| 3a | `prove.py` v0.5.0 (`schemas/v0_5.py`; answers a-three, b-one, c-doc-v0_5) | 0 | 6 of 6 `IDENTICAL` (overlay 13 files, fleet 12 files); 3 faithful runs `SKIPPED` (see 3 below) |
| 3b | `prove.py` v0.7.0 (`schemas/v0_7.py`; answers a-three, b-one) | 0 | 4 of 4 `IDENTICAL`; 2 faithful runs `SKIPPED` |
| 3c | `copyroom render py basic` | 0 | `rendered`, 11 files, digest `9c3a3be0...932aa2` |
| 3d | `copyroom golden py basic` (compare) | 0 | `match`, no added/changed/removed |
| 3e | `copyroom golden py probe` (compare) | 0 | `match`, digest `3003b423...d36870` |
| 3f | `copyroom release-check py` | 0 | `ready`; scenarios `basic` and `probe` both `passed` |
| 3g | `python scripts/check_render.py` | 0 | `generated/py/basic: ok`, `generated/py/probe: ok` |
| 4 | `git tag v0.8.0 851a7112` (local) | 0 | `v0.8.0` -> `851a7112f21e` (V); clone stayed clean |
| 5 | `git clone ...poddantic.git`; `jj git init --colocate`; 5 devman symlinks into `$T/devman`; names in `.git/info/exclude` | 0 | main = `ff982c11`; `jj st` clean; `.claude/` is a real directory holding the `skills` link |
| 6a | `migrate.py $T/poddantic $T/template-py v0.8.0 $T/work` (preview) | 1 | adopt dry run exit 1 (expected), `adopt --write` 0, marker dropped, preview exit 1: 7 conflicts |
| 6b | `poddantic-resolve.sh $T/work/preview` | 0 | every hunk count matched; 0 conflicts left |
| 6c | `jj squash --from @ --into uumwntkkoxtm` (in preview) | 0 | `jj resolve --list` empty; `jj log -r 'conflicts()'` empty |
| 6d | `migrate.py --apply ...` | 0 | `apply ok`; `verify ok` (default workspace, no guard flag) |
| 6e | `copyroom status` | 0 | `ok: true`, `source_kind: ref`, `ref: v0.8.0`, `commit: 851a7112f21e...`, no previews, no transactions |
| 6f | `copyroom update` (second) | 0 | `{"result": "no-change"}` |
| 6g | `devenv shell -- testee verify` in poddantic | 0 | GREEN 4/4: pytest, ruff, ruff-format, ty. `pyproject.toml` has no ruff or ty exclude (V, grep) |
| 7a | `migrate.py ...` second run | 0 | "already pinned at v0.8.0", then `verify ok` |
| 7b | `migrate.py` with one argument | 3 | argparse usage error |
| 7c | `migrate.py ... v9.9.9 ...` | 2 | "ref v9.9.9 not found" |
| 7d | `migrate.py` on a non-jj directory | 2 | "not a jj workspace; refusing to run" |
| 7e | `migrate.py` with an untracked file in the repo | 1 | "the jj working copy is not clean: A dirty.txt" |
| 7f | second clone (`poddantic-b`): migrate to preview, then `copyroom discard --preview` | 1, then 0 | `{"result": "discarded"}`; `jj log -r 'conflicts()'` empty; only the default workspace remains |

## 3. Template re-proof under templateer 0.5.0

Proofs were proven with templateer 0.4.2. They now pass byte for byte under 0.5.0 (V). Goldens match, so 0.5.0
renders the same bytes as the golden set. No diff to diagnose. Two notes, both old:

- The faithful mode is `SKIPPED` ("this CopyRoom reserves .agents"). `prove.py` documents this: faithful mode
  needs CopyRoom 0.8.1 or earlier. The overlay and fleet modes cover the shipped source.
- The converter prints `language yaml -> text` notes for three yaml templates (unquoted `{{ project_name }}`).
  This is the same as pilot 1. It does not change the output.

Nothing in template-py needs a change for 0.8.4 or templateer 0.5.0.

## 4. Pilot checks (question 6)

| Check | Result |
|---|---|
| No `.copyroom-local/sources` in the tree | V. `.copyroom-local/` holds only `journal`, `previews`, `write.lock` (untracked, in `.git/info/exclude`) |
| None in `jj file list` | V. The only match for `copyroom-local` is the marker `.copyroom-local.json` |
| `git for-each-ref refs/copyroom/` | V. Two refs: `refs/copyroom/sources/aaf75dda...` (baseline v0.5.0) and `refs/copyroom/sources/9e250d75...` (v0.8.0, the pinned source) |
| `jj bookmark list --all` shows no copyroom refs | V |
| `copyroom status` | V. exit 0, pin `v0.8.0`, commit `851a7112f21e` |
| Second update | V. `no-change`, exit 0 |
| Symlink targets unchanged | V. All five equal the first record in `links.json` |
| `testee verify` without an exclude | V. GREEN 4/4 (pilot 1: RED until the exclude was added) |
| No leftover preview heads after a discard | V (clone `-b`). Pilot 1 finding 4 is fixed in 0.8.4 |
| Net diff `main` to the result | V. Nine paths: `D .copier-answers.yml`, `A .copyroom-local.json`, `M .gitignore AGENTS.md README.md devenv.nix devenv.yaml pyproject.toml`, `D copyroom.project.yml` |

Observation: the baseline source ref (`aaf75dda...`) stays after the update. It is small and private. The
baseline `source` in the first revision pointed at a path in the work directory (deleted at cleanup); the
pinned layer reads the pinned commit, so this does not matter. (I)

## 5. Conflict table (compare with pilot 1)

Same 7 paths. The resolution script took the same hunk counts without a change, so the table did not move.

| Path | Hunks | Change from pilot 1 |
|---|---|---|
| `.gitignore` | 2 | none |
| `AGENTS.md` | 4 | none |
| `README.md` | 3 | none |
| `copyroom.project.yml` | modify/delete | none |
| `devenv.nix` | 9 | none |
| `devenv.yaml` | 2 | none in the recipe (`T T`). The pilot 1 table says "1 (2 with stale answers)"; the recipe always used two picks and `migrate.py` reads the real pins. The table text in PILOT.md was imprecise. |
| `pyproject.toml` | 1 | none |

The tracked source snapshot no longer exists, so the ruff and ty lint input problem (pilot 1 finding 5, gap G1)
is gone without a template change. The `Exclude CopyRoom state from ruff and ty` commit is not needed.

## 6. Changes to `migrate.py` (uncommitted file)

1. **Baseline build uses the installed copyroom.** The old code called `build-source.sh`, which runs
   `uv run --project $COPYROOM_PROJECT` (default `~/Documents/Projects/copyroom`, the real checkout). That used the
   checkout's own copyroom and `.venv`, not the 0.8.4 that the script had just checked. A new `build_baseline()`
   does the same steps (`git archive`, then `convert.py --schema`) with the interpreter of the `copyroom` on PATH
   (read from its shebang). `COPYROOM_PROJECT` is gone. The `--converter-dir` help text now says `convert.py`.
2. **`verify()` checks the 0.8.4 storage.** It now fails when the private ref
   `refs/copyroom/sources/<source_digest>` is missing, or when a jj bookmark name contains `copyroom`.
3. The pilot 1 edits (min version 0.8.4, no source-copy tracking check) were already in the file.

Tested after the edits: full migration (6a to 6d), rerun (7a), and the exit paths. Not changed: the stray
`WORKDIR` that a failed preflight leaves (`mkdir` runs before preflight). It is harmless.

## 7. Recommendation: GO

Tag template-py `v0.8.0` at `851a7112`.

- Re-proof is clean under CopyRoom 0.8.4 and templateer 0.5.0. No golden refresh is needed.
- G1 (ruff and ty exclude) no longer applies. Pilot 1 asked for a template change here; none is needed.
- The conflict table is unchanged, so the pilot 1 conclusion holds: all 7 are wording or repo-specific edits.

Still open from pilot 1 (not blockers, none retested here):

- G3: no Python version pin in `devenv.nix`. devenv chose CPython 3.14.7 again in this run (V). Decide later.
- Finding 1 (answers lag the repo): `migrate.py` still reads the pins from `devenv.yaml`.
- Finding 6: in the real run, pass the canonical clone `~/Documents/Projects/template-py` so `pin.repo` holds a stable path.
- Findings 2 and 3 (child-workspace limits, pyjutsu 0.23.0): run each migration in the default workspace.
- Finding 7 (no birth-only paths) is unchanged.
- The tag must sit on the commit that was proven. Push the tag only after the real clone is on `851a7112`.

## 8. Cleanup

`$T` and the helper files in `/tmp` were removed. Testee state directories keyed to `$T` paths were removed from
`~/.local/state/testee/repos/` (see the report for the count).
