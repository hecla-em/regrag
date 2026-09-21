"""Reading, writing and checking for a fetched document's stored bytes."""

from collections.abc import Callable

import pytest

from app.core.storage import LocalObjectStore, StorageError
from app.ingestion.enums import IngestRunStatus
from app.ingestion.exceptions import EmptyDownloadError
from app.ingestion.fetch.schemas import RawDocument
from app.ingestion.fetch.storage import document_key, read_document, write_document
from app.ingestion.schemas import IngestRun

HTML = b"<html>act</html>"


def run() -> IngestRun:
    return IngestRun(status=IngestRunStatus.SUCCESS)


def test_write_refuses_empty_content(local_store: LocalObjectStore):
    with pytest.raises(EmptyDownloadError, match="32023R2917"):
        write_document(local_store, "32023R2917", "32023R2917", b"")


def served(agent: str) -> bytes:
    """The same act as EUR-Lex serves it twice, its analytics id differing per request."""
    return (
        f'<html><head><script src="/rux.js" data-dtconfig="agentId={agent}"></script></head>'
        "<body><p>Ships shall monitor their emissions.</p></body></html>"
    ).encode()


def test_a_per_request_script_does_not_make_it_a_different_document(
    local_store: LocalObjectStore,
):
    """EUR-Lex stamps an analytics id into every response, so unchanged law arrives as
    different bytes each time and would otherwise store an object per download."""
    first, _ = write_document(local_store, "32023R1805", "32023R1805", served("aaa"))
    second, _ = write_document(local_store, "32023R1805", "32023R1805", served("bbb"))

    assert first == second
    assert len(list(local_store.root.rglob("*.html"))) == 1


def test_the_stored_document_keeps_its_text_and_loses_only_the_scripts(
    local_store: LocalObjectStore,
):
    sha256, _ = write_document(local_store, "32023R1805", "32023R1805", served("aaa"))
    stored = local_store.get(document_key("32023R1805", "32023R1805", sha256))

    assert b"Ships shall monitor their emissions." in stored
    assert b"dtconfig" not in stored
    assert b"<script" not in stored


def test_a_stripped_document_still_verifies_on_the_way_back_out(
    local_store: LocalObjectStore, make_document: Callable[..., RawDocument]
):
    """read_document re-hashes what it fetched, so the bytes stored must be the ones hashed."""
    sha256, size = write_document(local_store, "32023R1805", "32023R1805", served("aaa"))
    document = make_document(run(), sha256=sha256, size_bytes=size)

    assert b"Ships shall monitor" in read_document(local_store, document)


def test_read_refuses_bytes_that_are_not_the_ones_the_row_recorded(
    local_store: LocalObjectStore, store_document: Callable[..., RawDocument]
):
    """A restore can leave the row and the object disagreeing; parsing the wrong version is
    worse than failing."""
    document = store_document(run(), HTML)
    key = document_key(document.celex, document.resolved_celex, document.sha256)
    local_store.put(key, b"<html>something else</html>")

    with pytest.raises(StorageError, match="verify failed"):
        read_document(local_store, document)
