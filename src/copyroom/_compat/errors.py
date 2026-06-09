"""Shared structured error type.

A single ``CopyRoomError`` used across all workflow modules (§10.3 of the
implementation plan). Each domain module re-exports it so existing imports
like ``from .create import CopyRoomError`` keep working.
"""

from __future__ import annotations


class CopyRoomError(Exception):
    """Base error with a structured, user-facing message.

    The formatted message always begins with ``Error:`` and, when a ``state``
    is given, appends the lifecycle state the entity was left in.
    """

    def __init__(self, message: str, state: str | None = None) -> None:
        self.message = message
        self.state = state
        super().__init__(self._format())

    def _format(self) -> str:
        parts = [f"Error: {self.message}"]
        if self.state:
            parts.append(f"State left: {self.state}")
        return "\n".join(parts)
