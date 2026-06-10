"""Unit tests for the recorded-ref vs target-tag comparison (_compat/refs.py)."""

from __future__ import annotations

import pytest

from copyroom._compat.refs import same_version


@pytest.mark.parametrize(
    ("recorded", "target", "expected"),
    [
        # exact tag — the case the fixture template already exercises
        ("v1.0.0", "v1.0.0", True),
        ("v1.2.3", "v1.2.4", False),
        # describe suffix — a project generated at a post-tag commit
        ("v1.0.0-3-gdeadbee", "v1.0.0", True),
        ("v1.2.3-12-gabc1234", "v1.2.3", True),
        ("v1.0.0-3-gdeadbee", "v2.0.0", False),
        # bare SHA — no resolvable tag, can't prove "same version"
        ("deadbee", "v1.0.0", False),
        ("0123456789abcdef", "v1.0.0", False),
        # None on either side
        (None, "v1.0.0", False),
        ("v1.0.0", None, False),
        (None, None, False),
    ],
)
def test_same_version(recorded: str | None, target: str | None, expected: bool) -> None:
    assert same_version(recorded, target) is expected


def test_describe_suffix_with_dashes_in_tag() -> None:
    """A tag containing dashes still strips its describe suffix correctly."""
    assert same_version("v1.0.0-beta-2-gabc123", "v1.0.0-beta") is True
