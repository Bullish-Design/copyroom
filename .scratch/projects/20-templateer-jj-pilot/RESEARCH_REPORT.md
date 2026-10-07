# Templateer and plain jj pilot — 2026-10-07

## Result

The local pilot passed **49 checks**. Templateer rendered five files from one saved model. Plain jj recorded T0, a project edit, and T1. A separate workspace showed the merge before the active project changed. An explicit apply produced the same file bytes and modes as the clean preview. Templateer validated the merged preview and applied tree.

A separate case changed the same README line in the project and template. `jj resolve --list` named `README.md`, and the preview file held both edits. The active project stayed byte-for-byte unchanged through that preview. The pilot did not apply that conflict.

## Environment and exact command

- Templateer 0.4.1, Python 3.13.14, jj 0.45.1.
- Python and Templateer came from `/home/andrew/Documents/Projects/templateer_v2` under its devenv shell.
- jj came from Spike 12's pinned profile. Its resolved binary was `/nix/store/hy1qgl7m2ryhqx66h4ad2h04i-jujutsu-0.45.1/bin/jj`.
- [jj.toml](jj.toml) fixed the pilot identity and output settings. The pilot used `JJ_CONFIG` to avoid the user's jj settings.
- [source-hashes.txt](evidence/2026-10-07/source-hashes.txt) records the pilot script, tree composer, manifest, answers, and jj config hashes. Spike 14 records the Templateer source hashes.

From `/home/andrew/Documents/Projects/templateer_v2`:

```bash
SECRETSPEC_REASON='Run local Templateer and jj integration spike' MYPI_AGENT_ROOT=.agents/pi JJ_BIN=/home/andrew/Documents/Projects/copyroom/.scratch/projects/12-jj-render-merge/.devenv/profile/bin/jj JJ_CONFIG=/home/andrew/Documents/Projects/copyroom/.scratch/projects/20-templateer-jj-pilot/jj.toml PYTHONDONTWRITEBYTECODE=1 devenv shell -- uv run python /home/andrew/Documents/Projects/copyroom/.scratch/projects/20-templateer-jj-pilot/pilot.py
SECRETSPEC_REASON='Run local Templateer and jj integration spike' MYPI_AGENT_ROOT=.agents/pi devenv shell -- uv run ruff check /home/andrew/Documents/Projects/copyroom/.scratch/projects/20-templateer-jj-pilot/pilot.py
```

The first command returned zero with 49 passing checks. Ruff returned zero. See [run-final.txt](evidence/2026-10-07/run-final.txt), [ruff-final.txt](evidence/2026-10-07/ruff-final.txt), and the full [jj-transcript.txt](evidence/2026-10-07/jj-transcript.txt). Devenv printed unrelated mypi-agent setup warnings. No model request ran.

## The tested lifecycle

1. The pilot copied the local Templateer fixtures into disposable v1 and v2 source directories. It rendered v1 into a new jj project and committed that tree as T0.
2. The project changed the `pyproject.toml` version and added `notes.txt`. It saved metadata in `.copyroom-pilot.json` and committed the project edit as P0.
3. The pilot created a named jj workspace at T0. It cleared that workspace's generated files, rendered v2, and committed T1. It verified `merge-base(P0, T1) = T0`.
4. The pilot created a merge of P0 and T1 in the separate workspace. It used `jj diff --from P0 --to @` for preview. The active project's `@`, file bytes, and modes stayed unchanged.
5. For the clean case, the pilot checked merged content and Templateer validators. It then ran `jj new P0 T1` in the active project. The active files matched the preview exactly. It saved the v2 source digest and Templateer version in a new marker commit.
6. The pilot forgot and removed the preview workspace. The clean applied tree remained in the active project.

The [clean preview](evidence/2026-10-07/snapshots/clean-preview), [clean applied tree](evidence/2026-10-07/snapshots/clean-applied), and [conflict preview](evidence/2026-10-07/snapshots/conflict-preview) preserve file bytes and modes. The applied `scripts/about.py` is `0755`; the applied `pyproject.toml` is `0644`. The applied tree retains the project's version `0.1.1` and receives the template's `classifiers` field and YAML revision.

## Source identity

The project marker records a local source path, source content digest, manifest digest, answers digest, tree composer digest, and Templateer version. The source digest changed from `d33b0f178f3ad76dbbbf6d4a6d05c55fee9db9fd0eaae39b132a8ec2946f07e0` at v1 to `0793cfcf7cc28bc4f8d0d6116430faed0736b4e4be13fd58c371f536aa02bd77` at v2. These values are in the saved preview and applied markers.

The digest identifies source bytes but does not retrieve them. This pilot used temporary local paths, which disappeared after the run. A real project needs a stable local source path or a source snapshot. The render commits preserve the prior rendered bytes independently.

## Findings from failed runs

- The first run could not write into the jj project with Spike 14's `write_tree()` because `.jj` made the directory nonempty. The pilot now renders into a temporary directory and copies only the output files into the jj workspace.
- The first clean-case fixture added local and template lines at the same end of `pyproject.toml`. jj reported a real conflict. The final clean case changes an existing version line while the template adds a field elsewhere. The separate README case preserves the overlapping-edit test.
- On jj 0.45.1, `jj resolve --list` returns exit code **2** with `No conflicts found at this revision` for a clean tree. The pilot treats that exact result as an empty conflict list. It raises on other nonzero results. The full transcript contains both clean and conflicted calls.

## Limits

- The pilot covers one update, one clean merge, and one conflict. Spike 12 covers repeated updates. This pilot does not prove a later update with Templateer after the first apply.
- The source content digest excludes Python bytecode cache files. The test ran with `PYTHONDONTWRITEBYTECODE=1`. A production source snapshot needs an explicit file set.
- The experiment deletes disposable jj repos after saving file snapshots and a command transcript. It does not prove crash recovery, concurrent workspace edits, or relocation.
- The fixture schema and validators are local code. This spike assumes trusted local templates. The model generation path did not run.
- Templateer validation ran after the clean merge. A conflicted file cannot pass its normal artifact validator until the user resolves it.
