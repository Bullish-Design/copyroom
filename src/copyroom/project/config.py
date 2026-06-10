"""Validated loader for ``copyroom.project.yml``.

This is the one place ``copyroom.project.yml`` is parsed and validated. Hook
runners (``copyroom new``/``update``) and the read-only ``inspect``/``status``
commands all read through :func:`load_project_config` rather than reaching into
the raw dict, so the schema lives in exactly one place.

The schema mirrors COPYROOM_CONCEPT_FINAL.md ("Pydantic Models" / "Project
config"). Two deliberate properties keep config evolution additive and backward
compatible:

* **Every field is defaulted** — a missing file or any missing key yields a
  fully-formed config with sane defaults (so hook lookups just return ``[]``).
* **Unknown fields are tolerated** — Pydantic's default ``extra="ignore"`` is
  kept (never ``extra="forbid"``), so a newer template's config still loads on
  an older CLI.

Workflow *entities* stay plain dataclasses (internal state machines); Pydantic
is used here only for *config* validation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

from .._compat.errors import CopyRoomError

__all__ = [
    "ContextConfig",
    "CopyRoomError",
    "CopyRoomProjectConfig",
    "DevenvConfig",
    "GitPolicy",
    "ProjectMetadata",
    "load_project_config",
]


class GitPolicy(BaseModel):
    """Git workflow policy (advisory; not authoritative for Copier)."""

    default_branch: str = "main"
    update_branch_prefix: str = "template-update/"
    feature_branch_prefix: str = "feature/"
    fix_branch_prefix: str = "fix/"
    release_branch_prefix: str = "release/"
    tag_prefix: str = "v"
    require_clean_worktree: bool = True


class ContextConfig(BaseModel):
    """Declared context roots (docs/source/config) for agents and tooling."""

    docs: list[Path] = Field(default_factory=list)
    source: list[Path] = Field(default_factory=list)
    config: list[Path] = Field(default_factory=list)


class ProjectMetadata(BaseModel):
    """Project identity and template linkage."""

    kind: Literal["generated-project", "template-repo", "shared-tooling"] = "generated-project"
    name: str | None = None
    template_id: str | None = None
    template_source: str | None = None
    template_ref_policy: Literal["tagged", "branch", "commit", "unknown"] = "unknown"
    answers_file: Path = Path(".copier-answers.yml")


class DevenvConfig(BaseModel):
    """Optional devenv integration flags."""

    enabled: bool = False
    shell_command: str = "devenv shell"


class CopyRoomProjectConfig(BaseModel):
    """The full, validated ``copyroom.project.yml`` model.

    ``commands`` maps a name (``check``, ``post_project_create``,
    ``post_template_update``, …) to a list of shell command strings. A bare
    string value is accepted and normalized to a single-element list — this
    preserves the historical hook behavior where a lone string was valid.
    """

    version: int = 1
    project: ProjectMetadata = Field(default_factory=ProjectMetadata)
    git: GitPolicy = Field(default_factory=GitPolicy)
    context: ContextConfig = Field(default_factory=ContextConfig)
    devenv: DevenvConfig = Field(default_factory=DevenvConfig)
    commands: dict[str, list[str]] = Field(default_factory=dict)

    @field_validator("commands", mode="before")
    @classmethod
    def _normalize_commands(cls, value: object) -> object:
        """Coerce bare-string command values into single-element lists."""
        if not isinstance(value, dict):
            return value
        normalized: dict[object, object] = {}
        for key, cmds in value.items():
            normalized[key] = [cmds] if isinstance(cmds, str) else cmds
        return normalized


def load_project_config(path: str | Path) -> CopyRoomProjectConfig:
    """Load and validate a ``copyroom.project.yml`` at *path*.

    A **missing file** returns an all-defaults config (so callers that only want
    hooks get an empty ``commands`` map without special-casing). A file that is
    unreadable, isn't valid YAML, isn't a mapping, or fails validation raises
    :class:`CopyRoomError`.

    The top-level ``copyroom: {version: N}`` block (where the schema version
    lives in the on-disk format) is folded into the model's ``version`` field;
    unknown top-level keys are ignored.
    """
    path = Path(path)
    if not path.is_file():
        return CopyRoomProjectConfig()

    try:
        with open(path) as f:
            raw = yaml.safe_load(f)
    except (yaml.YAMLError, OSError) as exc:
        raise CopyRoomError(f"Failed to read {path.name}: {exc}") from exc

    if raw is None:
        return CopyRoomProjectConfig()
    if not isinstance(raw, dict):
        raise CopyRoomError(f"{path.name} is not a mapping.")

    data: dict[str, object] = {
        key: raw[key]
        for key in ("project", "git", "context", "devenv", "commands")
        if key in raw
    }
    meta = raw.get("copyroom")
    if isinstance(meta, dict) and "version" in meta:
        data["version"] = meta["version"]

    try:
        return CopyRoomProjectConfig(**data)
    except ValidationError as exc:
        raise CopyRoomError(f"Invalid {path.name}: {exc}") from exc
