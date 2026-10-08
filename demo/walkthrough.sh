#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(mktemp -d -t copyroom-templateer-walkthrough-XXXXXX)"
KEEP=0
PAUSE=0

while (($#)); do
  case "$1" in
    --keep) KEEP=1 ;;
    --pause) PAUSE=1 ;;
    *) echo "Unknown option: $1" >&2; exit 3 ;;
  esac
  shift
done

cleanup() {
  if ((KEEP)); then
    echo "Walkthrough files kept at $ROOT"
  else
    rm -rf "$ROOT"
  fi
}
trap cleanup EXIT

say() { printf '\n%s\n' "$*"; }
step() {
  say "== $*"
  if ((PAUSE)); then
    read -r -p "Press Enter to continue... " _
  fi
}
die() { echo "ERROR: $*" >&2; exit 1; }

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="$ROOT/source"
PROJECT="$ROOT/project"
ANSWERS="$SOURCE/answers.json"

step "Create a project from a local Templateer source"
cp -R "$REPO/.scratch/projects/26-templateer-jj-slice/example" "$SOURCE"
copyroom doctor --json
copyroom new "$SOURCE" "$PROJECT" --answers "$ANSWERS"
[[ -f "$PROJECT/.copyroom-local.json" ]] || die "project marker is missing"
[[ -d "$PROJECT/.jj" ]] || die "jj workspace is missing"

step "Preview a source update while preserving a project-owned file"
printf 'Keep this project note.\n' > "$PROJECT/notes.md"
cat >> "$SOURCE/templates/settings/template.j2" <<'EOF'

maintenance: "enabled"
EOF
(
  cd "$PROJECT"
  copyroom update --source "$SOURCE" --out "$ROOT/update-preview"
  copyroom preview list --project "$PROJECT"
  copyroom apply --project "$PROJECT" --preview "$ROOT/update-preview"
)
grep -q 'Keep this project note.' "$PROJECT/notes.md" || die "project-owned file was lost"
grep -q 'maintenance: "enabled"' "$PROJECT/config/project.yml" || die "source update was not applied"

step "Render and compare a full workshop golden tree"
WORKSHOP="$ROOT/workshop"
mkdir -p "$WORKSHOP/registry" "$WORKSHOP/scenarios" "$WORKSHOP/goldens"
cat > "$WORKSHOP/copyroom.yml" <<EOF
name: walkthrough
templates: {}
EOF
(
  cd "$WORKSHOP"
  copyroom registry add walkthrough --source "$SOURCE" --scaffold
  copyroom registry validate
  copyroom render walkthrough default
  copyroom golden walkthrough default --refresh
  copyroom golden walkthrough default
)

step "Inspect, templatize, and adopt a local source"
copyroom inspect --project "$PROJECT" --json
copyroom status --project "$PROJECT"
copyroom templatize --project "$PROJECT" --target "$ROOT/extracted-source" --name sample
cp -R "$PROJECT" "$ROOT/adopted"
rm -rf "$ROOT/adopted/.jj" "$ROOT/adopted/.copyroom-local" "$ROOT/adopted/.copyroom-local.json"
copyroom adopt "$SOURCE" --project "$ROOT/adopted" --answers "$ANSWERS" --write --template-only keep
[[ -f "$ROOT/adopted/.copyroom-local.json" ]] || die "adoption marker is missing"

step "Create an isolated candidate template workspace"
(
  cd "$WORKSHOP"
  copyroom template-checkout walkthrough
  copyroom template-test walkthrough
  copyroom template-discard walkthrough
)

say "Walkthrough complete. The project and source used local files, Templateer, and jj."
