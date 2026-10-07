#!/usr/bin/env bash
set -euo pipefail

cd "$DEVENV_ROOT"
demo_root=$(mktemp -d "$DEVENV_STATE/slice-walkthrough-XXXXXX")
cp -R example "$demo_root/source"

uv run python slice.py new \
  --source "$demo_root/source" \
  --target "$demo_root/project" \
  --answers "$demo_root/source/answers.json"

cat >> "$demo_root/source/templates/settings/template.j2" <<'EOF'
revision: "v2"
EOF

uv run python slice.py preview \
  --project "$demo_root/project" \
  --out "$demo_root/preview"

uv run python slice.py update \
  --project "$demo_root/project" \
  --preview "$demo_root/preview"

uv run python slice.py status --project "$demo_root/project"
printf 'demo %s\n' "$demo_root"
