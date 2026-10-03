#!/usr/bin/env bash
# VERIFY — add and update an overlay on a copy of a real base-template project.
#
# The source project is copied to a temporary directory. This script does not
# change the source repo.
#
# Run: devenv shell -- bash .scratch/projects/11-layer-isolation/verify-two-real-layers.sh
set -euo pipefail

SRC="${SRC:-/home/andrew/Documents/Projects/argentic}"
WORK="$(mktemp -d -t two-real-layers-XXXXXX)"
trap 'echo; echo "verify workdir: $WORK"' EXIT

copyroom() { uv run --quiet copyroom "$@"; }
say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok()  { printf '  \033[32mPASS\033[0m %s\n' "$*"; }
bad() { printf '  \033[31mFAIL\033[0m %s\n' "$*"; FAILED=1; }
FAILED=0
git_c() { git -c user.email=v@v -c user.name=v "$@"; }

say "copy a real base-template project into a sandbox"
TARGET="$WORK/project"
mkdir -p "$TARGET"
tar -C "$SRC" --exclude=.git --exclude=.jj --exclude=.devenv --exclude=.direnv \
    --exclude=.gitman --exclude=.venv --exclude=.testee -cf - . | tar -C "$TARGET" -xf -
git_c -C "$TARGET" init -q -b main
git_c -C "$TARGET" add -A
git_c -C "$TARGET" commit -qm "project baseline"

BASE_ANSWERS_BEFORE="$(sha256sum "$TARGET/.copier-answers.yml" | cut -d' ' -f1)"
grep -q 'template-py' "$TARGET/.copier-answers.yml" \
  && ok "base layer records the Python genome" || bad "unexpected base layer"

say "create a documentation overlay"
TEMPLATE="$WORK/project-docs"
mkdir -p "$TEMPLATE/template/docs"
cat > "$TEMPLATE/copier.yml" <<'YAML'
_subdirectory: template
_answers_file: .copier-answers.docs.yml
_preserve_symlinks: true
YAML
cat > "$TEMPLATE/template/.copier-answers.docs.yml.jinja" <<'JINJA'
# Changes here will be overwritten by Copier
{{ _copier_answers|to_nice_yaml -}}
JINJA
printf '# Guide v1\n' > "$TEMPLATE/template/docs/guide.md"
ln -s guide.md "$TEMPLATE/template/docs/index.md"
git_c -C "$TEMPLATE" init -q -b main
git_c -C "$TEMPLATE" add -A
git_c -C "$TEMPLATE" commit -qm "docs v1"
git_c -C "$TEMPLATE" tag v1.0.0

say "apply the overlay beside the real base layer"
(cd "$TARGET" && copyroom layer add "$TEMPLATE" --ref v1.0.0) \
  > "$WORK/add.log" 2>&1 \
  && ok "copyroom layer add succeeded" \
  || { bad "layer add failed"; sed 's/^/    /' "$WORK/add.log"; }
(cd "$TARGET" && copyroom layer list) | sed 's/^/    /'
LAYERS="$(cd "$TARGET" && copyroom layer list --json)"
printf '%s' "$LAYERS" | grep -q '"name": "base"' && ok "base layer remains" || bad "base layer is missing"
printf '%s' "$LAYERS" | grep -q '"name": "docs"' && ok "docs layer recorded" || bad "docs layer is missing"
[ -f "$TARGET/docs/guide.md" ] && ok "docs guide landed" || bad "docs guide missing"
[ -L "$TARGET/docs/index.md" ] && ok "docs index is a symlink" || bad "docs index is not a symlink"
[ "$(sha256sum "$TARGET/.copier-answers.yml" | cut -d' ' -f1)" = "$BASE_ANSWERS_BEFORE" ] \
  && ok "base answers are unchanged" || bad "overlay changed base answers"

say "update only the overlay"
git_c -C "$TARGET" add -A
git_c -C "$TARGET" commit -qm "apply docs overlay"
printf '# Guide v2\n' > "$TEMPLATE/template/docs/guide.md"
printf '# Review guide\n' > "$TEMPLATE/template/docs/review.md"
git_c -C "$TEMPLATE" add -A
git_c -C "$TEMPLATE" commit -qm "docs v2"
git_c -C "$TEMPLATE" tag v2.0.0
(cd "$TARGET" && copyroom update --layer docs) \
  > "$WORK/update.log" 2>&1 \
  && ok "docs update succeeded" \
  || { bad "docs update failed"; sed 's/^/    /' "$WORK/update.log"; }
grep -q 'Guide v2' "$TARGET/docs/guide.md" && ok "docs layer converged" || bad "docs layer is stale"
[ -f "$TARGET/docs/review.md" ] && ok "new docs file landed" || bad "new docs file missing"
[ "$(sha256sum "$TARGET/.copier-answers.yml" | cut -d' ' -f1)" = "$BASE_ANSWERS_BEFORE" ] \
  && ok "base answers are still unchanged" || bad "docs update changed base answers"

say "base status remains available with the overlay present"
(cd "$TARGET" && copyroom status) | sed 's/^/    /'

say "RESULT"
if [ "$FAILED" = 0 ]; then echo "  ALL CHECKS PASSED"; else echo "  SOME CHECKS FAILED"; fi
exit "$FAILED"
