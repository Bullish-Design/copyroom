#!/usr/bin/env bash
# Q6 — does jj reverse the merge completely, so preview needs no sandbox?
#
# CopyRoom's template-preview today copies the project to a temp dir, rewrites
# _src_path, git-inits a baseline, runs copier update, emits a patch and throws
# the sandbox away (template/preview.py, template/workspace.py). If jj can undo a
# real merge exactly, preview collapses to: merge, `jj diff`, undo.
#
# Two mechanisms are tested, because a preview implementation would prefer the
# explicit one: `jj undo` (last operation) and `jj op restore <id>` (named point).
source "$(dirname "$0")/lib.sh"

fingerprint_of_wc() { tree_fingerprint | sha256sum | cut -d' ' -f1; }

# ---------- jj undo ----------
W=$(workdir undo)
new_repo "$W/project"
cd "$W/project" || exit 2

T0=$(commit_render "$FIXTURES/base-v1" "template: render base v1")
printf 'notes\n' > NOTES.md
printf '\nProject note.\n' >> README.md
jjq commit -m "project: work"
P=$(commit_id @-)

jjq new "$T0"
T1=$(commit_render "$FIXTURES/base-v2" "template: render base v2")
require_dag "$T0" "$P" "$T1"

# Return to trunk and record the exact state a preview must restore.
jjq edit "$P"
BEFORE_WC=$(fingerprint_of_wc)
BEFORE_AT=$(commit_id @)
OP_BEFORE=$(jj op log --no-graph --limit 1 -T 'id.short()')
note "op before merge = $OP_BEFORE"

merge_under_test Q6 "$P" "$T1" -m "preview: converge base v1 -> v2"
DURING_WC=$(fingerprint_of_wc)
if [ "$BEFORE_WC" != "$DURING_WC" ]; then
  ok Q6 "the merge actually changed the working copy (preview has something to show)"
else
  bad Q6 "the merge changed nothing — the experiment is vacuous"
fi
# Finding (spike 12): `jj diff` on a MERGE commit is EMPTY, because a merge has
# no changes relative to its own auto-merged parents. A preview must diff against
# trunk explicitly. Getting this wrong would make preview look like a no-op.
note "jj diff --from <trunk> --to @ — what a preview would actually show:"
jj diff --summary --from "$P" --to @ 2>&1 | sed 's/^/-----       /'

jj undo >/dev/null 2>&1
assert_eq Q6 "jj undo restores @ to the pre-merge commit" "$BEFORE_AT" "$(commit_id @)"
assert_eq Q6 "jj undo restores the working copy byte-for-byte" "$BEFORE_WC" "$(fingerprint_of_wc)"

# ---------- jj op restore ----------
W2=$(workdir op-restore)
new_repo "$W2/project"
cd "$W2/project" || exit 2

T0=$(commit_render "$FIXTURES/base-v1" "template: render base v1")
printf 'notes\n' > NOTES.md
jjq commit -m "project: work"
P=$(commit_id @-)
jjq new "$T0"
T1=$(commit_render "$FIXTURES/base-v2" "template: render base v2")
require_dag "$T0" "$P" "$T1"
jjq edit "$P"

BEFORE_WC=$(fingerprint_of_wc)
BEFORE_AT=$(commit_id @)
OP=$(jj op log --no-graph --limit 1 -T 'id.short()')

merge_under_test Q6 "$P" "$T1" -m "preview: converge"
if jj op restore "$OP" >/dev/null 2>&1; then
  ok Q6 "jj op restore <id> accepts a named pre-merge operation"
  assert_eq Q6 "op restore returns @ to the pre-merge commit" "$BEFORE_AT" "$(commit_id @)"
  assert_eq Q6 "op restore returns the working copy byte-for-byte" "$BEFORE_WC" "$(fingerprint_of_wc)"
else
  bad Q6 "jj op restore <id> failed"
fi

summary
