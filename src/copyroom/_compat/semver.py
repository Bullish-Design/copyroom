"""Tiny semantic-version selector shared by the update/status/registry flows.

CopyRoom resolves a template's "latest" version itself (rather than letting
Copier pick implicitly) so the chosen ref is deterministic, reportable, and
usable as a concrete ``--vcs-ref``. The only thing needed for that is to pick
the highest semver tag out of a tag list — a pure, dependency-free function.

A ``vX.Y.Z`` tag is accepted with or without the leading ``v``; pre-release and
build metadata (``-rc1``, ``+build``) and any non-semver tags are ignored.
"""

from __future__ import annotations

import re

# X.Y.Z with an optional leading ``v`` and an optional pre-release/build suffix.
_SEMVER_RE = re.compile(
    r"^v?(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)(?P<suffix>[-+].*)?$",
)


def parse_semver(tag: str) -> tuple[int, int, int] | None:
    """Return ``(major, minor, patch)`` for a semver-ish *tag*, else ``None``.

    Tags carrying a pre-release/build suffix are skipped (return ``None``) so a
    release tag is always preferred over a pre-release of the same number.
    """
    match = _SEMVER_RE.match(tag.strip())
    if match is None or match.group("suffix"):
        return None
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
    )


def select_latest_semver(tags: list[str]) -> str | None:
    """Return the highest semver tag in *tags*, or ``None`` when there are none.

    Non-semver tags are ignored. The original tag string (with whatever ``v``
    prefix it carried) is returned so it can be passed straight back to git.
    """
    best: tuple[tuple[int, int, int], str] | None = None
    for tag in tags:
        parsed = parse_semver(tag)
        if parsed is None:
            continue
        if best is None or parsed > best[0]:
            best = (parsed, tag.strip())
    return best[1] if best is not None else None
