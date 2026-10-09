"""Share test setup for the publication mode."""

from __future__ import annotations

import pytest

from copyroom.local.guard import UNGUARDED_ENV, resolve_guard


@pytest.fixture(autouse=True)
def default_publication_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run guarded when a guard exists, and unguarded on stock tooling.

    Tests that need one mode set it themselves.
    """

    if resolve_guard() is None:
        monkeypatch.setenv(UNGUARDED_ENV, "1")
    else:
        monkeypatch.delenv(UNGUARDED_ENV, raising=False)
