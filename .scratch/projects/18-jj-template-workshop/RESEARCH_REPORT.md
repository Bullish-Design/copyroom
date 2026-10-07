# Local jj template workshop spike

Date: 2026-10-07

## Question

Can a local workshop edit a template and preview a project update while the active template and project stay unchanged?

## Method

Run [spike.py](spike.py) with the pinned spike 12 environment:

```bash
cd .scratch/projects/12-jj-render-merge
devenv shell -- bash -c 'export PATH="$DEVENV_PROFILE/bin"; python3 ../18-jj-template-workshop/spike.py'
```

The script creates two disposable colocated jj repositories. It never runs jj in the active CopyRoom repository. The template repo contains `files/`, which keeps jj metadata outside the render source. The project starts from prototype 13's `new` command. The script makes a project edit to a template-owned file. It then adds a separate template candidate workspace and a separate project preview workspace.

[evidence.json](evidence.json) records all commands, exit codes, checks, and the golden manifest. The command returned zero with 19 passing checks. Ruff passed on the script.

## Findings

1. The candidate workspace changed `version=1` to `version=2` and added `checks/ready.txt`. The active template revision and files stayed equal to their baseline values.
2. Prototype 13 rendered the candidate template with saved scenario answers. The entire rendered tree matched [the golden tree](fixtures/golden/). The check compared every path, file hash, and executable bit.
3. Prototype 13's `update` ran in the project preview workspace. The preview received the template change and added file. It also kept the project's `owner=project` edit to the template-owned file. `jj diff --from <project revision> --to @` showed the update.
4. The active project revision and files stayed unchanged through render, update-test, preview, and preview cleanup. The active template files also stayed unchanged.
5. Explicitly selecting the candidate revision in the active template workspace changed the template files. A later explicit project `update` applied the same result as preview and kept the local edit.

## Design consequence

A local workshop can use one candidate template workspace and one project preview workspace. A scenario stores answers and a full-tree golden result. The workshop checks the candidate render against golden, runs project checks in the preview workspace, and shows `jj diff --from <active project revision> --to @`. Applying the candidate to the active template and project remains a separate command.

## Limits

This spike uses prototype 13's small deterministic renderer. It does not test a real Templateer artifact in the workshop loop. It checks file content and executable bits, not symlinks or ownership. It runs one scenario and one project edit. It does not run a candidate project's `devenv test`, exercise conflicts, or test concurrent workspace changes. The separate [workspace spike](../15-jj-workspace/RESEARCH_REPORT.md) covers preview conflicts and controlled failure recovery.
