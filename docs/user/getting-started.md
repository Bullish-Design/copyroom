# Getting Started

This page gets CopyRoom installed and walks you through the core loop: generate a
project, update it, and see the agentic template-edit flow. For the *why* behind
any of it, read [concepts](concepts.md); for exhaustive flags, see the
[CLI reference](cli-reference.md).

---

## 1. Requirements

- **Python ≥ 3.13**
- **git** on your `PATH` (CopyRoom and Copier both shell out to it)
- **Copier ≥ 9.15.1, < 10** (installed automatically as a dependency)

CopyRoom pins Python 3.13. In this repository the supported way to run it is
through the devenv shell, which pins the toolchain for you.

## 2. Install

### In this repository (development)

```bash
devenv shell      # enters the pinned environment; puts `copyroom` on PATH
uv sync           # install dependencies
copyroom --help
```

Every CopyRoom command in this repo should be run inside `devenv shell` (or
prefixed `devenv shell -- …`) so it uses the pinned Python 3.13.

### As a tool elsewhere (uv)

CopyRoom is a standard `uv`-installable Python package (entry point
`copyroom = "copyroom.cli:main"`):

```bash
uv tool install copyroom        # once published
# or, from a checkout:
uv tool install /path/to/copyroom
copyroom --version              # → copyroom 0.3.0
```

### As a devenv module

Any devenv-managed project can pull the CLI onto its `PATH` by importing the
module this repo ships (`modules/copyroom.nix`):

```yaml
# devenv.yaml
inputs:
  copyroom:
    url: github:Bullish-Design/copyroom?ref=v0.1.0
    flake: false
imports:
  - copyroom
```

Set `copyroom.enable = false` to opt out, or override `copyroom.package` to
supply your own build.

## 3. Verify

```bash
copyroom --version     # copyroom 0.3.0
copyroom --help        # the full command list, grouped by mode
```

Run `copyroom` in an empty directory and it will tell you it found no mode — that
is the expected, designed behavior (see [concepts](concepts.md)).

---

## 4. The 60-second tour

### Create a project from a template

`new` needs an empty target. Because an empty dir has no markers, force the mode:

```bash
copyroom --mode project new gh:org/python-cli-template ./my-cli \
  --answers answers.yml
```

- `gh:org/python-cli-template` — the template source (any Copier source works:
  `gh:`/`gl:` shorthand, a full git URL, or a local path).
- `./my-cli` — the (empty or non-existent) target directory.
- `--answers answers.yml` — supply answers non-interactively (optional).

CopyRoom renders the template, records `.copier-answers.yml`, and prints next
steps. Then make it a git repo:

```bash
cd my-cli
git init && git add -A && git commit -m "Initial generation"
```

### Update the project when the template ships a new version

```bash
copyroom update v2.0.0          # pull template changes for tag v2.0.0
```

CopyRoom checks the worktree is clean, runs `copier update` (a three-way merge),
and reports added/modified/removed files plus any conflicts. Review with
`git diff`, then commit.

> Pass `--branch` to do the update on an isolation branch
> (`template-update/<template>-<ref>`) instead of the current one.

### Preview a template change *from inside your project* (agentic)

This is CopyRoom's signature loop. From inside the generated project:

```bash
copyroom template-checkout          # template → editable worktree on a scratch branch
# …edit the template files at the printed worktree path…
copyroom template-test              # confirm the edit still renders with your answers
copyroom template-preview           # diff: what your project would receive — nothing applied
```

`template-preview` writes a patch to `.copyroom/preview/<timestamp>.patch` and
summarizes the changes. **Your working tree is never touched.** Once the template
change is committed and tagged upstream, pull it in with `copyroom update <ref>`.
Full walkthrough: [editing a template from a project](template-editing.md).

---

## 5. The other two arcs

- **Authoring & releasing templates** — the [workshop](workshop.md):
  `render` a scenario, lock it with `golden`, simulate an upgrade with
  `update-test`, gate a release with `release-check`.
- **Bringing an existing repo under management** — [adoption](adoption.md):
  `templatize` extracts a template from a hand-written repo; `adopt` links a repo
  to a template and reports drift (report-only).

---

## 6. See everything at once

The repo's scripted demo runs **every** command against real templates,
projects, and a workshop in a throwaway directory:

```bash
devenv shell -- bash demo/walkthrough.sh          # full run
devenv shell -- bash demo/walkthrough.sh --pause  # step through it
devenv shell -- bash demo/walkthrough.sh --keep   # keep the scratch dir to poke at
```

It is the fastest way to build an intuition for the whole tool.

## Next steps

- [Concepts](concepts.md) — modes, markers, the safety model.
- [CLI reference](cli-reference.md) — every command and flag.
- [Configuration](configuration.md) — the three config files.
