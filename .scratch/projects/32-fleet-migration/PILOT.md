# 32 — Fleet migration pilot: poddantic, Copier to CopyRoom 0.8.3

Date: 2026-10-12. Scope: a throwaway clone only. No real checkout changed. No push, no remote tag.
Template under test: template-py `main` `851a7112`, local tag `v0.8.0` (never pushed).
Tools: `copyroom 0.8.3` from `git+https://github.com/Bullish-Design/copyroom.git@v0.8.3`, jj 0.46.0, testee 0.6.1.

Labels: **V** = verified by command output in this pilot. **I** = inferred.

## 1. Summary

The route works end to end (V). `adopt` against the v0.5.0 source succeeds with the devman symlinks in place.
The update to v0.8.0 gives 7 conflicts. All 7 are textual: the project already carries the Testee 0.6 and
RepoMan 0.14 wiring, and the template says the same thing in other words. After resolution, `copyroom status`
exits 0 and shows the pin `v0.8.0` and the commit. `testee verify` is GREEN 4/4.

Three things need a decision before the template tag (section 6): the template must exclude `.copyroom-local`
from ruff and ty; the answers file lags the repo (RepoMan and Testee tags); and `adopt --write` and
`update --apply` have limits in jj child workspaces.

## 2. Setup log

| Step | Command (short) | Exit | Key output |
|---|---|---|---|
| venv | `uv venv $T/cr` and `uv pip install "copyroom @ git+...@v0.8.3"` | 0 | `copyroom --version` prints `copyroom 0.8.3` |
| template | `git clone ... template-py`; `git tag v0.8.0 851a7112` (local) | 0 | HEAD `851a7112f21e...` |
| project | `git clone git@github.com:Bullish-Design/poddantic.git`; `jj git init --colocate` | 0 | main = `ff982c11`; `.jj` and `.git` as in the real repo |
| devman links | `ln -s` of `.agents`, `.claude/skills`, `devenv.local.nix`, `.envrc`, `.loci` to dirs in `$T/devman`; names added to `.git/info/exclude` | 0 | `jj st` still clean |
| baseline | `build-source.sh $T/template-py v0.5.0 .../schemas/v0_5.py $T/src-v050` | 0 | two notes: `copyroom_project_yml` and `devenv_yaml` fall back to language `text` |

## 3. Pilot steps

**a. Adopt.** Answers: `.copier-answers.yml` without `_*` keys and `repoman_dev_root`. The v0_5 schema keeps
`docman_ref`.

| Command | Exit | Result |
|---|---|---|
| `copyroom adopt $T/src-v050 --answers answers-v050.json` (dry run) | 1 | 9 paths differ from the v0.5.0 render: `.gitignore AGENTS.md README.md copyroom.project.yml devenv.nix devenv.yaml pyproject.toml src/poddantic/__init__.py tests/test_poddantic.py`. `template_only` is empty. |
| `... --write` | 0 | Commits `copyroom:adoption tree` and `copyroom:project inputs`. `--template-only keep` was not needed because no path exists only in the template. |

Dry run exit 1 is normal: it means "the project differs from the source". Checks after `--write`:
`jj diff main..@` shows only `A .copyroom-local.json` and `A .copyroom-local/sources/<digest>/**` (no project
file changed); `jj st` clean; the five symlinks and their targets unchanged (sha256 of the central files equal);
`copyroom status` exit 0 with `source_kind: path`.

**b. Drop the marker.** `rm .copier-answers.yml`; `jj commit -m "copyroom: drop the Copier marker"`. Exit 0.

**c. Preview.** `copyroom update --source $T/template-py/source --ref v0.8.0 --answers answers-v080.json --out $T/previewN`.
The answers file drops `_*`, `repoman_dev_root`, and `docman_ref` (the v0.8.0 schema has no `docman_ref`).

- Preview 1 used the answers file as it stands (`repoman_ref v0.12.0`, `testee_ref v0.5.1`). Exit 1, 7 conflicts.
  `devenv.yaml` came out with a duplicate `testee:` key, because the answers lag `devenv.yaml` (the repo pins
  RepoMan v0.14.0 and Testee v0.6.1 already). Discarded with `copyroom discard --preview` (exit 0).
- Preview 2 used `repoman_ref v0.14.0` and `testee_ref v0.6.1`, read from `devenv.yaml`. Exit 1, 7 conflicts.
  The `migrate.py` script does this pin read by default.

The `--out` path must be outside the project. The preview is a jj workspace; `jj resolve --list` there names the conflicts.

**d. Resolve and apply.** Recipe: `poddantic-resolve.sh`. It uses `pick_sides.py` to take a side per hunk.
Then `jj squash --from @ --into <first conflicted change>` in the preview, so that no conflicted commit
stays in the published history. (`jj squash` into the immediate parent leaves a conflicted ancestor; V.)

| Command | Exit | Result |
|---|---|---|
| `copyroom update --apply $T/preview2` | 0 | published. No guard refusal: the clone is the default workspace. |
| `copyroom status` | 0 | `ok: true`, `source_kind: ref`, `ref: v0.8.0`, `commit: 851a7112f21e...`, no conflicts, no pending previews |
| `copyroom update` (again) | 0 | `no-change` |
| `jj st` | 0 | clean |

Further checks (V): `.copier-answers.yml` and `copyroom.project.yml` gone; the five symlinks unchanged;
tracked CopyRoom state is only `.copyroom-local.json` and `.copyroom-local/sources/<digest>/**` (previews, journal, and
lock sit in `.git/info/exclude`, as CopyRoom wrote them).

**e. Checks.**

| Command | Result |
|---|---|
| `devenv shell -- uv sync --locked` and `uv run --no-sync pytest -q` | 0; 235 tests: 230 pass, 5 skipped (live tier). devenv used CPython 3.14.7 (see gap G3). |
| `testee verify` (first run) | RED: `ruff`, `ruff-format`, `ty` fail, all in `.copyroom-local/sources/<digest>/**/schema.py` (line too long, unformatted, `sorted` type error). pytest passes. |
| Added `extend-exclude = [".copyroom-local"]` to `[tool.ruff]` and `[tool.ty.src] exclude = [".copyroom-local"]`, committed as "Exclude CopyRoom state from ruff and ty" | |
| `testee verify` (second run) | GREEN 4/4 (pytest, ruff, ruff-format, ty). |
| Same, with the pure v0.8.0 render of `devenv.nix` (template argv `src tests`) | GREEN 4/4. The template wiring itself works on poddantic. |

Skipped: `devenv test` (it adds nothing beyond the Testee run here), and the live tier (needs RunPod keys).

## 4. Conflict table (7 paths)

Base = v0.5.0 render. P = project side (hand edits). T = v0.8.0 render.

| Path | Hunks | What conflicts | Resolution |
|---|---|---|---|
| `.gitignore` | 2 | P reworded the agent-link comment and changed `.agents/` to `.agents`. T rewords it differently and writes `.agents` and `.claude` with no slash. Same intent. | Take T. |
| `AGENTS.md` | 4 | P hand-edited the Testee text and kept `copier` and `docman`. T has the Testee 0.6 text in other words and drops both. | Take T (4 of 4). |
| `README.md` | 3 | Same Testee command block, push comment, and layout lines. T also adds a `devenv.yaml` layout line. | Take T (3 of 3). No duplicate section arose. |
| `copyroom.project.yml` | 1 (modify/delete) | P changed `testee verify --full` to `testee verify`. T deleted the file. CopyRoom 0.8 does not read it, and template-py's `check_render` bans it. | Delete the file. |
| `devenv.nix` | 9 | (1) header comment and the `let testeeFlake` block: P removed it, T removed it too, words differ. (2) `imports = [ testeeFlake... ]`: both removed it. (3) comment lines. (4) P moved `testee.prepare` to the top; T adds it lower. (5-8) check argv. (9) tasks. | 1-4 take T, then remove the doubled `testee.prepare` that auto-merge leaves (two definitions of one attribute would fail in Nix). 5-8 keep P: whole-tree `ruff check .`, `bash -c` wrappers, plain `pytest -q`. 9 keeps P: the `poddantic:lint` and `poddantic:test` devman tasks. |
| `devenv.yaml` | 1 (2 with stale answers) | Comment about the Devman overlay: P and T word it differently. With the stale answers, a second hunk made a duplicate `testee:` input. | Take T. Fix the answers first (section 5). |
| `pyproject.toml` | 1 | P keeps `[project.optional-dependencies]` (cloud, s3) directly above a comment block that T rewrote (adjacent-line conflict). | Keep the P extras table, take the T comment. |

Left as project content after resolution (not template conflicts): the `cloud` and `s3` extras, `[tool.ty.rules]`,
ruff per-file ignores, pytest markers and `-m 'not live'`, the check argv scope, the devman tasks, and the
`.gitignore` tail (`.runpod.env`, `tests/live/artifacts/`).

## 5. Findings about the migration

1. **Answers lag the repo.** `.copier-answers.yml` says `repoman_ref v0.12.0`, `testee_ref v0.5.1`; `devenv.yaml` says
   v0.14.0 and v0.6.1. 13 of the 14 template-py repos on this machine already carry `testee.prepare` and
   RepoMan v0.14 / Testee v0.6 (V, grep), so the lag is fleet-wide. The adopt baseline must keep the old
   answers (so the base render matches what the repo was born with). The update target must use the repo's real
   pins. `migrate.py` reads the pins from `devenv.yaml` for the target answers only.
2. **`adopt --write` refuses a jj child workspace** (exit 2, "adoption requires a colocated jj repository"). V.
   Run the migration in the default (colocated) workspace, on a clean empty change.
3. **`update --apply` in a colocated child workspace exits 2** with the pyjutsu 0.23.0 guard message. V.
   `--publish-unguarded` publishes it; `status` then exits 0. In the default workspace no flag is needed.
   `migrate.py --apply --unguarded` passes the flag only when asked.
4. **`copyroom discard --preview` leaves the preview's conflicted commits as visible heads** in the project
   repo (`jj log -r 'conflicts()'`). V. `jj abandon` removes them. This is a CopyRoom defect (small).
5. **The tracked source snapshot is lint input.** `.copyroom-local/sources/<digest>/` holds `.py` files.
   Whole-tree ruff and ty runs scan them (V, section 3e). This is a template gap (G1).
6. **The marker records the absolute path** of the template repo in `pin.repo` (`/tmp/...` in the pilot). In the real
   run, use the canonical clone (`~/Documents/Projects/template-py`) so the committed marker holds a stable path. I.
7. **CopyRoom has no birth-only path.** `src/<pkg>/__init__.py` and `tests/test_<pkg>.py` stay template-owned
   forever (`owners` lists them). They did not conflict because the template stub did not change since v0.5.0. Any
   later stub change conflicts in every repo. I (from `owners` and the absence of a seed field).
8. Exit codes seen: dry-run adopt 1 (differences); `adopt --write` 0; `update` preview 1 with conflicts, 0 when
   clean or `no-change`; `status` 0.

## 6. Template gaps (question f) and the v0.8.0 tag

**Template behind the fleet or the toolchain (fix before the tag):**

- **G1 (fix).** Add `extend-exclude = [".copyroom-local"]` under `[tool.ruff]` and a `[tool.ty.src]` section with
  `exclude = [".copyroom-local"]` to `source/templates/pyproject_toml/template.j2`. The template's own check argv
  (`src tests`) hides the problem; every repo with a whole-tree check hits it (poddantic does). Refresh the
  goldens. Repos that add the same lines by hand then merge without conflict.
- **G2 (decide).** Testee 0.6 wiring and RepoMan 0.14: no gap. The v0.8.0 render carries `testee.prepare`,
  `uv run --no-sync`, `testee verify`, and the locked Testee input. The pure render was GREEN on poddantic.
- **G3 (decide, optional).** No Python version in the template. `requires-python >=3.13` and ruff `py313` are fixed,
  but `devenv.nix` sets no `languages.python.version`, so devenv uses its own default (3.14.7 in the pilot). 3 of 14
  repos pin `version = "3.13"` by hand (V). Adding a pin now moves the venv of the 11 other repos. Options: (1) add
  `version = "3.13"` to the template; (2) add a `python_version` answer with default `3.13`; (3) leave it. I
  recommend (1) or (2) in a later release, not in v0.8.0, to keep the migration free of toolchain moves.
- **G4 (note).** Keep the two seed stubs stable until CopyRoom has birth-only paths (finding 7).

**Repo-specific edits (expected conflicts, no template change):** check argv scope and wrappers, `pytest -q`,
devman task names, optional-dependency tables, tool rules, `.gitignore` tail, `README.md` body.

**Wording-only conflicts** (`AGENTS.md`, `README.md`, `.gitignore`, comments in `devenv.*`): the hand migration
and the template say the same thing. A conflict is certain whenever the same lines changed on both sides.
No template change prevents them. The recipe is "take T unless the hunk holds project content".

**Before tagging v0.8.0:**

1. Apply G1, refresh goldens, rerun `release-check py`.
2. Decide G3.
3. Tag from the final commit, then rerun this pilot against the pushed tag in a fresh clone. The pilot used a
   local tag on `851a7112`; any template change after it invalidates the conflict table.
4. Use `migrate.py` with the canonical template clone for every fleet repo.

## 7. Script check (`migrate.py`)

Tested on a second clone: exit 1 with the 7 conflicts and the next-step text; rerun is idempotent (reuses the
preview); after `poddantic-resolve.sh` and `jj squash`, `--apply` exits 0 and `verify` passes; a further run reports
"already pinned". Other exits: not a jj workspace 2; dirty tree 1; missing ref 2; missing arguments 3.
Run in a jj child workspace: `adopt` step exits 2 (finding 2).

## 8. Cleanup

`$T` removed at the end of the pilot. Testee wrote state for the throwaway clones under
`~/.local/state/testee/repos/` (two directories keyed to `/tmp` paths); both were removed.
