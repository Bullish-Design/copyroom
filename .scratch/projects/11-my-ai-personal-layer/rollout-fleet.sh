#!/usr/bin/env bash
# Fleet rollout — put every eligible repo under CopyRoom management.
#
# Per repo, in this order:
#   1. copyroom layer add gh:Bullish-Design/my-ai   (the personal layer; seeds AGENTS.md if absent)
#   2. copyroom agent-files export                  (copyroom's canonical skills + CLAUDE.md symlink)
#   3. .gitignore carve-out for .agents/            (only if absent)
#   4. commit
#
# Order matters: `layer add` seeds AGENTS.md first, so `export` never writes its
# own blueprint over it. Neither step touches a repo's existing AGENTS.md.
#
# Eligibility, checked per repo — anything else is REPORTED, never forced:
#   * a git repo with a clean worktree (a dirty tree makes the review unreadable
#     and would sweep the user's work-in-progress into this commit);
#   * on a branch, OR detached with exactly one local branch at HEAD, which this
#     script fast-forwards afterwards (jj-colocated repos sit detached — my-ai
#     needed this).
#
# Usage: rollout-fleet.sh [--execute]   (default: dry run)
set -uo pipefail

ROOT="${ROOT:-/home/andrew/Documents/Projects}"
LAYER_SRC="${LAYER_SRC:-gh:Bullish-Design/my-ai}"
EXECUTE=0
[ "${1:-}" = "--execute" ] && EXECUTE=1

export PATH="$HOME/.local/share/repoman/venv/bin:$PATH"
ok() { printf '  \033[32m%s\033[0m\n' "$*"; }
warn() { printf '  \033[33m%s\033[0m\n' "$*"; }
err() { printf '  \033[31m%s\033[0m\n' "$*"; }

CARVE_OUT='
# Agent-files convention (copyroom docs/user/agent-files.md): `.agents/` is
# dual-use. `.agents/skills/` IS tracked, as are AGENTS.md and CLAUDE.md; the
# rest of `.agents/` is platform/tool runtime state and stays ignored.
.agents/**
!.agents/skills/
!.agents/skills/**
!AGENTS.md
!CLAUDE.md'

declare -a DONE=() SKIPPED_DIRTY=() SKIPPED_DETACHED=() FAILED=()

for d in "$ROOT"/*/; do
  repo="${d%/}"
  name="$(basename "$repo")"
  [ -d "$repo/.git" ] || continue
  # copyroom is handled through its own feature-branch worktree, not here, so
  # the branch this work lives on does not fall behind its own main.
  [ "$name" = copyroom ] && continue

  dirty="$(git -C "$repo" status --porcelain 2>/dev/null | wc -l)"
  if [ "$dirty" -ne 0 ]; then SKIPPED_DIRTY+=("$name($dirty)"); continue; fi

  # Resolve the branch to advance if HEAD is detached (jj-colocated repos).
  branch="$(git -C "$repo" symbolic-ref -q --short HEAD)"
  advance=""
  if [ -z "$branch" ]; then
    # for-each-ref lists real local branches only. `git branch --points-at`
    # emits a "(no branch)" placeholder when HEAD is detached, which would
    # otherwise be fast-forwarded into a branch literally named that.
    at_head="$(git -C "$repo" for-each-ref refs/heads --points-at HEAD --format='%(refname:short)')"
    if [ "$(printf '%s' "$at_head" | grep -c .)" -eq 1 ]; then
      advance="$at_head"
    else
      SKIPPED_DETACHED+=("$name"); continue
    fi
  fi

  echo "════════ $name${advance:+  (detached; will advance '$advance')}"
  if [ "$EXECUTE" -eq 0 ]; then ok "would roll out"; DONE+=("$name"); continue; fi

  agents_before="$(sha256sum "$repo/AGENTS.md" 2>/dev/null | cut -d' ' -f1)"

  # 1. the personal layer. A repo that already has it gets CONVERGED instead —
  #    skipping would strand it on whatever tag it first adopted.
  if [ ! -f "$repo/.copier-answers.my-ai.yml" ]; then
    if ! ( cd "$repo" && copyroom layer add "$LAYER_SRC" >/dev/null 2>&1 ); then
      err "layer add FAILED"; FAILED+=("$name:layer-add"); continue
    fi
  else
    out="$( cd "$repo" && copyroom update --layer my-ai 2>&1 )"
    if [ $? -ne 0 ]; then err "update --layer FAILED: $out"; FAILED+=("$name:update"); continue; fi
    printf '  %s\n' "$out" | head -2
  fi

  # 2. copyroom's canonical skills
  if ! ( cd "$repo" && copyroom agent-files export >/dev/null 2>&1 ); then
    err "agent-files export FAILED"; FAILED+=("$name:export"); continue
  fi

  # An existing AGENTS.md must survive both steps untouched.
  agents_after="$(sha256sum "$repo/AGENTS.md" 2>/dev/null | cut -d' ' -f1)"
  if [ -n "$agents_before" ] && [ "$agents_before" != "$agents_after" ]; then
    err "AGENTS.md MODIFIED — aborting this repo"; FAILED+=("$name:agents-md"); continue
  fi

  # 3. the .agents/ carve-out
  grep -q '^\.agents/\*\*' "$repo/.gitignore" 2>/dev/null || printf '%s\n' "$CARVE_OUT" >> "$repo/.gitignore"

  # 4. commit
  git -C "$repo" add -A
  if git -C "$repo" diff --cached --quiet; then ok "already converged — nothing to commit"; DONE+=("$name"); continue; fi
  git -C "$repo" commit -q -F - <<'MSG'
chore: bring this repo under CopyRoom management

Adds two things that every repo in the fleet now carries:

1. The my-ai personal layer — the user's standing agent configuration, as a
   Copier template layer recorded in .copier-answers.my-ai.yml. It converges
   independently of whatever template generated this repo:

       copyroom layer list             # the layers managing this repo
       copyroom update --layer my-ai   # converge the personal layer

2. CopyRoom's canonical skills (copyroom, copyroom-adopt,
   copyroom-template-edit) under .agents/skills/, materialized by
   `copyroom agent-files export`, plus the CLAUDE.md -> AGENTS.md symlink.

Also carves .agents/ out in .gitignore: .agents/skills/ is tracked, the rest
is tool runtime state that must never reach git.

This repo's own AGENTS.md is untouched. A repo without one gets a seed.

Requires copyroom >= 0.7.4.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG

  [ -n "$advance" ] && git -C "$repo" branch -f "$advance" HEAD
  ok "committed $(git -C "$repo" log --oneline -1 | cut -c1-7)"
  DONE+=("$name")
done

echo
echo "════════════════════════ SUMMARY"
printf 'rolled out (%d): %s\n\n' "${#DONE[@]}" "${DONE[*]}"
printf 'skipped, dirty worktree (%d): %s\n\n' "${#SKIPPED_DIRTY[@]}" "${SKIPPED_DIRTY[*]}"
printf 'skipped, detached HEAD with no single branch (%d): %s\n\n' "${#SKIPPED_DETACHED[@]}" "${SKIPPED_DETACHED[*]}"
printf 'FAILED (%d): %s\n' "${#FAILED[@]}" "${FAILED[*]}"
[ "${#FAILED[@]}" -eq 0 ]
