#!/usr/bin/env bash
# Q5 — is a conflict RECORDED IN THE COMMIT, leaving other jj ops usable?
#
# This is the claim that kills CopyRoom's `.rej` scanner, its inline-marker scan
# and its clean-worktree guard. With git, a conflicted merge is a broken
# mid-operation state you must clear before doing anything else. jj's pitch is
# that a conflict is ordinary committed data.
#
# The project sets ruff line-length to 80; template v2 sets it to 120. Same line,
# so this conflict is unavoidable and deliberate.
source "$(dirname "$0")/lib.sh"

W=$(workdir conflict)
new_repo "$W/project"
cd "$W/project" || exit 2

T0=$(commit_render "$FIXTURES/base-v1" "template: render base v1")
sed -i 's/line-length = 100/line-length = 80/' pyproject.toml
jjq commit -m "project: tighten ruff line-length to 80"
P=$(commit_id @-)

jjq new "$T0"
T1=$(commit_render "$FIXTURES/base-v2" "template: render base v2")

require_dag "$T0" "$P" "$T1"

# The merge must SUCCEED as an operation even though the content conflicts.
if jj new "$P" "$T1" -m "converge: base v1 -> v2" >/dev/null 2>&1; then
  ok Q5 "jj new succeeded despite a content conflict (no aborted operation)"
else
  bad Q5 "jj new failed on a conflicting merge"
fi
M=$(commit_id @)

CONFLICTS=$(conflicted_paths)
if printf '%s\n' "$CONFLICTS" | grep -q 'pyproject.toml'; then
  ok Q5 "the conflict is recorded and listed by jj resolve --list"
else
  bad Q5 "the contested file is not reported as conflicted"
  note "conflicted paths: ${CONFLICTS:-<none>}"
fi

# Is the conflict stored in the COMMIT, or only in the working copy?
if jj log --no-graph --ignore-working-copy -r "$M & conflicts()" -T commit_id | grep -q .; then
  ok Q5 "the commit itself is marked conflicted (conflicts() matches it)"
else
  bad Q5 "the commit is not marked conflicted — state lives only in the files"
fi

# Does the working copy materialise markers? Either answer is a finding: it tells
# us whether a `status`-style report still needs to scan file contents.
if grep -q '<<<<<<<' pyproject.toml; then
  ok Q5 "working copy materialises conflict markers (expected; report can scan)"
  note "a reporting command can still detect markers, as CopyRoom does today"
else
  ok Q5 "working copy holds no textual markers; conflict is metadata only"
fi

# The decisive part: are other operations still usable while conflicted?
for cmd in "jj status" "jj log -r ::@ --no-graph -T commit_id" "jj diff --summary" "jj op log"; do
  if $cmd >/dev/null 2>&1; then
    ok Q5 "usable while conflicted: $cmd"
  else
    bad Q5 "BLOCKED while conflicted: $cmd"
  fi
done

# Can we commit new work on top of an unresolved conflict and keep moving?
if jj new -m "project: carry on despite the conflict" >/dev/null 2>&1; then
  ok Q5 "can start new work on top of an unresolved conflict"
else
  bad Q5 "cannot proceed without resolving first (same trap as git)"
fi

summary
