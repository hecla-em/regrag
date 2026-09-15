"""Reusing or downloading a document's version, and the fetch stage in isolation."""

import hashlib

import httpx
import pytest

from app.core.storage import StorageError
from app.ingestion.discover.stage import discover_topics
from app.ingestion.enums import DocChange, IngestRunStatus
from app.ingestion.exceptions import DocumentFailed
from app.ingestion.fetch.models import RawDocsQuery
from app.ingestion.fetch.schemas import RawDocument
from app.ingestion.fetch.service import get_raw_documents
from app.ingestion.fetch.stage import _reuse_previous_version, fetch_document
from app.ingestion.fetch.storage import document_key, read_document
from app.ingestion.schemas import IngestRun
from app.ingestion.service import complete_ingest_run, create_ingest_run
from tests.conftest import MRV_SPARQL, binding, discovered_document, payload

pytestmark = pytest.mark.anyio


def stored(store_document, celex="32023R1805"):
    """A previous run's row whose bytes are still in the store."""
    return store_document(IngestRun(status=IngestRunStatus.SUCCESS), celex=celex)


def this_run() -> IngestRun:
    """The open run a reused version would be recorded against."""
    return IngestRun(status=IngestRunStatus.RUNNING)


def html_of(documents, celex, local_store) -> bytes:
    """The bytes the run left in the store for one celex, read back the way a later run would."""
    return read_document(local_store, {d.celex: d for d in documents}[celex])


def test_stored_version_is_reused_when_discovery_still_points_at_it(local_store, store_document):
    prev = stored(store_document)
    reused = _reuse_previous_version(
        local_store, discovered_document("32023R1805"), prev, this_run()
    )
    assert reused is not None
    document, content = reused
    assert document.resolved_celex == prev.resolved_celex
    assert content == b"<html>act</html>"
    assert (document.sha256, document.size_bytes, document.fetched_at) == (
        prev.sha256,
        prev.size_bytes,
        prev.fetched_at,
    )


def test_reuse_carries_the_title_discovery_found_this_run(local_store, store_document):
    """A title is discovery's, not the download's, so a reused document still gets this run's."""
    discovered = discovered_document(
        "32023R1805", title="Regulation (EU) 2023/1805 on renewable fuels"
    )
    reused = _reuse_previous_version(local_store, discovered, stored(store_document), this_run())
    assert reused is not None
    assert reused[0].title == "Regulation (EU) 2023/1805 on renewable fuels"


def test_reuse_carries_the_version_that_was_served_not_the_one_that_was_asked_for(
    local_store, store_document
):
    """The fallback case: reuse keeps pointing at the act CELLAR served, not at the candidate."""
    prev = store_document(
        IngestRun(status=IngestRunStatus.SUCCESS),
        celex="32023R1805",
        candidates=["02023R1805-20250101"],
    )
    asked_again = discovered_document("32023R1805", candidates=("02023R1805-20250101",))

    reused = _reuse_previous_version(local_store, asked_again, prev, this_run())

    assert reused is not None
    assert reused[0].resolved_celex == "32023R1805"


def test_a_newly_discovered_consolidation_is_not_reused(local_store, store_document):
    """Discovery pointing somewhere new is exactly the case that has to hit the network."""
    prev = stored(store_document)
    newer = discovered_document("32023R1805", candidates=("02023R1805-20250101",))
    assert _reuse_previous_version(local_store, newer, prev, this_run()) is None


def test_stored_version_no_longer_in_the_store_is_not_reused(local_store, store_document):
    prev = stored(store_document)
    (local_store.root / document_key(prev.celex, prev.resolved_celex, prev.sha256)).unlink()
    discovered = discovered_document("32023R1805")
    assert _reuse_previous_version(local_store, discovered, prev, this_run()) is None


def test_a_document_with_no_previous_run_has_nothing_to_reuse(local_store):
    discovered = discovered_document("32023R1805")
    assert _reuse_previous_version(local_store, discovered, None, this_run()) is None


def test_stored_bytes_that_do_not_match_the_row_are_not_reused(local_store, store_document):
    """A row and an object restored from different points in time: download it again."""
    prev = stored(store_document)
    key = document_key(prev.celex, prev.resolved_celex, prev.sha256)
    local_store.put(key, b"<html>a different version</html>")
    discovered = discovered_document("32023R1805")

    assert _reuse_previous_version(local_store, discovered, prev, this_run()) is None


def test_a_store_that_cannot_be_read_is_not_treated_as_a_missing_object(
    local_store, store_document, monkeypatch
):
    """An outage answers every read the same way, and re-downloading only fails at the write."""
    prev = stored(store_document)

    def outage(key: str) -> bytes:
        raise StorageError("get", key, "connection reset by peer")

    monkeypatch.setattr(local_store, "get", outage)

    with pytest.raises(StorageError):
        _reuse_previous_version(local_store, discovered_document("32023R1805"), prev, this_run())


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


async def test_first_run_ingests_all_as_new(db_session, local_store, corpus_client):
    client, _ = corpus_client({"mrv": MRV_SPARQL}, mrv_docs())
    changes, failed, documents = await fetch(db_session, client, ["mrv"], local_store)

    assert celexes(changes, DocChange.NEW) == ["32015R0757", "32023R2449"]
    assert failed == {}
    assert html_of(documents, "32015R0757", local_store) == b"<html>mrv</html>"
    rows = await get_raw_documents(db_session, RawDocsQuery(include_topics=["mrv"]))
    assert rows["32023R2449"].celex == "32023R2449"
    assert rows["32023R2449"].resolved_celex == "32023R2449"


async def test_unchanged_run_makes_no_html_requests_and_carries_sha(
    db_session, local_store, corpus_client
):
    """Steady state: discovery points at the versions already stored, so nothing is downloaded."""
    docs = mrv_docs()
    client, _ = corpus_client({"mrv": MRV_SPARQL}, docs)
    await fetch(db_session, client, ["mrv"], local_store)

    client, calls = corpus_client({"mrv": MRV_SPARQL}, docs)
    changes, _, _ = await fetch(db_session, client, ["mrv"], local_store)

    assert celexes(changes, DocChange.REUSED) == ["32015R0757", "32023R2449"]
    assert calls == []
    firsts = {
        r.celex: r.sha256
        for r in (
            await get_raw_documents(db_session, RawDocsQuery(include_topics=["mrv"]))
        ).values()
    }
    assert firsts["32015R0757"] == hashlib.sha256(b"<html>mrv</html>").hexdigest()


async def test_a_consolidation_eurlex_will_not_serve_is_not_asked_for_again(
    db_session, local_store, corpus_client
):
    """An act with a consolidated id but no consolidated text: run 1 falls back to the act.

    Comparing the stored version against the candidate would deny the match every run and
    re-download the whole corpus for as long as CELLAR serves no consolidation.
    """
    sparql = {
        "mrv": httpx.Response(
            200,
            json=payload(
                binding("32015R0757", force="1", cons="02015R0757-20250101"),
                binding("32023R2449", force="1"),
            ),
        )
    }
    docs = mrv_docs({"02015R0757-20250101": httpx.Response(404, text="gone")})
    client, _ = corpus_client(sparql, docs)
    await fetch(db_session, client, ["mrv"], local_store)

    client, calls = corpus_client(sparql, docs)
    changes, _, _ = await fetch(db_session, client, ["mrv"], local_store)

    assert calls == []
    assert celexes(changes, DocChange.REUSED) == ["32015R0757", "32023R2449"]


async def test_new_consolidation_is_updated_and_redownloaded(
    db_session, local_store, corpus_client
):
    """One request, not two: the download hands back the bytes it already pulled."""
    docs = mrv_docs({"32015R0757": httpx.Response(200, content=b"<html>v1</html>")})
    client, _ = corpus_client({"mrv": MRV_SPARQL}, docs)
    await fetch(db_session, client, ["mrv"], local_store)

    consolidated = httpx.Response(
        200,
        json=payload(
            binding("32015R0757", force="1", cons="02015R0757-20250101"),
            binding("32023R2449", force="1"),
        ),
    )
    docs = mrv_docs({"02015R0757-20250101": httpx.Response(200, content=b"<html>v2</html>")})
    client, calls = corpus_client({"mrv": consolidated}, docs)
    changes, _, documents = await fetch(db_session, client, ["mrv"], local_store)

    assert celexes(changes, DocChange.UPDATED) == ["32015R0757"]
    assert calls == ["02015R0757-20250101"]
    assert html_of(documents, "32015R0757", local_store) == b"<html>v2</html>"
    rows = await get_raw_documents(db_session, RawDocsQuery(include_topics=["mrv"]))
    assert rows["32015R0757"].resolved_celex == "02015R0757-20250101"


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


async def test_a_vanished_doc_gets_no_row_from_this_run(db_session, local_store, corpus_client):
    """Discovery is what reports the drop; fetch's part is simply never recording it again."""
    docs = mrv_docs()
    client, _ = corpus_client({"mrv": MRV_SPARQL}, docs)
    await fetch(db_session, client, ["mrv"], local_store)

    only_base_act = httpx.Response(200, json=payload(binding("32015R0757", force="1")))
    client, _ = corpus_client({"mrv": only_base_act}, docs)
    changes, _, _ = await fetch(db_session, client, ["mrv"], local_store)

    assert celexes(changes, DocChange.REUSED) == ["32015R0757"]
    assert "32023R2449" not in await get_raw_documents(
        db_session, RawDocsQuery(include_topics=["mrv"])
    )


async def test_a_store_outage_fails_the_run_rather_than_refetching_the_corpus(
    db_session, local_store, corpus_client, monkeypatch
):
    """Every document's bytes become unreadable at once: that is the store, not the corpus."""
    client, _ = corpus_client({"mrv": MRV_SPARQL}, mrv_docs())
    await fetch(db_session, client, ["mrv"], local_store)

    def outage(key: str) -> bytes:
        raise StorageError("get", key, "connection reset by peer")

    monkeypatch.setattr(local_store, "get", outage)
    client, calls = corpus_client({"mrv": MRV_SPARQL}, mrv_docs())
    changes, failed, _ = await fetch(db_session, client, ["mrv"], local_store)

    assert sorted(failed) == ["32015R0757", "32023R2449"]
    assert changes == {}
    assert calls == []


async def test_duplicate_celex_across_topics_ingested_once(db_session, local_store, corpus_client):
    shared = binding("32015R0757", force="1")
    sparql = {
        "mrv": httpx.Response(200, json=payload(shared)),
        "fueleu": httpx.Response(200, json=payload(binding("32023R1805", force="1"), shared)),
    }
    docs = {
        "32015R0757": httpx.Response(200, content=b"<html>mrv</html>"),
        "32023R1805": httpx.Response(200, content=b"<html>fueleu</html>"),
    }
    client, _ = corpus_client(sparql, docs)
    _, failed, _ = await fetch(db_session, client, ["fueleu", "mrv"], local_store)

    assert failed == {}
    rows = await get_raw_documents(db_session, RawDocsQuery(include_topics=["fueleu", "mrv"]))
    assert rows["32015R0757"].topic == "fueleu"
