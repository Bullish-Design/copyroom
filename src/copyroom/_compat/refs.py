"""Compare a project's recorded template ref against a resolved target tag.

Copier records ``_commit`` as ``git describe`` output, which takes three shapes:
an exact tag (``v1.2.3``), a describe suffix (``v1.2.3-3-gabc123``), or — when
the commit has no reachable tag — a bare SHA. CopyRoom needs to know whether a
recorded ref is *effectively the same version* as a resolved target tag, so a
no-arg ``update`` / ``status`` on a project generated at a post-tag commit reads
as a no-op rather than a spurious "update available".

A single :func:`same_version` helper backs both call sites
(``update.no_update_available`` and ``inspect.project_status``) so they can't
drift apart.
"""

from __future__ import annotations

import re

# A `git describe` suffix: "<tag>-<N>-g<sha>" (N = commits since the tag).
_DESCRIBE_RE = re.compile(r"^(?P<base>.+)-\d+-g[0-9a-f]+$")


def same_version(recorded_ref: str | None, target_tag: str | None) -> bool:
    """Return ``True`` when *recorded_ref* is the same version as *target_tag*.

    Handles the three ``git describe`` shapes Copier records in ``_commit``:

    * **exact tag** — ``v1.2.3`` equals target ``v1.2.3``;
    * **describe suffix** — ``v1.2.3-3-gabc123`` strips to base ``v1.2.3``;
    * **bare SHA** — no resolvable tag, so it can't be proven equal and returns
      ``False`` (treated as "not a no-op", preserving pre-fix behavior).

    ``None`` on either side → ``False`` (nothing to compare).
    """
    if recorded_ref is None or target_tag is None:
        return False
    if recorded_ref == target_tag:
        return True
    match = _DESCRIBE_RE.match(recorded_ref)
    return match is not None and match.group("base") == target_tag
