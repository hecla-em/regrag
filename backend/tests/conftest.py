"""Shared test fixtures."""

import pkgutil
from collections.abc import AsyncGenerator, Callable, Generator
from contextlib import asynccontextmanager
from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.messages.ai import UsageMetadata
from redis.asyncio import Redis
from sqlalchemy import URL, create_engine, delete, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool
from tenacity import wait_none

from app.chat.graph import nodes
from app.chat.graph.nodes.assess import call_assess_model
from app.chat.graph.nodes.decompose import call_decompose_model
from app.chat.graph.nodes.rewrite import call_rewrite_model
from app.chat.graph.nodes.synthesize import synthesize
from app.core.clock import utc_now
from app.core.config import BACKEND_ROOT, EMBED_DIMENSIONS, R2Config, config
from app.core.db.session import async_session_factory
from app.core.llm.models import Usage
from app.core.redis import redis_client
from app.core.storage import LocalObjectStore
from app.evals.judge.service import call_judge_model
from app.ingestion.chunk.models import Chunk
from app.ingestion.chunk.references import list_points
from app.ingestion.chunk.schemas import DocumentChunk
from app.ingestion.discover.models import ActsQueryRow, DiscoveredDocument
from app.ingestion.discover.sparql import run_acts_by_topic_query
from app.ingestion.embed.batch import embed_batch
from app.ingestion.enums import IngestRunStatus, SectionKind
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
MRV_HTML = (PARSE_FIXTURES / "32015R0757.html").read_text()

R2_ENV = {
    "R2_ACCOUNT_ID": "acc",
    "R2_ACCESS_KEY_ID": "key",
    "R2_SECRET_ACCESS_KEY": "secret",
    "R2_BUCKET": "regrag-raw",
}


def r2_config(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> R2Config:
    """R2 settings as they really arrive — from the environment; an empty one is left unset."""
    for name, value in {**R2_ENV, **overrides}.items():
        monkeypatch.setenv(name, value)
    return R2Config()


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


@pytest.fixture(scope="session")
def fueleu() -> ParsedDocument:
    """The OJ dialect fixture, parsed once: a ParsedDocument is frozen, so tests share one."""
    sections = parse_eurlex_html(FUELEU_HTML)
    return ParsedDocument(celex="32023R1805", topic="fueleu", sections=sections)


@pytest.fixture(scope="session")
def mrv() -> ParsedDocument:
    """The consolidated dialect fixture, parsed once and shared like fueleu."""
    return ParsedDocument(celex="32015R0757", topic="mrv", sections=parse_eurlex_html(MRV_HTML))


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


@pytest.fixture
def corpus_client() -> Callable[..., tuple[httpx.AsyncClient, list[str]]]:
    """Transport serving SPARQL payloads per topic and HTML responses per celex."""

    def _make(
        sparql: dict[str, httpx.Response], docs: dict[str, httpx.Response]
    ) -> tuple[httpx.AsyncClient, list[str]]:
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/sparql"):
                query = request.url.params["query"]
                for topic, base_celex in config.TOPIC_BASE_ACTS.items():
                    if base_celex in query:
                        return sparql[topic]
                raise AssertionError(f"no base act in query: {query[:80]}")
            celex = request.url.path.rsplit("/", 1)[-1]
            calls.append(celex)
            return docs[celex]

        return httpx.AsyncClient(transport=httpx.MockTransport(handler)), calls

    return _make


def binding(
    celex: str, force: str | None = None, cons: str | None = None, title: str | None = None
) -> dict:
    """One SPARQL result row for a celex, with optional in-force, consolidation and title."""
    b: dict = {"c": {"value": celex}}
    if force is not None:
        b["force"] = {"value": force}
    if cons is not None:
        b["cons"] = {"value": cons}
    if title is not None:
        b["title"] = {"value": title}
    return b


def payload(*bindings: dict) -> dict:
    """A SPARQL JSON response body wrapping the given result rows."""
    return {"results": {"bindings": list(bindings)}}


def act_row(
    celex: str,
    in_force: bool | None = None,
    consolidation: str | None = None,
    title: str | None = None,
):
    """One row as run_acts_by_topic_query hands it back, past the SPARQL envelope."""
    return ActsQueryRow(celex=celex, in_force=in_force, consolidation=consolidation, title=title)


MRV_SPARQL = httpx.Response(
    200, json=payload(binding("32015R0757", force="1"), binding("32023R2449", force="1"))
)


def discovered_document(
    celex: str = "32015R0757",
    topic: str = "mrv",
    candidates: tuple[str, ...] = (),
    title: str | None = None,
) -> DiscoveredDocument:
    """What discovery would hand fetch for one act, overridable per field."""
    return DiscoveredDocument(
        topic=topic, source="eurlex", celex=celex, candidates=candidates, title=title
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
