#!/usr/bin/env bash
# SPIKE — can a second Copier template layer onto a managed repo?
#
# Q1 Does a copy with the overlay answers file keep the base answers file?
# Q2 Does _answers_file in copier.yml provide the layer name?
# Q3 Does an update change only the selected layer?
# Q4 Does _skip_if_exists protect a README on copy and update?
# Q5 Does _preserve_symlinks keep the overlay's index link through updates?
#
# Run: devenv shell -- bash .scratch/projects/11-layer-isolation/spike-layers.sh
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
say "build the BASE template"
BASE="$WORK/base-template"
mkdir -p "$BASE/template/docs"
cat > "$BASE/copier.yml" <<'YAML'
_subdirectory: template
_preserve_symlinks: true
project_name:
  type: str
  default: demo
YAML
cat > "$BASE/template/.copier-answers.yml.jinja" <<'JINJA'
# Changes here will be overwritten by Copier
{{ _copier_answers|to_nice_yaml -}}
JINJA
cat > "$BASE/template/README.md.jinja" <<'JINJA'
# {{ project_name }} (base template v1)
JINJA
echo "# Base guide v1" > "$BASE/template/docs/base-guide.md"
ln -s base-guide.md "$BASE/template/docs/index.md"
git_init "$BASE" "base v1"; tag "$BASE" v1.0.0

# --------------------------------------------------------------------------- #
say "build the documentation overlay"
OVER="$WORK/project-docs"
mkdir -p "$OVER/template/docs"
cat > "$OVER/copier.yml" <<'YAML'
_subdirectory: template
_answers_file: .copier-answers.docs.yml
_preserve_symlinks: true
_skip_if_exists:
  - "README.md"
YAML
cat > "$OVER/template/.copier-answers.docs.yml.jinja" <<'JINJA'
# Changes here will be overwritten by Copier
{{ _copier_answers|to_nice_yaml -}}
JINJA
echo "# Overlay README" > "$OVER/template/README.md"
echo "# Overlay guide v1" > "$OVER/template/docs/overlay-guide.md"
ln -s overlay-guide.md "$OVER/template/docs/overlay-index.md"
git_init "$OVER" "docs overlay v1"; tag "$OVER" v1.0.0

# --------------------------------------------------------------------------- #
say "generate a project, then apply the overlay"
PROJ="$WORK/proj"
copier copy --quiet --defaults --vcs-ref v1.0.0 "$BASE" "$PROJ"
git_init "$PROJ" "generated from base"

copier copy --quiet --defaults --vcs-ref v1.0.0 -a .copier-answers.docs.yml "$OVER" "$PROJ"

say "Q1/Q2 — both answers files present and distinct?"
[ -f "$PROJ/.copier-answers.yml" ] && ok "base answers survive" || bad "base answers file gone"
[ -f "$PROJ/.copier-answers.docs.yml" ] && ok "overlay answers written" || bad "overlay answers missing"
grep -q 'base-template' "$PROJ/.copier-answers.yml" && ok "base source is unchanged" || bad "base source changed"
grep -q 'project-docs' "$PROJ/.copier-answers.docs.yml" && ok "overlay source is recorded" || bad "overlay source missing"

say "Q4 — did the overlay replace the base README?"
if grep -q "base template v1" "$PROJ/README.md"; then ok "_skip_if_exists protected the README"
else bad "README was overwritten: $(head -1 "$PROJ/README.md")"; fi

say "Q5 — overlay index remains a symlink?"
[ -L "$PROJ/docs/overlay-index.md" ] && ok "overlay index is a symlink" || bad "overlay index became a regular file"

git -C "$PROJ" add -A
git -C "$PROJ" -c user.email=s@s -c user.name=s commit -qm "apply docs overlay"

# --------------------------------------------------------------------------- #
say "bump both templates, then update only the overlay"
echo "# Overlay guide v2" > "$OVER/template/docs/overlay-guide.md"
echo "# Review guide" > "$OVER/template/docs/review.md"
echo "# Overlay README v2" > "$OVER/template/README.md"
git -C "$OVER" add -A; git -C "$OVER" -c user.email=s@s -c user.name=s commit -qm "docs overlay v2"; tag "$OVER" v2.0.0

echo "# Base guide v2" > "$BASE/template/docs/base-guide.md"
git -C "$BASE" add -A; git -C "$BASE" -c user.email=s@s -c user.name=s commit -qm "base v2"; tag "$BASE" v2.0.0

copier update --quiet --defaults --vcs-ref v2.0.0 -a .copier-answers.docs.yml "$PROJ"

say "Q3 — overlay converged, base layer untouched?"
grep -q "Overlay guide v2" "$PROJ/docs/overlay-guide.md" && ok "overlay guide converged" || bad "overlay guide is stale"
[ -f "$PROJ/docs/review.md" ] && ok "new overlay file was added" || bad "new overlay file is missing"
grep -q "Base guide v1" "$PROJ/docs/base-guide.md" && ok "base guide is unchanged" || bad "overlay update changed the base guide"
grep -q 'v1.0.0' "$PROJ/.copier-answers.yml" && ok "base answers are unchanged" || bad "base answers changed"
grep -q 'v2.0.0' "$PROJ/.copier-answers.docs.yml" && ok "overlay answers record v2" || bad "overlay answers were not updated"

say "Q4/Q5 (update path) — README and symlink stay intact?"
grep -q "base template v1" "$PROJ/README.md" && ok "README stayed unchanged" || bad "update replaced the README"
[ -L "$PROJ/docs/overlay-index.md" ] && ok "overlay symlink stayed intact" || bad "overlay symlink became a regular file"

say "update the base layer and confirm the overlay survives"
git -C "$PROJ" add -A; git -C "$PROJ" -c user.email=s@s -c user.name=s commit -qm "overlay update"
copier update --quiet --defaults --vcs-ref v2.0.0 "$PROJ"
grep -q "Base guide v2" "$PROJ/docs/base-guide.md" && ok "base layer updated" || bad "base update failed"
grep -q "Overlay guide v2" "$PROJ/docs/overlay-guide.md" && ok "overlay guide survived" || bad "base update changed the overlay"
[ -L "$PROJ/docs/overlay-index.md" ] && ok "symlink survived both updates" || bad "symlink became a regular file"

say "RESULT"
if [ "$FAILED" = 0 ]; then echo "  ALL CHECKS PASSED — Copier supports per-layer answers files."; else echo "  SOME CHECKS FAILED (see above)."; fi
exit "$FAILED"
