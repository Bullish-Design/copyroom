"""Repo adoption / templatization — turn a non-CopyRoom repo into a managed one.

Public entry points:

- :func:`adopt` — link a repo to a named/extracted template and report drift.
- :func:`templatize` — scaffold a self-contained template repo (Home A) whose
  golden snapshot is the repo, ready for the agent to parameterize.
"""

from __future__ import annotations

from .._compat.errors import CopyRoomError
from .adopt import adopt
from .templatize import templatize

__all__ = ["CopyRoomError", "adopt", "templatize"]
