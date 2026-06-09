"""Trust-gated execution of template-supplied shell commands.

``post_project_create`` / ``post_template_update`` hooks come from a fetched
(and therefore untrusted) template's ``copyroom.project.yml``. Running them is
arbitrary code execution, so they are **skipped with a warning unless the user
opts in** with ``--trust``.

Workshop registry *checks* are deliberately not routed through here: those are
the workshop author's own commands, run on their own machine against their own
templates, and are the whole point of ``test`` / ``release-check``.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

_DEFAULT_TIMEOUT = 120


def run_hook_commands(
    commands: Iterable[str],
    cwd: Path,
    *,
    trust: bool,
    label: str,
    timeout: int = _DEFAULT_TIMEOUT,
) -> None:
    """Run *commands* in *cwd*, honoring the trust gate.

    When ``trust`` is ``False`` each command is skipped with a clear warning.
    Failures of executed commands are reported but never raise — post-hooks are
    advisory and must not block completion.
    """
    for cmd in commands:
        if not trust:
            print(
                f"Skipping {label} command (re-run with --trust to execute): {cmd}",
                file=sys.stderr,
            )
            continue
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if result.returncode != 0:
                print(
                    f"Warning: {label} command '{cmd}' failed (exit {result.returncode}):",
                    file=sys.stderr,
                )
                if result.stderr:
                    print(result.stderr, file=sys.stderr, end="")
        except subprocess.TimeoutExpired:
            print(
                f"Warning: {label} command '{cmd}' timed out after {timeout}s",
                file=sys.stderr,
            )
        except Exception as exc:  # noqa: BLE001 - advisory, never fatal
            print(
                f"Warning: {label} command '{cmd}' raised {exc}",
                file=sys.stderr,
            )
