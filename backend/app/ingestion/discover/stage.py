"""Discover stage: a SPARQL query per topic, deduped into one corpus and diffed against the last."""

from collections.abc import Collection, Iterable, Sequence

import httpx

from app.core.config import config
from app.ingestion.discover.models import DiscoveredDocument
from app.ingestion.discover.select import select_documents
from app.ingestion.discover.sparql import run_acts_by_topic_query, run_cited_acts_query
from app.ingestion.enums import CITED_TOPIC
from app.ingestion.exceptions import CorpusShrankError


async def discover_topics(
    client: httpx.AsyncClient, topics: Sequence[str]
) -> list[DiscoveredDocument]:
    """Every topic's corpus, deduped by celex — the first topic to claim an act keeps it."""
    by_celex: dict[str, DiscoveredDocument] = {}
    for topic in topics:
        rows = await run_acts_by_topic_query(client, config.TOPIC_BASE_ACTS[topic])
        for document in select_documents(topic, rows):
            by_celex.setdefault(document.celex, document)
    return list(by_celex.values())


async def discover_cited_acts(
    client: httpx.AsyncClient, celexes: Collection[str]
) -> list[DiscoveredDocument]:
    """The acts the corpus cites, at their consolidated versions like any other document.

    They carry the sentinel topic: an act several topics cite belongs to none of them.
    """
    if not celexes:
        return []
    rows = await run_cited_acts_query(client, sorted(celexes))
    return select_documents(CITED_TOPIC, rows)


def find_dropped_celexes(
    discovered: Sequence[DiscoveredDocument], previous_celexes: Iterable[str]
) -> list[str]:
    """Celexes the previous run held that discovery no longer returns.

    Losing an implausible share is an error: a truncated result set is indistinguishable from a
    mass repeal, so refuse to call it one.
    """
    discovered_celexes = {document.celex for document in discovered}
    previous = set(previous_celexes)
    dropped = sorted(previous - discovered_celexes)
    suspicious = len(dropped) >= config.MIN_SUSPICIOUS_DROPS
    if suspicious and len(dropped) > config.MAX_DROP_RATIO * len(previous):
        raise CorpusShrankError(
            f"discovery lost {len(dropped)} of {len(previous)} documents: {', '.join(dropped)}"
        )
    return dropped
