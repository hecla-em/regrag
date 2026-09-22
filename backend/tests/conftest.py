"""Shared test fixtures."""

import pkgutil
import re
import zlib
from collections.abc import AsyncGenerator, Callable, Generator, Iterator
from contextlib import asynccontextmanager
from functools import cache, partial
from importlib import import_module
from math import sqrt
from pathlib import Path
from types import ModuleType
from typing import Any

import anyio
import httpx
import pytest
import sentry_sdk
from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.messages.ai import UsageMetadata
from redis.asyncio import Redis
from sentry_sdk.envelope import Envelope
from sentry_sdk.transport import Transport
from sentry_sdk.types import Event
from sqlalchemy import URL, create_engine, delete, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool
from tenacity import wait_none

from app.chat.graph import nodes
from app.chat.graph.nodes.assess import call_assess_model
from app.chat.graph.nodes.decompose import call_decompose_model
from app.chat.graph.nodes.rewrite import call_rewrite_model
from app.chat.graph.nodes.synthesize import synthesize
from app.chat.schemas import ChatRequest
from app.core.clock import utc_now
from app.core.config import BACKEND_ROOT, EMBED_DIMENSIONS, Environment, config
from app.core.db.session import async_session_factory, get_session
from app.core.llm.models import Usage
from app.core.redis import redis_client
from app.core.sentry import configure_sentry
from app.core.storage import LocalObjectStore
from app.evals.judge.service import call_judge_model
from app.ingestion.chunk.models import Chunk
from app.ingestion.chunk.references import list_points
from app.ingestion.chunk.schemas import DocumentChunk
from app.ingestion.chunk.service import get_corpus_stats, sync_document_chunks
from app.ingestion.chunk.tree import chunk_document
from app.ingestion.discover.models import ActsQueryRow
from app.ingestion.discover.sparql import run_acts_by_topic_query
from app.ingestion.embed.batch import embed_batch
from app.ingestion.enums import CITED_TOPIC, IngestRunStatus, SectionKind
from app.ingestion.fetch.download import _download_version_html
from app.ingestion.fetch.schemas import RawDocument
from app.ingestion.fetch.storage import write_document
from app.ingestion.parse.html.document import parse_eurlex_html
from app.ingestion.parse.models import ParsedDocument
from app.ingestion.schemas import IngestRun
from app.main import configure_app, lifespan
from app.retrieval.models import RetrievedChunk, SearchResult

RETRIED = (
    run_acts_by_topic_query,
    _download_version_html,
    embed_batch,
    call_rewrite_model,
    call_decompose_model,
    call_assess_model,
    synthesize,
    call_judge_model,
)

PARSE_FIXTURES = Path(__file__).parent / "ingestion" / "parse" / "fixtures"
FUELEU_HTML = (PARSE_FIXTURES / "32023R1805.html").read_text()


@pytest.fixture
def defuse_retry(monkeypatch: pytest.MonkeyPatch) -> Callable[[Callable], Callable]:
    """Strip tenacity's waits from a retry-wrapped function, keeping its retry behaviour."""

    def _defuse(fn: Callable) -> Callable:
        # ty: ignore[unresolved-attribute] — tenacity sets .retry dynamically, untyped
        monkeypatch.setattr(fn.retry, "wait", wait_none())
        return fn

    return _defuse


@pytest.fixture(autouse=True)
def no_retry_backoff(defuse_retry: Callable[[Callable], Callable]) -> None:
    """Defuse every retry-wrapped callable in RETRIED, so retry tests don't sleep."""
    for fn in RETRIED:
        defuse_retry(fn)


def _create_database_if_missing(url: URL) -> None:
    """CREATE DATABASE cannot run in a transaction, so issue it autocommitting on `postgres`."""
    engine = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    exists = text("SELECT 1 FROM pg_database WHERE datname = :name")
    with engine.connect() as conn:
        if not conn.scalar(exists, {"name": url.database}):
            conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    engine.dispose()


@pytest.fixture(scope="session")
def test_database() -> None:
    """Bring the test database into existence and up to head before anything connects.

    Reached through db_engine rather than autouse, so a run of the pure-unit tests still
    needs no server. Migrating every session is what keeps the schema honest: a new revision
    would otherwise only reach the suite once someone ran alembic against it by hand.
    """
    assert config.DB_NAME == "regrag_test", (
        "the suite deletes rows, so it never runs on a dev database"
    )
    migrate_to_head()


def migrate_to_head() -> None:
    """Create the configured database if it is missing, and upgrade it to head."""
    _create_database_if_missing(config.SQLALCHEMY_DATABASE_URI)
    alembic = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    alembic.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    command.upgrade(alembic, "head")


@pytest.fixture(scope="session")
def db_engine(test_database: None) -> AsyncEngine:
    """NullPool so each test's connection lives and dies inside its own event loop."""
    return create_async_engine(config.SQLALCHEMY_DATABASE_URI, poolclass=NullPool)


@asynccontextmanager
async def no_session(**kwargs: Any) -> AsyncGenerator[None, None]:
    """Stands in for get_session where the code under test never touches the session."""
    yield None


@asynccontextmanager
async def rolled_back_session(
    db_engine: AsyncEngine, *, clear: bool = True
) -> AsyncGenerator[AsyncSession, None]:
    """Session bound to a transaction that is always rolled back, optionally clearing ingest tables.

    Savepoint join mode so a commit inside the session outlives a later rollback, as in production.
    """
    async with db_engine.connect() as conn:
        trans = await conn.begin()
        if clear:
            await conn.execute(delete(DocumentChunk))
            await conn.execute(delete(RawDocument))
            await conn.execute(delete(IngestRun))
        async with async_session_factory(
            bind=conn, join_transaction_mode="create_savepoint"
        ) as session:
            yield session
        await trans.rollback()


@pytest.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """A session over empty ingest tables, whose writes never outlive the test."""
    async with rolled_back_session(db_engine) as session:
        yield session


@pytest.fixture
def make_document() -> Callable[..., RawDocument]:
    """Build a RawDocument whose identity fields derive from celex, overridable per field."""

    def _make(run: IngestRun, celex: str = "32023R1805", **overrides: Any) -> RawDocument:
        defaults: dict[str, Any] = {
            "run": run,
            "source": "eurlex",
            "celex": celex,
            "candidates": [],
            "resolved_celex": celex,
            "topic": "fueleu",
            "sha256": "a" * 64,
            "size_bytes": 758462,
            "fetched_at": utc_now(),
        }
        return RawDocument(**{**defaults, **overrides})

    return _make


@pytest.fixture
def local_store(tmp_path: Path) -> LocalObjectStore:
    """The real local store, rooted in tmp_path, so the suite needs no network."""
    return LocalObjectStore(tmp_path / "raw")


@pytest.fixture
def store_document(
    local_store: LocalObjectStore, make_document: Callable[..., RawDocument]
) -> Callable[..., RawDocument]:
    """Store bytes and return the row that keys them, so the row's sha is the stored one."""

    def _store(
        run: IngestRun,
        content: bytes = b"<html>act</html>",
        celex: str = "32023R1805",
        resolved_celex: str | None = None,
        **overrides: Any,
    ) -> RawDocument:
        resolved = resolved_celex or celex
        sha256, size_bytes = write_document(local_store, celex, resolved, content)
        return make_document(
            run,
            celex=celex,
            resolved_celex=resolved,
            sha256=sha256,
            size_bytes=size_bytes,
            **overrides,
        )

    return _store


def parse_fixture(celex: str, topic: str) -> ParsedDocument:
    """One trimmed fixture act, parsed as ingest parses it."""
    html = (PARSE_FIXTURES / f"{celex}.html").read_text()
    return ParsedDocument(celex=celex, topic=topic, sections=parse_eurlex_html(html))


@pytest.fixture(scope="session")
def fueleu() -> ParsedDocument:
    """The OJ dialect fixture, parsed once: a ParsedDocument is frozen, so tests share one."""
    return parse_fixture("32023R1805", "fueleu")


@pytest.fixture(scope="session")
def mrv() -> ParsedDocument:
    """The consolidated dialect fixture, parsed once and shared like fueleu."""
    return parse_fixture("32015R0757", "mrv")


@pytest.fixture
async def ingest_run(db_session: AsyncSession) -> IngestRun:
    """A flushed run for chunks to hang off, since their ingest_run_id is a real FK."""
    run = IngestRun(status=IngestRunStatus.RUNNING)
    db_session.add(run)
    await db_session.flush()
    return run


@pytest.fixture
async def later_run(db_session: AsyncSession, ingest_run: IngestRun) -> IngestRun:
    """A second run, ordered after ingest_run, for tests about which run a chunk belongs to."""
    run = IngestRun(status=IngestRunStatus.RUNNING)
    db_session.add(run)
    await db_session.flush()
    return run


@pytest.fixture
def make_chunk_row() -> Callable[..., DocumentChunk]:
    """Build a persisted-chunk row with sane defaults, overridable per field."""

    def _make(run: IngestRun, **overrides: Any) -> DocumentChunk:
        defaults: dict[str, Any] = {
            "run": run,
            "celex": "32023R1805",
            "topic": "fueleu",
            "content_hash": "b" * 64,
            "occurrence": 0,
            "kind": SectionKind.PARAGRAPH,
            "article": "4",
            "annex": None,
            "title": "Greenhouse gas intensity limit",
            "paragraph": "1",
            "heading_path": ["Chapter I", "Section 2"],
            "part": 1,
            "parts": 1,
            "position": 0,
            "citation": "Article 4(1)",
            "text": "The greenhouse gas intensity of the energy used on board.",
            "references": [{"raw": "Annex I", "annex": "I"}],
        }
        fields: dict[str, Any] = {**defaults, **overrides}
        fields.setdefault("points", list(list_points(fields["text"])))
        return DocumentChunk(**fields)

    return _make


TOKEN = re.compile(r"\w+")
PROBES = 64
"""Dimensions each token contributes to: a one-hot token would leave most texts exactly
orthogonal, which gives an HNSW graph walk no gradient to descend."""


@cache
def token_probes(token: str) -> tuple[int, ...]:
    """The dimensions a token lands on, spread wide so any two texts overlap somewhere."""
    return tuple(
        zlib.crc32(f"{token}:{probe}".encode()) % EMBED_DIMENSIONS for probe in range(PROBES)
    )


def toy_embed(text: str) -> list[float]:
    """Token hashes into the real width, L2-normalised, so overlapping texts land near."""
    vector = [0.0] * EMBED_DIMENSIONS
    for token in TOKEN.findall(text.lower()):
        for index in token_probes(token):
            vector[index] += 1.0
    norm = sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] if norm else vector


async def vacuum_chunks(db_engine: AsyncEngine) -> None:
    """Reclaim the HNSW entries every rolled-back insert left behind, as autovacuum does live."""
    autocommit = db_engine.execution_options(isolation_level="AUTOCOMMIT")
    async with autocommit.connect() as conn:
        await conn.execute(text("VACUUM document_chunks"))


async def delete_runs(db_engine: AsyncEngine, ingest_run_id: int | None = None) -> None:
    """Committed delete of one run or every run, cascading to the chunks hanging off it."""
    stmt = delete(IngestRun)
    if ingest_run_id is not None:
        stmt = stmt.where(IngestRun.id == ingest_run_id)
    async with async_session_factory(bind=db_engine) as session:
        await session.execute(stmt)
        await session.commit()


SEEDED_CORPUS_VERSION = "2026-01-01-5eeded0"
"""Stamped on the stored corpus, since an answer is only cached under a corpus version."""

ON_TOPIC_COSINE = 0.75
"""The refusal gate's bar over the toy vectors. Every text shares stopwords there, so an
off-topic question scores about 0.6 against the corpus and an on-topic one above 0.8."""


async def store_corpus(
    db_engine: AsyncEngine, fueleu: ParsedDocument, mrv: ParsedDocument
) -> list[DocumentChunk]:
    """Chunk, store and embed both fixture acts, committed so every test reads the same rows."""
    await delete_runs(db_engine)
    await vacuum_chunks(db_engine)
    async with async_session_factory(bind=db_engine) as session:
        run = IngestRun(status=IngestRunStatus.RUNNING, corpus_version=SEEDED_CORPUS_VERSION)
        session.add(run)
        await session.flush()
        for document in (fueleu, mrv):
            await sync_document_chunks(
                session,
                celex=document.celex,
                chunks=chunk_document(document),
                ingest_run_id=run.id,
            )
        stmt = (
            select(DocumentChunk)
            .where(DocumentChunk.ingest_run_id == run.id)
            .order_by(DocumentChunk.id)
        )
        rows = list(await session.scalars(stmt))
        for row in rows:
            row.embedding = toy_embed(row.text)
        stats = await get_corpus_stats(session)
        run.chunk_count, run.avg_chunk_chars = stats.chunk_count, stats.avg_chunk_chars
        await session.commit()
        session.expunge_all()
        return rows


@pytest.fixture(scope="session")
def corpus(
    db_engine: AsyncEngine, fueleu: ParsedDocument, mrv: ParsedDocument
) -> Iterator[list[DocumentChunk]]:
    """Both fixture acts stored once for the whole session, since retrieval only ever reads them."""
    rows = anyio.run(store_corpus, db_engine, fueleu, mrv)
    yield rows
    anyio.run(delete_runs, db_engine, rows[0].ingest_run_id)


async def toy_query_embed(texts: list[str], **kwargs: Any) -> list[list[float]]:
    """Stands in for embed at query time, landing questions in the corpus's toy space."""
    return [toy_embed(text) for text in texts]


@pytest.fixture
def query_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Query vectors share the corpus's space, so a search is a real nearest-neighbour test."""
    monkeypatch.setattr("app.retrieval.search.embed", toy_query_embed)


@pytest.fixture
def identity_rerank(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ordering tests assert on fused order, so the rerank stand-in must preserve it."""

    async def _identity(
        query: str, results: tuple[SearchResult, ...], *, limit: int
    ) -> tuple[SearchResult, ...]:
        return results[:limit]

    monkeypatch.setattr("app.retrieval.search.rerank_results", _identity)


@pytest.fixture
def app() -> FastAPI:
    """A throwaway app wired like production, so tests never mutate the real one."""
    app = FastAPI(lifespan=lifespan)
    configure_app(app)
    return app


@pytest.fixture
def client(app: FastAPI) -> Generator[TestClient, None, None]:
    """Held in its context so the lifespan runs: a test's requests then share one event loop,
    and the Redis pool and engine are drained on it before the next test opens its own."""
    with TestClient(app) as client:
        yield client


def assert_error_shape(response: httpx.Response, status_code: int, error: str) -> dict[str, Any]:
    """Assert the single error schema: {error, message, request_id} + optional detail."""
    assert response.status_code == status_code
    body = response.json()
    assert body["error"] == error
    assert isinstance(body["message"], str) and body["message"]
    assert body["request_id"] == response.headers["X-Request-ID"]
    assert set(body) <= {"error", "message", "request_id", "detail"}
    return body


class RecordingTransport(Transport):
    """Keeps what Sentry would have sent, so a test reads it and nothing leaves."""

    def __init__(self) -> None:
        super().__init__()
        self.events: list[Event] = []
        self.check_ins: list[dict[str, Any]] = []

    def capture_envelope(self, envelope: Envelope) -> None:
        for item in envelope.items:
            if event := item.get_event():
                self.events.append(event)
            elif item.type == "check_in" and (check_in := item.payload.json):
                self.check_ins.append(check_in)


@pytest.fixture
def sentry(monkeypatch: pytest.MonkeyPatch) -> Generator[RecordingTransport, None, None]:
    """Sentry configured as in prod, and again by any code under test that configures it,
    with what it sends kept on the transport instead."""
    transport = RecordingTransport()
    monkeypatch.setattr(config, "ENVIRONMENT", Environment.PROD)
    monkeypatch.setattr(config, "SENTRY_DSN", "https://public@sentry.invalid/1")
    monkeypatch.setattr(sentry_sdk, "init", partial(sentry_sdk.init, transport=transport))
    configure_sentry()
    try:
        yield transport
    finally:
        sentry_sdk.get_global_scope().set_client(None)


async def clear_ledger() -> None:
    """Committed delete of every recorded chat request, their steps cascading with them."""
    async with get_session() as session:
        await session.execute(delete(ChatRequest))


@pytest.fixture
def seeded_client(
    client: TestClient,
    corpus: list[DocumentChunk],
    query_embeddings: None,
    identity_rerank: None,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[TestClient, None, None]:
    """The app over the stored corpus, the real ledger and the real Redis, both emptied
    around the test. Only the model is left to fake."""
    assert client.portal is not None
    monkeypatch.setattr(config, "MIN_COSINE_SIMILARITY", ON_TOPIC_COSINE)
    client.portal.call(redis_client.flushdb)
    client.portal.call(clear_ledger)
    yield client
    client.portal.call(clear_ledger)


@pytest.fixture
def rate_limited_client(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """The limiter on with small limits, counting in the suite's Redis index, emptied first."""
    assert client.portal is not None
    client.portal.call(redis_client.flushdb)
    monkeypatch.setattr(config, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(config, "RATE_LIMIT_PER_CLIENT", 2)
    monkeypatch.setattr(config, "RATE_LIMIT_PER_IP", 3)
    monkeypatch.setattr(config, "RATE_LIMIT_WINDOW_SECONDS", 60)
    return client


def unreachable_redis() -> Redis:
    """A client pointed at a closed port, for the checks that must survive Redis being gone."""
    return Redis.from_url("redis://localhost:9/0", socket_connect_timeout=0.2)


class FakeProvider:
    """Records each batch's texts and answers with numbered vectors, raising on scripted calls."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.errors: dict[int, Exception] = {}

    async def __call__(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
        self.calls.append(list(texts))
        if error := self.errors.get(len(self.calls)):
            raise error
        return [[float(index)] * EMBED_DIMENSIONS for index in range(len(texts))]


@pytest.fixture(autouse=True)
def embeddings(monkeypatch: pytest.MonkeyPatch) -> FakeProvider:
    """No test reaches a provider: every embed call is recorded and answered locally."""
    provider = FakeProvider()
    monkeypatch.setattr("app.ingestion.embed.batch.embed", provider)
    return provider


@pytest.fixture(autouse=True)
def no_card_match(monkeypatch: pytest.MonkeyPatch) -> None:
    """No question sits near a tool's card, so a shut gate stays shut without an embed call."""

    async def _no_match(question: str) -> tuple[str, ...]:
        return ()

    monkeypatch.setattr("app.chat.graph.nodes.retrieve.match_tool_cards", _no_match)


@pytest.fixture
def corpus_client() -> Callable[..., tuple[httpx.AsyncClient, list[str]]]:
    """Transport serving SPARQL payloads per topic and HTML responses per celex.

    A test that registers no cited payload cites nothing, so the hop runs and finds no acts.
    """

    def _make(
        sparql: dict[str, httpx.Response], docs: dict[str, httpx.Response]
    ) -> tuple[httpx.AsyncClient, list[str]]:
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/sparql"):
                query = request.url.params["query"]
                if "VALUES ?target" in query:
                    return sparql.get(CITED_TOPIC, httpx.Response(200, json=payload()))
                for topic, base_celex in config.TOPIC_BASE_ACTS.items():
                    if f"celex/{base_celex}>" in query:
                        return sparql[topic]
                raise AssertionError(f"no base act in query: {query[:80]}")
            celex = request.url.path.rsplit("/", 1)[-1]
            calls.append(celex)
            return docs[celex]

        return httpx.AsyncClient(transport=httpx.MockTransport(handler)), calls

    return _make


def binding(
    celex: str,
    force: str | None = None,
    cons: str | None = None,
    title: str | None = None,
    basis: str | None = None,
) -> dict:
    """One SPARQL result row for a celex, with optional in-force, consolidation, title and
    legal basis article."""
    b: dict = {"c": {"value": celex}}
    if force is not None:
        b["force"] = {"value": force}
    if cons is not None:
        b["cons"] = {"value": cons}
    if title is not None:
        b["title"] = {"value": title}
    if basis is not None:
        b["basis"] = {"value": basis}
    return b


def payload(*bindings: dict) -> dict:
    """A SPARQL JSON response body wrapping the given result rows."""
    return {"results": {"bindings": list(bindings)}}


def act_row(
    celex: str,
    in_force: bool | None = None,
    consolidation: str | None = None,
    title: str | None = None,
    basis_article: str | None = None,
):
    """One row as run_acts_by_topic_query hands it back, past the SPARQL envelope."""
    return ActsQueryRow(
        celex=celex,
        in_force=in_force,
        consolidation=consolidation,
        title=title,
        basis_article=basis_article,
    )


MRV_SPARQL = httpx.Response(
    200, json=payload(binding("32015R0757", force="1"), binding("32023R2449", force="1"))
)


async def chunk_versions(session: AsyncSession, celex: str | None = None) -> set[str | None]:
    """The corpus versions the stored chunks resolve to through the run that stored them."""
    stmt = select(IngestRun.corpus_version).join(
        DocumentChunk, DocumentChunk.ingest_run_id == IngestRun.id
    )
    if celex is not None:
        stmt = stmt.where(DocumentChunk.celex == celex)
    return set(await session.scalars(stmt))


async def chunk_rows(session: AsyncSession, celex: str | None = None) -> list[DocumentChunk]:
    """Persisted chunks in insertion order, for one document or the whole table."""
    stmt = select(DocumentChunk).order_by(DocumentChunk.id)
    if celex is not None:
        stmt = stmt.where(DocumentChunk.celex == celex)
    return list(await session.scalars(stmt))


def chunk(**overrides: Any) -> Chunk:
    """A chunk with sane defaults, overridable per field."""
    defaults: dict[str, Any] = {
        "celex": "32023R1805",
        "topic": "fueleu",
        "kind": SectionKind.PARAGRAPH,
        "text": "The greenhouse gas intensity limit.",
        "article": "4",
        "paragraph": "1",
    }
    return Chunk(**{**defaults, **overrides})


RETRIEVED_CHUNK: dict[str, Any] = {
    "id": 1,
    "celex": "32023R1805",
    "topic": "fueleu",
    "act_title": "Regulation (EU) 2023/1805 on the use of renewable and low-carbon fuels",
    "kind": SectionKind.PARAGRAPH,
    "citation": "Article 4(1)",
    "article": "4",
    "paragraph": "1",
    "title": "Greenhouse gas intensity limit",
    "text": "The greenhouse gas intensity of the energy used on board.",
    "position": 1,
    "part": 1,
    "parts": 1,
}
"""One retrieved chunk's fields with sane defaults, the base of the retrieval factories."""


def retrieved_chunk(**overrides: Any) -> RetrievedChunk:
    """A retrieved chunk with sane defaults, overridable per field."""
    return RetrievedChunk(**{**RETRIEVED_CHUNK, **overrides})


USAGE = UsageMetadata(input_tokens=1500, output_tokens=40, total_tokens=1540)
"""What a faked model reports spending, as langchain carries it."""
REPLY_METADATA = {"model_name": config.CHAT_MODEL, "model_provider": "litellm"}
"""What langchain-litellm sets as a reply's response_metadata: the model it called."""
REPORTED_USAGE = Usage.from_metadata(USAGE, config.CHAT_MODEL)
"""USAGE as a step records it, priced at the chat model."""


def reply_message(usage: UsageMetadata = USAGE, model: str | None = config.CHAT_MODEL) -> AIMessage:
    """A model's reply as litellm hands it back: the usage it reported, stamped with the
    model it called — or with nothing, for a reply that named no model."""
    metadata = {"model_name": model, "model_provider": "litellm"} if model else {}
    return AIMessage(content="", usage_metadata=usage, response_metadata=metadata)


PROVIDER_REQUEST = httpx.Request("POST", "https://api.provider.example")


def provider_error(exc_type, status_code: int | None = None, *, message: str | None = None):
    """An openai exception as litellm surfaces one: on a status when given, else as a
    connection failure, which carries the message only when one is given."""
    if status_code is None:
        return exc_type(request=PROVIDER_REQUEST, **({"message": message} if message else {}))
    return exc_type(
        message=message or "provider said no",
        response=httpx.Response(status_code, request=PROVIDER_REQUEST),
        body=None,
    )


def install_chat_model(monkeypatch: pytest.MonkeyPatch, model: BaseChatModel) -> None:
    """Point every node that calls a model at one fake. Each node imports chat_model by
    name, so the fake is set on each node module rather than on the one it came from; the
    nodes are found rather than listed, so one added later is faked without a change here.
    The fake takes the model and its keywords, since a node turning streaming off passes
    one."""
    for module in model_node_modules():
        monkeypatch.setattr(f"{module.__name__}.chat_model", lambda *_, **__: model)


def model_node_modules() -> list[ModuleType]:
    """The node modules that call a model, read off the package rather than listed."""
    return [
        module
        for info in pkgutil.iter_modules(nodes.__path__)
        if hasattr(module := import_module(f"{nodes.__name__}.{info.name}"), "chat_model")
    ]


def install_search(monkeypatch: pytest.MonkeyPatch, fake_search: Callable[..., Any]) -> None:
    """Point retrieve at a fake search; the node imports it by name, so it is set there."""
    monkeypatch.setattr("app.chat.graph.nodes.retrieve.search", fake_search)


def search_result(**overrides: Any) -> SearchResult:
    """A scored search hit with sane defaults, overridable per field."""
    defaults: dict[str, Any] = {
        **RETRIEVED_CHUNK,
        "rrf_score": 0.9,
        "vector_rank": 1,
        "text_rank": 1,
        "cosine_similarity": 0.8,
    }
    return SearchResult(**{**defaults, **overrides})


def junk_result(**overrides: Any) -> SearchResult:
    """A hit below both retrieval bars, which the gate keeps out of the context."""
    return search_result(**{"cosine_similarity": 0.2, "reranker_relevance": 0.3, **overrides})
