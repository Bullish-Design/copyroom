"""Find and call pyjutsu's guarded publication command."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .errors import LocalError

GUARD_ENV = "COPYROOM_PYJUTSU"
UNGUARDED_ENV = "COPYROOM_PUBLISH_UNGUARDED"
PROBE_ID = "0" * 40
PROBE_SECONDS = 30


@dataclass(frozen=True)
class Guard:
    """One resolved pyjutsu executable that supports guarded publication."""

    path: str
    version: str | None

    def describe(self) -> dict[str, object]:
        return {"guard": True, "path": self.path, "version": self.version}


@dataclass
class GuardResult:
    """The parsed `key=value` output of one pyjutsu command."""

    code: int
    fields: dict[str, str] = field(default_factory=dict)
    stderr: str = ""

    @property
    def result(self) -> str:
        return self.fields.get("result", "")


def _parse(stdout: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            fields[key] = value
    return fields


def _run(path: str, *args: str) -> GuardResult:
    try:
        completed = subprocess.run(
            [path, *args], text=True, capture_output=True, check=False,
            timeout=PROBE_SECONDS if args[:1] != ("publish-if",) else None,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LocalError(f"cannot run {path}: {exc}", 2) from exc
    return GuardResult(completed.returncode, _parse(completed.stdout), completed.stderr)


def _version(path: str) -> str | None:
    """Read the pyjutsu version from the Python that sits beside the script."""

    python = Path(path).parent / "python"
    if not python.exists():
        return None
    try:
        completed = subprocess.run(
            [str(python), "-c", "import pyjutsu; print(pyjutsu.__version__)"],
            text=True, capture_output=True, check=False, timeout=PROBE_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return completed.stdout.strip() or None if completed.returncode == 0 else None


@lru_cache(maxsize=8)
def _probe(path: str) -> Guard | None:
    """Confirm that the executable guards publication by making it fail in a known way.

    A version number cannot prove the capability. The probe names a repository that
    does not exist. A guard answers with `result=error reason=repo-not-found` and exit 2.
    """

    try:
        helped = subprocess.run(
            [path, "--help"], text=True, capture_output=True, check=False,
            timeout=PROBE_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if "publish-if" not in helped.stdout + helped.stderr:
        return None
    with tempfile.TemporaryDirectory(prefix="copyroom-probe-") as scratch:
        try:
            probed = _run(
                path, "publish-if", "--repo", str(Path(scratch) / "absent"),
                "--expect-wc", PROBE_ID, "--onto", PROBE_ID, "-m", "copyroom capability probe",
            )
        except LocalError:
            return None
    if probed.code != 2 or probed.fields.get("reason") != "repo-not-found":
        return None
    return Guard(path, _version(path))


def resolve_guard() -> Guard | None:
    """Return the guard named by COPYROOM_PYJUTSU, or the one on PATH, when it works."""

    named = os.environ.get(GUARD_ENV) or shutil.which("pyjutsu")
    if not named:
        return None
    path = os.path.abspath(named)
    if not (os.path.isfile(path) and os.access(path, os.X_OK)):
        return None
    return _probe(path)


def unguarded_requested(flag: bool) -> bool:
    """Tell whether the caller chose the weaker publication path."""

    return flag or os.environ.get(UNGUARDED_ENV) == "1"


def publish_if(
    guard: Guard,
    repo: Path,
    expect_wc: str,
    onto: str,
    description: str,
) -> GuardResult:
    """Run one guarded publication."""

    return _run(
        guard.path, "publish-if", "--repo", str(repo), "--expect-wc", expect_wc,
        "--onto", onto, "-m", description,
    )


def recover(guard: Guard, repo: Path) -> GuardResult:
    """Finish a publication that stopped after its operation landed."""

    return _run(guard.path, "recover", "--repo", str(repo))


__all__ = [
    "GUARD_ENV", "UNGUARDED_ENV", "Guard", "GuardResult", "publish_if", "recover",
    "resolve_guard", "unguarded_requested",
]
