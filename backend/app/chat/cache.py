"""The answer cache: a first question's answer and sources in Redis, keyed on the release,
the last finished ingest and the question as normalized, so a deploy or an ingest retires
every answer at once — and the chat stream's entry point, which replays a hit in place of
running the graph."""

import hashlib
import logging
import re
import unicodedata
from collections.abc import AsyncGenerator
from uuid import uuid4

from pydantic import ValidationError
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.enums import ChatOutcome
from app.chat.events import ChatEvent
from app.chat.models import CachedAnswer, ChatQuery, ChatState
from app.chat.stream import record_run, replay_answer, run_graph
from app.core.config import config
from app.core.db.session import get_session
from app.ingestion.service import get_latest_finished_run_id

logger = logging.getLogger(__name__)

TRAILING_PUNCTUATION = re.compile(r"[\s?!.]+$")


def normalize_question(question: str) -> str:
    """The question with only its typing undone: width, case, spacing and trailing marks.
    Every word stays, since a dropped one can flip what the law says."""
    folded = unicodedata.normalize("NFKC", question).casefold()
    return TRAILING_PUNCTUATION.sub("", " ".join(folded.split()))


async def answer_key(session: AsyncSession, question: str) -> str | None:
    """The key a question's answer lives under for this release and corpus, or None before
    any ingest has finished."""
    run_id = await get_latest_finished_run_id(session)
    if run_id is None:
        return None
    digest = hashlib.sha256(normalize_question(question).encode()).hexdigest()
    return f"chat:answer:{config.BUILD_ID}:{run_id}:{digest}"


async def lookup_answer(redis: Redis, key: str) -> CachedAnswer | None:
    """The answer kept under the key, or None on a miss, when Redis is unreachable, or when
    the entry no longer reads as a CachedAnswer."""
    try:
        payload = await redis.get(key)
    except RedisError:
        logger.exception("answer cache lookup failed; running the graph")
        return None
    if payload is None:
        return None
    try:
        return CachedAnswer.model_validate_json(payload)
    except ValidationError:
        logger.warning("cached answer unreadable; running the graph", exc_info=True)
        return None


async def store_answer(redis: Redis, key: str, answer: CachedAnswer) -> None:
    """Keep the answer under the key for the configured TTL; a failed write is logged."""
    try:
        await redis.set(key, answer.model_dump_json(), ex=config.CHAT_CACHE_TTL_SECONDS)
    except RedisError:
        logger.exception("answer not cached")


async def cache_stream(query: ChatQuery, redis: Redis) -> AsyncGenerator[ChatEvent, None]:
    """One question's events. A first question already answered in this corpus replays
    from the cache, ahead of the spend cap since it costs nothing; otherwise the graph runs,
    and an answered first question is kept for the next asker. A follow-up is never cached,
    since its answer depends on the turns before it."""
    key = None
    if config.CHAT_CACHE_ENABLED and query.thread_id is None:
        async with get_session(auto_commit=False) as session:
            key = await answer_key(session, query.question)

    if key and (hit := await lookup_answer(redis, key)):
        state = ChatState(
            question=query.question, answer=hit.answer, sources=hit.sources, cached=True
        )
        async for event in record_run(state, replay_answer(state)):
            yield event
        return

    state = ChatState(question=query.question, thread_id=query.thread_id or uuid4())
    async for event in record_run(state, run_graph(query, state)):
        yield event
    if key and state.outcome is ChatOutcome.DONE:
        await store_answer(redis, key, CachedAnswer(answer=state.answer, sources=state.sources))
