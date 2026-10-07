#!/usr/bin/env bash
# Run inside spike 12's devenv shell. All generated state stays in this spike.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p evidence

show_input() {
  devenv shell -- bash -c 'cat "$SPIKE_TEMPLATE_PATH/value.txt"; printf "INPUT_PATH=%s\n" "$SPIKE_TEMPLATE_PATH"'
}

printf 'devenv: '
devenv --version
printf 'template version one\n' > template/value.txt
printf '\n=== path input: baseline with fresh evaluation ===\n'
devenv shell --refresh-eval-cache -- bash -c 'cat "$SPIKE_TEMPLATE_PATH/value.txt"; printf "INPUT_PATH=%s\n" "$SPIKE_TEMPLATE_PATH"'
cp devenv.lock evidence/lock-before-update.json
sha256sum devenv.lock

printf 'template version two\n' > template/value.txt
printf '\n=== path input: normal shell after edit ===\n'
show_input
printf '\n=== path input: devenv update local-template ===\n'
devenv update local-template > evidence/update-output.txt 2>&1
sha256sum devenv.lock
printf '\n=== path input: normal shell after update ===\n'
show_input
printf '\n=== path input: refresh evaluation cache ===\n'
devenv shell --refresh-eval-cache -- bash -c 'cat "$SPIKE_TEMPLATE_PATH/value.txt"; printf "INPUT_PATH=%s\n" "$SPIKE_TEMPLATE_PATH"'
cp devenv.lock evidence/lock-after-update.json
sha256sum devenv.lock

printf '\n=== path input from local jj repository ===\n'
if [ ! -d .devenv/state/template-repo/.jj ]; then
  mkdir -p .devenv/state/template-repo
  (cd .devenv/state/template-repo && jj git init --colocate)
  printf 'repo version one\n' > .devenv/state/template-repo/value.txt
  (cd .devenv/state/template-repo && jj commit -m 'template v1')
fi
cd repo-case
printf 'repo version one\n' > ../.devenv/state/template-repo/value.txt
devenv shell --refresh-eval-cache -- bash -c 'cat "$SPIKE_TEMPLATE_PATH/value.txt"; printf "INPUT_PATH=%s\n" "$SPIKE_TEMPLATE_PATH"'
cp devenv.lock ../evidence/repo-lock-before-edit.json
printf 'repo version two uncommitted\n' > ../.devenv/state/template-repo/value.txt
devenv shell -- bash -c 'cat "$SPIKE_TEMPLATE_PATH/value.txt"; printf "INPUT_PATH=%s\n" "$SPIKE_TEMPLATE_PATH"'
cp devenv.lock ../evidence/repo-lock-after-edit.json
sha256sum devenv.lock
