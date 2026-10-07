#!/usr/bin/env bash
# Run inside spike 12's devenv shell. The local template repo is disposable.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p evidence .devenv/state
repo="$PWD/.devenv/state/template-repo"
marker="$PWD/.devenv/state/template-repo.spike-owned"
if [ -e "$repo" ] && [ ! -e "$marker" ]; then
  echo 'Refusing to replace a repo without the spike marker.' >&2
  exit 2
fi
rm -rf "$repo"
mkdir -p "$repo"
printf 'spike-owned\n' > "$marker"
(cd "$repo" && jj git init --colocate)
printf 'version one\n' > "$repo/value.txt"
(cd "$repo" && jj commit -m 'template v1' && jj bookmark create main -r @-)

printf 'devenv: '
devenv --version
printf '\n=== committed version one ===\n'
(cd "$repo" && jj log --no-graph -r main -T commit_id)
printf '\n'
devenv shell --refresh-eval-cache -- bash -c 'cat "$SPIKE_TEMPLATE_PATH/value.txt"; printf "INPUT_PATH=%s\n" "$SPIKE_TEMPLATE_PATH"'
cp devenv.lock evidence/lock-v1.json
sha256sum devenv.lock

printf 'version two\n' > "$repo/value.txt"
printf '\n=== uncommitted edit; fresh evaluation ===\n'
devenv shell --refresh-eval-cache -- bash -c 'cat "$SPIKE_TEMPLATE_PATH/value.txt"; printf "INPUT_PATH=%s\n" "$SPIKE_TEMPLATE_PATH"'
sha256sum devenv.lock

(cd "$repo" && jj commit -m 'template v2' && jj bookmark set main -r @-)
printf '\n=== committed version two, before devenv update ===\n'
(cd "$repo" && jj log --no-graph -r main -T commit_id)
printf '\n'
devenv shell --refresh-eval-cache -- bash -c 'cat "$SPIKE_TEMPLATE_PATH/value.txt"; printf "INPUT_PATH=%s\n" "$SPIKE_TEMPLATE_PATH"'
cp devenv.lock evidence/lock-v2-before-update.json
sha256sum devenv.lock

printf '\n=== devenv update local-template ===\n'
devenv update local-template > evidence/update-output.txt 2>&1
cp devenv.lock evidence/lock-v2-after-update.json
sha256sum devenv.lock
devenv shell --refresh-eval-cache -- bash -c 'cat "$SPIKE_TEMPLATE_PATH/value.txt"; printf "INPUT_PATH=%s\n" "$SPIKE_TEMPLATE_PATH"'
