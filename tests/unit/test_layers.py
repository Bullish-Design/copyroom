"""Unit tests for the template-layer model (``copyroom.project.layers``).

Pure filename/discovery logic — no Copier, no git. The end-to-end behavior these
names describe is covered in ``tests/integration/test_layers.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from copyroom._compat.errors import CopyRoomError
from copyroom.project.layers import (
    BASE_LAYER,
    answers_filename,
    discover_layers,
    layer_name_from_answers_file,
    resolve_layer,
    template_default_layer,
)


class TestAnswersFilename:
    def test_base_is_the_default_file(self) -> None:
        assert answers_filename() == ".copier-answers.yml"
        assert answers_filename(None) == ".copier-answers.yml"
        assert answers_filename(BASE_LAYER) == ".copier-answers.yml"

    def test_named_layer_gets_an_infix(self) -> None:
        assert answers_filename("my-ai") == ".copier-answers.my-ai.yml"

    @pytest.mark.parametrize("bad", ["../escape", "a/b", "", ".hidden", "trailing."])
    def test_a_name_that_could_escape_the_root_is_refused(self, bad: str) -> None:
        # The name becomes part of a filename, so path separators and leading
        # dots must never reach the filesystem.
        with pytest.raises(CopyRoomError, match="Invalid layer name"):
            answers_filename(bad)


class TestLayerNameFromAnswersFile:
    def test_round_trips(self) -> None:
        for name in (BASE_LAYER, "my-ai", "fleet_ops", "a.b"):
            assert layer_name_from_answers_file(answers_filename(name)) == name

    def test_ignores_unrelated_files(self) -> None:
        assert layer_name_from_answers_file("copyroom.project.yml") is None
        assert layer_name_from_answers_file(".copier-answers.yaml") is None
        assert layer_name_from_answers_file(".copier-answers..yml") is None

    def test_accepts_a_full_path(self) -> None:
        assert layer_name_from_answers_file("/repo/.copier-answers.my-ai.yml") == "my-ai"


class TestDiscoverLayers:
    def test_empty_for_an_unmanaged_repo(self, tmp_path: Path) -> None:
        assert discover_layers(tmp_path) == []

    def test_base_sorts_first_then_alphabetical(self, tmp_path: Path) -> None:
        for name in ("zeta", "my-ai", BASE_LAYER, "alpha"):
            (tmp_path / answers_filename(name)).write_text("_src_path: x\n")
        assert [layer.name for layer in discover_layers(tmp_path)] == [
            BASE_LAYER, "alpha", "my-ai", "zeta",
        ]

    def test_reads_the_copier_metadata(self, tmp_path: Path) -> None:
        (tmp_path / ".copier-answers.my-ai.yml").write_text(
            "_src_path: /src/my-ai\n_commit: v1.2.3\n_template: my-ai\n"
        )
        (layer,) = discover_layers(tmp_path)
        assert (layer.name, layer.ref, layer.template_id) == ("my-ai", "v1.2.3", "my-ai")
        assert layer.template_source == "/src/my-ai"
        assert layer.is_base is False

    def test_a_malformed_answers_file_still_lists(self, tmp_path: Path) -> None:
        # Listing must never fail because one layer is broken — the commands
        # that act on a layer report that themselves.
        (tmp_path / ".copier-answers.broken.yml").write_text("- not: a mapping\n")
        (layer,) = discover_layers(tmp_path)
        assert layer.name == "broken"
        assert layer.ref is None


class TestResolveLayer:
    def test_names_the_layers_present_when_asked_for_a_missing_one(self, tmp_path: Path) -> None:
        (tmp_path / ".copier-answers.yml").write_text("_src_path: x\n")
        with pytest.raises(CopyRoomError, match=r"Layers present: base"):
            resolve_layer(tmp_path, "my-ai")

    def test_points_at_the_bootstrap_commands_when_nothing_is_managed(self, tmp_path: Path) -> None:
        with pytest.raises(CopyRoomError, match="copyroom layer add"):
            resolve_layer(tmp_path, "my-ai")

    def test_defaults_to_base(self, tmp_path: Path) -> None:
        (tmp_path / ".copier-answers.yml").write_text("_commit: v1.0.0\n")
        assert resolve_layer(tmp_path).name == BASE_LAYER


class TestTemplateDefaultLayer:
    def test_reads_the_declared_answers_file(self, tmp_path: Path) -> None:
        (tmp_path / "copier.yml").write_text("_answers_file: .copier-answers.my-ai.yml\n")
        assert template_default_layer(tmp_path) == "my-ai"

    def test_none_when_the_template_declares_the_base_file(self, tmp_path: Path) -> None:
        # A genome names the default file; that is not a layer name.
        (tmp_path / "copier.yml").write_text("_answers_file: .copier-answers.yml\n")
        assert template_default_layer(tmp_path) is None

    def test_none_when_undeclared_or_unreadable(self, tmp_path: Path) -> None:
        assert template_default_layer(tmp_path) is None
        (tmp_path / "copier.yml").write_text("project_name:\n  type: str\n")
        assert template_default_layer(tmp_path) is None
