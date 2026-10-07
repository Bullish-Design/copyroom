#!/usr/bin/env bash
# Q3 — does a local edit to a TEMPLATE-OWNED file survive the merge?
#
# This is what Copier's three-way merge exists to protect, and the reason
# `copier update` cannot simply overwrite. The project appends a line at the end
# of README.md; template v2 inserts a different line under the heading. Different
# regions, so a correct 3-way merge keeps both.
source "$(dirname "$0")/lib.sh"

W=$(workdir local-edit)
new_repo "$W/project"
cd "$W/project" || exit 2

T0=$(commit_render "$FIXTURES/base-v1" "template: render base v1")

# The project edits a file the template owns.
printf '\nProject-specific note, hand-written.\n' >> README.md
jjq commit -m "project: append a note to the template's README"
P=$(commit_id @-)

jjq new "$T0"
T1=$(commit_render "$FIXTURES/base-v2" "template: render base v2")

require_dag "$T0" "$P" "$T1"
merge_under_test Q3 "$P" "$T1" -m "converge: base v1 -> v2"

assert_clean Q3 "non-overlapping edits to the same file merge without conflict"

assert_file_has Q3 "the project's hand-written line survived" README.md "Project-specific note, hand-written."
assert_file_has Q3 "the template's v2 line landed"            README.md "Managed by the base template."
assert_file_has Q3 "the shared v1 line is still present"      README.md "Generated from the base template."
note "README.md after the merge:"
sed 's/^/-----       /' README.md

summary
