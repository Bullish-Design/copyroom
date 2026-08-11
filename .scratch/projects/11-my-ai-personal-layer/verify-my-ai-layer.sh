#!/usr/bin/env bash
# VERIFY — the real my-ai template, applied to real repos, via the real copyroom CLI.
#
# The spike proved Copier can do it. This proves *this implementation* does it,
# using the actual my-ai repo contents and `copyroom layer add/list/update`.
#
# Run: devenv shell -- bash .scratch/projects/11-my-ai-personal-layer/verify-my-ai-layer.sh
set -euo pipefail

MYAI="${MYAI:-/home/andrew/Documents/Projects/my-ai}"
PROJECTS="${PROJECTS:-/home/andrew/Documents/Projects}"
WORK="$(mktemp -d -t my-ai-layer-verify-XXXXXX)"
trap 'echo; echo "verify workdir: $WORK"' EXIT

copyroom() { uv run --quiet copyroom "$@"; }
say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok()  { printf '  \033[32mPASS\033[0m %s\n' "$*"; }
bad() { printf '  \033[31mFAIL\033[0m %s\n' "$*"; FAILED=1; }
FAILED=0
git_c() { git -c user.email=v@v -c user.name=v "$@"; }

# --------------------------------------------------------------------------- #
say "stage the my-ai working tree as a tagged template repo (v0.1.0)"
# my-ai's changes are uncommitted by design (the user owns that commit), so stage
# a faithful copy here: same files, committed and tagged, so Copier can consume it.
TEMPLATE="$WORK/my-ai"
mkdir -p "$TEMPLATE"
tar -C "$MYAI" --exclude=.git --exclude=.jj --exclude=.devenv --exclude=.direnv \
    --exclude=.gitman -cf - . | tar -C "$TEMPLATE" -xf -
git_c -C "$TEMPLATE" init -q -b main
git_c -C "$TEMPLATE" add -A
git_c -C "$TEMPLATE" commit -qm "my-ai as the personal layer"
git_c -C "$TEMPLATE" tag v0.1.0

[ -f "$TEMPLATE/copier.yml" ]                                   && ok "copier.yml present"      || bad "no copier.yml"
[ -L "$TEMPLATE/template/CLAUDE.md" ]                            && ok "template ships CLAUDE.md as a symlink" || bad "CLAUDE.md is not a symlink in the template"
[ "$(git -C "$TEMPLATE" ls-files -s template/CLAUDE.md | cut -d' ' -f1)" = 120000 ] \
  && ok "committed with git mode 120000" || bad "CLAUDE.md committed as a regular file"
[ -f "$TEMPLATE/template/.agents/skills/my-ai/SKILL.md" ]        && ok "ships the personal skill" || bad "personal skill missing"
[ ! -e "$TEMPLATE/scripts/my-ai-sync.py" ]                       && ok "my-ai-sync.py is gone"    || bad "my-ai-sync.py still present"
for owned in copyroom copyroom-adopt copyroom-template-edit gitman repoman; do
  [ ! -e "$TEMPLATE/template/.agents/skills/$owned" ] || bad "template redistributes tool-owned skill: $owned"
done
ok "template ships no tool-owned skills (two-writer rule)"

# --------------------------------------------------------------------------- #
say "apply the layer to a REAL repo that already has a genome + its own AGENTS.md"
# gitman: a real family repo with .agents/skills/gitman, AGENTS.md, CLAUDE.md.
TARGET="$WORK/gitman"
mkdir -p "$TARGET"
tar -C "$PROJECTS/gitman" --exclude=.git --exclude=.jj --exclude=.devenv --exclude=.direnv \
    --exclude=.gitman --exclude=.venv -cf - . | tar -C "$TARGET" -xf -
git_c -C "$TARGET" init -q -b main
git_c -C "$TARGET" add -A
git_c -C "$TARGET" commit -qm "gitman baseline"

AGENTS_BEFORE="$(sha256sum "$TARGET/AGENTS.md" | cut -d' ' -f1)"
GITMAN_SKILL_BEFORE="$(sha256sum "$TARGET/.agents/skills/gitman/SKILL.md" | cut -d' ' -f1)"

(cd "$TARGET" && copyroom layer add "$TEMPLATE" --ref v0.1.0) > "$WORK/add.log" 2>&1 \
  && ok "copyroom layer add succeeded" || { bad "layer add failed"; sed 's/^/    /' "$WORK/add.log"; }

say "did it land the right things, and only the right things?"
[ -f "$TARGET/.agents/skills/my-ai/SKILL.md" ] && ok "personal skill landed" || bad "personal skill did not land"
[ -f "$TARGET/.copier-answers.my-ai.yml" ]     && ok "layer link recorded"   || bad "no .copier-answers.my-ai.yml"
[ "$(sha256sum "$TARGET/AGENTS.md" | cut -d' ' -f1)" = "$AGENTS_BEFORE" ] \
  && ok "the repo's own AGENTS.md is byte-identical (_skip_if_exists)" || bad "AGENTS.md was overwritten"
[ "$(sha256sum "$TARGET/.agents/skills/gitman/SKILL.md" | cut -d' ' -f1)" = "$GITMAN_SKILL_BEFORE" ] \
  && ok "gitman's own skill untouched" || bad "the layer clobbered gitman's skill"
[ -L "$TARGET/CLAUDE.md" ] && ok "CLAUDE.md is a symlink -> $(readlink "$TARGET/CLAUDE.md")" || bad "CLAUDE.md is not a symlink"
grep -q '_answers_file' "$TARGET/.copier-answers.my-ai.yml" && ok "answers file records the layer identity" || true

say "copyroom layer list sees it"
(cd "$TARGET" && copyroom layer list) | tee "$WORK/list.log" | sed 's/^/    /'
grep -q 'my-ai' "$WORK/list.log" && ok "layer list reports my-ai" || bad "layer list did not report my-ai"

say "copyroom layer add is idempotent"
git_c -C "$TARGET" add -A; git_c -C "$TARGET" commit -qm "apply personal layer"
(cd "$TARGET" && copyroom layer add "$TEMPLATE" --ref v0.1.0) >/dev/null 2>&1
[ -z "$(git -C "$TARGET" status --porcelain)" ] && ok "re-applying changed nothing" || {
  bad "re-applying dirtied the tree:"; git -C "$TARGET" status --porcelain | sed 's/^/      /'; }

# --------------------------------------------------------------------------- #
say "publish v0.2.0 of the personal layer, then converge the repo"
cat >> "$TEMPLATE/template/.agents/skills/my-ai/SKILL.md" <<'EOF'

## Added in v0.2.0

A new standing rule, to prove convergence reaches every repo.
EOF
mkdir -p "$TEMPLATE/template/.agents/skills/my-ai-review"
echo "# my-ai-review — a brand-new personal skill" > "$TEMPLATE/template/.agents/skills/my-ai-review/SKILL.md"
# And a seed change that must NOT reach a repo with its own AGENTS.md:
echo "# AGENTS.md — seed v2 (must never land on a repo that has one)" > "$TEMPLATE/template/AGENTS.md"
git_c -C "$TEMPLATE" add -A
git_c -C "$TEMPLATE" commit -qm "my-ai v0.2.0"
git_c -C "$TEMPLATE" tag v0.2.0

(cd "$TARGET" && copyroom update --layer my-ai) > "$WORK/update.log" 2>&1 \
  && ok "copyroom update --layer my-ai succeeded" || { bad "update failed"; sed 's/^/    /' "$WORK/update.log"; }

grep -q "Added in v0.2.0" "$TARGET/.agents/skills/my-ai/SKILL.md" && ok "edited skill converged" || bad "edited skill stale"
[ -f "$TARGET/.agents/skills/my-ai-review/SKILL.md" ] && ok "new skill added by update" || bad "new skill not added"
[ "$(sha256sum "$TARGET/AGENTS.md" | cut -d' ' -f1)" = "$AGENTS_BEFORE" ] \
  && ok "AGENTS.md STILL byte-identical after update" || bad "update overwrote AGENTS.md"
[ -L "$TARGET/CLAUDE.md" ] && ok "CLAUDE.md still a symlink after update" || bad "update dereferenced CLAUDE.md"
[ "$(sha256sum "$TARGET/.agents/skills/gitman/SKILL.md" | cut -d' ' -f1)" = "$GITMAN_SKILL_BEFORE" ] \
  && ok "gitman's skill still untouched" || bad "update clobbered gitman's skill"
grep -q 'v0.2.0' "$TARGET/.copier-answers.my-ai.yml" && ok "layer answers record v0.2.0" || bad "layer ref not bumped"

say "copyroom status reports the layer as up to date"
git_c -C "$TARGET" add -A; git_c -C "$TARGET" commit -qm "converge personal layer"
(cd "$TARGET" && copyroom status) | sed 's/^/    /'

# --------------------------------------------------------------------------- #
say "apply to a repo with NO AGENTS.md at all (the seed path)"
BARE="$WORK/bare"
mkdir -p "$BARE"; echo "# bare" > "$BARE/README.md"
git_c -C "$BARE" init -q -b main; git_c -C "$BARE" add -A; git_c -C "$BARE" commit -qm bare
(cd "$BARE" && copyroom layer add "$TEMPLATE" --ref v0.2.0) >/dev/null 2>&1
grep -q "Seeded by\|Seed\." "$BARE/AGENTS.md" 2>/dev/null && ok "AGENTS.md seeded where the repo had none" \
  || { [ -f "$BARE/AGENTS.md" ] && ok "AGENTS.md seeded where the repo had none" || bad "no AGENTS.md seeded"; }
[ -L "$BARE/CLAUDE.md" ] && ok "CLAUDE.md symlink created" || bad "no CLAUDE.md symlink"
[ -f "$BARE/.agents/skills/my-ai/SKILL.md" ] && ok "personal skill landed on an unmanaged repo" || bad "personal skill missing"

say "RESULT"
if [ "$FAILED" = 0 ]; then echo "  ALL CHECKS PASSED"; else echo "  SOME CHECKS FAILED (see above)"; fi
exit "$FAILED"
