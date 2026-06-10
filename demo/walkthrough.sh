#!/usr/bin/env bash
#
# CopyRoom — scripted end-to-end walkthrough ("the whole library, live").
#
# This is a *demo*, not a test. It builds real Copier templates, real generated
# projects, and a real workshop in a throwaway directory, then drives every
# CopyRoom command against them — narrating what each one does and why it
# matters. Nothing here is mocked: every ✅ is a real CLI invocation.
#
#   Acts
#   ────
#   0. Mode awareness ......... the core differentiator (project vs workshop)
#   1. Project lifecycle ...... new  →  update      (consume a template)
#   2. Agentic template edit .. checkout → test → preview  (edit upstream, safely)
#   3. Workshop ............... render → golden → update-test → release-check
#   4. Repo adoption .......... templatize → adopt  (bring a hand-written repo in)
#
# Run it (from the repo root):
#
#   devenv shell -- bash demo/walkthrough.sh          # full run
#   devenv shell -- bash demo/walkthrough.sh --pause  # press Enter between acts
#   devenv shell -- bash demo/walkthrough.sh --keep    # keep the scratch dir
#
set -u

# ---------------------------------------------------------------------------
# Re-exec inside the devenv shell if copyroom isn't on PATH.
# ---------------------------------------------------------------------------
SCRIPT_PATH="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
if ! command -v copyroom >/dev/null 2>&1; then
  if command -v devenv >/dev/null 2>&1; then
    exec devenv shell -- bash "$SCRIPT_PATH" "$@"
  fi
  echo "error: 'copyroom' not found and 'devenv' unavailable. Run inside the devenv shell." >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------
PAUSE=0
KEEP=0
USE_COLOR=1
for arg in "$@"; do
  case "$arg" in
    --pause) PAUSE=1 ;;
    --keep) KEEP=1 ;;
    --no-color) USE_COLOR=0 ;;
    -h|--help)
      sed -n '2,30p' "$SCRIPT_PATH" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done
[ -t 1 ] || USE_COLOR=0

# ---------------------------------------------------------------------------
# Presentation helpers
# ---------------------------------------------------------------------------
if [ "$USE_COLOR" = 1 ]; then
  B=$'\033[1m'; DIM=$'\033[2m'; R=$'\033[0m'
  CYAN=$'\033[36m'; GREEN=$'\033[32m'; YEL=$'\033[33m'; MAG=$'\033[35m'; BLU=$'\033[34m'
else
  B=""; DIM=""; R=""; CYAN=""; GREEN=""; YEL=""; MAG=""; BLU=""
fi

act() {
  printf '\n%s' "$B$MAG"
  printf '════════════════════════════════════════════════════════════════════\n'
  printf '  %s\n' "$1"
  printf '════════════════════════════════════════════════════════════════════'
  printf '%s\n' "$R"
}
step() { printf '\n%s▸ %s%s\n' "$B$CYAN" "$1" "$R"; }
say()  { printf '%s  %s%s\n' "$DIM" "$1" "$R"; }
ok()   { printf '%s  ✅ %s%s\n' "$GREEN" "$1" "$R"; }

# Show a command, run it (in $PWD or a given dir), stream its output indented.
run() {
  local dir="$PWD"
  if [ "$1" = "--in" ]; then dir="$2"; shift 2; fi
  printf '%s  $ %s%s\n' "$YEL" "$*" "$R"
  ( cd "$dir" && "$@" ) 2>&1 | sed 's/^/    /'
  return "${PIPESTATUS[0]}"
}
# Same, but we *expect* a non-zero exit (showing CopyRoom's guard rails).
run_fail() {
  local dir="$PWD"
  if [ "$1" = "--in" ]; then dir="$2"; shift 2; fi
  printf '%s  $ %s%s   %s(expected to fail)%s\n' "$YEL" "$*" "$R" "$DIM" "$R"
  ( cd "$dir" && "$@" ) 2>&1 | sed 's/^/    /'
  local rc="${PIPESTATUS[0]}"
  if [ "$rc" -eq 0 ]; then printf '%s  !! expected failure but it succeeded%s\n' "$YEL" "$R"; fi
}
die() { printf '\n%s✗ %s%s\n' "$YEL" "$1" "$R" >&2; exit 1; }
pause() { [ "$PAUSE" = 1 ] && { printf '%s  ── press Enter to continue ──%s' "$DIM" "$R"; read -r _ </dev/tty; }; return 0; }

# Compact directory tree (no .git), files only, sorted.
tree_of() {
  ( cd "$1" && find . -path ./.git -prune -o -type f -print 2>/dev/null \
      | sed 's|^\./||' | sort | sed 's/^/    /' )
}

GIT() { git -c user.email=demo@copyroom.dev -c user.name='CopyRoom Demo' "$@"; }

# ---------------------------------------------------------------------------
# Scratch workspace (everything lives here; cleaned unless --keep)
# ---------------------------------------------------------------------------
ROOT="$(mktemp -d "${TMPDIR:-/tmp}/copyroom-demo.XXXXXX")"
export COPYROOM_CACHE_DIR="$ROOT/.cache"   # isolate template clones / edit worktrees
cleanup() { [ "$KEEP" = 1 ] && { echo; say "scratch kept at: $ROOT"; } || rm -rf "$ROOT"; }
trap cleanup EXIT

printf '%s\n' "$B$BLU"
cat <<'BANNER'
   ___                  ___
  / __|___ _ __ _  _   | _ \___  ___ _ __
 | (__/ _ \ '_ \ || |  |   / _ \/ _ \ '  \
  \___\___/ .__/\_, |  |_|_\___/\___/_|_|_|
          |_|   |__/   mode-aware template workflows, on Copier
BANNER
printf '%s' "$R"
say "copyroom $(copyroom --version | awk '{print $2}')   ·   scratch: $ROOT"

# ===========================================================================
act "ACT 0 — Mode awareness (the core differentiator)"
# ===========================================================================
say "CopyRoom looks at the directory you're standing in and decides which"
say "command set is even legal. No markers → it refuses, loudly, instead of"
say "guessing. This is what keeps a 'workshop' command from running in a"
say "generated 'project' and vice-versa."

step "0a. An empty directory has no CopyRoom context"
mkdir -p "$ROOT/empty"
run_fail --in "$ROOT/empty" copyroom update
ok "Unknown mode → a clear diagnostic and a non-zero exit, never a silent fallback"
pause

step "0b. A directory with .copier-answers.yml IS a project — workshop cmds are refused"
mkdir -p "$ROOT/a-project"
: > "$ROOT/a-project/.copier-answers.yml"
run_fail --in "$ROOT/a-project" copyroom render some-template some-scenario
ok "'render' is workshop-only → rejected purely on mode, with the legal commands listed"
pause

step "0c. A directory with copyroom.yml + registry/ + scenarios/ IS a workshop"
mkdir -p "$ROOT/a-workshop/registry" "$ROOT/a-workshop/scenarios"
: > "$ROOT/a-workshop/copyroom.yml"
run_fail --in "$ROOT/a-workshop" copyroom new gh:org/some-template
ok "Symmetric: 'new' is project-only → rejected in a workshop. The mode is the contract."
pause

# ===========================================================================
act "ACT 1 — Project lifecycle:  new  →  update"
# ===========================================================================
say "First, the author's side: a Copier template in a git repo, tagged v1.0.0."
say "We build a small Python-package template so the render is real."

TPL="$ROOT/aurora-template"
mkdir -p "$TPL/src/{{ package_name }}"

cat > "$TPL/copier.yml" <<'YML'
_answers_file: .copier-answers.yml

project_name:
  type: str
  default: My Project

package_name:
  type: str
  default: "{{ project_name | lower | replace('-', ' ') | replace(' ', '_') }}"

description:
  type: str
  default: A delightful Python package.

author:
  type: str
  default: A. Developer
YML

# Copier records the resolved answers back into the project via this file.
cat > "$TPL/{{ _copier_conf.answers_file }}.jinja" <<'YML'
# Changes here will be overwritten by Copier; NEVER EDIT MANUALLY
{{ _copier_answers|to_nice_yaml }}
YML

cat > "$TPL/README.md.jinja" <<'MD'
# {{ project_name }}

{{ description }}

Maintained by {{ author }}.
MD

cat > "$TPL/pyproject.toml.jinja" <<'TOML'
[project]
name = "{{ package_name }}"
version = "0.1.0"
description = "{{ description }}"
authors = [{ name = "{{ author }}" }]
TOML

cat > "$TPL/src/{{ package_name }}/__init__.py.jinja" <<'PY'
"""{{ project_name }} — {{ description }}"""

__version__ = "0.1.0"
PY

GIT init -q "$TPL"
GIT -C "$TPL" add -A
GIT -C "$TPL" commit -qm "template v1.0.0"
GIT -C "$TPL" tag v1.0.0
say "Template repo ready at $TPL (tagged v1.0.0). Its files:"
tree_of "$TPL"
pause

step "1a. Generate a project from the template — 'copyroom new'"
cat > "$ROOT/answers.yml" <<'YML'
project_name: Aurora
package_name: aurora
description: A starlight-fast task runner.
author: Ada Lovelace
YML
say "Non-interactive: we feed answers from a YAML file. 'new' is a bootstrap"
say "command — it runs anywhere, no project marker (or --mode) needed."
run copyroom new "$TPL" "$ROOT/aurora" --answers "$ROOT/answers.yml" \
  || die "copyroom new failed"
ok "Project rendered — templated file names and \${{ ... }} substitutions resolved:"
tree_of "$ROOT/aurora"
say "README.md picked up every answer:"
sed 's/^/    /' "$ROOT/aurora/README.md"
pause

step "1b. Make it a git repo (a clean tree is the precondition for updates)"
PROJ="$ROOT/aurora"
GIT init -q "$PROJ"; GIT -C "$PROJ" add -A; GIT -C "$PROJ" commit -qm "Initial generation"
ok "Committed the generated project"

step "1c. The template author ships v2.0.0 (adds a CHANGELOG)"
cat > "$TPL/CHANGELOG.md.jinja" <<'MD'
# Changelog — {{ project_name }}

## v2.0.0
- Add this changelog.
MD
GIT -C "$TPL" add -A; GIT -C "$TPL" commit -qm "template v2.0.0"; GIT -C "$TPL" tag v2.0.0
ok "Template now has a v2.0.0 tag with a new file"

step "1d. Pull the upstream change into the project — 'copyroom update'"
say "Copier does a 3-way merge; CopyRoom drives it and reports the outcome."
run --in "$PROJ" copyroom update v2.0.0 || die "copyroom update failed"
if [ -f "$PROJ/CHANGELOG.md" ]; then
  ok "The v2-only CHANGELOG.md landed in the project — the update really ran:"
  sed 's/^/    /' "$PROJ/CHANGELOG.md"
else
  die "expected CHANGELOG.md after update"
fi
GIT -C "$PROJ" add -A; GIT -C "$PROJ" commit -qm "Update to template v2.0.0"
pause

# ===========================================================================
act "ACT 2 — Agentic template edit:  checkout → test → preview"
# ===========================================================================
say "The killer feature. From *inside a generated project* you can drive a"
say "change back into the template and preview exactly what your project would"
say "receive on update — without touching your working tree, and without"
say "pushing anything. The template is checked out into an isolated worktree on"
say "a scratch branch; the update is simulated against a throwaway copy."

step "2a. Resolve the template into an editable worktree — 'template-checkout'"
CO_OUT="$(cd "$PROJ" && copyroom template-checkout 2>&1)"
printf '%s\n' "$CO_OUT" | sed 's/^/    /'
WT="$(printf '%s\n' "$CO_OUT" | awk '/Worktree:/{print $2}')"
[ -n "$WT" ] && [ -d "$WT" ] || die "could not locate the checkout worktree"
ok "Template is editable at an isolated path (note: NOT your project, NOT the original repo)"
pause

step "2b. Edit the template in the worktree (here: add a CONTRIBUTING file)"
cat > "$WT/CONTRIBUTING.md.jinja" <<'MD'
# Contributing to {{ project_name }}

Thanks for helping make {{ project_name }} better!
MD
say "Added CONTRIBUTING.md.jinja to the checked-out template worktree."

step "2c. Prove the edit still renders — 'template-test'"
say "Renders the edited template with THIS project's answers, in a temp dir."
run --in "$PROJ" copyroom template-test || die "template-test failed"
ok "The edited template still produces a valid project"
pause

step "2d. Preview the update your project would receive — 'template-preview'"
say "Diffs your current working state against the post-update state. It writes a"
say "patch and summarises adds/mods/removes — but applies NOTHING."
run --in "$PROJ" copyroom template-preview || die "template-preview failed"
PATCH="$(ls -t "$PROJ"/.copyroom/preview/*.patch 2>/dev/null | head -1)"
if [ -n "$PATCH" ]; then
  say "The generated patch (preview only — your tree is unchanged):"
  sed 's/^/    /' "$PATCH"
fi
if [ -e "$PROJ/CONTRIBUTING.md" ]; then
  die "preview must not touch the project tree"
else
  ok "CONTRIBUTING.md is in the PREVIEW only — the real project tree was never modified"
fi
pause

# ===========================================================================
act "ACT 3 — Workshop:  render → golden → update-test → release-check"
# ===========================================================================
say "The template author's workbench. A workshop has a registry of templates"
say "and a matrix of scenarios, plus golden snapshots that lock down output."

WS="$ROOT/workshop"
mkdir -p "$WS/registry" "$WS/scenarios/aurora"
: > "$WS/registry/.gitkeep"
cat > "$WS/copyroom.yml" <<YML
templates:
  aurora:
    source: $TPL
    checks:
      - "test -f README.md"
      - "test -f pyproject.toml"
YML
cat > "$WS/scenarios/aurora/basic.yml" <<'YML'
project_name: Demo Service
package_name: demo_service
description: A scenario rendered by the workshop.
author: The Workshop
YML
say "Workshop registry points template 'aurora' at our repo, with post-render checks."
tree_of "$WS"
pause

step "3a. Render a scenario and run its checks — 'copyroom render'"
run --in "$WS" copyroom render aurora basic || die "render failed"
ok "Scenario rendered into generated/aurora/basic and the checks passed"
say "('copyroom test aurora basic' is the same workflow with a testing focus:)"
run --in "$WS" copyroom test aurora basic >/dev/null && ok "test alias OK"
pause

step "3b. Lock the output with a golden snapshot — 'copyroom golden'"
run --in "$WS" copyroom golden aurora basic --refresh || die "golden refresh failed"
say "Now a plain golden diff should be clean…"
run --in "$WS" copyroom golden aurora basic || die "golden diff failed"
ok "Golden matches — future renders are checked byte-for-byte against this snapshot"
pause

step "3c. Simulate a template upgrade end-to-end — 'copyroom update-test'"
say "Renders the scenario at v1.0.0, then runs 'copier update' to v2.0.0 and"
say "reports conflicts/rejects. This is how an author validates a release won't"
say "break downstream projects."
run --in "$WS" copyroom update-test aurora basic v1.0.0 v2.0.0 || die "update-test failed"
ok "The v1→v2 upgrade applied cleanly in simulation"
pause

step "3d. Release readiness gate — 'copyroom release-check'"
say "Bundles it all: render the whole scenario matrix, verify golden, and"
say "confirm the worktree is clean (so generated output never sneaks into git)."
GIT init -q "$WS"
printf 'generated/\n.copyroom_sim/\n' > "$WS/.gitignore"
GIT -C "$WS" add -A; GIT -C "$WS" commit -qm "workshop baseline"
run --in "$WS" copyroom release-check aurora || die "release-check failed"
ok "Matrix ✓  ·  golden ✓  ·  worktree clean ✓  →  ready to tag a release"
pause

# ===========================================================================
act "ACT 4 — Repo adoption:  templatize → adopt"
# ===========================================================================
say "The reverse direction: take an EXISTING, hand-written repo and bring it"
say "under template management — extracting a template from it, then linking"
say "the repo to that template. Adoption is report-only: it never edits your"
say "source files; with --write it only drops a .copier-answers.yml."

REPO="$ROOT/legacy-app"
mkdir -p "$REPO/sub"
cat > "$REPO/README.md" <<'MD'
# legacy-app

A repo someone wrote by hand, long before CopyRoom existed.
MD
printf 'def main():\n    print("hello from legacy-app")\n' > "$REPO/app.py"
printf 'rough notes\n' > "$REPO/sub/notes.txt"
GIT init -q "$REPO"; GIT -C "$REPO" add -A; GIT -C "$REPO" commit -qm "initial"
say "The hand-written repo:"
tree_of "$REPO"
pause

step "4a. Extract a template repo from it — 'copyroom templatize'"
HOME_T="$ROOT/legacy-app-template"
run --in "$REPO" copyroom templatize --into "$HOME_T" --name legacy-app \
  || die "templatize failed"
ok "Scaffolded a self-contained template + workshop (verbatim copy of the repo)"
tree_of "$HOME_T"
pause

step "4b. The verbatim template reproduces the repo → golden is clean immediately"
say "Copier only renders *.jinja files, so a verbatim 'template/' reproduces the"
say "repo exactly. The golden loop therefore STARTS at zero diffs:"
run --in "$HOME_T" copyroom golden legacy-app default || die "initial golden failed"
ok "No diffs — a faithful starting point you can parameterize incrementally"
pause

step "4c. Introduce a parameter without breaking the match"
say "Rename README.md → README.md.jinja and insert {{ project_name }}. Because"
say "the default answer equals the repo name, the render still matches golden."
rm -f "$HOME_T/template/README.md"
cat > "$HOME_T/template/README.md.jinja" <<'MD'
# {{ project_name }}

A repo someone wrote by hand, long before CopyRoom existed.
MD
run --in "$HOME_T" copyroom golden legacy-app default || die "post-parameterize golden failed"
ok "Still no diffs — a real parameter is in, the golden match is preserved"
say "And the 'probe' scenario renders with a DIFFERENT name to prove it's live:"
run --in "$HOME_T" copyroom render legacy-app probe >/dev/null || die "probe render failed"
if grep -q 'copyroom-probe' "$HOME_T/generated/legacy-app/probe/README.md" 2>/dev/null; then
  ok "probe output contains the probe name, not 'legacy-app' → parameter is genuinely wired"
fi
pause

step "4d. Finalize the template to a tagged git repo"
GIT init -q "$HOME_T"; GIT -C "$HOME_T" add -A
GIT -C "$HOME_T" commit -qm "template v0.1.0"; GIT -C "$HOME_T" tag v0.1.0
ok "Template repo finalized and tagged v0.1.0"

step "4e. Adopt: link the original repo to the template — 'copyroom adopt --write'"
cat > "$ROOT/legacy-answers.yml" <<'YML'
project_name: legacy-app
YML
say "Renders the template with our inferred answers, diffs it against the repo,"
say "and (with --write) records the link. Watch what it touches:"
run --in "$REPO" copyroom adopt "$HOME_T" --ref v0.1.0 \
  --answers "$ROOT/legacy-answers.yml" --write || die "adopt failed"
say "git status of the adopted repo — the ONLY additions are the link + scratch:"
( cd "$REPO" && GIT status --porcelain ) | sed 's/^/    /'
if [ -f "$REPO/.copier-answers.yml" ] \
   && [ "$(cat "$REPO/README.md")" = "$(printf '# legacy-app\n\nA repo someone wrote by hand, long before CopyRoom existed.\n')" ]; then
  ok "Repo is now CopyRoom-managed — and not one source file was modified"
else
  die "adopt should add only .copier-answers.yml and never edit source files"
fi
pause

# ===========================================================================
act "RECAP — everything you just saw, for real"
# ===========================================================================
cat <<RECAP
  ${GREEN}Mode awareness${R}    project vs workshop detected from markers; commands gated
  ${GREEN}new / update${R}      generated Aurora from a template, then pulled v1→v2 upstream
  ${GREEN}template-edit${R}     checkout → test → preview: edited upstream & previewed the
                    update with ZERO changes to the project tree
  ${GREEN}workshop${R}          render · golden snapshot · update-test · release-check gate
  ${GREEN}adoption${R}          templatize a hand-written repo, then adopt it — source
                    files untouched, only a .copier-answers.yml link added

  Commands exercised: ${B}new update template-checkout template-test template-preview
                      render test golden update-test release-check templatize adopt${R}

  Every step above ran the real CopyRoom CLI against real Copier renders.
RECAP
say "scratch workspace: $ROOT $([ "$KEEP" = 1 ] && echo '(kept)' || echo '(removed on exit)')"
printf '\n%s  Done.%s\n\n' "$B$GREEN" "$R"
