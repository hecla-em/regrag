"""The answer cache: a first question's answer and sources in Redis, keyed on the release,
the last finished ingest and the question as normalized, so a deploy or an ingest retires
every answer at once."""

import hashlib
import logging
import re
import unicodedata

from pydantic import ValidationError
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.models import CachedAnswer
from app.core.config import config
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
