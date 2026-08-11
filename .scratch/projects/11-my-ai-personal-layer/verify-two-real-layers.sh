#!/usr/bin/env bash
# VERIFY — the gap I flagged: the real my-ai layer on a repo whose base layer is
# the REAL genome (template-py), not a fixture.
#
# Runs against a COPY of argentic so the real repo is never touched. Proves both
# layers coexist, converge independently, and that the genome's own update still
# works with the personal layer present.
#
# Run: devenv shell -- bash .scratch/projects/11-my-ai-personal-layer/verify-two-real-layers.sh
set -euo pipefail

SRC="${SRC:-/home/andrew/Documents/Projects/argentic}"
MYAI="${MYAI:-/home/andrew/Documents/Projects/my-ai}"
WORK="$(mktemp -d -t two-real-layers-XXXXXX)"
trap 'echo; echo "verify workdir: $WORK"' EXIT

export PATH="$HOME/.local/share/repoman/venv/bin:$PATH"
say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok()  { printf '  \033[32mPASS\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31mFAIL\033[0m %s\n' "$*"; FAILED=1; }
# A check that cannot run must SAY SO. Silently vanishing reads as "passed".
skip() { printf '  \033[33mSKIP\033[0m %s\n' "$*"; }
FAILED=0
git_c() { git -c user.email=v@v -c user.name=v "$@"; }

say "clone a real template-py-generated repo (argentic) into a sandbox"
TARGET="$WORK/argentic"
mkdir -p "$TARGET"
tar -C "$SRC" --exclude=.git --exclude=.jj --exclude=.devenv --exclude=.direnv \
    --exclude=.gitman --exclude=.venv --exclude=.testee -cf - . | tar -C "$TARGET" -xf -
git_c -C "$TARGET" init -q -b main
git_c -C "$TARGET" add -A
git_c -C "$TARGET" commit -qm "argentic baseline"

BASE_ANSWERS_BEFORE="$(sha256sum "$TARGET/.copier-answers.yml" | cut -d' ' -f1)"
AGENTS_BEFORE="$(sha256sum "$TARGET/AGENTS.md" 2>/dev/null | cut -d' ' -f1 || true)"
GENOME_SKILL="$TARGET/.agents/skills/devenv-authoring/SKILL.md"
GENOME_SKILL_BEFORE="$(sha256sum "$GENOME_SKILL" 2>/dev/null | cut -d' ' -f1 || true)"
grep -q 'template-py' "$TARGET/.copier-answers.yml" \
  && ok "base layer is the real genome (gh:Bullish-Design/template-py)" || bad "unexpected base layer"

say "apply the real personal layer on top"
( cd "$TARGET" && copyroom layer add "$MYAI" --ref v0.1.0 ) | sed 's/^/    /'

say "both layers recorded?"
( cd "$TARGET" && copyroom layer list ) | sed 's/^/    /'
LAYERS="$( cd "$TARGET" && copyroom layer list --json )"
printf '%s' "$LAYERS" | grep -q '"name": "base"'  && ok "base layer intact"     || bad "base layer lost"
printf '%s' "$LAYERS" | grep -q '"name": "my-ai"' && ok "my-ai layer recorded"  || bad "my-ai layer missing"
[ "$(sha256sum "$TARGET/.copier-answers.yml" | cut -d' ' -f1)" = "$BASE_ANSWERS_BEFORE" ] \
  && ok "the genome's answers file is byte-identical" || bad "the overlay mutated the genome's answers file"

say "did the personal layer respect what the repo and the genome own?"
[ -f "$TARGET/.agents/skills/my-ai/SKILL.md" ] && ok "personal skill landed" || bad "personal skill missing"
if [ -n "$AGENTS_BEFORE" ]; then
  [ "$(sha256sum "$TARGET/AGENTS.md" | cut -d' ' -f1)" = "$AGENTS_BEFORE" ] \
    && ok "the repo's AGENTS.md is byte-identical (_skip_if_exists)" || bad "AGENTS.md overwritten"
else
  skip "no pre-existing AGENTS.md in this repo — the layer SEEDED one instead."
  skip "  (see docs/user/layers.md 'Rollout order': the genome ships AGENTS.md too,"
  skip "   so update the base layer FIRST to avoid an avoidable merge on it.)"
  grep -q 'The `my-ai` personal layer wrote this file' "$TARGET/AGENTS.md" \
    && ok "AGENTS.md seeded by the personal layer" || bad "no AGENTS.md seeded"
fi
if [ -n "$GENOME_SKILL_BEFORE" ]; then
  [ "$(sha256sum "$GENOME_SKILL" | cut -d' ' -f1)" = "$GENOME_SKILL_BEFORE" ] \
    && ok "a genome-owned skill (devenv-authoring) is untouched" || bad "the overlay clobbered a genome skill"
else
  skip "this repo predates the genome's devenv-* skills — nothing to compare."
fi
[ -L "$TARGET/CLAUDE.md" ] && ok "CLAUDE.md is a symlink" || bad "CLAUDE.md is not a symlink"

say "the genome's OWN update still works with the personal layer present"
git_c -C "$TARGET" add -A; git_c -C "$TARGET" commit -qm "apply the personal layer"
( cd "$TARGET" && copyroom update ) > "$WORK/base-update.log" 2>&1 || true
if grep -qi "already at" "$WORK/base-update.log"; then
  ok "base layer reports up-to-date (a no-op is exit 0, not a failure)"
else
  sed 's/^/    /' "$WORK/base-update.log"
  grep -qi "updated to" "$WORK/base-update.log" \
    && ok "base layer updated cleanly alongside the overlay" \
    || bad "the base-layer update misbehaved with an overlay present"
fi
[ -f "$TARGET/.agents/skills/my-ai/SKILL.md" ] \
  && ok "the personal skill survived the genome's update" || bad "the genome's update removed the personal skill"

say "status reports both layers"
( cd "$TARGET" && copyroom status ) | sed 's/^/    /'

say "RESULT"
if [ "$FAILED" = 0 ]; then echo "  ALL CHECKS PASSED"; else echo "  SOME CHECKS FAILED"; fi
exit "$FAILED"
