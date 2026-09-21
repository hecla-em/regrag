"""The ingest orchestrator end to end: the run report, run lifecycle, corpus versioning."""

import re

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import ProgrammingError

from app.core.config import config
from app.core.llm.errors import LLMError
from app.core.storage import StorageError
from app.ingestion import pipeline
from app.ingestion.celex import consolidated_stem
from app.ingestion.enums import CITED_TOPIC, DocChange, IngestRunStatus, Stage
from app.ingestion.exceptions import CorpusShrankError, MalformedDiscoveryError, ParseError
from app.ingestion.fetch import stage as fetch_stage
from app.ingestion.fetch.models import RawDocsQuery
from app.ingestion.fetch.schemas import RawDocument
from app.ingestion.fetch.service import get_raw_documents
from app.ingestion.fetch.storage import document_key
from app.ingestion.models import IngestRunResult
from app.ingestion.pipeline import ingest
from app.ingestion.schemas import IngestRun
from tests.conftest import (
    FUELEU_HTML,
    MRV_SPARQL,
    binding,
    chunk_rows,
    chunk_versions,
    payload,
)

pytestmark = pytest.mark.anyio


SMALL_ACT = (
    '<html><body><div class="eli-subdivision" id="art_1">'
    '<p class="oj-ti-art">Article 1</p>'
    '<p class="oj-normal">1. Ships shall monitor their emissions.</p>'
    '<p class="oj-normal">2. Companies shall report them annually.</p>'
    "</div></body></html>"
)
"""What the corpus-bookkeeping tests serve: they assert on runs and counts, not on text,
and parsing the full act for each of them costs more than the whole rest of the module."""


def small_act() -> httpx.Response:
    """A fresh response per document, since a served one has its content consumed."""
    return httpx.Response(200, content=SMALL_ACT.encode())


def mrv_docs(overrides: dict[str, httpx.Response] | None = None) -> dict[str, httpx.Response]:
    """The two-document mrv corpus, with per-celex responses overridable."""
    return {"32015R0757": small_act(), "32023R2449": small_act()} | (overrides or {})


def committed(report: IngestRunResult, change: DocChange) -> list[str]:
    """The celexes the run committed into one of fetch's buckets."""
    return sorted(doc.celex for doc in report.committed if doc.change is change)


async def ingest_mrv(db_session, local_store, corpus_client, sparql=None, docs=None):
    """Run the real pipeline over the two-document mrv corpus, network stubbed."""
    client, _ = corpus_client({"mrv": sparql or MRV_SPARQL}, mrv_docs() if docs is None else docs)
    return await ingest(db_session, client=client, topics=["mrv"], store=local_store)


async def test_sparql_failure_aborts_and_marks_run_aborted(db_session, local_store, corpus_client):
    client, _ = corpus_client({"mrv": httpx.Response(500, text="down")}, {})
    with pytest.raises(httpx.HTTPStatusError):
        await ingest(db_session, client=client, topics=["mrv"], store=local_store)

    run = (await db_session.scalars(select(IngestRun))).one()
    assert run.status is IngestRunStatus.ABORTED
    assert run.completed_at is not None


async def test_completed_run_is_stamped_with_a_dated_corpus_version(
    db_session, local_store, corpus_client
):
    report = await ingest_mrv(db_session, local_store, corpus_client)

    run = await db_session.get(IngestRun, report.run_id)
    assert run.status is IngestRunStatus.SUCCESS
    assert run.completed_at is not None
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}-[0-9a-f]{7}", run.corpus_version)


async def test_unchanged_corpus_keeps_the_previous_corpus_version(
    db_session, local_store, corpus_client
):
    docs = mrv_docs()
    client, _ = corpus_client({"mrv": MRV_SPARQL}, docs)
    first = await ingest(db_session, client=client, topics=["mrv"], store=local_store)
    client, _ = corpus_client({"mrv": MRV_SPARQL}, docs)
    second = await ingest(db_session, client=client, topics=["mrv"], store=local_store)

    versions = [(await db_session.get(IngestRun, r.run_id)).corpus_version for r in (first, second)]
    assert versions[0] is not None
    assert versions[0] == versions[1]


async def test_changed_document_produces_a_new_corpus_version(
    db_session, local_store, corpus_client
):
    """The new consolidation is fetched in one request, its chunks reconciled, the corpus
    version moved on."""
    first = await ingest_mrv(db_session, local_store, corpus_client)

    consolidated = httpx.Response(
        200,
        json=payload(
            binding("32015R0757", force="1", cons="02015R0757-20250101"),
            binding("32023R2449", force="1"),
        ),
    )
    amended = SMALL_ACT.replace("report them annually", "report them every quarter")
    client, calls = corpus_client(
        {"mrv": consolidated},
        mrv_docs({"02015R0757-20250101": httpx.Response(200, content=amended.encode())}),
    )
    second = await ingest(db_session, client=client, topics=["mrv"], store=local_store)

    assert calls == ["02015R0757-20250101"]
    assert committed(second, DocChange.UPDATED) == ["32015R0757"]
    assert (second.chunks.added, second.chunks.deleted) == (1, 1)
    rows = await get_raw_documents(db_session, RawDocsQuery(include_topics=["mrv"]))
    assert rows["32015R0757"].resolved_celex == "02015R0757-20250101"
    versions = [(await db_session.get(IngestRun, r.run_id)).corpus_version for r in (first, second)]
    assert versions[0] != versions[1]


async def test_failed_run_is_stamped_with_what_it_committed(db_session, local_store, corpus_client):
    """The document that did land moved the corpus, so the version has to show it."""
    report = await ingest_mrv(
        db_session,
        local_store,
        corpus_client,
        docs=mrv_docs({"32023R2449": httpx.Response(400, text="bad")}),
    )

    run = await db_session.get(IngestRun, report.run_id)
    assert run.status is IngestRunStatus.FAILED
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}-[0-9a-f]{7}", run.corpus_version)


async def test_a_completed_run_records_what_each_stage_did(db_session, local_store, corpus_client):
    report = await ingest_mrv(db_session, local_store, corpus_client)

    run = await db_session.get(IngestRun, report.run_id)
    assert run.result == report.report()
    assert run.result["fetch"]["new"] == 2
    assert run.result["embed"]["embedded"] > 0


async def test_a_stage_failure_is_answerable_from_the_run_row(
    db_session, local_store, corpus_client
):
    report = await ingest_mrv(
        db_session,
        local_store,
        corpus_client,
        docs=mrv_docs({"32023R2449": httpx.Response(400, text="bad")}),
    )

    run = await db_session.get(IngestRun, report.run_id)
    assert "32023R2449" in run.result["fetch"]["failed"]
    assert run.result["fetch"]["new"] == 1


async def test_a_run_aborted_before_any_stage_ran_still_stores_a_report(
    db_session, local_store, corpus_client
):
    """The row owes a reader a status and a report; the counts are test_models' to pin."""
    client, _ = corpus_client({"mrv": httpx.Response(500, text="down")}, {})
    with pytest.raises(httpx.HTTPStatusError):
        await ingest(db_session, client=client, topics=["mrv"], store=local_store)

    run = (await db_session.scalars(select(IngestRun))).one()
    assert run.status is IngestRunStatus.ABORTED
    assert run.result == IngestRunResult(run_id=run.id).report()


async def test_malformed_sparql_payload_raises_discovery_error(
    db_session, local_store, corpus_client
):
    client, _ = corpus_client({"mrv": httpx.Response(200, json={"unexpected": True})}, {})
    with pytest.raises(MalformedDiscoveryError, match="malformed"):
        await ingest(db_session, client=client, topics=["mrv"], store=local_store)


async def test_a_failure_after_fetch_still_marks_the_run_aborted(
    db_session, local_store, corpus_client, monkeypatch
):
    async def explode(*args, **kwargs):
        raise RuntimeError("chunking blew up")

    monkeypatch.setattr("app.ingestion.pipeline.chunk_and_store_document", explode)
    client, _ = corpus_client({"mrv": MRV_SPARQL}, mrv_docs())
    with pytest.raises(RuntimeError):
        await ingest(db_session, client=client, topics=["mrv"], store=local_store)

    run = (await db_session.scalars(select(IngestRun))).one()
    assert run.status is IngestRunStatus.ABORTED
    assert run.completed_at is not None


async def test_a_failure_closing_the_run_out_still_marks_it_aborted(
    db_session, local_store, corpus_client, monkeypatch
):
    """The closing commit is where an integrity error or a Ctrl-C lands, so it must be covered."""
    real = pipeline.complete_ingest_run
    calls = []

    async def explode_once(session, run, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise RuntimeError("commit blew up")
        return await real(session, run, **kwargs)

    monkeypatch.setattr(pipeline, "complete_ingest_run", explode_once)
    client, _ = corpus_client({"mrv": MRV_SPARQL}, mrv_docs())
    with pytest.raises(RuntimeError, match="commit blew up"):
        await ingest(db_session, client=client, topics=["mrv"], store=local_store)

    run = (await db_session.scalars(select(IngestRun))).one()
    assert run.status is IngestRunStatus.ABORTED
    assert run.completed_at is not None


async def test_an_aborted_run_reports_exactly_the_documents_it_committed(
    db_session, local_store, corpus_client, monkeypatch
):
    """The row must not claim a document the abort rolled back: counts land after the commit."""
    real = pipeline.chunk_and_store_document
    calls: list[int] = []

    async def die_on_the_second(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("chunking blew up")
        return await real(*args, **kwargs)

    monkeypatch.setattr(pipeline, "chunk_and_store_document", die_on_the_second)
    client, _ = corpus_client({"mrv": MRV_SPARQL}, mrv_docs())
    with pytest.raises(RuntimeError):
        await ingest(db_session, client=client, topics=["mrv"], store=local_store)

    run = (await db_session.scalars(select(IngestRun))).one()
    stored = (await db_session.scalars(select(RawDocument))).all()
    assert run.result["fetch"]["new"] == len(stored) == 1
    assert run.result["parse"]["parsed"] == 1
    assert run.status is IngestRunStatus.ABORTED


async def test_run_persists_chunks_for_every_document(db_session, local_store, corpus_client):
    report = await ingest_mrv(db_session, local_store, corpus_client)

    rows = await chunk_rows(db_session)
    assert report.ok
    assert report.chunks.added == len(rows) > 0
    assert {row.celex for row in rows} == {"32015R0757", "32023R2449"}
    assert {row.ingest_run_id for row in rows} == {report.run_id}
    assert await chunk_versions(db_session) == {report.corpus_version}


async def test_second_identical_run_adds_and_removes_nothing(
    db_session, local_store, corpus_client
):
    docs = mrv_docs()
    client, _ = corpus_client({"mrv": MRV_SPARQL}, docs)
    await ingest(db_session, client=client, topics=["mrv"], store=local_store)
    before = {row.id for row in await chunk_rows(db_session)}

    client, calls = corpus_client({"mrv": MRV_SPARQL}, docs)
    second = await ingest(db_session, client=client, topics=["mrv"], store=local_store)

    assert calls == []
    assert committed(second, DocChange.REUSED) == ["32015R0757", "32023R2449"]
    assert (second.chunks.added, second.chunks.deleted) == (0, 0)
    assert second.chunks.kept == len(before)
    assert {row.id for row in await chunk_rows(db_session)} == before


ONLY_SEED_SPARQL = httpx.Response(200, json=payload(binding("32015R0757", force="1")))


def new_version(celex: str) -> str:
    """A consolidated version the last run never saw, so the act has to be downloaded again."""
    return f"{consolidated_stem(celex)}20250101"


async def test_dropped_document_loses_its_chunks(db_session, local_store, corpus_client):
    docs = mrv_docs()
    client, _ = corpus_client({"mrv": MRV_SPARQL}, docs)
    await ingest(db_session, client=client, topics=["mrv"], store=local_store)
    assert await chunk_rows(db_session, "32023R2449")

    client, _ = corpus_client({"mrv": ONLY_SEED_SPARQL}, docs)
    report = await ingest(db_session, client=client, topics=["mrv"], store=local_store)

    assert report.dropped == ["32023R2449"]
    assert await chunk_rows(db_session, "32023R2449") == []
    assert await chunk_rows(db_session, "32015R0757")


async def test_dropped_document_loses_its_chunks_after_an_intervening_failed_fetch(
    db_session, local_store, corpus_client
):
    """A failed fetch does not hide the drop from the next run, and the chunks must still go.

    The failure has to land on a version the run actually downloads: an unchanged act is
    never requested, so it has no way to fail.
    """
    await ingest_mrv(db_session, local_store, corpus_client)
    assert await chunk_rows(db_session, "32023R2449")

    consolidated = httpx.Response(
        200,
        json=payload(
            binding("32015R0757", force="1"),
            binding("32023R2449", force="1", cons=new_version("32023R2449")),
        ),
    )
    client, _ = corpus_client(
        {"mrv": consolidated},
        mrv_docs({new_version("32023R2449"): httpx.Response(400, text="bad")}),
    )
    await ingest(db_session, client=client, topics=["mrv"], store=local_store)

    report = await ingest_mrv(db_session, local_store, corpus_client, sparql=ONLY_SEED_SPARQL)

    assert report.dropped == ["32023R2449"]
    assert await chunk_rows(db_session, "32023R2449") == []
    assert await chunk_rows(db_session, "32015R0757")


WIDE_CELEXES = ["32015R0757", "32023R2449", "32026R0001", "32026R0002", "32026R0003"]
WIDE_SPARQL = httpx.Response(
    200, json=payload(*(binding(celex, force="1") for celex in WIDE_CELEXES))
)


def wide_docs() -> dict[str, httpx.Response]:
    """A five-document mrv corpus, enough that losing most of it is implausible."""
    return {celex: small_act() for celex in WIDE_CELEXES}


async def test_discovery_losing_most_of_the_corpus_aborts_and_deletes_nothing(
    db_session, local_store, corpus_client
):
    """A truncated result set reads exactly like a mass repeal, so refuse to act on it."""
    client, _ = corpus_client({"mrv": WIDE_SPARQL}, wide_docs())
    await ingest(db_session, client=client, topics=["mrv"], store=local_store)
    before = {row.id for row in await chunk_rows(db_session)}
    assert before

    client, _ = corpus_client({"mrv": ONLY_SEED_SPARQL}, wide_docs())
    with pytest.raises(CorpusShrankError, match="lost 4 of 5"):
        await ingest(db_session, client=client, topics=["mrv"], store=local_store)

    assert {row.id for row in await chunk_rows(db_session)} == before


async def test_a_plausible_repeal_still_prunes(db_session, local_store, corpus_client):
    """One document out of five is an ordinary repeal, not a truncated response."""
    client, _ = corpus_client({"mrv": WIDE_SPARQL}, wide_docs())
    await ingest(db_session, client=client, topics=["mrv"], store=local_store)

    kept = [binding(celex, force="1") for celex in WIDE_CELEXES if celex != "32026R0003"]
    client, _ = corpus_client({"mrv": httpx.Response(200, json=payload(*kept))}, wide_docs())
    report = await ingest(db_session, client=client, topics=["mrv"], store=local_store)

    assert report.dropped == ["32026R0003"]
    assert await chunk_rows(db_session, "32026R0003") == []


async def test_an_incomplete_run_prunes_nothing(db_session, local_store, corpus_client):
    """A run that could not fetch its whole corpus has no business declaring anything obsolete."""
    await ingest_mrv(db_session, local_store, corpus_client)
    assert await chunk_rows(db_session, "32023R2449")

    seed_consolidated = httpx.Response(
        200, json=payload(binding("32015R0757", force="1", cons=new_version("32015R0757")))
    )
    client, _ = corpus_client(
        {"mrv": seed_consolidated},
        mrv_docs({new_version("32015R0757"): httpx.Response(400, text="bad")}),
    )
    report = await ingest(db_session, client=client, topics=["mrv"], store=local_store)

    assert report.dropped == ["32023R2449"]
    assert not report.ok
    assert report.chunks.deleted == 0
    assert await chunk_rows(db_session, "32023R2449")


FUELEU_PLUS_SHARED = httpx.Response(
    200, json=payload(binding("32023R1805", force="1"), binding("32015R0757", force="1"))
)


async def test_a_celex_another_topic_still_holds_survives_being_dropped(
    db_session, local_store, corpus_client
):
    """32015R0757 is tagged fueleu because fueleu saw it first; mrv still wanting it must win."""
    shared_docs = {
        "32023R1805": httpx.Response(200, content=FUELEU_HTML.encode()),
        "32015R0757": httpx.Response(200, content=FUELEU_HTML.encode()),
    }
    client, _ = corpus_client({"fueleu": FUELEU_PLUS_SHARED}, shared_docs)
    await ingest(db_session, client=client, topics=["fueleu"], store=local_store)
    assert {row.topic for row in await chunk_rows(db_session, "32015R0757")} == {"fueleu"}

    await ingest_mrv(db_session, local_store, corpus_client)

    client, _ = corpus_client({"fueleu": FUELEU_SPARQL}, shared_docs)
    report = await ingest(db_session, client=client, topics=["fueleu"], store=local_store)

    assert report.dropped == ["32015R0757"]
    assert await chunk_rows(db_session, "32015R0757")


async def test_unparseable_document_is_recorded_and_others_persist(
    db_session, local_store, corpus_client
):
    client, _ = corpus_client(
        {"mrv": MRV_SPARQL},
        mrv_docs({"32023R2449": httpx.Response(200, content=b"<html>not eur-lex</html>")}),
    )
    report = await ingest(db_session, client=client, topics=["mrv"], store=local_store)

    assert "32023R2449" in report.failures[Stage.PARSE]
    assert not report.ok
    assert await chunk_rows(db_session, "32015R0757")
    assert await chunk_rows(db_session, "32023R2449") == []
    run = await db_session.get(IngestRun, report.run_id)
    assert run.status is IngestRunStatus.FAILED


async def test_a_freshly_downloaded_document_is_parsed_without_reading_it_back(
    db_session, local_store, corpus_client, monkeypatch
):
    """The download already holds the bytes, so parse must not pay a second storage round trip.

    Asserted over the whole loop rather than the fetch stage: fetch alone never reads the store
    for a document it just downloaded, so only a run that goes on to parse can catch the reread.
    """
    reads: list[str] = []

    def record(key: str) -> bytes:
        reads.append(key)
        raise AssertionError(f"parse read {key} back from the store")

    monkeypatch.setattr(local_store, "get", record)
    report = await ingest_mrv(db_session, local_store, corpus_client)

    assert report.ok
    assert reads == []


async def test_a_source_document_lost_from_the_store_is_downloaded_again(
    db_session, local_store, corpus_client
):
    docs = mrv_docs()
    client, _ = corpus_client({"mrv": MRV_SPARQL}, docs)
    await ingest(db_session, client=client, topics=["mrv"], store=local_store)
    for path in local_store.root.rglob("*.html"):
        path.unlink()

    client, _ = corpus_client({"mrv": MRV_SPARQL}, docs)
    report = await ingest(db_session, client=client, topics=["mrv"], store=local_store)

    rows = await get_raw_documents(db_session, RawDocsQuery(include_topics=["mrv"]))
    row = rows["32015R0757"]
    assert local_store.exists(document_key(row.celex, row.resolved_celex, row.sha256))
    assert report.ok


async def test_a_store_write_failure_is_recorded_not_raised(
    db_session, local_store, corpus_client, monkeypatch
):
    def full_disk(key, content):
        raise StorageError("put", key, OSError(28, "No space left on device"))

    monkeypatch.setattr(local_store, "put", full_disk)
    report = await ingest_mrv(db_session, local_store, corpus_client)

    assert sorted(report.failures[Stage.FETCH]) == ["32015R0757", "32023R2449"]
    assert all("StorageError" in reason for reason in report.failures[Stage.FETCH].values())
    assert not report.ok


async def test_an_interrupt_still_marks_the_run_aborted(
    db_session, local_store, corpus_client, monkeypatch
):
    async def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr("app.ingestion.pipeline.chunk_and_store_document", interrupt)
    client, _ = corpus_client({"mrv": MRV_SPARQL}, mrv_docs())
    with pytest.raises(KeyboardInterrupt):
        await ingest(db_session, client=client, topics=["mrv"], store=local_store)

    run = (await db_session.scalars(select(IngestRun))).one()
    assert run.status is IngestRunStatus.ABORTED
    assert run.completed_at is not None


async def test_a_database_failure_does_not_mask_itself(
    db_session, local_store, corpus_client, monkeypatch
):
    """The failure handler must roll back first, or its own commit raises over the real cause."""

    async def explode(*args, **kwargs):
        await db_session.execute(text("SELECT * FROM no_such_table"))

    monkeypatch.setattr("app.ingestion.pipeline.chunk_and_store_document", explode)
    client, _ = corpus_client({"mrv": MRV_SPARQL}, mrv_docs())
    with pytest.raises(ProgrammingError):
        await ingest(db_session, client=client, topics=["mrv"], store=local_store)

    run = (await db_session.scalars(select(IngestRun))).one()
    assert run.status is IngestRunStatus.ABORTED


async def test_partial_fetch_stamps_the_chunks_it_stored(db_session, local_store, corpus_client):
    report = await ingest_mrv(
        db_session,
        local_store,
        corpus_client,
        docs=mrv_docs({"32023R2449": httpx.Response(400, text="bad")}),
    )

    assert report.corpus_version is not None
    assert await chunk_versions(db_session, "32015R0757") == {report.corpus_version}


async def test_chunks_stay_attributed_to_the_run_that_first_stored_them(
    db_session, local_store, corpus_client
):
    """A later whole-corpus run leaves matched chunks pointing at the run they came from,
    and so at the version that failed run was stamped with."""
    partial = await ingest_mrv(
        db_session,
        local_store,
        corpus_client,
        docs=mrv_docs({"32023R2449": httpx.Response(400, text="bad")}),
    )

    report = await ingest_mrv(db_session, local_store, corpus_client)

    assert report.corpus_version != partial.corpus_version
    rows = await chunk_rows(db_session, "32015R0757")
    assert {row.ingest_run_id for row in rows} == {partial.run_id}
    assert await chunk_versions(db_session, "32015R0757") == {partial.corpus_version}


async def test_failed_fetch_still_chunks_what_was_downloaded(
    db_session, local_store, corpus_client
):
    report = await ingest_mrv(
        db_session,
        local_store,
        corpus_client,
        docs=mrv_docs({"32023R2449": httpx.Response(400, text="bad")}),
    )

    assert "32023R2449" in report.failures[Stage.FETCH]
    assert not report.ok
    assert await chunk_rows(db_session, "32015R0757")


FUELEU_SPARQL = httpx.Response(200, json=payload(binding("32023R1805", force="1")))


async def ingest_fueleu(db_session, local_store, corpus_client) -> IngestRunResult:
    """Run the real pipeline over the saved FuelEU fixture, network stubbed."""
    client, _ = corpus_client(
        {"fueleu": FUELEU_SPARQL},
        {"32023R1805": httpx.Response(200, content=FUELEU_HTML.encode())},
    )
    return await ingest(db_session, client=client, topics=["fueleu"], store=local_store)


async def test_fueleu_chunks_are_stamped_and_topic_tagged(db_session, local_store, corpus_client):
    report = await ingest_fueleu(db_session, local_store, corpus_client)

    rows = await chunk_rows(db_session, "32023R1805")
    assert {row.topic for row in rows} == {"fueleu"}
    assert await chunk_versions(db_session, "32023R1805") == {report.corpus_version}
    assert report.corpus_version is not None
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}-[0-9a-f]{7}", report.corpus_version)


async def test_single_topic_run_leaves_another_topics_chunks_alone(
    db_session, local_store, corpus_client
):
    await ingest_fueleu(db_session, local_store, corpus_client)
    before = {row.id for row in await chunk_rows(db_session, "32023R1805")}
    assert before

    await ingest_mrv(db_session, local_store, corpus_client)

    assert {row.id for row in await chunk_rows(db_session, "32023R1805")} == before


async def test_a_run_embeds_every_chunk_it_stored(db_session, local_store, corpus_client):
    report = await ingest_fueleu(db_session, local_store, corpus_client)

    rows = await chunk_rows(db_session, "32023R1805")
    assert report.ok
    assert report.embed.embedded == len(rows) > 0
    assert all(row.embedding is not None for row in rows)


async def test_a_second_run_embeds_nothing_and_reports_the_rest_unchanged(
    db_session, local_store, corpus_client
):
    await ingest_fueleu(db_session, local_store, corpus_client)
    stored = len(await chunk_rows(db_session, "32023R1805"))

    second = await ingest_fueleu(db_session, local_store, corpus_client)

    assert second.ok
    assert second.failures[Stage.EMBED] == {}
    assert (second.embed.embedded, second.embed.already_embedded) == (0, stored)


async def test_a_document_that_fails_does_not_stop_the_documents_after_it(
    db_session, local_store, corpus_client
):
    """The loop is per document across three stages: one bad document skips only itself."""
    docs = mrv_docs({"32015R0757": httpx.Response(400, text="bad")})
    client, _ = corpus_client({"mrv": MRV_SPARQL}, docs)

    report = await ingest(db_session, client=client, topics=["mrv"], store=local_store)

    assert list(report.failures[Stage.FETCH]) == ["32015R0757"]
    assert committed(report, DocChange.NEW) == ["32023R2449"]
    assert report.chunks.added > 0
    assert not report.ok


async def test_every_ingestion_error_is_recorded_against_its_own_document(
    db_session, local_store, corpus_client, monkeypatch
):
    """The loop catches the whole IngestionError family, not only the ones fetch raises itself."""

    def unparseable(*args, **kwargs):
        raise ParseError("unrecognised EUR-Lex dialect")

    monkeypatch.setattr(fetch_stage, "_reuse_previous_version", unparseable)
    report = await ingest_mrv(db_session, local_store, corpus_client)

    assert sorted(report.failures[Stage.FETCH]) == ["32015R0757", "32023R2449"]
    assert set(report.failures[Stage.FETCH].values()) == {
        "ParseError: unrecognised EUR-Lex dialect"
    }


async def test_a_row_that_will_not_flush_fails_only_its_own_document(
    db_session, local_store, corpus_client, monkeypatch
):
    """A database error on one row skips that document without poisoning the run's transaction.

    Asserted here rather than over the fetch stage alone: only the real loop commits, which is
    what makes the surviving document's rows readable afterwards rather than merely pending.
    """
    real = fetch_stage._download_new_version

    async def unstorable(client, store, discovered, run):
        document, content = await real(client, store, discovered, run)
        if discovered.celex == "32015R0757":
            document.size_bytes = 2**40
        return document, content

    monkeypatch.setattr(fetch_stage, "_download_new_version", unstorable)
    report = await ingest_mrv(db_session, local_store, corpus_client)

    assert list(report.failures[Stage.FETCH]) == ["32015R0757"]
    assert committed(report, DocChange.NEW) == ["32023R2449"]
    assert list(await get_raw_documents(db_session, RawDocsQuery(include_topics=["mrv"]))) == [
        "32023R2449"
    ]


async def test_a_document_that_fails_to_parse_leaves_no_row_behind(
    db_session, local_store, corpus_client
):
    """A document lands whole or not at all, so no count can claim work the loop rolled back."""
    client, _ = corpus_client(
        {"mrv": MRV_SPARQL},
        mrv_docs({"32023R2449": httpx.Response(200, content=b"<html>not eur-lex</html>")}),
    )
    report = await ingest(db_session, client=client, topics=["mrv"], store=local_store)

    assert list(report.failures[Stage.PARSE]) == ["32023R2449"]
    assert committed(report, DocChange.NEW) == ["32015R0757"]
    assert "32023R2449" not in await get_raw_documents(
        db_session, RawDocsQuery(include_topics=["mrv"])
    )


async def test_a_failed_document_leaves_the_rows_the_next_one_needs_readable(
    db_session, local_store, corpus_client
):
    """Rolling one document back must not expire the previous run's rows out from under the rest."""
    docs = mrv_docs()
    client, _ = corpus_client({"mrv": MRV_SPARQL}, docs)
    await ingest(db_session, client=client, topics=["mrv"], store=local_store)

    consolidated = httpx.Response(
        200,
        json=payload(
            binding("32015R0757", force="1", cons=new_version("32015R0757")),
            binding("32023R2449", force="1"),
        ),
    )
    client, _ = corpus_client(
        {"mrv": consolidated},
        mrv_docs({new_version("32015R0757"): httpx.Response(400, text="bad")}),
    )
    report = await ingest(db_session, client=client, topics=["mrv"], store=local_store)

    assert list(report.failures[Stage.FETCH]) == ["32015R0757"]
    assert committed(report, DocChange.REUSED) == ["32023R2449"]


async def test_a_run_that_died_mid_loop_does_not_stand_for_its_topics_corpus(
    db_session, local_store, corpus_client, monkeypatch
):
    """An aborted run holds a prefix, not a corpus: another topic must not prune the rest."""
    docs = mrv_docs()
    client, _ = corpus_client({"mrv": MRV_SPARQL}, docs)
    await ingest(db_session, client=client, topics=["mrv"], store=local_store)
    assert await chunk_rows(db_session, "32023R2449")

    real = pipeline.chunk_and_store_document
    calls: list[int] = []

    async def die_on_the_second(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise KeyboardInterrupt
        return await real(*args, **kwargs)

    monkeypatch.setattr(pipeline, "chunk_and_store_document", die_on_the_second)
    client, _ = corpus_client({"mrv": MRV_SPARQL}, docs)
    with pytest.raises(KeyboardInterrupt):
        await ingest(db_session, client=client, topics=["mrv"], store=local_store)

    monkeypatch.setattr(pipeline, "chunk_and_store_document", real)
    client, _ = corpus_client(
        {"fueleu": FUELEU_SPARQL},
        {"32023R1805": httpx.Response(200, content=FUELEU_HTML.encode())},
    )
    await ingest(db_session, client=client, topics=["fueleu"], store=local_store)

    assert await chunk_rows(db_session, "32023R2449")


async def test_a_run_that_dies_in_embed_keeps_its_documents_and_chunks(
    db_session, local_store, corpus_client, monkeypatch
):
    """A late failure must not discard the fetch and chunk work the run already committed."""

    real_embed_chunks = pipeline.embed_chunks

    async def provider_gone(session):
        raise RuntimeError("provider gone")

    monkeypatch.setattr(pipeline, "embed_chunks", provider_gone)
    client, _ = corpus_client({"mrv": MRV_SPARQL}, mrv_docs())

    with pytest.raises(RuntimeError):
        await ingest(db_session, client=client, topics=["mrv"], store=local_store)

    assert await chunk_versions(db_session) != set()
    assert set(await get_raw_documents(db_session, RawDocsQuery(include_topics=["mrv"]))) == {
        "32015R0757",
        "32023R2449",
    }

    monkeypatch.setattr(pipeline, "embed_chunks", real_embed_chunks)
    stored = len(await chunk_rows(db_session))
    client, calls = corpus_client({"mrv": MRV_SPARQL}, mrv_docs())
    second = await ingest(db_session, client=client, topics=["mrv"], store=local_store)

    assert calls == []
    assert second.embed.embedded == stored
    assert second.chunks.added == 0
    assert second.ok


async def test_a_failed_embed_batch_fails_the_run_and_the_next_run_fills_the_gap(
    db_session, local_store, corpus_client, embeddings
):
    """A batch the provider refuses is recorded, not raised, so nothing else marks the run."""
    embeddings.errors[1] = LLMError("embedding call failed")

    first = await ingest_mrv(db_session, local_store, corpus_client)

    run = await db_session.get(IngestRun, first.run_id)
    assert run.status is IngestRunStatus.FAILED
    assert list(first.embed.failed) == ["32015R0757"]
    lost = first.embed.failed["32015R0757"].chunks

    client, calls = corpus_client({"mrv": MRV_SPARQL}, mrv_docs())
    second = await ingest(db_session, client=client, topics=["mrv"], store=local_store)

    assert calls == []
    assert second.embed.embedded == lost
    assert second.ok


async def test_a_consolidation_cellar_will_not_serve_is_not_asked_for_again(
    db_session, local_store, corpus_client
):
    """An act with a consolidated id but no consolidated text falls back to the act itself.
    Reuse compares the candidates, not the version served, or the fallback would be denied
    every night and the corpus downloaded again for as long as CELLAR serves no consolidation."""
    sparql = httpx.Response(
        200,
        json=payload(
            binding("32015R0757", force="1", cons="02015R0757-20250101"),
            binding("32023R2449", force="1"),
        ),
    )
    unserved = {"02015R0757-20250101": httpx.Response(404, text="gone")}
    await ingest_mrv(db_session, local_store, corpus_client, sparql, mrv_docs(unserved))

    client, calls = corpus_client({"mrv": sparql}, mrv_docs(unserved))
    second = await ingest(db_session, client=client, topics=["mrv"], store=local_store)

    assert calls == []
    assert committed(second, DocChange.REUSED) == ["32015R0757", "32023R2449"]


async def test_a_store_outage_fails_the_run_rather_than_refetching_the_corpus(
    db_session, local_store, corpus_client, monkeypatch
):
    """Every document's bytes unreadable at once is the store, not the corpus: nothing is
    downloaded again, and nothing already stored is pruned."""
    await ingest_mrv(db_session, local_store, corpus_client)
    before = {row.id for row in await chunk_rows(db_session)}

    def outage(key: str) -> bytes:
        raise StorageError("get", key, "connection reset by peer")

    monkeypatch.setattr(local_store, "get", outage)
    client, calls = corpus_client({"mrv": MRV_SPARQL}, mrv_docs())
    second = await ingest(db_session, client=client, topics=["mrv"], store=local_store)

    assert calls == []
    assert sorted(second.failures[Stage.FETCH]) == ["32015R0757", "32023R2449"]
    assert not second.ok
    assert {row.id for row in await chunk_rows(db_session)} == before


async def test_a_run_where_every_document_fails_still_reports_the_later_stages(
    db_session, local_store, corpus_client, monkeypatch
):
    """Parse and chunk had nothing to do; the row reports that as zeroes, not as a failure."""

    def full_disk(key, content):
        raise StorageError("put", key, OSError(28, "No space left on device"))

    monkeypatch.setattr(local_store, "put", full_disk)
    client, _ = corpus_client({"mrv": MRV_SPARQL}, mrv_docs())

    report = await ingest(db_session, client=client, topics=["mrv"], store=local_store)

    assert report.report()["parse"] == {"documents": 0, "parsed": 0, "failed": {}}
    assert report.report()["chunk"] == {
        "chunks": 0,
        "added": 0,
        "deleted": 0,
        "kept": 0,
        "updated": 0,
        "failed": {},
    }
    assert not report.ok


CITING_ACT = (
    '<html><body><div class="eli-subdivision" id="art_1">'
    '<p class="oj-ti-art">Article 1</p>'
    '<p class="oj-normal">1. Verifiers shall be accredited under Article 4 of '
    "Regulation (EC) No 765/2008.</p>"
    "</div></body></html>"
)
"""One act citing a division of another, which is what the hop follows."""

HOP_ACT = (
    '<html><body><div class="eli-subdivision" id="art_1">'
    '<p class="oj-ti-art">Article 1</p>'
    '<p class="oj-normal">1. Permits shall meet Article 15 of Directive 2010/75/EU.</p>'
    "</div></body></html>"
)
"""What a hop document cites in its turn, which no run may follow."""


def citing_docs(hop: str = SMALL_ACT) -> dict[str, httpx.Response]:
    """An mrv corpus whose seed cites Regulation 765/2008, plus that act itself."""
    return mrv_docs(
        {
            "32015R0757": httpx.Response(200, content=CITING_ACT.encode()),
            "32008R0765": httpx.Response(200, content=hop.encode()),
        }
    )


CITED_SPARQL_JSON = payload(binding("32008R0765", force="1"))


async def test_the_hop_stores_the_act_a_chunk_cites_a_division_of(
    db_session, local_store, corpus_client
):
    client, _ = corpus_client(
        {"mrv": MRV_SPARQL, CITED_TOPIC: httpx.Response(200, json=CITED_SPARQL_JSON)},
        citing_docs(),
    )

    report = await ingest(db_session, client=client, topics=["mrv"], store=local_store)

    assert report.ok
    assert report.discovered == 3
    stored = {row.celex: row.topic for row in await chunk_rows(db_session)}
    assert stored["32008R0765"] == CITED_TOPIC


async def test_the_hop_does_not_follow_what_it_brought_in(db_session, local_store, corpus_client):
    """The cited acts cite further acts. Reading their citations too would follow the graph one
    step further every run, and the closure of that is most of EU law."""

    def run_client():
        return corpus_client(
            {"mrv": MRV_SPARQL, CITED_TOPIC: httpx.Response(200, json=CITED_SPARQL_JSON)},
            citing_docs(hop=HOP_ACT),
        )[0]

    first = await ingest(db_session, client=run_client(), topics=["mrv"], store=local_store)
    second = await ingest(db_session, client=run_client(), topics=["mrv"], store=local_store)

    assert (first.discovered, second.discovered) == (3, 3)
    assert "32010L0075" not in {row.celex for row in await chunk_rows(db_session)}


async def test_a_cited_act_nothing_cites_any_more_is_pruned(db_session, local_store, corpus_client):
    client, _ = corpus_client(
        {"mrv": MRV_SPARQL, CITED_TOPIC: httpx.Response(200, json=CITED_SPARQL_JSON)},
        citing_docs(),
    )
    await ingest(db_session, client=client, topics=["mrv"], store=local_store)
    assert await chunk_rows(db_session, "32008R0765")

    silent, _ = corpus_client(
        {"mrv": MRV_SPARQL, CITED_TOPIC: httpx.Response(200, json=payload())}, citing_docs()
    )
    report = await ingest(db_session, client=silent, topics=["mrv"], store=local_store)

    assert report.ok
    assert await chunk_rows(db_session, "32008R0765") == []


async def test_the_hop_is_on_by_default(db_session, local_store, corpus_client):
    client, _ = corpus_client(
        {"mrv": MRV_SPARQL, CITED_TOPIC: httpx.Response(200, json=CITED_SPARQL_JSON)},
        citing_docs(),
    )

    report = await ingest(db_session, client=client, topics=["mrv"], store=local_store)

    assert report.discovered == 3


FLAT_ACT = (
    '<html><body><p class="oj-ti-art">Article 1</p>'
    '<p class="oj-normal">1. Member States shall set national targets.</p>'
    "</body></html>"
)
"""A consolidation rendered without the eli-subdivision wrappers the parser looks for, which is
how 32018R0842 comes back and what the hop has to survive one of."""


async def test_a_hop_document_that_will_not_parse_does_not_fail_the_run(
    db_session, local_store, corpus_client
):
    """A cited act is followed opportunistically, not asked for. Judged on it, one unparseable
    act would skip the prune and exit 1 on every run that followed the citation."""
    client, _ = corpus_client(
        {"mrv": MRV_SPARQL, CITED_TOPIC: httpx.Response(200, json=CITED_SPARQL_JSON)},
        citing_docs(hop=FLAT_ACT),
    )

    report = await ingest(db_session, client=client, topics=["mrv"], store=local_store)

    assert list(report.failures[Stage.PARSE]) == ["32008R0765"]
    assert report.ok
    assert report.corpus_complete
    assert report.status is IngestRunStatus.SUCCESS


async def test_a_seed_that_will_not_parse_still_fails_the_run(
    db_session, local_store, corpus_client
):
    """Only the hop is forgiven: a topic's own act failing still means the corpus is incomplete."""
    client, _ = corpus_client(
        {"mrv": MRV_SPARQL, CITED_TOPIC: httpx.Response(200, json=CITED_SPARQL_JSON)},
        mrv_docs({"32023R2449": httpx.Response(200, content=FLAT_ACT.encode())}),
    )

    report = await ingest(db_session, client=client, topics=["mrv"], store=local_store)

    assert list(report.failures[Stage.PARSE]) == ["32023R2449"]
    assert not report.ok
    assert not report.corpus_complete


async def test_turning_the_hop_off_leaves_what_it_brought_in_alone(
    db_session, local_store, corpus_client, monkeypatch
):
    """Off has to mean out of scope: read as a topic this run names, every hop row a previous
    run made would read as dropped by a discovery that no longer asks for it."""
    client, _ = corpus_client(
        {"mrv": MRV_SPARQL, CITED_TOPIC: httpx.Response(200, json=CITED_SPARQL_JSON)},
        citing_docs(),
    )
    await ingest(db_session, client=client, topics=["mrv"], store=local_store)

    monkeypatch.setattr(config, "FOLLOW_CITED_ACTS", False)
    off, _ = corpus_client({"mrv": MRV_SPARQL}, citing_docs())
    report = await ingest(db_session, client=off, topics=["mrv"], store=local_store)

    assert report.ok
    assert report.dropped == []
    assert await chunk_rows(db_session, "32008R0765")


async def test_a_single_topic_run_keeps_another_topic_cited_act(
    db_session, local_store, corpus_client
):
    """The hop reads the whole corpus, so the topics a run leaves out keep what they cite."""
    client, _ = corpus_client(
        {"mrv": MRV_SPARQL, CITED_TOPIC: httpx.Response(200, json=CITED_SPARQL_JSON)},
        citing_docs(),
    )
    await ingest(db_session, client=client, topics=["mrv"], store=local_store)

    fueleu = httpx.Response(200, json=payload(binding("32023R1805", force="1")))
    other, _ = corpus_client(
        {"fueleu": fueleu, CITED_TOPIC: httpx.Response(200, json=CITED_SPARQL_JSON)},
        {"32023R1805": small_act(), "32008R0765": small_act()},
    )
    report = await ingest(db_session, client=other, topics=["fueleu"], store=local_store)

    assert report.ok
    assert await chunk_rows(db_session, "32008R0765")
    assert await chunk_rows(db_session, "32015R0757")
    standing = await get_raw_documents(db_session, RawDocsQuery())
    assert "32008R0765" in standing
