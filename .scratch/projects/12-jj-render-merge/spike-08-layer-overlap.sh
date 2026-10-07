#!/usr/bin/env bash
# Q10 — what happens when two independent layers own the same path?
source "$(dirname "$0")/lib.sh"

# Case A: both layers add the same bytes. One layer then deletes the file while
# the other keeps it. A clean merge can still delete the other layer's file.
W=$(workdir overlap-delete)
new_repo "$W/project"
cd "$W/project" || exit 2
printf 'shared\n' > shared.txt
jjq commit -m "copyroom:render base v1"
B0=$(commit_id @-)
jjq new 'root()'
printf 'shared\n' > shared.txt
jjq commit -m "copyroom:render overlay v1"
O0=$(commit_id @-)
merge_under_test Q10 "$B0" "$O0" -m "project: scaffold two layers"
assert_clean Q10 "identical shared files scaffold cleanly"
P=$(commit_id @)

jjq new "$B0"
rm shared.txt
jjq commit -m "copyroom:render base v2"
B1=$(commit_id @-)
jjq new "$O0"
printf 'overlay-only\n' > overlay.txt
jjq commit -m "copyroom:render overlay v2"
O1=$(commit_id @-)
merge_under_test Q10 "$P" "$B1" "$O1" -m "project: update both layers"
assert_clean Q10 "overlapping deletion has no jj conflict"
assert_absent Q10 "one layer deletes the other layer's unchanged file" shared.txt
assert_present Q10 "unrelated overlay file still lands" overlay.txt

# Case B: nearby edits from the project and both layers produce a conflict.
W=$(workdir overlap-edit)
new_repo "$W/project"
cd "$W/project" || exit 2
printf 'A=old\nB=old\nC=old\n' > shared.txt
jjq commit -m "copyroom:render base v1"
B0=$(commit_id @-)
jjq new 'root()'
printf 'A=old\nB=old\nC=old\n' > shared.txt
jjq commit -m "copyroom:render overlay v1"
O0=$(commit_id @-)
jjq new "$B0" "$O0"
sed -i 's/B=old/B=project/' shared.txt
jjq commit -m "project: edit shared file"
P=$(commit_id @-)

jjq new "$B0"
sed -i 's/A=old/A=base/' shared.txt
jjq commit -m "copyroom:render base v2"
B1=$(commit_id @-)
jjq new "$O0"
sed -i 's/C=old/C=overlay/' shared.txt
jjq commit -m "copyroom:render overlay v2"
O1=$(commit_id @-)
merge_under_test Q10 "$P" "$B1" "$O1" -m "project: update shared file"
if conflicted_paths | grep -q '^shared.txt$' && is_conflicted '@'; then
  ok Q10 "nearby edits produce a recorded three-sided conflict"
else
  bad Q10 "nearby edits did not produce the expected conflict"
fi

summary
