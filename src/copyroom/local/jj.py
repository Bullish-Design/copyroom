"""Plain jj commands used by the local workflow."""

from __future__ import annotations

import fcntl
import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .errors import LocalError
from .source import LOCK_FILE


class JJ:
    """Run jj with argument lists and preserve command output."""

    def __init__(self, cwd: Path) -> None:
        self.cwd = cwd

    def run(self, *args: str, allow_no_conflicts: bool = False) -> str:
        """Run one jj command and return stdout."""

        if shutil.which("jj") is None:
            raise LocalError("jj is required for local project workflows")
        result = subprocess.run(
            ["jj", *args], cwd=self.cwd, text=True, capture_output=True, check=False,
        )
        if allow_no_conflicts and result.returncode == 2 and "No conflicts found" in result.stderr:
            return ""
        if result.returncode:
            detail = result.stderr.strip() or result.stdout.strip()
            raise LocalError(f"jj {' '.join(args)} failed ({result.returncode}): {detail}")
        return result.stdout

    def commit_id(self, rev: str) -> str:
        """Return one full commit ID."""

        value = self.run("log", "--no-graph", "-r", rev, "-T", "commit_id").strip()
        if len(value) != 40:
            raise LocalError(f"expected one commit for {rev}, got {value!r}")
        return value

    def tracked_paths(self, rev: str = "@") -> set[str]:
        """Return paths in one revision's tracked tree."""

        output = self.run("file", "list", "-r", rev)
        return {line for line in output.splitlines() if line}

    def operation_id(self) -> str:
        """Return the current operation ID."""

        return self.run(
            "op", "log", "--at-op=@", "--ignore-working-copy", "--no-graph", "-n", "1",
            "-T", "id",
        ).strip()

    def operation_parents(self, operation: str) -> list[str]:
        """Return the parent operation IDs for one operation."""

        output = self.run(
            "op", "log", f"--at-op={operation}", "--no-graph", "-n", "1", "-T",
            'parents.map(|parent| parent.id()).join(" ")',
        )
        return output.split()

    def conflicts(self) -> list[str]:
        """List paths with unresolved jj conflicts."""

        output = self.run("resolve", "--list", allow_no_conflicts=True)
        return [line.split()[0] for line in output.splitlines() if line.strip()]

    def render_head(self, project_id: str, layer: str = "base") -> str:
        """Find the visible render head for a project."""

        expression = f'heads(::@ & subject(glob:"copyroom:render {project_id} {layer} *"))'
        lines = self.run(
            "log", "--no-graph", "-r", expression, "-T", 'commit_id ++ "\\n"',
        ).splitlines()
        if len(lines) != 1:
            raise LocalError(f"expected one render head, found {len(lines)}")
        return lines[0]

    def render_heads(self, project_id: str) -> list[tuple[str, str]]:
        """Return every visible render head and its subject for one project."""

        expression = f'heads(::@ & subject(glob:"copyroom:render {project_id} *"))'
        output = self.run(
            "log", "--no-graph", "-r", expression, "-T",
            'commit_id ++ "\\t" ++ description.first_line() ++ "\\n"',
        )
        rows: list[tuple[str, str]] = []
        for line in output.splitlines():
            commit_id, separator, description = line.partition("\t")
            if separator:
                rows.append((commit_id, description))
        return rows

    def workspaces(self) -> list[dict[str, str]]:
        """Return workspace names and paths for the repository."""

        output = self.run(
            "workspace", "list", "-T", 'name ++ "\\t" ++ root ++ "\\n"',
        )
        workspaces: list[dict[str, str]] = []
        for line in output.splitlines():
            name, separator, path = line.partition("\t")
            if separator:
                workspaces.append({"name": name, "path": path})
        return workspaces

    def merge_base(self, first: str, second: str) -> str:
        """Return the commit at the merge base for two revisions."""

        return self.commit_id(f"heads(::{first} & ::{second})")


@contextmanager
def project_lock(project: Path) -> Iterator[None]:
    """Hold a process-safe lock for CopyRoom project writes."""

    path = project / LOCK_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("a+b") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            yield
    except OSError as exc:
        raise LocalError(f"cannot lock project {project}: {exc}") from exc


__all__ = ["JJ", "project_lock"]
