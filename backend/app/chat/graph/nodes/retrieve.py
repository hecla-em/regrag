"""retrieve: the corpus's best answers to the question, gated query by query."""

import asyncio
from collections.abc import Sequence
from itertools import zip_longest
from typing import Any

from app.chat.blocks import ContextBlock
from app.chat.graph.node import traced
from app.chat.models import ChatState
from app.chat.toolbox.service import find_tool_mentions, match_tool_cards
from app.core.config import config
from app.core.db.session import get_session
from app.retrieval.expand import expand_sections
from app.retrieval.models import SearchRequest, SearchResult
from app.retrieval.search import search
from app.retrieval.thresholds import meets_thresholds


async def search_query(query: str) -> tuple[SearchResult, ...]:
    """One query's hits from its own session, so the queries a question split into can
    search at once rather than in turn."""
    async with get_session(auto_commit=False) as session:
        return await search(session, SearchRequest(query=query, limit=config.CHAT_SOURCES))


def interleave_by_rank(
    per_query: Sequence[Sequence[SearchResult]],
) -> tuple[SearchResult, ...]:
    """Every query's hits as one list, each query's first before any query's second, so no
    part's best hit is pushed out by another part's depth; a chunk two queries both found
    is kept once, at its earliest place."""
    merged: list[SearchResult] = []
    seen: set[int] = set()
    for rank in zip_longest(*per_query):
        for hit in rank:
            if hit is None or hit.id in seen:
                continue
            seen.add(hit.id)
            merged.append(hit)
    return tuple(merged)


@traced
async def retrieve(state: ChatState) -> dict[str, Any]:
    """The corpus's best answers to each query the question split into — or to the question
    as it will be searched, restated for a follow-up — gated query by query, so an
    out-of-corpus part admits nothing, and widened to their sections. hits keeps every
    query's hits, gated or not, so a refusal and a split can be read against what search
    found. With the loop on, what the question names in a dataset tool's data is looked up
    beside the search; when no query clears the gate, such a name, or a tool's card the
    question sits near, may open it instead."""
    queries = state.queries or (state.retrieval_question,)
    searches = asyncio.gather(*(search_query(query) for query in queries))
    if config.ASSESS_ENABLED:
        per_query, named = await asyncio.gather(
            searches, find_tool_mentions(state.retrieval_question)
        )
    else:
        per_query, named = await searches, {}
    mentions = tuple(mention for found in named.values() for mention in found)
    hits = interleave_by_rank(per_query)
    cleared = [found for found in per_query if meets_thresholds(found)]
    if not cleared:
        matched = tuple(named) or (
            await match_tool_cards(state.retrieval_question) if config.ASSESS_ENABLED else ()
        )
        return {
            "hits": hits,
            "sources": (),
            "retrieved_sources": 0,
            "matched_tools": matched,
            "mentions": mentions,
        }

    sources: tuple[ContextBlock, ...] = interleave_by_rank(cleared)
    if config.EXPAND_SECTIONS:
        async with get_session(auto_commit=False) as session:
            sources = await expand_sections(session, sources, limit=config.CHAT_CONTEXT_CHUNKS)

    return {
        "hits": hits,
        "sources": sources,
        "retrieved_sources": len(sources),
        "mentions": mentions,
    }
