"""Scaffold a self-contained template repo (Home A) from an existing repo.

``copyroom templatize`` turns a hand-written repo R into the *starting point* of
a CopyRoom template: a sibling ``R-template/`` directory that is, at once, a
Copier template (``copier.yml`` + ``template/``) and the workshop that exercises
it (``copyroom.yml`` + ``registry/`` + ``scenarios/`` + ``golden/``).

The trick is **verbatim-then-parameterize**: ``template/`` starts as a byte-for-
byte copy of R, and ``golden/<id>/default/`` is a snapshot of R. Because Copier
only renders files ending in ``.jinja`` (default ``_templates_suffix``), the
verbatim ``template/`` reproduces R exactly under the default answers, so
``copyroom golden`` reports ``no_diffs`` from the very first render. The agent
then introduces ``{{ project_name }}`` (and other vars) by renaming files to
``.jinja``; rendering with ``project_name=<R name>`` yields the literal again,
so the golden match is preserved while parameters are introduced.

The scaffold is left a **plain (non-git) directory**: Copier renders a plain
dir's working tree directly, so each edit is seen immediately during the loop.
Converting it to a git repo + tag is a finalize step done just before ``adopt``.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from .._compat.errors import CopyRoomError
from .._compat.state_machine import StateMachine
from .model import (
    EXCLUDE_DIRS,
    VALID_TEMPLATIZATION_TRANSITIONS,
    Templatization,
    TemplatizationStatus,
)

__all__ = ["CopyRoomError", "templatize"]

_sm = StateMachine(VALID_TEMPLATIZATION_TRANSITIONS, entity_name="Templatization")

# Files/dirs never copied into template/ or golden/ (see EXCLUDE_DIRS).
_COPY_IGNORE = shutil.ignore_patterns(*EXCLUDE_DIRS, "*.pyc")

# A deliberately distinct answer for the probe scenario. It shares no substring
# with a typical repo name, so an over-broad substitution (a var applied too
# widely) renders obviously-wrong output the agent can spot. No golden backs it:
# R is ground truth only for the default answers (see CONCEPT.md, decision 4).
_PROBE_PROJECT_NAME = "copyroom-probe-xyz"

_ANSWERS_JINJA = (
    "# Changes here will be overwritten by Copier; NEVER EDIT MANUALLY\n"
    "{{ _copier_answers|to_nice_yaml }}\n"
)


def _slugify(name: str) -> str:
    """Reduce *name* to a registry-safe template id (lowercase, ``[a-z0-9_-]``)."""
    slug = re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-")
    return slug or "template"


def templatize(
    repo_root: str | Path | None = None,
    into: str | Path | None = None,
    name: str | None = None,
    template_id: str | None = None,
) -> Templatization:
    """Scaffold Home A from *repo_root*; return the ``Templatization``.

    Parameters
    ----------
    repo_root:
        The repo to templatize (defaults to the cwd).
    into:
        Where to create the template repo (defaults to ``<repo>-template`` as a
        sibling of *repo_root*).
    name:
        The project name to record as the template's default (defaults to the
        repo directory name).
    template_id:
        The workshop/registry id for the template (defaults to a slug of *name*).

    Raises ``CopyRoomError`` if *repo_root* is missing or the target already
    exists and is non-empty.
    """
    root = Path(repo_root).resolve() if repo_root is not None else Path.cwd().resolve()
    if not root.is_dir():
        raise CopyRoomError(f"Repo not found: {root}", state="not_started")

    project_name = name or root.name
    tid = template_id or _slugify(project_name)
    home_dir = (
        Path(into).resolve()
        if into is not None
        else root.parent / f"{root.name}-template"
    )

    if home_dir.exists() and any(home_dir.iterdir()):
        raise CopyRoomError(
            f"Target already exists and is not empty: {home_dir}",
            state="not_started",
        )

    tz = Templatization(
        repo_root=root, home_dir=home_dir, template_id=tid, project_name=project_name,
    )

    # --- scaffold (initiated -> scaffolded) ---
    try:
        _scaffold(tz)
    except OSError as exc:
        tz.status = _sm.transition(
            TemplatizationStatus.initiated, TemplatizationStatus.failed,
        )
        raise CopyRoomError(
            f"Failed to scaffold template repo: {exc}", state="initiated",
        ) from exc
    tz.status = _sm.transition(
        TemplatizationStatus.initiated, TemplatizationStatus.scaffolded,
    )

    # --- capture golden = snapshot of R (scaffolded -> golden_captured) ---
    try:
        golden_dir = home_dir / "golden" / tid / "default"
        shutil.copytree(root, golden_dir, ignore=_COPY_IGNORE)
    except OSError as exc:
        tz.status = _sm.transition(
            TemplatizationStatus.scaffolded, TemplatizationStatus.failed,
        )
        raise CopyRoomError(
            f"Failed to capture golden snapshot: {exc}", state="scaffolded",
        ) from exc
    tz.status = _sm.transition(
        TemplatizationStatus.scaffolded, TemplatizationStatus.golden_captured,
    )

    tz.status = _sm.transition(
        TemplatizationStatus.golden_captured, TemplatizationStatus.complete,
    )
    return tz


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _scaffold(tz: Templatization) -> None:
    """Write the Copier-template + workshop skeleton (everything but golden/)."""
    home = tz.home_dir
    tid = tz.template_id
    home.mkdir(parents=True, exist_ok=True)

    # Copier config at the template root; _subdirectory keeps workshop files
    # (scenarios/, golden/, copyroom.yml) out of generated projects.
    (home / "copier.yml").write_text(
        "_subdirectory: template\n"
        "_answers_file: .copier-answers.yml\n"
        "\n"
        "project_name:\n"
        "  type: str\n"
        f"  default: {tz.project_name}\n"
    )

    # template/ = verbatim copy of R (the agent parameterizes this).
    template_dir = home / "template"
    shutil.copytree(tz.repo_root, template_dir, ignore=_COPY_IGNORE)
    (template_dir / ".copier-answers.yml.jinja").write_text(_ANSWERS_JINJA)

    # Workshop registry: inline source + a registry/ dir (required for the
    # workshop-mode detector). A *relative* source ("." = the workshop root)
    # keeps the repo relocatable — an absolute path would dangle on move/re-clone
    # (P3-2). It is resolved against the workshop root for both validation and
    # Copier (resolve_source_for_copier).
    (home / "copyroom.yml").write_text(
        "templates:\n"
        f"  {tid}:\n"
        "    source: .\n"
    )
    (home / "registry").mkdir(exist_ok=True)
    (home / "registry" / ".gitkeep").write_text("")

    # Scenarios: default reproduces R; probe flushes over-parameterization.
    scenario_dir = home / "scenarios" / tid
    scenario_dir.mkdir(parents=True, exist_ok=True)
    (scenario_dir / "default.yml").write_text(f"project_name: {tz.project_name}\n")
    (scenario_dir / "probe.yml").write_text(f"project_name: {_PROBE_PROJECT_NAME}\n")

    (home / ".gitignore").write_text("generated/\n.copyroom_sim/\n")
