"""The answer cache: a first question's answer in Redis, keyed so a deploy, a changed setting
or a moved corpus retires every answer, and the decorator that puts it around a run."""

import asyncio
import functools
import hashlib
import json
import logging
import re
import unicodedata
from collections.abc import AsyncGenerator, Callable

from pydantic import ValidationError
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.enums import ChatOutcome
from app.chat.events import ChatEvent, SourcesEvent, TextEvent
from app.chat.models import CachedAnswer, ChatQuery, ChatState
from app.core.config import ANSWER_CONFIG_SECTIONS, config, get_config_snapshot
from app.core.db.session import get_session
from app.core.redis import redis_client
from app.ingestion.service import get_latest_corpus_version

logger = logging.getLogger(__name__)

TRAILING_PUNCTUATION = re.compile(r"[\s?!.]+$")


def normalize_question(question: str) -> str:
    """The question with only its typing undone: width, case, spacing and trailing marks.
    Every word stays, since a dropped one can flip what the law says."""
    folded = unicodedata.normalize("NFKC", question).casefold()
    return TRAILING_PUNCTUATION.sub("", " ".join(folded.split()))


def hash_answer_settings() -> str:
    """The settings that shape an answer, hashed, so changing one retires every answer. The
    cache's own settings stay out, since they change no answer."""
    snapshot = get_config_snapshot(ANSWER_CONFIG_SECTIONS)
    shaping = {name: value for name, value in snapshot.items() if "_CACHE_" not in name}
    return hashlib.sha256(json.dumps(shaping, sort_keys=True, default=str).encode()).hexdigest()


async def answer_key(session: AsyncSession, question: str) -> str | None:
    """The key a question's answer lives under for this release, settings and corpus, or
    None before any corpus version exists."""
    version = await get_latest_corpus_version(session)
    if version is None:
        return None
    digest = hashlib.sha256(normalize_question(question).encode()).hexdigest()
    return f"chat:answer:{config.BUILD_ID}:{hash_answer_settings()[:12]}:{version}:{digest}"


async def lookup_answer(redis: Redis, key: str) -> CachedAnswer | None:
    """The answer kept under the key, or None on a miss, when Redis is unreachable, or when
    the entry no longer reads as a CachedAnswer."""
    try:
        payload = await redis.get(key)
    except RedisError as exc:
        logger.warning("answer cache lookup failed, running the graph: %s", exc)
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
    except RedisError as exc:
        logger.warning("answer not cached: %s", exc)


pending_stores: set[asyncio.Task[None]] = set()
"""The stores still in flight, held so none is collected before it lands."""


def store_in_background(redis: Redis, key: str, answer: CachedAnswer) -> None:
    """Keep the answer in a task of its own, so the run ends without waiting on Redis and a
    client leaving on done cannot cancel the write."""
    task = asyncio.create_task(store_answer(redis, key, answer))
    pending_stores.add(task)
    task.add_done_callback(pending_stores.discard)


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
    """The run with the answer cache around it: a hit fills the state and sends sources and
    the whole answer, and a miss runs through, kept for the next asker if it answered."""

    @functools.wraps(run)
    async def cached_run(query: ChatQuery, state: ChatState) -> AsyncGenerator[ChatEvent, None]:
        key = await find_answer_key(query)
        if key and (hit := await lookup_answer(redis_client, key)):
            state.answer, state.sources, state.cached = hit.answer, hit.sources, True
            yield SourcesEvent.from_results(state.sources)
            yield TextEvent(data=state.answer)
            return
        async for event in run(query, state):
            yield event
        if key and state.outcome is ChatOutcome.DONE:
            answer = CachedAnswer(answer=state.answer, sources=state.sources)
            store_in_background(redis_client, key, answer)

    return cached_run
