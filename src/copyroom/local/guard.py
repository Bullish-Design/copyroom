"""Find and call pyjutsu's guarded publication command."""

from __future__ import annotations

import os
import re
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
# jj 0.45 and later record a Git HEAD for each workspace. An older jj-lib drops the Git
# HEAD of every workspace except `default` when it writes an operation.
CHILD_SAFE_JJ_LIB = (0, 45)
VERSION_LINE = re.compile(r"^pyjutsu (\S+) \(jj-lib (\S+)\)\s*$")


@dataclass(frozen=True)
class Guard:
    """One resolved pyjutsu executable that supports guarded publication."""

    path: str
    version: str | None
    jj_lib: str | None = None

    def describe(self) -> dict[str, object]:
        return {"guard": True, "path": self.path, "version": self.version, "jj_lib": self.jj_lib}

    def keeps_child_git_head(self) -> bool:
        """Tell whether this build keeps the Git HEAD of a child workspace.

        Only the jj-lib version decides. A build that reports none is old: pyjutsu
        0.23 has no `--version` probe.
        """

        jj_lib = _release(self.jj_lib)
        return jj_lib is not None and jj_lib[:2] >= CHILD_SAFE_JJ_LIB


@dataclass
class GuardResult:
    """The parsed `key=value` output of one pyjutsu command."""

    code: int
    fields: dict[str, str] = field(default_factory=dict)
    stderr: str = ""

    @property
    def result(self) -> str:
        return self.fields.get("result", "")


def _release(text: str | None) -> tuple[int, ...] | None:
    """Read the numeric release parts of a version such as `0.44.0`."""

    match = re.match(r"\d+(?:\.\d+)*", text or "")
    return tuple(int(part) for part in match.group().split(".")) if match else None


def is_colocated_child_workspace(project: Path) -> bool:
    """Tell whether `project` is a colocated jj workspace that is a Git worktree.

    `jj workspace add --colocate` writes a `.git` file there. It reads
    `gitdir: <repo>/.git/worktrees/NAME`. The main repository and a workspace without
    `--colocate` have no such file. A Git submodule has one, but it points into `modules`.
    """

    marker = project / ".git"
    if not marker.is_file():
        return False
    try:
        lines = marker.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return False
    for line in lines:
        key, separator, value = line.partition(":")
        if separator and key.strip() == "gitdir":
            return (project / value.strip()).resolve().parent.name == "worktrees"
    return False


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


def _interpreter(path: str) -> str | None:
    """Find the Python that runs a pyjutsu script: its shebang, else a sibling python."""

    try:
        with open(path, "rb") as stream:
            first = stream.readline().decode("utf-8", "replace").strip()
    except OSError:
        return None
    if first.startswith("#!"):
        parts = first[2:].split()
        if parts and os.path.isabs(parts[0]) and not parts[0].endswith("/env"):
            return parts[0]
    sibling = Path(path).parent / "python"
    return str(sibling) if sibling.exists() else None


def _versions(path: str) -> tuple[str | None, str | None]:
    """Read the pyjutsu version and its jj-lib version.

    pyjutsu 0.24.0 and later print `pyjutsu VERSION (jj-lib VERSION)` for `--version`.
    Older builds have no such flag. For them, ask the script's interpreter instead.
    """

    try:
        probed = subprocess.run(
            [path, "--version"], text=True, capture_output=True, check=False,
            timeout=PROBE_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        probed = None
    if probed is not None and probed.returncode == 0:
        match = VERSION_LINE.match(probed.stdout.strip())
        if match:
            return match.group(1), match.group(2)
    return _interpreter_versions(path)


def _interpreter_versions(path: str) -> tuple[str | None, str | None]:
    python = _interpreter(path)
    if python is None:
        return None, None
    code = (
        "import pyjutsu; print(pyjutsu.__version__); "
        "print(getattr(pyjutsu, 'JJ_VERSION', ''))"
    )
    try:
        completed = subprocess.run(
            [python, "-c", code], text=True, capture_output=True, check=False,
            timeout=PROBE_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None, None
    if completed.returncode != 0:
        return None, None
    lines = [*completed.stdout.splitlines(), "", ""]
    return lines[0].strip() or None, lines[1].strip() or None


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
    return Guard(path, *_versions(path))


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
    "is_colocated_child_workspace", "resolve_guard", "unguarded_requested",
]
