"""The two fixture acts chunked end to end, held against a committed snapshot."""

import json
from pathlib import Path

import pytest

from app.ingestion.chunk.tree import chunk_document
from app.ingestion.parse.html.document import parse_eurlex_html
from app.ingestion.parse.models import ParsedDocument
from tests.ingestion.chunk.conftest import snapshot_chunks

SNAPSHOTS = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("celex", ["32023R1805", "32015R0757"])
def test_fixture_chunks_match_snapshot(
    celex: str, fueleu: ParsedDocument, mrv: ParsedDocument
) -> None:
    """Parse and chunk together, in both dialects. After a change that is meant to move the
    chunks, regenerate with fixtures/snapshot.py and read the diff."""
    document = {parsed.celex: parsed for parsed in (fueleu, mrv)}[celex]
    snapshot = json.loads((SNAPSHOTS / f"{celex}.chunks.json").read_text())

    assert snapshot_chunks(document) == snapshot


def test_an_act_whose_sole_annex_is_unnumbered_still_addresses_every_chunk() -> None:
    """32024R2031 carries its substance in one annex labelled 'ANNEX', with no numeral to read."""
    sections = parse_eurlex_html(
        "<html><body>"
        '<div class="eli-subdivision" id="art_1">'
        '<p class="oj-ti-art">Article 1</p><p class="oj-normal">Subject matter.</p></div>'
        '<div id="anx_1"><p class="oj-doc-ti">ANNEX</p>'
        '<div class="oj-normal">Template body.</div></div>'
        "</body></html>"
    ).sections
    document = ParsedDocument(celex="32024R2031", topic="fueleu", sections=sections)
    assert [c.citation for c in chunk_document(document)] == ["Article 1", "Annex"]
