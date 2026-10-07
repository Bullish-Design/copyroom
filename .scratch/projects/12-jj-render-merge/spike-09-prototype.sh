#!/usr/bin/env bash
# Check the separate local new/update prototype in disposable repositories.
set -euo pipefail
python3 "$DEVENV_ROOT/../13-local-jj-prototype/test_prototype.py"
