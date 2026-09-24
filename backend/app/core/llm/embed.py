"""Voyage embeddings through LiteLLM: one call, wrapped errors."""

import logging
import math
from collections.abc import Sequence
from enum import StrEnum
from operator import itemgetter

import litellm

from app.core.config import EMBED_DIMENSIONS, config
from app.core.llm.errors import LLMError, llm_retry, wrap_provider_errors
from app.core.llm.keys import api_key_for

logger = logging.getLogger(__name__)

EMBED_BATCH_SIZE = 128
"""Voyage's ceiling on texts per embedding request."""


class EmbedInput(StrEnum):
    """Which side of an asymmetric embedding a text is on."""

    DOCUMENT = "document"
    QUERY = "query"


@wrap_provider_errors("embedding call")
async def embed(texts: list[str], *, input_type: EmbedInput) -> list[list[float]]:
    """Embed texts in one provider call, in input order. Retries are the caller's."""
    if not texts:
        return []
    response = await litellm.aembedding(
        model=config.EMBED_MODEL,
        input=texts,
        input_type=input_type.value,
        dimensions=EMBED_DIMENSIONS,
        api_key=api_key_for(config.EMBED_MODEL),
        timeout=config.EMBED_TIMEOUT,
    )
    if len(response.data) != len(texts):
        logger.warning(
            "embedding response misaligned: got %d items for %d inputs",
            len(response.data),
            len(texts),
        )
        raise LLMError("embedding call failed")
    return [item["embedding"] for item in sorted(response.data, key=itemgetter("index"))]


@llm_retry
async def embed_query(query: str) -> list[float]:
    """Embed one query, retrying transient provider failures."""
    (vector,) = await embed([query], input_type=EmbedInput.QUERY)
    return vector


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """How alike two embeddings are in meaning: 1 for the same direction, near 0 for unrelated."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))
