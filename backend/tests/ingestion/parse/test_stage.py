"""The parse stage on one fetched document: what parsed, and what would not.

One bad document not stopping the others is the pipeline's loop now, and is covered there.
"""

from collections.abc import Callable

import pytest

from app.ingestion.enums import IngestRunStatus, Stage
from app.ingestion.exceptions import DocumentFailed
from app.ingestion.fetch.schemas import RawDocument
from app.ingestion.parse.stage import parse_document
from app.ingestion.schemas import IngestRun
from tests.conftest import FUELEU_HTML as HTML


def row(make_document: Callable[..., RawDocument], celex: str = "32023R1805") -> RawDocument:
    """A row as the fetch stage would have recorded it before handing its bytes over."""
    return make_document(IngestRun(status=IngestRunStatus.RUNNING), celex=celex)


def test_parses_the_document_it_was_handed(make_document: Callable[..., RawDocument]) -> None:
    parsed = parse_document(row(make_document), HTML.encode("utf-8"))
    assert (parsed.celex, parsed.topic) == ("32023R1805", "fueleu")


def test_parsed_document_carries_the_title_of_its_act(
    make_document: Callable[..., RawDocument],
) -> None:
    raw = make_document(
        IngestRun(status=IngestRunStatus.RUNNING),
        title="Regulation (EU) 2023/1805 on renewable fuels",
    )
    assert (
        parse_document(raw, HTML.encode("utf-8")).act_title
        == "Regulation (EU) 2023/1805 on renewable fuels"
    )


def test_html_that_will_not_parse_fails_the_document_at_the_parse_stage(
    make_document: Callable[..., RawDocument],
) -> None:
    with pytest.raises(DocumentFailed) as excinfo:
        parse_document(row(make_document), b"<html></html>")

    assert (excinfo.value.stage, excinfo.value.celex) == (Stage.PARSE, "32023R1805")
    assert excinfo.value.reason.startswith("ParseError")


def test_html_that_is_not_utf8_fails_the_document_too(
    make_document: Callable[..., RawDocument],
) -> None:
    with pytest.raises(DocumentFailed) as excinfo:
        parse_document(row(make_document), b"\xff\xfe<html>")

    assert excinfo.value.reason.startswith("UnicodeDecodeError")
