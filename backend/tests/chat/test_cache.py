"""The answer cache: what a question normalizes to, what moves its key, and what happens
when Redis or a stored entry cannot be read."""

import logging

import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat import cache
from app.chat.cache import answer_key, lookup_answer, normalize_question, store_answer
from app.chat.models import CachedAnswer
from app.core.clock import utc_now
from app.core.config import config
from app.core.db.crud import create_record
from app.ingestion.enums import IngestRunStatus
from app.ingestion.schemas import IngestRun
from tests.conftest import retrieved_chunk, unreachable_redis

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


async def record_run(session: AsyncSession, status: IngestRunStatus) -> IngestRun:
    completed_at = None if status is IngestRunStatus.RUNNING else utc_now()
    return await create_record(session, IngestRun(status=status, completed_at=completed_at))


async def test_the_key_is_one_per_normalized_question(db_session: AsyncSession) -> None:
    run = await record_run(db_session, IngestRunStatus.SUCCESS)

    key = await answer_key(db_session, "What is FuelEU?")

    assert key is not None
    assert key.startswith(f"chat:answer:{config.BUILD_ID}:{run.id}:")
    assert key == await answer_key(db_session, "  what is fueleu ")
    assert key != await answer_key(db_session, "What is MRV?")


@pytest.mark.parametrize(
    "status", [IngestRunStatus.SUCCESS, IngestRunStatus.FAILED, IngestRunStatus.ABORTED]
)
async def test_any_finished_ingest_moves_every_key(
    db_session: AsyncSession, status: IngestRunStatus
) -> None:
    """A run that failed some documents still committed the rest, so it retires answers too."""
    await record_run(db_session, IngestRunStatus.SUCCESS)
    before = await answer_key(db_session, "What is FuelEU?")

    await record_run(db_session, status)

    assert await answer_key(db_session, "What is FuelEU?") != before


async def test_a_run_still_going_keeps_the_key_until_it_finishes(db_session: AsyncSession) -> None:
    """Answers written mid-run then die with the key the finished run replaces."""
    await record_run(db_session, IngestRunStatus.SUCCESS)
    before = await answer_key(db_session, "What is FuelEU?")

    await record_run(db_session, IngestRunStatus.RUNNING)

    assert await answer_key(db_session, "What is FuelEU?") == before


async def test_a_new_build_moves_every_key(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A deploy can change the chunker, prompts or model without any ingest running."""
    await record_run(db_session, IngestRunStatus.SUCCESS)
    before = await answer_key(db_session, "What is FuelEU?")

    monkeypatch.setattr(config, "BUILD_ID", "registry.fly.io/regrag:deployment-2")

    assert await answer_key(db_session, "What is FuelEU?") != before


async def test_there_is_no_key_before_an_ingest_has_finished(db_session: AsyncSession) -> None:
    await record_run(db_session, IngestRunStatus.RUNNING)

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

    with caplog.at_level(logging.ERROR, logger=cache.logger.name):
        assert await lookup_answer(redis, "chat:answer:v:k") is None
        await store_answer(redis, "chat:answer:v:k", answer)

    assert [record.getMessage() for record in caplog.records] == [
        "answer cache lookup failed; running the graph",
        "answer not cached",
    ]
    await redis.aclose()
