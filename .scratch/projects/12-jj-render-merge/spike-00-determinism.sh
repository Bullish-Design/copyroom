#!/usr/bin/env bash
# Q8 — is render(template, answers) byte-identical across runs?
#
# This runs FIRST and alone because it is load-bearing: the whole design rests
# on T0 being reproducible. If the renderer drifts, merge-base(trunk, T1) points
# at a tree nobody can rebuild, and every update produces spurious conflicts.
# A failure here invalidates every other result in this spike.
source "$(dirname "$0")/lib.sh"

W=$(workdir determinism)

python3 "$RENDER" "$FIXTURES/base-v1" "$ANSWERS" "$W/a" 2>/dev/null
python3 "$RENDER" "$FIXTURES/base-v1" "$ANSWERS" "$W/b" 2>/dev/null
if diff -r "$W/a" "$W/b" >/dev/null 2>&1; then
  ok Q8 "render(base-v1) is byte-identical across two runs"
else
  bad Q8 "render(base-v1) differs between runs"
  diff -r "$W/a" "$W/b" 2>&1 | head -20 | while read -r l; do note "$l"; done
fi

python3 "$RENDER" "$FIXTURES/base-v2" "$ANSWERS" "$W/c" 2>/dev/null
python3 "$RENDER" "$FIXTURES/base-v2" "$ANSWERS" "$W/d" 2>/dev/null
if diff -r "$W/c" "$W/d" >/dev/null 2>&1; then
  ok Q8 "render(base-v2) is byte-identical across two runs"
else
  bad Q8 "render(base-v2) differs between runs"
fi

# v1 and v2 must actually differ, or every other experiment is vacuous.
if diff -r "$W/a" "$W/c" >/dev/null 2>&1; then
  bad Q8 "base-v1 and base-v2 render identically — the fixtures prove nothing"
else
  ok Q8 "base-v1 and base-v2 render differently (fixtures are meaningful)"
fi

# Path templating: `src/{{ module }}/` must become `src/demo_app/`.
assert_present Q8 "a path segment is templated (src/demo_app/)" "$W/a/src/demo_app/__init__.py"
assert_absent  Q8 "no literal brace path survives" "$W/a/src/{{ module }}"

# Strict undefined: an unknown variable must fail, not render empty.
printf 'value = "{{ nope }}"\n' > "$W/bad-template-file"
mkdir -p "$W/bad" && cp "$W/bad-template-file" "$W/bad/x.toml"
if python3 "$RENDER" "$W/bad" "$ANSWERS" "$W/bad-out" >/dev/null 2>&1; then
  bad Q8 "an undefined variable rendered silently (should be a hard error)"
else
  ok Q8 "an undefined variable is a hard error (strict undefined)"
fi

summary
