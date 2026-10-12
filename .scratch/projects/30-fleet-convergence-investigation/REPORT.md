# 30 — Fleet convergence investigation (issues #3 and #4)

Date: 2026-10-12. CopyRoom `main` = `fdf6e570` (0.8.1 plus 11 commits).
Scope: investigation only. No code change, tag, or release.

Labels: **V** = verified (command output or code cited). **I** = inferred.
**U** = unknown.

Guidance from the user during this investigation: backward compatibility is
not a goal. The whole fleet will upgrade once CopyRoom reaches its final
state. Rank options by the cleanest end state. Treat old recorded
requirements as context, not as constraints.

## 1. Summary and recommendation

CopyRoom 0.8.0 deliberately replaced Copier with local Templateer sources and
jj (V). No working path from a Copier project to 0.8.x exists today. The
documented route (`templatize`, then `adopt`) cannot convert a template that
has variables (V). `adopt --write` also fails on every fleet repo, because
devman links `.agents`, `.claude`, and `devenv.local.nix` as gitignored
symlinks (V for `.agents`; I for the others). Issue #3 is a Copier check-order
defect in the old engine. 0.8.x refuses the same situation safely at
preflight (V).

**Recommendation:** go forward only. Do not revive Copier and do not cut a
0.7.8. The plan has four parts:

1. Fix one CopyRoom root cause first. CopyRoom reads the project by walking
   the filesystem with a fixed exclude list. It must read the jj tracked tree
   instead. This unblocks `adopt` on fleet repos. The change is small and can
   land alone.
2. Convert template-py and template-nix into Templateer sources with a
   one-time script. A 69-line prototype reproduced both templates byte for
   byte (V). Remove `.agents/**` from the templates, because devman owns
   `.agents`.
3. Migrate each fleet repo once. Adopt it against the converted source at the
   version that created it (v0.5.0). Then `update` to the new source. This
   keeps a true merge base, so hand edits surface as real conflicts.
4. After the fleet migrates, delete the legacy-marker refusal, the Copier
   fixtures, and `docs/copier/` from CopyRoom.

## 2. Evidence table

| # | Claim | Label | Source |
|---|---|---|---|
| E1 | Copier was removed from runtime dependencies in `df9b9d4` (2026-10-07). The commit replaces `copier>=9.15.1,<10` with `templateer==0.4.1`. | V | `git show df9b9d4 -- pyproject.toml` |
| E2 | The decision is recorded: "The tested design can cover CopyRoom's local project lifecycle without Copier." | V | `.scratch/projects/25-templateer-jj-evaluation/RESEARCH_REPORT.md:7` |
| E3 | The plan says: "Replace CopyRoom's Copier engine … Accept local template sources only." It also asks for "a clear migration path or a clear refusal". | V | `.scratch/projects/27-templateer-jj-implementation/IMPLEMENTATION_GUIDE.md:7, 321-323` |
| E4 | The only migration text is a manual recipe: templatize, review, `adopt --answers FILE --write`. | V | `docs/copier/overview.md`; `docs/user/local-workflows.md:286`; `README.md:80` |
| E5 | 0.8.x has no Copier code apart from the legacy-marker refusal. The repo has no CHANGELOG. | V | `grep -rni copier src/` finds only `cli.py:71-75, 90-94, 105-108` |
| E6 | `_project_root` and `_workshop_root` refuse with exit 1 when `.copier-answers.yml` or `.copier-answers.*.yml` exists. A `.copyroom-local.json` in the same directory wins first. | V | `src/copyroom/cli.py:64-108` |
| E7 | On 0.8.1, `update`, `status`, and `inspect` in a poddantic clone exit 1 with the legacy message. Without the answers file they exit 2 with "no local CopyRoom project marker found". `update v0.7.0` exits 3, because `update` takes no ref. | V | reproduction in `mktemp -d` |
| E8 | `adopt` needs SOURCE with `manifest.json` (exit 3 otherwise) and a JSON `--answers` file. It cannot read Copier YAML. The refusal text suggests that FILE can be the Copier file, which is misleading. | V | `cli.py:111-114`; `local/source.py:26-35` |
| E9 | template-py v0.7.0 has `copier.yml` and no `manifest.json`. `adopt` against it exits 3 with "not a local Templateer source". | V | clone of tag v0.7.0; reproduction |
| E10 | On 0.7.7, a symlinked `.agents` makes `copyroom update v0.7.0` fail: `ForbiddenPathError: ".agents/devenv" is forbidden`, then "Update failed at state: failed", exit 1, clean tree. | V | reproduction |
| E11 | Controls without a symlinked `.agents` (none, or a real directory) give 7 conflicts, not 6: `.gitignore`, `AGENTS.md`, `README.md`, `copyroom.project.yml`, `devenv.nix`, `devenv.yaml`, `pyproject.toml`. | V | reproduction |
| E12 | On 0.7.7, a conflict in `copyroom.project.yml` always makes the update report `failed`, because the post-update parse fails. | V | 0.7.7 `project/update.py:387-399` |
| E13 | Copier raises at `_main.py:838-839`, before the exclude check at `:840`. `_skip_if_exists` is checked later still (`:505`). `--exclude '.agents' --exclude '.agents/**'` still fails. | V | copier 9.19.0 source; direct `copier update` run |
| E14 | template-py v0.7.0 ships `template/.agents/devenv/**` (13 docs). It does not ship `.agents/skills/**`; that pattern appears only in `_copy_without_render`. | V | file listing of tag v0.7.0 |
| E15 | 0.8.x never writes through a symlinked `.agents` from the CLI. A source that renders `.agents/**` is refused at preflight: exit 1 "render-owned path is not tracked by jj", or exit 2 "output path collision". A source without `.agents/**` updates cleanly with the symlink in place. | V | throwaway experiment; `local/workflow.py:240-274` |
| E16 | `adopt --write` fails when the project has a gitignored `.agents` symlink: exit 1 "adoption merge did not preserve the project tree". It leaves `.jj`, `.git`, a lock file, and a baseline commit, and writes no marker. | V | throwaway experiment |
| E17 | The cause of E16: `working_files` walks the filesystem and skips only `STATE_EXCLUDES`. It ignores `.gitignore`. `adopt` compares that digest with a fresh jj workspace, which holds only tracked files. | V (code) / I (link to E16) | `local/workflow.py:51, 82-109`; `local/manage.py:160, 185-186` |
| E18 | devman links `.agents`, `.claude`, and `devenv.local.nix` into each project, and lists them in a local gitignore. | V | `~/.config/devman/projects/template-py/links.yaml`, `.local.gitignore` |
| E19 | 21 top-level repos carry `.copier-answers.yml`: 14 from template-py (all `_commit: v0.5.0`), 6 from template-nix, and pytuin (copyroom demo fixture). 20 of the 21 have `.agents` as a devman symlink; mnemonix has none. | V | file reads only |
| E20 | `_src_path` varies across the fleet: `gh:` form, SSH URL, absolute local path, and relative path. | V | file reads only |
| E21 | `copyroom templatize` does not parameterize. It freezes one render as literal artifacts. Only `--parameterize PATH` swaps the directory name for `{{ project_name }}`. | V | `local/manage.py:258-380`; run on a Copier render |
| E22 | A 69-line one-time converter (`.jinja` files become artifacts, other files become `static`, links become `symlinks`) reproduced template-py v0.7.0 (2 answer sets) and template-nix v0.3.0 (3 `module_class` values) with 0 diffs. | V | prototype in `mktemp -d`, now deleted |
| E23 | Templateer renders every listed artifact. It cannot skip a file. template-nix has 3 conditional files, so it needs a second source (a layer). | V | `local/composer.py:285-330` |
| E24 | Templateer sets `trim_blocks` and `lstrip_blocks`; Copier does not. The converter must add a newline after `%}`. | V | templateer `renderer.py:39-42`; converter diff |
| E25 | Path segments must be a whole `{{ field }}`. `test_{{ package_name }}.py` needs a computed field. | V | `local/composer.py:121-148` |
| E26 | 0.7.7 `golden --refresh` runs `shutil.copytree(generated_dir, golden_dir)` without `symlinks=True`. It stores `CLAUDE.md` as a regular file. The committed template-py goldens hold stale regular-file `CLAUDE.md` copies (mode 100644). | V | 0.7.7 `workshop/golden.py:195`; `git ls-files -s` |
| E27 | 0.8.x workshop keeps symlinks: `shutil.copytree(output, expected, symlinks=True)`. A test refresh kept `CLAUDE.md` as a link. | V | `local/workshop.py:277`; throwaway workshop |
| E28 | 0.8.x workshop has `render`, `golden`, `release-check`, `test`. It uses `goldens/`, renders the working source (not the latest tag), and ignores `copyroom.yml` `checks:`. | V | `cli.py:455-500`; `local/workshop.py` |
| E29 | On 0.8.1, `copyroom render py basic` in template-py exits 2: "source is not a local Templateer source". | V | reproduction |
| E30 | Tags v0.8.0 and v0.8.1 pin `templateer = { path = "../templateer_v2", editable = true }`. A plain git install fails. | V | `git show v0.8.1:pyproject.toml`; install attempt |
| E31 | `main` fixed this in `641d463`: `templateer = { git = "…/templateer_v2.git", tag = "v0.4.2" }`. | V | `git show main:pyproject.toml`; `uv.lock` |
| E32 | The v0.8.1 `flake.nix` already pins Templateer by git tag, so the Nix route works. | V | `git show v0.8.1:flake.nix:24` |
| E33 | RepoMan maps `copy` to CopyRoom with the description "(Copier)", invokes only `copyroom status`, and expects CopyRoom sub-skills. | V | repoman `registry.py:60-62`, `modules/managers/copyroom.nix:25`, `src/repoman/devman/check.py` |
| E34 | Only 2 tests cover the legacy refusal. Both use `inspect`. No test has a symlinked directory in a destination project. No test runs `adopt --write` through the CLI. | V | `tests/integration/test_cli.py:232`; `tests/unit/test_cli_messages.py:40`; grep |
| E35 | Repo state: only the `…+guard` bookmark is conflicted. One side, `eb6c9f7c` (15 files, not described), is not in `::main`. The origin side of `…+kickoff` (`a5440959`) is not in `main`. The `v6-copyroom` workspace is empty and has nothing that `main` lacks. Origin lacks tags v0.6.1 and v0.7.0. | V | `jj bookmark list --all`; `jj workspace list`; `git ls-remote --tags` |

Correction to the brief: the brief said 6 conflicts and that template-py ships
`.agents/skills/**`. Both are wrong (E11, E14). Hindsight memory called
`57cd43f` the Project 27 cutover. It is the Project 26 slice; `df9b9d4`
removed Copier (E1).

## 3. Root causes

### Issue #3 (0.7.x, symlinked `.agents`)

Copier resolves each destination path before it applies excludes
(`copier/_main.py:827-841`, E13). `.agents` itself passes, because Copier
resolves only the parent of a symlink. The next entry, `.agents/devenv`, is a
plain path. `resolve()` follows the link to devman's central store, outside
the destination root, so Copier raises `ForbiddenPathError`. `--exclude` and
`_skip_if_exists` are checked later, so neither helps.

The trigger is the template, not CopyRoom. template-py ships
`template/.agents/devenv/**` into a directory that devman owns (E14, E18).

### Issue #4 (0.8.x, legacy marker refusal)

The refusal is deliberate (E2, E3, E6). The defect is that the advertised exit
does not work:

1. `adopt` needs a Templateer source. template-py and template-nix have none
   (E9).
2. `templatize` freezes one render. It is not a template converter (E21).
3. The refusal text suggests that the Copier file can be FILE. FILE must be
   JSON (E8).
4. `adopt --write` fails on any project with gitignored paths outside
   `STATE_EXCLUDES`. Every devman-linked repo has such paths (E16, E17, E18).

Cause 4 is a CopyRoom architecture defect, not a migration gap. CopyRoom has
two views of a project: a filesystem walk (`working_files`) and jj's tracked
tree (`tracked_tree_digest`). They disagree whenever `.gitignore` hides a
path. The same split explains why a gitignored `.agents` symlink shows up as a
"project-only" path in collision checks (E15).

## 4. Question A — direction

- Dropping Copier was deliberate (V, E1–E3). The stated reason: Templateer
  plus jj covers the local lifecycle, and the setup is personal and
  local-only.
- The plan asked for "a clear migration path or a clear refusal". 0.8.0
  shipped the refusal and a manual recipe. It did not ship a converter or a
  fleet plan (V, E4). No document lists fleet migration as a non-goal (V by
  search of `.scratch/projects/20-29` and `docs/`).
- `adopt` is meant for a user who already has a local Templateer source and a
  JSON answers file. It attaches an existing project to that source without
  changing project files (I from code, E8). It records one layer, `base`,
  writes `.copyroom-local.json`, snapshots the source, and keeps any
  `.copier-answers.yml` as a project-only path (V by code reading).
- A compatibility mode would reverse a recorded decision. Under the user's
  guidance, that decision is context, not a veto. It still loses on merit (see
  section 6).

## 5. Question B — fixing #3

| Option | Blast radius | Makes update work? | Verdict |
|---|---|---|---|
| Pre-check in 0.7.x with a clear error | ~20 lines in 0.7.7 `project/update.py` before `execute_update` | No | Not needed. 0.8.x already refuses cleanly (E15). |
| Render into a scratch copy and merge | Large: changes the 0.7.x update model, answers, conflicts, hooks | Yes | Reject. It rebuilds what 0.8.x already does with jj. |
| Skip symlinked paths (move the link aside) | Medium, fragile on interrupt | Partly | Reject. Copier then writes a real `.agents/devenv`. |
| Honour `_skip_if_exists` | None | No. Checked after the raise (E13). | Does not work. |
| Template stops shipping `.agents/**` | Zero in CopyRoom; one template release | Yes | **Recommend.** devman already owns `.agents/devenv` centrally (E18). |

Under a forward-only policy, #3 closes by migration. The template change is
still required, because 0.8.x also refuses a source that renders `.agents/**`
into a symlinked `.agents` (E15).

## 6. Question C — convergence options

| Option | Effort | Risk | Reversibility | Each fleet repo must | Verdict |
|---|---|---|---|---|---|
| 1. Copier compatibility mode in 0.8.x | High. 0.8.x cannot render Copier templates, so this brings back a second engine. | High: two engines, two marker formats, two merge models | Low: becomes permanent surface | Nothing at first, then migrate later anyway | Reject. It contradicts the clean end state. |
| 2. Templateer sources plus `adopt` | Medium: converter (proven), hand-written schema, template-nix layer split, one CopyRoom fix | Medium: first adopt per repo; mitigated by a pilot | High: jj `op restore`; the marker is one commit | Write JSON answers, adopt, delete `.copier-answers.yml`, then update | **Recommend**, with option 4 as its driver |
| 3. 0.7.8 patch line | Small for a clear error; large for a real fix | Low | High | Pin 0.7.8, then stay on Copier | Reject. It extends a dead line, and the real fix is the template change anyway. |
| 4. One-time migration script | Small: YAML to JSON (drop `_*` keys, add secret and derived fields), adopt, remove marker | Low with dry-run first | High | Run the script once | **Recommend** as the per-repo step of option 2. Keep it outside CopyRoom so CopyRoom carries no Copier code. |
| 5. Birth-only template, hand-edit policy | None | Drift grows without bound | High | Nothing | Reject. It removes the `copy` role's purpose. |

Key design point for option 2 (I): adopt each repo against the converted
**v0.5.0** source, the version that created it. Then run `update` to the new
source. If you adopt directly at v0.7.0, every template change since v0.5.0
looks like a project edit, and later updates never deliver it. Adopting at the
creation version gives jj a true merge base. The 7 known conflicts (E11) then
surface as real conflicts.

## 7. Question D — minimal change for symlinked `.agents`

On the forward path, two changes are needed:

1. **CopyRoom:** read the project through jj's tracked view, so gitignored
   devman links are invisible to adopt digests and collision checks. Keep the
   existing refusal for render paths that exist through a link (E15). Add a
   clear message when a render path sits under a symlinked directory: "render
   path X is under symlinked directory Y; remove Y from the source". Use
   exit 1.
2. **Templates:** do not render `.agents/**`. devman owns it.

If the user wants convergence on 0.7.7 before the migration, the smallest
stopgap is a template-py v0.7.1 without `.agents/devenv/**`. It needs no
CopyRoom change (I; the controls in E11 show that the update runs). Each repo
still resolves 7 conflicts by hand, and `copyroom.project.yml` conflicts
report `failed` (E12). This work is thrown away at migration, so I do not
recommend it.

## 8. Question E — workshop

With 0.8.x as the default, template-py becomes a 0.8.x workshop (V for the
contract, E28; I for the layout):

- Put the Templateer source in a subdirectory (for example `source/`). The
  repo root has a `CLAUDE.md` symlink, and a source must contain no symlinks
  (`composer.py:79-80`).
- `copyroom.yml` gets `templates.py.source: source`. Keep `registry/` and
  `scenarios/py/{basic,probe}.yml`.
- Rename `golden/` to `goldens/` and refresh on 0.8.x. This fixes the stale
  `CLAUDE.md` goldens (E26, E27). It also drops the `devenv.local.yaml` golden
  defect: the golden's own `.gitignore` hides that file from git.
- Move the ~45 `checks:` shell lines into the generated project's
  `devenv test`. 0.8.x `release-check` runs `devenv test` per scenario and
  ignores `checks:` (E28).
- The README commands keep their names: `copyroom render py basic`,
  `copyroom golden py basic --refresh`, `copyroom release-check py`. They now
  render the working source, not the latest tag.

## 9. Question F — packaging

`main` already fixed the source (E31). The fix needs a release: cut v0.8.2
from `main`. Do not move v0.8.0 or v0.8.1, because both are on origin (E35).
After that, a plain `uv pip install "copyroom @ git+…@v0.8.2"` should resolve
Templateer from its git tag (I). pyjutsu stays a pinned wheel URL. It needs
Linux x86-64 with glibc 2.39 or later; other platforms build the sdist with
Rust 1.89 or later (V, `pyproject.toml:59-61`).

## 10. Recommended ordered plan

1. **Lane `project-view-tracked` (CopyRoom, lands alone).**
   - Make `working_files` and `working_digest` respect jj's ignore rules, or
     compare `tracked_tree_digest` in `adopt` (`manage.py:160, 185-189`).
   - Make `adopt --write` roll back what it created (`.jj`, `.git`, baseline
     commit, lock) when it fails.
   - Add the symlinked-parent refusal message.
   - Change the legacy refusal text to name the real steps: convert the
     source, write JSON answers, adopt.
   - Add the tests in section 11.
2. **Release CopyRoom v0.8.2** from `main` (needs approval).
3. **template-py:** convert v0.5.0 and the current template with the
   one-time converter. Hand-write the schema (`package_name` default,
   `test_file` computed field, `managers` list, `repoman_dev_root`). Drop
   `.agents/devenv/**` and the answers-file template. Restructure the
   workshop (section 8). Release it.
4. **template-nix:** the same, with the 3 conditional module files in a
   second source (layer). Drop `.copier-answers.my-ai.yml`.
5. **RepoMan:** update the `copy` description, the CopyRoom pin, the sub-skill
   check, and the README commands (E33).
6. **Fleet:** run the migration script repo by repo, each in a gitman
   workspace. Pilot on a throwaway clone of poddantic, then the real repo,
   then the rest.
7. **CopyRoom cleanup lane:** delete the legacy-marker refusal,
   `docs/copier/`, `tests/integration/fixtures/template/copier.yml`, and the
   stale Copier-style demo fixture.

## 11. Test plan (question G)

Today (V, E34): 2 tests cover the legacy refusal, both through `inspect`.
Symlink tests cover only symlinks inside renders (`docs/current`) and refused
source links. No test runs the CLI `adopt --write`.

Add to lane 1:

1. `adopt --write` on a project with gitignored symlinks `.agents`, `.claude`,
   and `devenv.local.nix`. It succeeds, link targets stay unchanged, and the
   marker is written.
2. A failed `adopt --write` leaves no `.jj`, `.git`, lock, or commit when it
   created them.
3. `update` preview and apply with a gitignored `.agents` symlink and a source
   without `.agents/**`. The link and its target stay unchanged (pins E15
   scenario 3).
4. A source that renders `.agents/x` and a project with a symlinked `.agents`
   (ignored and not ignored). Refuse with the new message and exit 1. Nothing
   is written through the link.
5. `working_files` with a symlinked directory: one entry, no descent.
6. Legacy refusal, parametrized over every project and workshop command, for
   both `.copier-answers.yml` and `.copier-answers.x.yml`. Exit 1 and the new
   text. No marker gives exit 2.
7. A `.copyroom-local.json` next to a leftover `.copier-answers.yml` wins
   (pins `cli.py:68-69`).
8. A CLI end-to-end test: legacy repo, then JSON answers and adopt, then
   `status` and `update` succeed.

Lane 7 deletes tests 6 and 7 with the refusal.

Fleet verification, per repo: `copyroom status` exits 0, `testee verify`
passes, and the `.agents` link target is unchanged.

## 12. Rollout plan

| Step | Who | Runs | Gate |
|---|---|---|---|
| 1 | CopyRoom agent | lane 1, `pytest`, `ruff`, `demo/walkthrough.sh` | gate green; land on `main` |
| 2 | User approves, agent runs | tag and push v0.8.2 | install check from git in `mktemp -d` |
| 3 | template-py agent | converter, schema, workshop, `release-check py` | goldens match; `devenv test` passes |
| 4 | template-nix agent | the same, plus the layer split | 3 `module_class` renders match |
| 5 | RepoMan agent | pin and text updates | RepoMan tests |
| 6 | Fleet agent | migration script: pilot clone, poddantic, then 13 template-py repos, 6 template-nix repos | per-repo checks in section 11 |
| 7 | CopyRoom agent | cleanup lane | gate green |

## 13. Decisions (2026-10-12)

- Forward only: options 2 and 4. No Copier compatibility mode, no 0.7.8.
- Lane 1 is approved. The v0.8.2 release and the changes to the templates,
  RepoMan, and the fleet are approved.
- pytuin joins template-py. It adopts at the current template version,
  because it has no real creation version.
- devman owns the agent view (`.agents`). Templates stop shipping
  `.agents/**`. The design of agent-skill ownership is still open.

## 13a. Original open questions for the user

1. Do you confirm the forward-only direction (options 2 and 4), with no
   Copier compatibility mode and no 0.7.8?
2. May the templates drop `.agents/devenv/**`, so that devman's central
   `agents/devenv` is the only copy?
3. Should Templateer's format get lighter before the conversion? Today it is
   4 files per artifact, with `schema.py` repeated in each one. The converter
   can generate the bulk, so this is not a blocker.
4. Should template-nix model conditional files as a second layer (works
   today), or should Templateer gain optional outputs?
5. Is pytuin (answers from the CopyRoom demo fixture) in scope?
6. Repo state (not touched): the conflicted `…+guard` bookmark has an
   undescribed side `eb6c9f7c` that `main` lacks, and the origin side of
   `…+kickoff` differs. Do you want those reviewed or abandoned? The
   `v6-copyroom` workspace is empty and safe to forget.

## 14. Files created outside the repo

| Agent | Created | Removed |
|---|---|---|
| Reproduction of #3/#4 | `/tmp/tmp.Rs7GNZ371k/` (clones, venvs v077/v081, logs, scripts), `/tmp/copyroom_repro_T.txt` | yes, `ls -d` reports "No such file or directory" |
| Workshop and fleet | `/tmp/tmp.d33xfGbiNi/` (template-py clone, venvs, workshop copies), `/tmp/.t_path_ste` | yes, confirmed |
| `.agents` experiment on `main` | `/tmp/tmp.xsUcFtLlm1/` (sources S1–S6, projects, previews, targets), `/tmp/exp_T_path` | yes, confirmed |
| Converter and templatize | `/tmp/tmp.uZtG3IaRBA/` (clones, Copier venv, renders, converted sources), `/tmp/T_path` | yes, confirmed |
| All agents running uv | entries in the shared cache `~/.cache/uv` | no; the cache is shared and safe to keep |
| Orchestrator | memory file `~/.claude/projects/-home-andrew-Documents-Projects-copyroom/memory/prefer-clean-architecture-over-legacy.md` | kept on purpose; it records your guidance |

No agent ran CopyRoom, Copier, or `rsync` in a real checkout under
`/home/andrew/Documents/Projects/`. Agents read only `.git/config` and
answers files there. `git status` in CopyRoom is clean apart from this
directory.
