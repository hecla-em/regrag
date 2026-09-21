"""Reusing or downloading a document's version, and the fetch stage in isolation."""

import httpx
import pytest

from app.ingestion.discover.stage import discover_topics
from app.ingestion.enums import DocChange, IngestRunStatus
from app.ingestion.exceptions import DocumentFailed
from app.ingestion.fetch.models import RawDocsQuery
from app.ingestion.fetch.schemas import RawDocument
from app.ingestion.fetch.service import get_raw_documents
from app.ingestion.fetch.stage import fetch_document
from app.ingestion.fetch.storage import read_document
from app.ingestion.schemas import IngestRun
from app.ingestion.service import complete_ingest_run, create_ingest_run
from tests.conftest import MRV_SPARQL, binding, payload

pytestmark = pytest.mark.anyio


def stored(store_document, celex="32023R1805"):
    """A previous run's row whose bytes are still in the store."""
    return store_document(IngestRun(status=IngestRunStatus.SUCCESS), celex=celex)


def html_of(documents, celex, local_store) -> bytes:
    """The bytes the run left in the store for one celex, read back the way a later run would."""
    return read_document(local_store, {d.celex: d for d in documents}[celex])


def mrv_docs(overrides: dict[str, httpx.Response] | None = None) -> dict[str, httpx.Response]:
    """The two-document mrv corpus, with per-celex responses overridable."""
    return {
        "32015R0757": httpx.Response(200, content=b"<html>mrv</html>"),
        "32023R2449": httpx.Response(200, content=b"<html>act</html>"),
    } | (overrides or {})


Fetched = tuple[dict[str, DocChange], dict[str, str], list[RawDocument]]


async def fetch(db_session, client, topics, store) -> Fetched:
    """Drive the fetch stage alone, with the run, discovery and savepoint the pipeline supplies."""
    run = await create_ingest_run(db_session)
    previous = await get_raw_documents(db_session, RawDocsQuery(include_topics=topics))
    discovered = await discover_topics(client, topics)
    documents: list[RawDocument] = []
    changes: dict[str, DocChange] = {}
    failed: dict[str, str] = {}
    for document in discovered:
        try:
            async with db_session.begin_nested():
                fetched = await fetch_document(
                    db_session,
                    client=client,
                    discovered=document,
                    previous=previous.get(document.celex),
                    run=run,
                    store=store,
                )
        except DocumentFailed as failure:
            failed[failure.celex] = failure.reason
        else:
            documents.append(fetched.raw)
            changes[document.celex] = fetched.change
    await complete_ingest_run(db_session, run, status=IngestRunStatus.SUCCESS)
    return changes, failed, documents


def celexes(changes: dict[str, DocChange], change: DocChange) -> list[str]:
    """The celexes the run put in one of fetch's buckets."""
    return sorted(celex for celex, value in changes.items() if value is change)


async def test_still_rendering_doc_fails_leaving_the_parsed_bytes_readable(
    db_session, local_store, corpus_client
):
    """The regression: a 202 used to be stored as an empty file, wiping the last good copy.

    A new consolidation is what forces the download; an unchanged act is never requested at all.
    """
    client, _ = corpus_client({"mrv": MRV_SPARQL}, mrv_docs())
    _, _, first = await fetch(db_session, client, ["mrv"], local_store)

    consolidated = httpx.Response(
        200,
        json=payload(
            binding("32015R0757", force="1", cons="02015R0757-20250101"),
            binding("32023R2449", force="1"),
        ),
    )
    rendering = mrv_docs({"02015R0757-20250101": httpx.Response(202, content=b"")})
    client, _ = corpus_client({"mrv": consolidated}, rendering)
    changes, failed, _ = await fetch(db_session, client, ["mrv"], local_store)

    assert "32015R0757" in failed
    assert html_of(first, "32015R0757", local_store) == b"<html>mrv</html>"
    assert celexes(changes, DocChange.REUSED) == ["32023R2449"]
