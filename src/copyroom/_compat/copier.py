"""Copier subprocess wrapper.

Uses ``subprocess.run`` to invoke Copier rather than its Python API.
This isolates Copier errors cleanly, makes stderr forwarding trivial,
and avoids coupling to Copier's internal API.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

# Copier can clone remote templates on first use, so allow generous headroom
# before assuming it has hung. Raised as ``subprocess.TimeoutExpired``, which
# call sites already handle via their ``except Exception`` guards.
_COPIER_TIMEOUT = 300


def copier_copy(
    source: str,
    destination: Path,
    answers_file: Path | None = None,
    timeout: int = _COPIER_TIMEOUT,
) -> subprocess.CompletedProcess[str]:
    """Run ``copier copy`` and return the result.

    Parameters
    ----------
    source:
        Template source (local path or git URL).
    destination:
        Directory to create the project in.
    answers_file:
        Optional path to a YAML answers file.
    timeout:
        Seconds to wait before raising ``subprocess.TimeoutExpired``.
    """
    cmd = ["copier", "copy", "--quiet", "--defaults"]
    if answers_file is not None:
        cmd.extend(["--data-file", str(answers_file)])
    cmd.extend([source, str(destination)])
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def copier_update(
    destination: Path,
    vcs_ref: str | None = None,
    timeout: int = _COPIER_TIMEOUT,
) -> subprocess.CompletedProcess[str]:
    """Run ``copier update`` and return the result.

    Parameters
    ----------
    destination:
        Project directory to update.
    vcs_ref:
        Optional VCS ref (tag / branch) to update to.
    timeout:
        Seconds to wait before raising ``subprocess.TimeoutExpired``.
    """
    cmd = ["copier", "update", "--defaults"]
    if vcs_ref is not None:
        cmd.extend(["--vcs-ref", vcs_ref])
    cmd.append(str(destination))
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
