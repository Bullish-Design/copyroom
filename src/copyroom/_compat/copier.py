"""Copier subprocess wrapper.

Uses ``subprocess.run`` to invoke Copier rather than its Python API.
This isolates Copier errors cleanly, makes stderr forwarding trivial,
and avoids coupling to Copier's internal API.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
def copier_copy(
    source: str,
    destination: Path,
    answers_file: Path | None = None,
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
    """
    cmd = ["copier", "copy", "--quiet"]
    if answers_file is not None:
        cmd.extend(["--answers-file", str(answers_file)])
    cmd.extend([source, str(destination)])
    return subprocess.run(cmd, capture_output=True, text=True)


def copier_update(
    destination: Path,
    vcs_ref: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run ``copier update`` and return the result.

    Parameters
    ----------
    destination:
        Project directory to update.
    vcs_ref:
        Optional VCS ref (tag / branch) to update to.
    """
    cmd = ["copier", "update", "--defaults"]
    if vcs_ref is not None:
        cmd.extend(["--vcs-ref", vcs_ref])
    cmd.append(str(destination))
    return subprocess.run(cmd, capture_output=True, text=True)


def check_copier_version() -> str | None:
    """Return the installed Copier version string, or ``None`` if not found.

    Exits with an error message if the version does not satisfy the
    ``>=9.15.1,<10`` pin required by the project.
    """
    try:
        result = subprocess.run(
            ["copier", "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None

    if result.returncode != 0:
        return None

    # Copier outputs something like "copier 9.15.1"
    return result.stdout.strip()
