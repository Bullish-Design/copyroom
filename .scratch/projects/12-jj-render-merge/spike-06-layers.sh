#!/usr/bin/env bash
# Q7 — does an n-parent merge converge two layers at once, order-free?
#
# CopyRoom's layer model needs two guarantees. Today it gets them from Copier's
# -a flag plus a hack: `update --all-layers` commits to git between layers,
# because Copier refuses a dirty destination (project/update.py). If layers are
# simply parents of one commit, both guarantees become graph properties:
#
#   A. convergence is order-free (no arbitration between layers)
#   B. converging one layer leaves the other untouched (independent convergence)
#
#     root
#      |\
#      B0 O0                  two template lines, each its own scaffold render
#      |\ /|
#      | P |                  P = merge(B0, O0) + project work
#      B1 O1                  each layer's next render
#       \|/
#        M = jj new P B1 O1
source "$(dirname "$0")/lib.sh"

# build <dir> <first> <second> — echoes nothing; leaves cwd in the repo.
# <first>/<second> name the convergence order: the strings B1 and O1.
build() {
  local dir="$1" first="$2" second="$3"
  new_repo "$dir"
  cd "$dir" || exit 2

  B0=$(commit_render "$FIXTURES/base-v1" "template: render base v1")
  jjq new 'root()'
  O0=$(commit_render "$FIXTURES/overlay-v1" "template: render overlay v1")

  jjq new "$B0" "$O0" -m "scaffold: base + overlay"
  printf 'notes\n' > NOTES.md
  jjq commit -m "project: work on the scaffold"
  P=$(commit_id @-)

  jjq new "$B0"
  B1=$(commit_render "$FIXTURES/base-v2" "template: render base v2")
  jjq new "$O0"
  O1=$(commit_render "$FIXTURES/overlay-v2" "template: render overlay v2")

  local a b
  eval "a=\$$first"
  eval "b=\$$second"
  # Both layers must genuinely fork from their own scaffold render, or the
  # convergence proves nothing.
  require_dag "$B0" "$P" "$B1"
  require_dag "$O0" "$P" "$O1"
  merge_under_test Q7 "$P" "$a" "$b" -m "converge: both layers ($first then $second)"
}

# ---------- base-then-overlay ----------
W=$(workdir layers-base-first)
build "$W/project" B1 O1
assert_eq Q7 "the scaffold commit has 2 parents (two layers)" "2" "$(parent_count "$P")"
assert_eq Q7 "the convergence commit has 3 parents"           "3" "$(parent_count "$(commit_id @)")"

if [ -z "$(conflicted_paths)" ]; then
  ok Q7 "a 3-parent convergence of two independent layers is clean"
else
  bad Q7 "the n-parent convergence conflicted"
  jj resolve --list 2>&1 | sed 's/^/-----       /'
fi

assert_file_has Q7 "base layer reached v2"     pyproject.toml "line-length = 120"
assert_present  Q7 "base layer v2 file landed" justfile
assert_file_has Q7 "overlay layer reached v2"  .overlay/README.md "overlay v2"
assert_present  Q7 "overlay layer v2 file landed" docs/guide.md
assert_present  Q7 "project work survived both layers" NOTES.md
assert_absent   Q7 "base layer deletion applied" .github/workflows/ci.yml
FP_BASE_FIRST=$(tree_fingerprint | sha256sum | cut -d' ' -f1)

# ---------- overlay-then-base ----------
W2=$(workdir layers-overlay-first)
build "$W2/project" O1 B1
FP_OVERLAY_FIRST=$(tree_fingerprint | sha256sum | cut -d' ' -f1)
assert_eq Q7 "convergence is order-free (identical trees)" "$FP_BASE_FIRST" "$FP_OVERLAY_FIRST"

# ---------- Q7b: converge ONE layer only ----------
# CopyRoom's stated invariant: one layer's update never reaches another layer's
# files. Here it should fall out of the graph for free.
W3=$(workdir layers-single)
new_repo "$W3/project"
cd "$W3/project" || exit 2

B0=$(commit_render "$FIXTURES/base-v1" "template: render base v1")
jjq new 'root()'
O0=$(commit_render "$FIXTURES/overlay-v1" "template: render overlay v1")
jjq new "$B0" "$O0" -m "scaffold: base + overlay"
printf 'notes\n' > NOTES.md
jjq commit -m "project: work"
P=$(commit_id @-)
jjq new "$B0"
B1=$(commit_render "$FIXTURES/base-v2" "template: render base v2")

require_dag "$B0" "$P" "$B1"
merge_under_test Q7 "$P" "$B1" -m "converge: base layer only"
assert_clean Q7 "converging one layer alone is clean"
assert_file_has Q7 "the converged layer advanced"            pyproject.toml "line-length = 120"
assert_file_has Q7 "the OTHER layer stayed at v1 (isolation)" .overlay/README.md "overlay v1"
assert_absent   Q7 "the other layer's v2 file did not appear" docs/guide.md
note "this is the independent-convergence invariant, with no -a flag involved"

summary
