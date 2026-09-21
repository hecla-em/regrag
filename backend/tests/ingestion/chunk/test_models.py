"""The two hashes a chunk carries, which decide what a run re-embeds and what it only updates."""

from typing import Any

import pytest

from tests.conftest import chunk


@pytest.mark.parametrize(
    ("changed", "content_moves", "metadata_moves"),
    [
        pytest.param({"text": "Something else entirely."}, True, False, id="the text is content"),
        pytest.param({"celex": "32015R0757"}, True, False, id="so is the document it sits in"),
        pytest.param({"heading_path": ("Chapter I",)}, True, False, id="and the headings above"),
        pytest.param(
            {"article": "5"}, True, True, id="a different article moves both, as its citation does"
        ),
        pytest.param({"topic": "mrv"}, False, True, id="the topic is where it came from"),
        pytest.param({"act_title": "FuelEU"}, False, True, id="a renamed act must not re-embed"),
        pytest.param(
            {"position": 7}, False, True, id="an inserted paragraph shifts positions, not content"
        ),
        pytest.param({"points": ("a",)}, False, True, id="points derive from the text"),
    ],
)
def test_each_changed_field_moves_the_hash_it_belongs_to(
    changed: dict[str, Any], content_moves: bool, metadata_moves: bool
) -> None:
    before, after = chunk(), chunk(**changed)

    assert (after.content_hash != before.content_hash) is content_moves
    assert (after.metadata_hash != before.metadata_hash) is metadata_moves
