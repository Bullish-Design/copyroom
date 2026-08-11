"""Copier subprocess wrapper.

Uses ``subprocess.run`` to invoke Copier rather than its Python API.
This isolates Copier errors cleanly, makes stderr forwarding trivial,
and avoids coupling to Copier's internal API.

Two Copier flags are easy to confuse, so both wrappers name them apart:

* ``data_file`` → ``--data-file``: a YAML file of *answer values* fed **into**
  a render (a workshop scenario, or a project's recorded answers replayed
  against an edited template).
* ``answers_file`` → ``-a/--answers-file``: the path Copier **records the link
  at**, relative to the destination. This is what makes template *layers*
  possible — one repo managed by several templates, each with its own answers
  file (see ``copyroom/project/layers.py``).
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
    data_file: Path | None = None,
    vcs_ref: str | None = None,
    answers_file: str | Path | None = None,
    timeout: int = _COPIER_TIMEOUT,
) -> subprocess.CompletedProcess[str]:
    """Run ``copier copy`` and return the result.

    Parameters
    ----------
    source:
        Template source (local path or git URL).
    destination:
        Directory to create the project in.
    data_file:
        Optional YAML file of answer values to render with (``--data-file``).
    vcs_ref:
        Optional VCS ref (tag / branch / commit) to render. Without it Copier
        renders the latest tag, which is wrong when rendering an edit branch;
        the template-edit workflow passes the scratch branch here.
    answers_file:
        Optional path (relative to *destination*) for the answers file Copier
        records, e.g. ``.copier-answers.my-ai.yml``. Omit for the template's own
        default — the base layer's ``.copier-answers.yml``.
    timeout:
        Seconds to wait before raising ``subprocess.TimeoutExpired``.
    """
    cmd = ["copier", "copy", "--quiet", "--defaults"]
    if vcs_ref is not None:
        cmd.extend(["--vcs-ref", vcs_ref])
    if data_file is not None:
        cmd.extend(["--data-file", str(data_file)])
    if answers_file is not None:
        cmd.extend(["--answers-file", str(answers_file)])
    cmd.extend([source, str(destination)])
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def copier_update(
    destination: Path,
    vcs_ref: str | None = None,
    exclude: list[str] | None = None,
    answers_file: str | Path | None = None,
    timeout: int = _COPIER_TIMEOUT,
) -> subprocess.CompletedProcess[str]:
    """Run ``copier update`` and return the result.

    Parameters
    ----------
    destination:
        Project directory to update.
    vcs_ref:
        Optional VCS ref (tag / branch) to update to.
    exclude:
        Optional shell-style patterns of files/folders the template must stop
        managing (mapped from ``agent.overlay`` — the permanently-diverge
        contract). Each is passed as a ``-x/--exclude`` flag.
    answers_file:
        Optional path (relative to *destination*) of the answers file to update
        from — i.e. **which layer** to converge. Omit for the base layer's
        ``.copier-answers.yml``.
    timeout:
        Seconds to wait before raising ``subprocess.TimeoutExpired``.
    """
    cmd = ["copier", "update", "--defaults"]
    if vcs_ref is not None:
        cmd.extend(["--vcs-ref", vcs_ref])
    for pattern in exclude or []:
        cmd.extend(["--exclude", pattern])
    if answers_file is not None:
        cmd.extend(["--answers-file", str(answers_file)])
    cmd.append(str(destination))
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
