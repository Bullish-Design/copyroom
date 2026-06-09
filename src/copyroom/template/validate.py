"""Render-test an edited template — ``copyroom template-test``.

Renders the project's template (from the scratch edit branch) using the
project's own recorded answers into a throwaway directory and confirms it
generates cleanly. An optional ``--check`` command runs against the output.

This catches "the edit broke rendering" early, with a clear message, before the
heavier update preview.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from .._compat import gitutil
from .._compat.copier import copier_copy
from .._compat.errors import CopyRoomError
from .model import ValidateResult
from .workspace import checkout_template, resolve_project_root

__all__ = ["CopyRoomError", "validate_template"]

_CHECK_TIMEOUT = 120


def validate_template(
    project_root: str | Path | None = None,
    from_ref: str | None = None,
    check_cmd: str | None = None,
) -> ValidateResult:
    """Render the edited template with the project's answers; report success.

    Resolves (idempotently) the same scratch worktree ``template-checkout``
    created, commits the agent's pending edits onto the edit branch so they are
    rendered, then runs ``copier copy`` into a temp dir.
    """
    root = resolve_project_root(project_root)
    answers_file = root / ".copier-answers.yml"

    checkout = checkout_template(root, from_ref)
    assert (
        checkout.worktree_dir is not None
        and checkout.branch is not None
        and checkout.repo_dir is not None
    )

    # Commit pending edits so Copier (which renders a ref, not the worktree's
    # uncommitted files) sees them on the edit branch.
    gitutil.commit_all(checkout.worktree_dir, "copyroom: template edits (test)")

    out = Path(tempfile.mkdtemp(prefix="copyroom_tmpl_test_"))
    result = ValidateResult(output_dir=str(out))

    try:
        rendered = copier_copy(
            source=str(checkout.repo_dir),
            destination=out,
            answers_file=answers_file,
            vcs_ref=checkout.branch,
        )
    except Exception as exc:
        result.ok = False
        result.messages.append(f"Copier render failed: {exc}")
        return result

    if rendered.returncode != 0:
        result.ok = False
        result.messages.append("Template did not render cleanly.")
        if rendered.stderr:
            result.messages.append(rendered.stderr.strip())
        return result

    if check_cmd:
        try:
            check = subprocess.run(
                check_cmd,
                shell=True,
                cwd=str(out),
                capture_output=True,
                text=True,
                timeout=_CHECK_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            result.ok = False
            result.messages.append(f"Check timed out ({_CHECK_TIMEOUT}s): {check_cmd}")
            return result
        if check.returncode != 0:
            result.ok = False
            result.messages.append(f"Check failed (exit {check.returncode}): {check_cmd}")
            if check.stderr:
                result.messages.append(check.stderr.strip())
            return result

    result.ok = True
    result.messages.append("Template renders cleanly with the project's answers.")
    return result
