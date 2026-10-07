#!/usr/bin/env bash
# Q1 — does jj merge a commit holding ONLY a subtree of the project cleanly?
# Q2 — does merge-base hold across two successive renders (T0 -> T1)?
#
# These two gate the entire design. The DAG under test:
#
#     root
#      |
#      T0   render(base-v1)        <- the scaffold; template files ONLY
#      |\
#      | \
#      P   T1   render(base-v2)    <- T1 is a child of T0, NOT of P
#      |   |
#      \  /
#       M = jj new P T1            <- `update`
#
# T1 never contains the project's own files. The claim is that jj treats them as
# additions on P's side (they are absent from the merge base T0 too) rather than
# as deletions on T1's side. If that is wrong, the design is dead.
source "$(dirname "$0")/lib.sh"

W=$(workdir subtree-merge)
new_repo "$W/project"
cd "$W/project" || exit 2

T0=$(commit_render "$FIXTURES/base-v1" "template: render base v1")
note "T0 = $T0"

# --- P: project work on top of T0 ---------------------------------------
mkdir -p src/demo_app
printf 'def run():\n    return 1\n' > src/demo_app/core.py
printf 'notes\n' > NOTES.md
jjq commit -m "project: add core.py and NOTES.md"
P=$(commit_id @-)
note "P  = $P"

# --- T1: render v2 as a child of T0 -------------------------------------
jjq new "$T0"
T1=$(commit_render "$FIXTURES/base-v2" "template: render base v2")
note "T1 = $T1"

# T1 must hold template files only. This is the "subtree" in Q1.
if jj file list --ignore-working-copy -r "$T1" | grep -q 'src/demo_app/core.py'; then
  bad Q1 "T1 contains a project-only file — the template line is not isolated"
else
  ok Q1 "T1 holds template files only (no project-only paths)"
fi
assert_parent Q1 "T1's parent is T0 (identity, not just arity)" "$T0" "$T1"

# --- Q2: the merge base must be T0, computed by jj, not recorded by us ---
MB=$(merge_base "$P" "$T1")
assert_eq Q2 "jj computes merge-base(P, T1) = T0" "$T0" "$MB"
note "this is the field that replaces _commit in the answers file"

# --- Q1: the merge itself ------------------------------------------------
merge_under_test Q1 "$P" "$T1" -m "converge: base v1 -> v2"
M=$(commit_id @)
assert_eq Q1 "the merge commit has 2 parents" "2" "$(parent_count "$M")"

assert_clean Q1 "the merge is clean (both jj signals agree)"

# The merged tree must carry BOTH sides.
assert_present    Q1 "project-only file survived the merge" "src/demo_app/core.py"
assert_present    Q1 "project-only file survived the merge" "NOTES.md"
assert_file_has   Q1 "template v2 change landed (ruff line-length 120)" pyproject.toml "line-length = 120"
assert_file_lacks Q1 "template v1 value is gone (line-length 100)"      pyproject.toml "line-length = 100"
assert_file_has   Q1 "template v2 addition landed ([tool.ty])"          pyproject.toml "[tool.ty]"
assert_present    Q1 "template v2 new file landed (justfile)"           justfile
assert_present    Q1 "unchanged template file still present"            src/demo_app/__init__.py

summary
