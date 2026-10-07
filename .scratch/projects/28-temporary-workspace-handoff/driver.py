"""Run one CopyRoom operation in a separate process for race experiments."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from copyroom.local.errors import LocalError
from copyroom.local.workflow import add_layer, apply, preview


def main() -> int:
    action = sys.argv[1]
    project = Path(sys.argv[2])
    if action == "preview":
        result = preview(project, Path(sys.argv[3]))
    elif action == "apply":
        result = apply(project, Path(sys.argv[3]))
    elif action == "layer-add":
        result = add_layer(project, Path(sys.argv[4]), Path(sys.argv[5]), sys.argv[6])
    else:
        raise SystemExit(f"unknown action: {action}")
    print(json.dumps({"ok": True, "result": result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except LocalError as exc:
        print(json.dumps({"ok": False, "code": exc.code, "error": str(exc)}, sort_keys=True))
        raise SystemExit(exc.code) from None
