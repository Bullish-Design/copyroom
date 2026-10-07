# Shared helpers for spike 12. Sourced by each spike-*.sh, never run directly.
#
# Output contract, so a reader (or an evaluating agent) can parse results:
#   <QID> PASS  <description>
#   <QID> FAIL  <description>
#   ----- note  <free text>
# Each script ends with a one-line summary and exits non-zero if anything failed.
#
# HARD-WON LESSON, recorded here because it nearly produced confident wrong
# answers: the first run of this spike silently built the WRONG DAG. Two faults
# combined — `JJ_RANDOMNESS_SEED=0` in devenv.nix made every commit collide, and
# every DAG-construction `jj` call sent its output to /dev/null, so the resulting
# "Newly-created commit already exists" error was invisible. Worse, the
# assertions were too weak to notice: a T1 wrongly rooted on P still has exactly
# one parent, so a parent-COUNT check passed. Hence `jjq`, `assert_parent` and
# `require_dag` below. A spike that fails loudly is worth more than one that
# passes quietly.

set -uo pipefail

SPIKE_DIR="${DEVENV_ROOT:?DEVENV_ROOT unset — run inside devenv}"
RENDER="$SPIKE_DIR/render.py"
FIXTURES="$SPIKE_DIR/fixtures"
ANSWERS="$FIXTURES/answers.json"
: "${SPIKE_WORK:?SPIKE_WORK unset — run inside devenv}"

# jj's reproducible-id hooks corrupt this spike (see devenv.nix). Refuse to run
# if something put them back, rather than producing plausible nonsense.
if [ -n "${JJ_RANDOMNESS_SEED:-}" ] || [ -n "${JJ_TIMESTAMP:-}" ]; then
  echo "FATAL  JJ_RANDOMNESS_SEED/JJ_TIMESTAMP are set; they make every jj" >&2
  echo "       commit collide and silently corrupt the DAG. Unset them." >&2
  exit 2
fi

PASS=0
FAIL=0

ok()   { printf '%s PASS  %s\n' "$1" "$2"; PASS=$((PASS + 1)); }
bad()  { printf '%s FAIL  %s\n' "$1" "$2"; FAIL=$((FAIL + 1)); }
note() { printf '%s\n' "----- note  $*"; }

# jjq <args...> — run jj quietly, but ABORT on failure.
# Every DAG-CONSTRUCTION call goes through this. A call whose success is the
# thing under test must NOT use it: use plain `jj` and report the outcome.
jjq() {
  local out
  if ! out=$(jj "$@" 2>&1); then
    printf 'FATAL  `jj %s` failed:\n' "$*" >&2
    printf '%s\n' "$out" | sed 's/^/       /' >&2
    exit 2
  fi
}

# assert_eq <qid> <desc> <expected> <actual>
assert_eq() {
  if [ "$3" = "$4" ]; then
    ok "$1" "$2"
  else
    bad "$1" "$2"
    note "expected: $3"
    note "actual:   $4"
  fi
}

# assert_parent <qid> <desc> <expected-parent-id> <rev>
# Identity, not arity. A parent COUNT of 1 says nothing about WHICH commit.
assert_parent() { assert_eq "$1" "$2" "$3" "$(commit_id "$4-")"; }

# assert_file_has <qid> <desc> <file> <pattern>
assert_file_has() {
  if [ -f "$3" ] && grep -qF -- "$4" "$3"; then
    ok "$1" "$2"
  else
    bad "$1" "$2"
    note "no match for '$4' in $3"
    [ -f "$3" ] || note "file does not exist"
  fi
}

# assert_file_lacks <qid> <desc> <file> <pattern>
assert_file_lacks() {
  if [ -f "$3" ] && grep -qF -- "$4" "$3"; then
    bad "$1" "$2"
    note "unexpected match for '$4' in $3"
  else
    ok "$1" "$2"
  fi
}

assert_absent() {
  if [ -e "$3" ]; then bad "$1" "$2"; note "$3 still exists"; else ok "$1" "$2"; fi
}

assert_present() {
  if [ -e "$3" ]; then ok "$1" "$2"; else bad "$1" "$2"; note "$3 is missing"; fi
}

# workdir <name> -> a clean directory, echoed
workdir() {
  local d="$SPIKE_WORK/$1"
  rm -rf "$d"
  mkdir -p "$d"
  printf '%s' "$d"
}

# new_repo <path> — a colocated jj repo, matching how the family's repos are set up
new_repo() {
  mkdir -p "$1"
  (cd "$1" && jjq git init --colocate)
}

# Remove every working-copy path except the VCS dirs. Used to build T1 as an
# exact render(v2): `jj new T0` hands us T0's tree, and a template file deleted
# between v1 and v2 must actually disappear from the commit.
wipe_wc() {
  find . -mindepth 1 -maxdepth 1 ! -name .jj ! -name .git -exec rm -rf {} +
}

render_here() { python3 "$RENDER" "$1" "$ANSWERS" .; }

commit_id() { jj log --no-graph --ignore-working-copy -r "$1" -T commit_id; }

# merge_base <rev-a> <rev-b> — the greatest common ancestor, as a commit id
merge_base() {
  jj log --no-graph --ignore-working-copy -r "heads(::$1 & ::$2)" -T commit_id
}

# parent_count <revset> — counted via the `parents()` REVSET rather than a
# template method, so the helper does not depend on jj's template keywords.
parent_count() {
  jj log --no-graph --ignore-working-copy -r "parents($1)" -T 'commit_id ++ "\n"' \
    | grep -c . || true
}

# commit_render <template-dir> <message> -> echoes the new commit id
# Replaces the whole working copy with render(template), then commits. The wipe
# is what makes a file DELETED between two template versions actually disappear
# from the commit instead of lingering from the parent's tree.
commit_render() {
  wipe_wc
  render_here "$1" >/dev/null
  jjq commit -m "$2"
  commit_id @-
}

# require_dag <base> <side-a> <side-b> — abort unless the two sides really fork
# from <base>. A GUARD, not an assertion: where the fork point is a precondition
# rather than the measurement, a wrong DAG makes every later result noise.
# (spike-01 measures this instead, with assert_eq — that is its whole point.)
require_dag() {
  local mb
  mb=$(merge_base "$2" "$3")
  if [ "$mb" != "$1" ]; then
    printf 'FATAL  wrong DAG: merge-base(%.8s, %.8s) = %.8s, expected %.8s\n' \
      "$2" "$3" "$mb" "$1" >&2
    exit 2
  fi
}

# conflicted_paths — one path per line, empty when the tree is clean
conflicted_paths() { jj resolve --list 2>/dev/null | awk '{print $1}'; }

# is_conflicted <revset> — does jj itself mark the revision conflicted?
is_conflicted() {
  jj log --no-graph --ignore-working-copy -r "$1 & conflicts()" -T commit_id | grep -q .
}

# assert_clean <qid> <desc> — requires BOTH signals to agree.
# `jj resolve --list` exits 2 with "No conflicts found" on a clean tree, so an
# empty result alone could equally mean the command broke. Cross-check with the
# conflicts() revset so "clean" cannot be a false negative.
assert_clean() {
  local paths
  paths=$(conflicted_paths)
  if [ -z "$paths" ] && ! is_conflicted "@"; then
    ok "$1" "$2"
  else
    bad "$1" "$2"
    [ -n "$paths" ] && printf '%s\n' "$paths" | while read -r c; do note "conflicted: $c"; done
    is_conflicted "@" && note "jj marks @ as conflicted" || true
  fi
}

# merge_under_test <qid> <args...> — run `jj new <args>`. The operation's own
# success is part of the result here, so report a failure rather than abort.
merge_under_test() {
  local qid="$1"; shift
  local out
  if out=$(jj new "$@" 2>&1); then return 0; fi
  bad "$qid" "the merge operation itself failed"
  printf '%s\n' "$out" | sed 's/^/----- note  /'
  return 1
}

# tree_fingerprint — every tracked path plus a hash of its bytes, sorted.
tree_fingerprint() {
  find . -type f -not -path './.jj/*' -not -path './.git/*' -print0 \
    | sort -z \
    | xargs -0 -I{} sh -c 'printf "%s  " "{}"; sha256sum < "{}" | cut -d" " -f1'
}

summary() {
  printf '\n%s: %d passed, %d failed\n' "$(basename "$0")" "$PASS" "$FAIL"
  [ "$FAIL" -eq 0 ]
}
