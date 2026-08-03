#!/usr/bin/env bash
# Symlink spike: does Copier preserve a `CLAUDE.md -> AGENTS.md` symlink through
# `copier copy` (new) and `copier update`?
#
# Run: devenv shell -- bash .scratch/projects/07-agent-files/symlink-spike.sh
set -u

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
echo "spike workdir: $WORK"

TEMPLATE="$WORK/template"
PROJECT="$WORK/project"

# --- Build a template with an AGENTS.md + a CLAUDE.md symlink to it ---
mkdir -p "$TEMPLATE/template"
cat > "$TEMPLATE/copier.yml" <<'YAML'
_answers_file: .copier-answers.yml
project_name:
  type: str
  default: myproject
YAML
cat > "$TEMPLATE/template/README.md.jinja" <<'MD'
# {{ project_name }}
MD
cat > "$TEMPLATE/template/AGENTS.md" <<'MD'
# AGENTS — canonical instructions
MD
ln -s AGENTS.md "$TEMPLATE/template/CLAUDE.md"

echo "=== template tree (before) ==="
ls -la "$TEMPLATE/template"

# --- copier copy (the `new` path) ---
copier copy --quiet --defaults "$TEMPLATE" "$PROJECT" 2>/dev/null

echo "=== after copier copy ==="
ls -la "$PROJECT"
if [ -L "$PROJECT/CLAUDE.md" ]; then
  echo "NEW: symlink PRESERVED -> $(readlink "$PROJECT/CLAUDE.md")"
elif [ -f "$PROJECT/CLAUDE.md" ]; then
  echo "NEW: symlink became a REGULAR FILE (content: $(cat "$PROJECT/CLAUDE.md"))"
else
  echo "NEW: CLAUDE.md MISSING"
fi

# --- git init the template, tag v1, then update to v2 with a new skill ---
git -C "$TEMPLATE" init -q
git -C "$TEMPLATE" config user.email t@t
git -C "$TEMPLATE" config user.name t
git -C "$TEMPLATE" add -A
git -C "$TEMPLATE" commit -qm v1
git -C "$TEMPLATE" tag v1.0.0

mkdir -p "$TEMPLATE/template/.agents/skills/newskill"
cat > "$TEMPLATE/template/.agents/skills/newskill/SKILL.md" <<'MD'
# new skill
MD
git -C "$TEMPLATE" add -A
git -C "$TEMPLATE" commit -qm v2
git -C "$TEMPLATE" tag v2.0.0

echo "=== after copier update (v1.0.0 -> v2.0.0) ==="
copier update --quiet --defaults --vcs-ref v2.0.0 "$PROJECT" 2>/dev/null
ls -la "$PROJECT"
if [ -L "$PROJECT/CLAUDE.md" ]; then
  echo "UPDATE: symlink PRESERVED -> $(readlink "$PROJECT/CLAUDE.md")"
elif [ -f "$PROJECT/CLAUDE.md" ]; then
  echo "UPDATE: symlink became a REGULAR FILE (content: $(cat "$PROJECT/CLAUDE.md"))"
else
  echo "UPDATE: CLAUDE.md MISSING"
fi
echo "=== update tree ==="
find "$PROJECT" -maxdepth 3 | sort
