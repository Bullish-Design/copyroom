"""Repo adoption / templatization — turn a non-CopyRoom repo into a managed one.

Public entry points:

- :func:`adopt` — link a repo to a named/extracted template and report drift.
- :func:`templatize` — scaffold a self-contained template repo (Home A) whose
  golden snapshot is the repo, ready for the agent to parameterize.
- :func:`add_layer` — apply a template to a repo as an extra *layer*, so one
  repo can be managed by several templates at once (the personal layer).
"""

from __future__ import annotations

from .._compat.errors import CopyRoomError
from .adopt import adopt
from .layer import add_layer, list_layers
from .templatize import templatize

__all__ = ["CopyRoomError", "add_layer", "adopt", "list_layers", "templatize"]
