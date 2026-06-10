"""Unit tests for the semver tag selector (_compat/semver.py)."""

from __future__ import annotations

from copyroom._compat.semver import parse_semver, select_latest_semver


class TestParseSemver:
    def test_plain_vtag(self) -> None:
        assert parse_semver("v1.2.3") == (1, 2, 3)

    def test_without_v_prefix(self) -> None:
        assert parse_semver("1.2.3") == (1, 2, 3)

    def test_non_semver_returns_none(self) -> None:
        assert parse_semver("latest") is None
        assert parse_semver("v1.2") is None
        assert parse_semver("release-1") is None

    def test_prerelease_suffix_is_skipped(self) -> None:
        assert parse_semver("v1.2.3-rc1") is None
        assert parse_semver("1.2.3+build5") is None


class TestSelectLatestSemver:
    def test_picks_highest(self) -> None:
        assert select_latest_semver(["v1.0.0", "v2.0.0", "v1.5.0"]) == "v2.0.0"

    def test_numeric_not_lexical(self) -> None:
        # 10 > 9 numerically (lexical sort would pick v0.9.0).
        assert select_latest_semver(["v0.9.0", "v0.10.0"]) == "v0.10.0"

    def test_ignores_non_semver_tags(self) -> None:
        assert select_latest_semver(["latest", "v1.0.0", "nightly"]) == "v1.0.0"

    def test_missing_v_prefix_tags_considered(self) -> None:
        assert select_latest_semver(["1.0.0", "2.0.0"]) == "2.0.0"

    def test_empty_list_returns_none(self) -> None:
        assert select_latest_semver([]) is None

    def test_no_semver_tags_returns_none(self) -> None:
        assert select_latest_semver(["latest", "dev", "v1.2"]) is None

    def test_returns_original_tag_string(self) -> None:
        # The chosen tag is returned verbatim so it can be passed back to git.
        assert select_latest_semver(["1.0.0", "v2.0.0"]) == "v2.0.0"
