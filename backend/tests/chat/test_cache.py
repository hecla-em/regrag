"""The answer cache: what a question normalizes to, what moves its key, what happens when
Redis or a stored entry cannot be read, and the stream a hit replays in place of a run."""

import logging
from uuid import UUID

import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat import cache
from app.chat.cache import (
    answer_key,
    hash_answer_settings,
    lookup_answer,
    normalize_question,
    store_answer,
)
from app.chat.enums import ChatOutcome
from app.chat.events import DoneEvent, ErrorEvent, SourcesEvent, TextEvent
from app.chat.models import CachedAnswer, ChatQuery, ChatTurn
from app.core.clock import utc_now
from app.core.config import config
from app.core.db.crud import create_record
from app.core.llm.errors import LLMError
from app.ingestion.enums import IngestRunStatus
from app.ingestion.schemas import IngestRun
from tests.chat.conftest import (
    FUELEU_KEY,
    collect_events,
    fake_chat_model,
    install_versioned_key,
    restated_message,
)
from tests.conftest import install_chat_model, install_search, retrieved_chunk, unreachable_redis

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    "asked",
    ["What is FuelEU?", "  what   is\nfueleu ", "WHAT IS FUELEU?!.", "Ｗhat is FuelEU"],
)
def test_retyped_variants_normalize_to_one_form(asked: str) -> None:
    assert normalize_question(asked) == "what is fueleu"


def test_normalization_keeps_every_word() -> None:
    """A dropped word can flip a regulatory answer, so every word stays in the key."""
    assert normalize_question("What does Article 5 not require?") != normalize_question(
        "What does Article 5 require?"
    )


def test_normalization_keeps_punctuation_inside_the_question() -> None:
    assert normalize_question("Article 5(1)?") != normalize_question("Article 51?")


async def add_ingest_run(
    session: AsyncSession, status: IngestRunStatus, corpus_version: str | None = None
) -> IngestRun:
    completed_at = None if status is IngestRunStatus.RUNNING else utc_now()
    run = IngestRun(status=status, completed_at=completed_at, corpus_version=corpus_version)
    return await create_record(session, run)


async def test_the_key_is_one_per_normalized_question(db_session: AsyncSession) -> None:
    await add_ingest_run(db_session, IngestRunStatus.SUCCESS, "2026-09-17-abc")

    key = await answer_key(db_session, "What is FuelEU?")

    settings = hash_answer_settings()[:12]
    assert key is not None
    assert key.startswith(f"chat:answer:{config.BUILD_ID}:{settings}:2026-09-17-abc:0:")
    assert key == await answer_key(db_session, "  what is fueleu ")
    assert key != await answer_key(db_session, "What is MRV?")


async def test_a_run_over_an_unchanged_corpus_keeps_the_key(db_session: AsyncSession) -> None:
    """The nightly ingest finishes a run every day, and most days nothing moved."""
    await add_ingest_run(db_session, IngestRunStatus.SUCCESS, "2026-09-17-abc")
    before = await answer_key(db_session, "What is FuelEU?")

    await add_ingest_run(db_session, IngestRunStatus.SUCCESS, "2026-09-17-abc")

    assert await answer_key(db_session, "What is FuelEU?") == before


async def test_a_new_corpus_version_moves_every_key(db_session: AsyncSession) -> None:
    await add_ingest_run(db_session, IngestRunStatus.SUCCESS, "2026-09-17-abc")
    before = await answer_key(db_session, "What is FuelEU?")

    await add_ingest_run(db_session, IngestRunStatus.SUCCESS, "2026-09-18-def")

    assert await answer_key(db_session, "What is FuelEU?") != before


@pytest.mark.parametrize("status", [IngestRunStatus.FAILED, IngestRunStatus.ABORTED])
async def test_an_unsuccessful_ingest_moves_every_key(
    db_session: AsyncSession, status: IngestRunStatus
) -> None:
    """A run that failed some documents still committed the rest, with no version to show it."""
    await add_ingest_run(db_session, IngestRunStatus.SUCCESS, "2026-09-17-abc")
    before = await answer_key(db_session, "What is FuelEU?")

    await add_ingest_run(db_session, status)

    assert await answer_key(db_session, "What is FuelEU?") != before


async def test_a_run_still_going_keeps_the_key_until_it_finishes(db_session: AsyncSession) -> None:
    await add_ingest_run(db_session, IngestRunStatus.SUCCESS, "2026-09-17-abc")
    before = await answer_key(db_session, "What is FuelEU?")

    await add_ingest_run(db_session, IngestRunStatus.RUNNING)

    assert await answer_key(db_session, "What is FuelEU?") == before


async def test_a_new_build_moves_every_key(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A deploy can change the chunker, prompts or model without any ingest running."""
    await add_ingest_run(db_session, IngestRunStatus.SUCCESS, "2026-09-17-abc")
    before = await answer_key(db_session, "What is FuelEU?")

    monkeypatch.setattr(config, "BUILD_ID", "registry.fly.io/regrag:deployment-2")

    assert await answer_key(db_session, "What is FuelEU?") != before


def test_a_setting_that_shapes_answers_moves_the_settings_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A secrets-only release restarts the same image, so the build alone would not show it."""
    before = hash_answer_settings()

    monkeypatch.setattr(config, "CHAT_MODEL", "anthropic/claude-sonnet-5")

    assert hash_answer_settings() != before


def test_the_cache_settings_stay_out_of_the_settings_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = hash_answer_settings()

    monkeypatch.setattr(config, "CHAT_CACHE_TTL_SECONDS", 60)

    assert hash_answer_settings() == before


@pytest.mark.parametrize("status", [IngestRunStatus.RUNNING, IngestRunStatus.FAILED])
async def test_there_is_no_key_before_a_corpus_version(
    db_session: AsyncSession, status: IngestRunStatus
) -> None:
    await add_ingest_run(db_session, status)

    assert await answer_key(db_session, "What is FuelEU?") is None


async def test_a_stored_answer_is_read_back_whole(answer_cache: Redis) -> None:
    answer = CachedAnswer(answer="Ships must comply [1].", sources=(retrieved_chunk(),))

    await store_answer(answer_cache, "chat:answer:v:k", answer)

    assert await lookup_answer(answer_cache, "chat:answer:v:k") == answer
    assert await answer_cache.ttl("chat:answer:v:k") == config.CHAT_CACHE_TTL_SECONDS


async def test_an_unknown_key_is_a_miss(answer_cache: Redis) -> None:
    assert await lookup_answer(answer_cache, "chat:answer:v:missing") is None


async def test_an_unreadable_answer_is_a_logged_miss(
    answer_cache: Redis, caplog: pytest.LogCaptureFixture
) -> None:
    """An entry written in an older shape must not fail the question it would have answered."""
    await answer_cache.set("chat:answer:v:k", '{"answer": "a", "sources": [{"id": 1}]}')

    with caplog.at_level(logging.WARNING, logger=cache.logger.name):
        assert await lookup_answer(answer_cache, "chat:answer:v:k") is None

    assert [record.getMessage() for record in caplog.records] == [
        "cached answer unreadable; running the graph"
    ]


async def test_redis_away_is_a_logged_miss_and_a_logged_skip(
    caplog: pytest.LogCaptureFixture,
) -> None:
    redis = unreachable_redis()
    answer = CachedAnswer(answer="a", sources=())

    with caplog.at_level(logging.WARNING, logger=cache.logger.name):
        assert await lookup_answer(redis, "chat:answer:v:k") is None
        await store_answer(redis, "chat:answer:v:k", answer)

    lookup, store = caplog.records
    assert (lookup.levelno, store.levelno) == (logging.WARNING, logging.WARNING)
    assert lookup.getMessage().startswith("answer cache lookup failed, running the graph: ")
    assert store.getMessage().startswith("answer not cached: ")
    await redis.aclose()


@pytest.fixture
def cache_on(monkeypatch, answer_cache):
    """The answer cache on, over an emptied Redis standing in for the shared client."""
    install_versioned_key(monkeypatch)
    monkeypatch.setattr("app.chat.cache.redis_client", answer_cache)
    return answer_cache


FUELEU = ChatQuery(question="What is FuelEU?")
CACHED_ANSWER = CachedAnswer(answer="From the cache [1].", sources=(retrieved_chunk(),))
THREAD_ID = UUID("11111111-2222-3333-4444-555555555555")


class TestCacheStream:
    """The decorator on the graph run: a repeated first question is answered from Redis, and
    recorded by the same stream as any other."""

    async def test_a_repeated_question_replays_the_answer_without_a_model_call(
        self, cache_on, two_results, answer_model, recorded_requests
    ):
        first = await collect_events(FUELEU)
        second = await collect_events(ChatQuery(question="  what is FUELEU "))

        assert len(answer_model.received) == 1
        assert [event.event for event in second] == ["sources", "text", "done"]
        assert second[0] == next(e for e in first if isinstance(e, SourcesEvent))
        assert second[1] == TextEvent(data="Answered [1].")
        answered, cached = recorded_requests
        assert (answered.outcome, cached.outcome) == (ChatOutcome.DONE, ChatOutcome.CACHED)
        assert cached.question == "  what is FUELEU "
        assert (cached.steps, cached.usage(), len(cached.sources)) == ((), None, 2)
        assert cached.total_ms is not None
        assert second[-1] == DoneEvent(data={"thread_id": cached.thread_id})
        assert cached.thread_id != answered.thread_id

    async def test_a_hit_is_served_past_the_spend_cap(self, cache_on, answer_model, monkeypatch):
        """An answer that costs nothing to serve is not what the cap guards."""
        await store_answer(cache_on, FUELEU_KEY, CACHED_ANSWER)

        async def spent_the_cap(session, since):
            return config.CHAT_DAILY_SPEND_CAP_USD

        monkeypatch.setattr("app.chat.stream.spent_since", spent_the_cap)

        events = await collect_events(FUELEU)

        assert [event.event for event in events] == ["sources", "text", "done"]

    async def test_a_follow_up_neither_reads_nor_writes_the_cache(
        self, cache_on, two_results, recorded_requests, monkeypatch, rewrite_turns
    ):
        """A follow-up's answer depends on the thread before it, which the key does not hold."""
        await store_answer(cache_on, FUELEU_KEY, CACHED_ANSWER)
        rewrite_turns(restated_message("What is FuelEU, after the earlier question?"))

        async def one_turn(session, thread_id):
            return (ChatTurn(question="Earlier?", answer="Before."),)

        monkeypatch.setattr("app.chat.stream.load_thread_history", one_turn)
        install_chat_model(monkeypatch, fake_chat_model("Fresh [1]."))

        follow_up = ChatQuery(question=FUELEU.question, thread_id=THREAD_ID)
        events = await collect_events(follow_up)

        assert "".join(e.data for e in events if isinstance(e, TextEvent)) == "Fresh [1]."
        assert await cache_on.dbsize() == 1
        [state] = recorded_requests
        assert (state.outcome, state.thread_id) == (ChatOutcome.DONE, THREAD_ID)

    async def test_a_refusal_is_not_kept(self, cache_on, one_junk_result, answer_model):
        await collect_events(FUELEU)

        assert await cache_on.dbsize() == 0

    async def test_a_failed_run_is_not_kept(self, cache_on, monkeypatch):
        async def failing_search(session, request):
            raise LLMError("embedding call failed")

        install_search(monkeypatch, failing_search)

        events = await collect_events(FUELEU)

        assert isinstance(events[-1], ErrorEvent)
        assert await cache_on.dbsize() == 0

    async def test_before_any_corpus_the_graph_runs_and_nothing_is_kept(
        self, cache_on, two_results, answer_model, monkeypatch
    ):
        async def no_corpus(session, question):
            return None

        monkeypatch.setattr("app.chat.cache.answer_key", no_corpus)

        await collect_events(FUELEU)
        await collect_events(FUELEU)

        assert len(answer_model.received) == 2
        assert await cache_on.dbsize() == 0

    async def test_with_the_cache_off_the_graph_runs_and_nothing_is_kept(
        self, cache_on, two_results, answer_model, monkeypatch
    ):
        monkeypatch.setattr(config, "CHAT_CACHE_ENABLED", False)

        await collect_events(FUELEU)
        await collect_events(FUELEU)

        assert len(answer_model.received) == 2
        assert await cache_on.dbsize() == 0

    async def test_redis_away_runs_the_graph(
        self, cache_on, two_results, answer_model, monkeypatch
    ):
        redis = unreachable_redis()
        monkeypatch.setattr("app.chat.cache.redis_client", redis)

        events = await collect_events(FUELEU)

        assert isinstance(events[-1], DoneEvent)
        assert len(answer_model.received) == 1
        await redis.aclose()
