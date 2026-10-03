#!/usr/bin/env bash
# VERIFY — exercise the layer commands against a generated project.
#
# The Copier spike checks Copier itself. This script checks CopyRoom's CLI,
# using temporary template repos and targets. It does not change a real repo.
#
# Run: devenv shell -- bash .scratch/projects/11-layer-isolation/verify-overlay-layer.sh
set -euo pipefail

WORK="$(mktemp -d -t overlay-layer-verify-XXXXXX)"
trap 'echo; echo "verify workdir: $WORK"' EXIT

copyroom() { uv run --quiet copyroom "$@"; }
say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok()  { printf '  \033[32mPASS\033[0m %s\n' "$*"; }
bad() { printf '  \033[31mFAIL\033[0m %s\n' "$*"; FAILED=1; }
FAILED=0
git_c() { git -c user.email=v@v -c user.name=v "$@"; }
commit_repo() {
  git_c -C "$1" add -A
  git_c -C "$1" commit -qm "$2"
}

say "create a base template and a documentation overlay"
BASE="$WORK/base"
mkdir -p "$BASE/template"
cat > "$BASE/copier.yml" <<'YAML'
_subdirectory: template
project_name:
  type: str
  default: sample
YAML
printf '# {{ project_name }}\n' > "$BASE/template/README.md.jinja"
git_c -C "$BASE" init -q -b main
commit_repo "$BASE" "base v1"
git_c -C "$BASE" tag v1.0.0

TEMPLATE="$WORK/project-docs"
mkdir -p "$TEMPLATE/template/docs"
cat > "$TEMPLATE/copier.yml" <<'YAML'
_subdirectory: template
_answers_file: .copier-answers.docs.yml
_preserve_symlinks: true
_skip_if_exists:
  - "README.md"
YAML
cat > "$TEMPLATE/template/.copier-answers.docs.yml.jinja" <<'JINJA'
# Changes here will be overwritten by Copier
{{ _copier_answers|to_nice_yaml -}}
JINJA
printf '# Overlay README\n' > "$TEMPLATE/template/README.md"
printf '# Guide v1\n' > "$TEMPLATE/template/docs/guide.md"
ln -s guide.md "$TEMPLATE/template/docs/index.md"
git_c -C "$TEMPLATE" init -q -b main
commit_repo "$TEMPLATE" "docs v1"
git_c -C "$TEMPLATE" tag v1.0.0

say "generate a project and add the overlay"
TARGET="$WORK/project"
uv run --quiet copier copy --defaults --vcs-ref v1.0.0 "$BASE" "$TARGET" >/dev/null
git_c -C "$TARGET" init -q -b main
commit_repo "$TARGET" "generated project"
README_BEFORE="$(sha256sum "$TARGET/README.md" | cut -d' ' -f1)"
(cd "$TARGET" && copyroom layer add "$TEMPLATE" --ref v1.0.0) \
  > "$WORK/add.log" 2>&1 \
  && ok "copyroom layer add succeeded" \
  || { bad "layer add failed"; sed 's/^/    /' "$WORK/add.log"; }
[ -f "$TARGET/.copier-answers.docs.yml" ] && ok "layer link recorded" || bad "layer link missing"
[ -f "$TARGET/docs/guide.md" ] && ok "overlay guide landed" || bad "overlay guide missing"
[ -L "$TARGET/docs/index.md" ] && ok "overlay symlink landed" || bad "overlay symlink missing"
[ "$(sha256sum "$TARGET/README.md" | cut -d' ' -f1)" = "$README_BEFORE" ] \
  && ok "repo README stayed unchanged" || bad "overlay replaced the repo README"

say "layer list reports the overlay"
(cd "$TARGET" && copyroom layer list) | tee "$WORK/list.log" | sed 's/^/    /'
grep -q 'docs' "$WORK/list.log" && ok "layer list reports docs" || bad "layer list missed docs"

say "reapplying the same template is clean"
commit_repo "$TARGET" "apply docs overlay"
(cd "$TARGET" && copyroom layer add "$TEMPLATE" --ref v1.0.0) >/dev/null 2>&1
[ -z "$(git_c -C "$TARGET" status --porcelain)" ] \
  && ok "reapplying changed nothing" || bad "reapplying dirtied the worktree"

say "publish v2 and update the docs layer"
printf '# Guide v2\n' > "$TEMPLATE/template/docs/guide.md"
printf '# Review guide\n' > "$TEMPLATE/template/docs/review.md"
printf '# Overlay README v2\n' > "$TEMPLATE/template/README.md"
commit_repo "$TEMPLATE" "docs v2"
git_c -C "$TEMPLATE" tag v2.0.0
(cd "$TARGET" && copyroom update --layer docs) \
  > "$WORK/update.log" 2>&1 \
  && ok "copyroom update --layer docs succeeded" \
  || { bad "update failed"; sed 's/^/    /' "$WORK/update.log"; }
grep -q 'Guide v2' "$TARGET/docs/guide.md" && ok "guide converged" || bad "guide is stale"
[ -f "$TARGET/docs/review.md" ] && ok "new file landed" || bad "new file missing"
[ -L "$TARGET/docs/index.md" ] && ok "symlink stayed intact" || bad "symlink changed"
[ "$(sha256sum "$TARGET/README.md" | cut -d' ' -f1)" = "$README_BEFORE" ] \
  && ok "repo README survived the update" || bad "update replaced the repo README"
grep -q 'v2.0.0' "$TARGET/.copier-answers.docs.yml" && ok "answer ref advanced" || bad "answer ref stayed old"

say "the overlay also applies to a repo with no base template"
BARE="$WORK/bare"
mkdir -p "$BARE"
git_c -C "$BARE" init -q -b main
printf '# Bare repo\n' > "$BARE/README.md"
commit_repo "$BARE" "bare repo"
(cd "$BARE" && copyroom layer add "$TEMPLATE" --ref v2.0.0) >/dev/null 2>&1
[ -f "$BARE/.copier-answers.docs.yml" ] && ok "overlay link added" || bad "overlay link missing"
[ -f "$BARE/docs/guide.md" ] && ok "guide added to unmanaged repo" || bad "guide missing"

say "RESULT"
if [ "$FAILED" = 0 ]; then echo "  ALL CHECKS PASSED"; else echo "  SOME CHECKS FAILED"; fi
exit "$FAILED"
