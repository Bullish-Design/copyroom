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

from pydantic import BaseModel

from .template.workspace import _cache_root  # reuse the real cache resolver


class DoctorCheck(BaseModel):
    """A single environment check and its outcome."""

    name: str
    ok: bool
    detail: str = ""


class DoctorReport(BaseModel):
    """The aggregate of all environment checks."""

    checks: list[DoctorCheck]

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

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


def run_doctor() -> DoctorReport:
    """Run every environment check and return the aggregate report."""
    return DoctorReport(checks=[_check_copier(), _check_git(), _check_cache()])


def format_doctor_report(report: DoctorReport) -> str:
    """Render *report* as plain text (one line per check)."""
    lines = []
    for c in report.checks:
        mark = "OK  " if c.ok else "✗   "
        lines.append(f"{mark}{c.name}" + (f" — {c.detail}" if c.detail else ""))
    return "\n".join(lines)
