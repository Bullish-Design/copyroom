"""Run the crash matrix on the unguarded publication path.

The matrix kills a process around `jj new`. The guarded path has no `jj new`, and
pyjutsu's own suite covers its crash states.
"""

from __future__ import annotations

import pytest

from copyroom.local.guard import UNGUARDED_ENV


@pytest.fixture(autouse=True)
def unguarded_publication(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(UNGUARDED_ENV, "1")
