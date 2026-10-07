#!/usr/bin/env bash
# Q4 — does a file DELETED between v1 and v2 get removed from trunk?
#
# Two cases, because they behave differently and both matter:
#   A. the project never touched the file  -> expect a clean deletion
#   B. the project MODIFIED the file       -> expect a delete/modify conflict
#
# Case B is the honest limit of the design: no three-way merge can guess the
# intent, Copier included. What matters is that jj surfaces it rather than
# silently discarding the project's work.
source "$(dirname "$0")/lib.sh"

# ---------- Case A: untouched by the project ----------
W=$(workdir deletion-untouched)
new_repo "$W/project"
cd "$W/project" || exit 2

T0=$(commit_render "$FIXTURES/base-v1" "template: render base v1")
assert_present Q4 "v1 shipped the CI workflow" .github/workflows/ci.yml

printf 'notes\n' > NOTES.md
jjq commit -m "project: unrelated work"
P=$(commit_id @-)

jjq new "$T0"
T1=$(commit_render "$FIXTURES/base-v2" "template: render base v2")

# The deletion must be real in T1, not merely absent from the render dir.
if jj file list --ignore-working-copy -r "$T1" | grep -q '.github/workflows/ci.yml'; then
  bad Q4 "T1 still tracks the deleted file — wipe_wc did not take effect"
else
  ok Q4 "T1 no longer tracks the file the template dropped"
fi

require_dag "$T0" "$P" "$T1"
merge_under_test Q4 "$P" "$T1" -m "converge: base v1 -> v2"
assert_clean Q4 "case A merged cleanly"
assert_absent  Q4 "case A: the dropped file is gone from trunk" .github/workflows/ci.yml
assert_present Q4 "case A: unrelated project work untouched"    NOTES.md

# ---------- Case B: modified by the project ----------
W2=$(workdir deletion-modified)
new_repo "$W2/project"
cd "$W2/project" || exit 2

T0=$(commit_render "$FIXTURES/base-v1" "template: render base v1")
printf '      - run: echo "project added a step"\n' >> .github/workflows/ci.yml
jjq commit -m "project: customise the CI workflow"
P=$(commit_id @-)

jjq new "$T0"
T1=$(commit_render "$FIXTURES/base-v2" "template: render base v2")
require_dag "$T0" "$P" "$T1"
merge_under_test Q4 "$P" "$T1" -m "converge: base v1 -> v2"

CONFLICTS=$(conflicted_paths)
if printf '%s\n' "$CONFLICTS" | grep -q 'ci.yml'; then
  ok Q4 "case B: delete/modify is reported as a conflict, not silently resolved"
  note "jj resolve --list:"
  jj resolve --list 2>&1 | sed 's/^/-----       /'
else
  bad Q4 "case B: the project's edit was discarded WITHOUT a conflict"
  note "conflicted paths were: ${CONFLICTS:-<none>}"
  if [ -e .github/workflows/ci.yml ]; then
    note "file still exists — the deletion lost"
  else
    note "file is gone — the project's customisation was silently dropped"
  fi
fi

summary
