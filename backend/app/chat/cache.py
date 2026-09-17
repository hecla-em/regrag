"""The answer cache: a first question's answer and sources in Redis, keyed on the release,
the last finished ingest and the question as normalized, so a deploy or an ingest retires
every answer at once — and the decorator that puts it around a run."""

import functools
import hashlib
import logging
import re
import unicodedata
from collections.abc import AsyncGenerator, Callable

from pydantic import ValidationError
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.enums import ChatOutcome
from app.chat.events import ChatEvent, ChatThread, DoneEvent, SourcesEvent, TextEvent
from app.chat.models import CachedAnswer, ChatQuery, ChatState
from app.core.config import config
from app.core.db.session import get_session
from app.core.redis import redis_client
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


ChatRun = Callable[[ChatQuery, ChatState], AsyncGenerator[ChatEvent, None]]
"""A run of one question: the events it sends, filling the state it is handed."""


async def find_answer_key(query: ChatQuery) -> str | None:
    """The key for a first question, or None when the cache is off or the question
    continues a thread, whose answer depends on the turns before it."""
    if not config.CHAT_CACHE_ENABLED or query.thread_id is not None:
        return None
    async with get_session(auto_commit=False) as session:
        return await answer_key(session, query.question)


def cache_stream(run: ChatRun) -> ChatRun:
    """The run with the answer cache around it. A hit fills the state and sends the sources,
    the whole answer as one text, and done, with no step frames since no step ran; a miss
    runs through, and an answered one is kept for the next asker."""

    @functools.wraps(run)
    async def cached_run(query: ChatQuery, state: ChatState) -> AsyncGenerator[ChatEvent, None]:
        key = await find_answer_key(query)
        if key and (hit := await lookup_answer(redis_client, key)):
            state.answer, state.sources, state.cached = hit.answer, hit.sources, True
            yield SourcesEvent.from_results(state.sources)
            yield TextEvent(data=state.answer)
            yield DoneEvent(data=ChatThread(thread_id=state.thread_id))
            return
        async for event in run(query, state):
            yield event
        if key and state.outcome is ChatOutcome.DONE:
            answer = CachedAnswer(answer=state.answer, sources=state.sources)
            await store_answer(redis_client, key, answer)

    return cached_run
