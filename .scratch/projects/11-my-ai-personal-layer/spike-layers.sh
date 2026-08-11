#!/usr/bin/env bash
# SPIKE — can a second Copier template layer onto a repo that already has one?
#
# Question set (project 11, the personal layer):
#   Q1  Does `copier copy -a .copier-answers.my-ai.yml` write ONLY that answers
#       file, leaving the base layer's `.copier-answers.yml` untouched?
#   Q2  Does `_answers_file:` in the template's copier.yml set that default, so
#       the flag is belt-and-braces rather than load-bearing?
#   Q3  Does `copier update -a <layer answers>` update ONLY the overlay layer?
#   Q4  Does `_skip_if_exists: [AGENTS.md]` protect a repo-owned AGENTS.md on
#       BOTH copy and update?
#   Q5  Does `_preserve_symlinks: true` keep CLAUDE.md a symlink through both?
#
# Run:  devenv shell -- bash .scratch/projects/11-my-ai-personal-layer/spike-layers.sh
set -euo pipefail

WORK="$(mktemp -d -t copyroom-spike-layers-XXXXXX)"
trap 'echo; echo "spike workdir: $WORK  (kept for inspection)"' EXIT
copier() { uv run --quiet copier "$@"; }
say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok()  { printf '  \033[32mPASS\033[0m %s\n' "$*"; }
bad() { printf '  \033[31mFAIL\033[0m %s\n' "$*"; FAILED=1; }
FAILED=0

git_init() { git -C "$1" init -q -b main; git -C "$1" add -A; git -C "$1" -c user.email=s@s -c user.name=s commit -qm "$2"; }
tag()      { git -C "$1" -c user.email=s@s -c user.name=s tag "$2"; }

# --------------------------------------------------------------------------- #
say "build the BASE template (stands in for template-py, the genome)"
BASE="$WORK/base-template"
mkdir -p "$BASE/template/.agents/skills/base"
cat > "$BASE/copier.yml" <<'YAML'
_subdirectory: template
_preserve_symlinks: true
_copy_without_render:
  - ".agents/skills/**"
project_name:
  type: str
  default: demo
YAML
cat > "$BASE/template/.copier-answers.yml.jinja" <<'JINJA'
# Changes here will be overwritten by Copier
{{ _copier_answers|to_nice_yaml -}}
JINJA
cat > "$BASE/template/README.md.jinja" <<'JINJA'
# {{ project_name }} (base layer v1)
JINJA
cat > "$BASE/template/AGENTS.md.jinja" <<'JINJA'
# AGENTS.md — {{ project_name }} (from the GENOME, v1)
JINJA
ln -s AGENTS.md "$BASE/template/CLAUDE.md"
echo "base skill v1" > "$BASE/template/.agents/skills/base/SKILL.md"
git_init "$BASE" "base v1"; tag "$BASE" v1.0.0

# --------------------------------------------------------------------------- #
say "build the OVERLAY template (stands in for my-ai, the personal layer)"
OVER="$WORK/my-ai"
mkdir -p "$OVER/template/.agents/skills/my-ai"
cat > "$OVER/copier.yml" <<'YAML'
_subdirectory: template
_answers_file: .copier-answers.my-ai.yml
_preserve_symlinks: true
_copy_without_render:
  - ".agents/skills/**"
_skip_if_exists:
  - "AGENTS.md"
YAML
cat > "$OVER/template/.copier-answers.my-ai.yml.jinja" <<'JINJA'
# Changes here will be overwritten by Copier
{{ _copier_answers|to_nice_yaml -}}
JINJA
cat > "$OVER/template/AGENTS.md" <<'MD'
# AGENTS.md — seeded by my-ai (only when the repo had none)
MD
ln -s AGENTS.md "$OVER/template/CLAUDE.md"
echo "my-ai skill v1" > "$OVER/template/.agents/skills/my-ai/SKILL.md"
git_init "$OVER" "my-ai v1"; tag "$OVER" v1.0.0

# --------------------------------------------------------------------------- #
say "generate a project from the BASE layer, then LAYER the overlay onto it"
PROJ="$WORK/proj"
copier copy --quiet --defaults --vcs-ref v1.0.0 "$BASE" "$PROJ"
git_init "$PROJ" "generated from base"

copier copy --quiet --defaults --vcs-ref v1.0.0 -a .copier-answers.my-ai.yml "$OVER" "$PROJ"

say "Q1/Q2 — both answers files present and distinct?"
[ -f "$PROJ/.copier-answers.yml" ]        && ok "base .copier-answers.yml survives"          || bad "base answers file gone"
[ -f "$PROJ/.copier-answers.my-ai.yml" ]  && ok "overlay .copier-answers.my-ai.yml written"  || bad "overlay answers file missing"
grep -q 'base-template' "$PROJ/.copier-answers.yml"     && ok "base answers still point at the base template"  || bad "base answers retargeted!"
grep -q 'my-ai'         "$PROJ/.copier-answers.my-ai.yml" && ok "overlay answers point at my-ai"                || bad "overlay answers wrong src"

say "Q4 — did the overlay clobber the genome's AGENTS.md?"
if grep -q "from the GENOME" "$PROJ/AGENTS.md"; then ok "_skip_if_exists protected the repo-owned AGENTS.md"
else bad "AGENTS.md was overwritten: $(head -1 "$PROJ/AGENTS.md")"; fi

say "Q5 — CLAUDE.md still a symlink after layering?"
[ -L "$PROJ/CLAUDE.md" ] && ok "CLAUDE.md is a symlink -> $(readlink "$PROJ/CLAUDE.md")" || bad "CLAUDE.md dereferenced into a regular file"

say "both layers' skills coexist?"
[ -f "$PROJ/.agents/skills/base/SKILL.md" ]  && ok "genome skill present"   || bad "genome skill lost"
[ -f "$PROJ/.agents/skills/my-ai/SKILL.md" ] && ok "personal skill present" || bad "personal skill missing"

git -C "$PROJ" add -A
git -C "$PROJ" -c user.email=s@s -c user.name=s commit -qm "layer my-ai on top"

# --------------------------------------------------------------------------- #
say "bump BOTH templates, then update ONLY the overlay layer"
echo "my-ai skill v2 — new personal law" > "$OVER/template/.agents/skills/my-ai/SKILL.md"
mkdir -p "$OVER/template/.agents/skills/my-ai-review"
echo "brand new personal skill" > "$OVER/template/.agents/skills/my-ai-review/SKILL.md"
cat > "$OVER/template/AGENTS.md" <<'MD'
# AGENTS.md — my-ai seed v2 (must NOT land: the repo owns its AGENTS.md)
MD
git -C "$OVER" add -A; git -C "$OVER" -c user.email=s@s -c user.name=s commit -qm "my-ai v2"; tag "$OVER" v2.0.0

echo "base skill v2" > "$BASE/template/.agents/skills/base/SKILL.md"
git -C "$BASE" add -A; git -C "$BASE" -c user.email=s@s -c user.name=s commit -qm "base v2"; tag "$BASE" v2.0.0

copier update --quiet --defaults --vcs-ref v2.0.0 -a .copier-answers.my-ai.yml "$PROJ"

say "Q3 — overlay converged, base layer untouched?"
grep -q "v2 — new personal law" "$PROJ/.agents/skills/my-ai/SKILL.md" && ok "personal skill converged to v2" || bad "personal skill stale"
[ -f "$PROJ/.agents/skills/my-ai-review/SKILL.md" ] && ok "a NEW personal skill was added by update" || bad "new personal skill not added"
grep -q "base skill v1" "$PROJ/.agents/skills/base/SKILL.md" && ok "genome skill untouched (still v1 — its own layer updates it)" || bad "overlay update reached into the genome layer"
grep -q 'v1.0.0' "$PROJ/.copier-answers.yml" && ok "base answers file untouched by the overlay update" || bad "base answers file mutated"
grep -q 'v2.0.0' "$PROJ/.copier-answers.my-ai.yml" && ok "overlay answers file records v2.0.0" || bad "overlay answers file not bumped"

say "Q4 (update path) — AGENTS.md still repo-owned?"
if grep -q "from the GENOME" "$PROJ/AGENTS.md"; then ok "_skip_if_exists held through update too"
else bad "update overwrote AGENTS.md: $(head -1 "$PROJ/AGENTS.md")"; fi

say "Q5 (update path) — CLAUDE.md still a symlink?"
[ -L "$PROJ/CLAUDE.md" ] && ok "CLAUDE.md is still a symlink" || bad "CLAUDE.md dereferenced by update"

say "now update the BASE layer (no -a) and confirm the overlay survives"
git -C "$PROJ" add -A; git -C "$PROJ" -c user.email=s@s -c user.name=s commit -qm "overlay update"
copier update --quiet --defaults --vcs-ref v2.0.0 "$PROJ"
grep -q "base skill v2" "$PROJ/.agents/skills/base/SKILL.md" && ok "genome layer updated on its own answers file" || bad "genome update failed"
grep -q "v2 — new personal law" "$PROJ/.agents/skills/my-ai/SKILL.md" && ok "personal skill survived the genome update" || bad "genome update clobbered the personal layer"
[ -L "$PROJ/CLAUDE.md" ] && ok "CLAUDE.md symlink survived both layers" || bad "CLAUDE.md dereferenced"

say "RESULT"
if [ "$FAILED" = 0 ]; then echo "  ALL CHECKS PASSED — Copier supports per-layer answers files."; else echo "  SOME CHECKS FAILED (see above)."; fi
exit "$FAILED"
