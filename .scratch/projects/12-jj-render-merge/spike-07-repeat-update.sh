#!/usr/bin/env bash
# Q9 — repeat an update after project work and find the current render head.
source "$(dirname "$0")/lib.sh"

W=$(workdir repeat-update)
new_repo "$W/project"
cd "$W/project" || exit 2

T0=$(commit_render "$FIXTURES/base-v1" "copyroom:render base v1")
printf '\nProject note before update.\n' >> README.md
jjq commit -m "project: edit before first update"
P0=$(commit_id @-)

jjq new "$T0"
T1=$(commit_render "$FIXTURES/base-v2" "copyroom:render base v2")
require_dag "$T0" "$P0" "$T1"
merge_under_test Q9 "$P0" "$T1" -m "project: first update"
assert_clean Q9 "first update is clean"

printf '\nProject note after update.\n' >> README.md
printf 'project-only\n' > local.txt
jjq commit -m "project: edit after first update"
P1=$(commit_id @-)

# The graph identifies the render head by its stable layer marker. An update
# must reject zero or several heads instead of guessing from commit order.
HEADS=$(jj log --no-graph --ignore-working-copy \
  -r 'heads(::'"$P1"' & subject(glob:"copyroom:render base *"))' \
  -T 'commit_id ++ "\n"')
assert_eq Q9 "one marked render head is T1" "$T1" "$HEADS"

V3="$W/base-v3"
cp -a "$FIXTURES/base-v2" "$V3"
sed -i 's/line-length = 120/line-length = 140/' "$V3/pyproject.toml"
printf 'template-v3\n' > "$V3/template-v3.txt"

jjq new "$T1"
T2=$(commit_render "$V3" "copyroom:render base v3")
assert_parent Q9 "T2 is a child of T1" "$T1" "$T2"
assert_eq Q9 "second merge base is T1" "$T1" "$(merge_base "$P1" "$T2")"

merge_under_test Q9 "$P1" "$T2" -m "project: second update"
assert_clean Q9 "second update is clean"
assert_file_has Q9 "v3 template change landed" pyproject.toml "line-length = 140"
assert_present Q9 "v3 template file landed" template-v3.txt
assert_file_has Q9 "first project edit survived" README.md "Project note before update."
assert_file_has Q9 "second project edit survived" README.md "Project note after update."
assert_file_has Q9 "project-only file survived" local.txt "project-only"

HEADS=$(jj log --no-graph --ignore-working-copy \
  -r 'heads(::@ & subject(glob:"copyroom:render base *"))' \
  -T 'commit_id ++ "\n"')
assert_eq Q9 "marked render head advanced to T2" "$T2" "$HEADS"

summary
