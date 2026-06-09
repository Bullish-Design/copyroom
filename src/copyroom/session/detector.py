"""Mode detection by walking ancestor directories for markers.

Maps to DetectWorkshopMode / DetectProjectMode rules in
copyroom-session.allium (L38-L84).
"""

from __future__ import annotations

from pathlib import Path

from .model import CLIMode


def is_workshop(path: Path) -> bool:
    """Check if *path* contains workshop markers.

    Workshop markers (from DetectWorkshopMode guidance):
        ancestor contains ``copyroom.yml`` AND subdirectory ``registry/``
        AND subdirectory ``scenarios/``.
    """
    return (
        (path / "copyroom.yml").is_file()
        and (path / "registry").is_dir()
        and (path / "scenarios").is_dir()
    )


def is_project(path: Path) -> bool:
    """Check if *path* contains project markers.

    Project markers (from DetectProjectMode guidance):
        ancestor contains ``.copier-answers.yml`` OR ``copyroom.project.yml``.
    """
    return (path / ".copier-answers.yml").is_file() or (
        path / "copyroom.project.yml"
    ).is_file()


def detect_mode(cwd: str | Path | None = None) -> CLIMode | None:
    """Walk up ancestors from *cwd* to root, detecting the mode.

    Resolution rules (see §10.4 of the implementation plan):

    1. Start at *cwd* (or ``Path.cwd()``), walk up each ancestor.
    2. At each ancestor, check workshop markers first, then project markers.
    3. The **closest ancestor** with any marker wins (proximity over
       mode-type priority).
    4. If no ancestor matches, return ``None`` → ``unknown_mode``.

    Returns
    -------
    CLIMode or None
        ``CLIMode.workshop``, ``CLIMode.project``, or ``None`` when
        no markers are found.
    """
    if cwd is None:
        cwd = Path.cwd()
    elif isinstance(cwd, str):
        cwd = Path(cwd)

    # Walk ancestors including cwd itself. Proximity wins across levels (the
    # closest ancestor with any marker decides); within a *single* directory
    # that has both marker sets, workshop takes priority over project.
    for ancestor in [cwd.resolve()] + list(cwd.resolve().parents):
        if is_workshop(ancestor):
            return CLIMode.workshop
        if is_project(ancestor):
            return CLIMode.project

    return None  # → unknown_mode


def detect_workshop_root(cwd: str | Path | None = None) -> Path | None:
    """Walk up ancestors from *cwd* to find the workshop root.

    Returns the first ancestor that contains workshop markers
    (``copyroom.yml`` + ``registry/`` + ``scenarios/``), or ``None``
    if no workshop root is found.

    This is the path that Phase 4 (release checks) and other workshop
    commands use to locate ``scenarios/``, ``registry/``, and
    ``copyroom.yml`` without hard-coding ``Path.cwd()``.

    Returns
    -------
    Path or None
        The workshop root directory, or ``None`` if no workshop is found.
    """
    if cwd is None:
        cwd = Path.cwd()
    elif isinstance(cwd, str):
        cwd = Path(cwd)

    for ancestor in [cwd.resolve()] + list(cwd.resolve().parents):
        if is_workshop(ancestor):
            return ancestor

    return None
