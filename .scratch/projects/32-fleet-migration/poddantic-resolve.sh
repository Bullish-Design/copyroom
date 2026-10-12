#!/usr/bin/env bash
# Pilot resolution recipe for poddantic (template-py v0.5.0 -> v0.8.0).
# Usage: poddantic-resolve.sh PREVIEW_DIR
# Run it in the CopyRoom devenv shell. P = project side, T = template side.
# The recipe records the choices of the pilot. Other repos need their own review.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
cd "$1"
pick() { python3 -I "$here/pick_sides.py" "$@"; }

pick .gitignore T T          # agent-link comment and names: the template is newer
pick AGENTS.md T T T T       # Testee 0.6 text: same meaning, newer words in the template
pick README.md T T T
pick devenv.yaml T T         # the pins are equal once the answers match devenv.yaml
# devenv.nix: header T, imports T, comment T, prepare T, four checks P, tasks P
pick devenv.nix T T T T P P P P P
rm -f copyroom.project.yml   # v0.8.0 drops this file on purpose

# pyproject.toml has one hunk: keep the project's extras table, take the template comment.
tmp=$(mktemp)
cat > "$tmp" <<'TXT'
[project.optional-dependencies]
# Live infra is lazily imported behind these extras — the pure core (models, config,
# sweep, events, _types, lifecycle) never needs them.
cloud = ["runpod>=1.6", "paramiko>=3.4"]  # RunPod provider: pod lifecycle + SSH/SFTP
s3 = ["boto3>=1.34"]                        # RunPod volume storage: pod-free S3 I/O

# The dev group declares the check tools (pytest, ruff, ty) directly: Testee
# carries none of them. Testee is a host-profile command, not a dependency of
# this project. `testee.prepare` in devenv.nix runs `uv sync --locked`, so keep
# `uv.lock` in Git. Testee's Nix module in devenv.nix declares the checks.
# The host profile puts the managers (copyroom, gitman) and `testee` on PATH.
TXT
pick pyproject.toml "@$tmp"
rm -f "$tmp"

# devenv.nix now holds `testee.prepare` twice (project copy and template copy).
# Keep the template copy and re-add the project's comment on its checks.
python3 -I - <<'PY'
import pathlib
p = pathlib.Path("devenv.nix"); s = p.read_text()
line = '  testee.prepare = [ [ "uv" "sync" "--locked" ] ];\n'
top = line + "\n"
assert s.count(line) == 2, "expected two prepare lines"
s = s.replace(top, "", 1)
note = line + '''
  # Repo-specific checks (kept against the template's `src tests` argv): they
  # cover the whole tree, and the plain pytest invocation keeps the offline
  # discipline. pyproject addopts carry `-m 'not live'`, and tests/live refuses
  # collection unless PODDANTIC_LIVE=1 - no extras, no credentials, in any profile.
'''
s = s.replace(line, note, 1)
p.write_text(s)
PY
echo "resolved; next: jj squash --from @ --into <first conflicted change>"
