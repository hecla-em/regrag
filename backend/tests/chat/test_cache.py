"""The answer cache: what a question normalizes to, the corpus its key is tied to, and what
happens when Redis is not there."""

import logging

import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat import cache
from app.chat.cache import answer_key, lookup_answer, normalize_question, store_answer
from app.chat.models import CachedAnswer
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


async def record_corpus(session: AsyncSession, version: str) -> None:
    await create_record(session, IngestRun(status=IngestRunStatus.SUCCESS, corpus_version=version))


async def test_the_key_is_one_per_normalized_question(db_session: AsyncSession) -> None:
    await record_corpus(db_session, "2026-09-16-abc1234")

    key = await answer_key(db_session, "What is FuelEU?")

    assert key is not None
    assert key.startswith("chat:answer:2026-09-16-abc1234:")
    assert key == await answer_key(db_session, "  what is fueleu ")
    assert key != await answer_key(db_session, "What is MRV?")


async def test_a_new_corpus_version_moves_every_key(db_session: AsyncSession) -> None:
    """How an ingest invalidates the cache: its run mints a version, and no old key matches."""
    await record_corpus(db_session, "2026-09-16-abc1234")
    before = await answer_key(db_session, "What is FuelEU?")

    await record_corpus(db_session, "2026-09-17-def5678")

    assert await answer_key(db_session, "What is FuelEU?") != before


async def test_there_is_no_key_before_a_corpus_exists(db_session: AsyncSession) -> None:
    assert await answer_key(db_session, "What is FuelEU?") is None


async def test_a_stored_answer_is_read_back_whole(answer_cache: Redis) -> None:
    answer = CachedAnswer(answer="Ships must comply [1].", sources=(retrieved_chunk(),))

    await store_answer(answer_cache, "chat:answer:v:k", answer)

    assert await lookup_answer(answer_cache, "chat:answer:v:k") == answer
    assert await answer_cache.ttl("chat:answer:v:k") == config.CHAT_CACHE_TTL_SECONDS


async def test_an_unknown_key_is_a_miss(answer_cache: Redis) -> None:
    assert await lookup_answer(answer_cache, "chat:answer:v:missing") is None


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
