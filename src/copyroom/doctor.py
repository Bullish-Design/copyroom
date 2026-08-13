"""Environment precondition checks for CopyRoom (`copyroom doctor`).

These checks answer "is this machine able to run CopyRoom at all?" — Copier is
importable at a supported version, git is on PATH, and the template cache is
writable. They are *environment* checks: unlike ``inspect``/``status`` they need
no managed project and run in any directory. RepoMan's conductor drives every
manager's ``doctor`` uniformly; this is CopyRoom's conforming implementation.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from importlib.metadata import version as _pkg_version
from pathlib import Path

from pydantic import BaseModel

from .template.workspace import _cache_root  # reuse the real cache resolver


class DoctorCheck(BaseModel):
    """A single environment check and its outcome.

    ``warn_only`` marks advisory checks (e.g. the ``agent-files`` convention
    check): a failed warn-only check is reported but does **not** fail the
    aggregate report — flipping it to fail is a deliberate later decision.
    """

    name: str
    ok: bool
    detail: str = ""
    warn_only: bool = False


class DoctorReport(BaseModel):
    """The aggregate of all environment checks."""

    checks: list[DoctorCheck]

    @property
    def ok(self) -> bool:
        """True when every non-warn-only check passes."""
        return all(c.ok for c in self.checks if not c.warn_only)

    def to_dict(self) -> dict:
        return self.model_dump()


def _check_copier() -> DoctorCheck:
    try:
        import copier  # noqa: F401

        v = _pkg_version("copier")
    except Exception as exc:  # ImportError or metadata missing
        return DoctorCheck(name="copier", ok=False, detail=f"not importable: {exc}")
    # pyproject pins copier>=9.15.1,<10
    major = int(v.split(".")[0])
    ok = 9 <= major < 10
    return DoctorCheck(name="copier", ok=ok, detail=f"{v}" + ("" if ok else " (need >=9.15,<10)"))


def _check_git() -> DoctorCheck:
    if shutil.which("git") is None:
        return DoctorCheck(name="git", ok=False, detail="not found on PATH")
    try:
        out = subprocess.run(["git", "--version"], capture_output=True, text=True, timeout=5)
        return DoctorCheck(name="git", ok=out.returncode == 0, detail=out.stdout.strip())
    except Exception as exc:
        return DoctorCheck(name="git", ok=False, detail=str(exc))


def _check_cache() -> DoctorCheck:
    root = _cache_root()
    try:
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=root, delete=True):
            pass
        return DoctorCheck(name="cache", ok=True, detail=str(root))
    except Exception as exc:
        return DoctorCheck(name="cache", ok=False, detail=f"{root}: {exc}")


def _check_agent_files(target: str | Path | None = None) -> DoctorCheck:
    """Warn-level convention check: the cwd's agent-files conformance.

    Reuses ``agent-files check`` and is deliberately ``warn_only``: a repo that
    hasn't adopted the convention (or has drifted) is reported, never fatal.
    """
    from .agent.files import check_agent_files, resolve_target

    report = check_agent_files(resolve_target(target))
    summary = (
        "conformant"
        if report.ok
        else "non-conformant — run 'copyroom agent-files check' for details"
    )
    return DoctorCheck(
        name="agent-files",
        ok=report.ok,
        detail=summary,
        warn_only=True,
    )


def _check_template_source(target: str | Path | None = None) -> DoctorCheck:
    """Warn-level check: every recorded layer's ``_src_path`` still resolves.

    A local template source that has moved (or was recorded as a bare directory
    name, which Copier resolves against the invocation directory) makes
    ``update`` impossible, and nothing else surfaces it until an update fails.
    Remote sources are reported unchecked — validating them needs the network.

    ``warn_only`` because ``doctor`` runs anywhere: an unmanaged directory has no
    layers, and a moved template is a repair task, not a broken machine.
    """
    from .agent.files import resolve_target
    from .project.layers import discover_layers, source_status

    root = resolve_target(target)
    layers = discover_layers(root)
    if not layers:
        return DoctorCheck(name="template-source", ok=True, detail="no managed layers here", warn_only=True)

    broken = []
    for layer in layers:
        status, detail = source_status(layer, root)
        if status == "missing":
            broken.append(f"{layer.name}: {detail}")
    if broken:
        return DoctorCheck(
            name="template-source",
            ok=False,
            detail="unresolvable: " + "; ".join(broken),
            warn_only=True,
        )
    return DoctorCheck(
        name="template-source",
        ok=True,
        detail=f"{len(layers)} layer(s) resolve",
        warn_only=True,
    )


def run_doctor() -> DoctorReport:
    """Run every environment check and return the aggregate report."""
    return DoctorReport(
        checks=[
            _check_copier(),
            _check_git(),
            _check_cache(),
            _check_agent_files(),
            _check_template_source(),
        ]
    )


def format_doctor_report(report: DoctorReport) -> str:
    """Render *report* as plain text (one line per check)."""
    lines = []
    for c in report.checks:
        if c.warn_only:
            mark = "WARN " if not c.ok else "OK  "
        else:
            mark = "OK  " if c.ok else "✗   "
        lines.append(f"{mark}{c.name}" + (f" — {c.detail}" if c.detail else ""))
    return "\n".join(lines)
