"""The ingestion domain's own rows, and the corpus-wide questions asked across every topic."""

import hashlib
import json
from collections.abc import Collection, Iterable, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utc_now, utc_today
from app.core.db.crud import create_record, update_record
from app.ingestion.discover.models import DiscoveredDocument
from app.ingestion.enums import IngestRunStatus
from app.ingestion.fetch.models import RawDocsQuery
from app.ingestion.fetch.schemas import RawDocument
from app.ingestion.fetch.service import get_raw_documents
from app.ingestion.models import IngestRunUpdate
from app.ingestion.schemas import IngestRun


async def create_ingest_run(session: AsyncSession) -> IngestRun:
    """Open a run in the RUNNING state, committed so it outlives the fetch that follows."""
    return await create_record(session, IngestRun(status=IngestRunStatus.RUNNING))


async def get_latest_corpus_version(session: AsyncSession) -> str | None:
    """The corpus version of the most recent run that was stamped with one."""
    stmt = (
        select(IngestRun.corpus_version)
        .where(IngestRun.corpus_version.is_not(None))
        .order_by(IngestRun.id.desc())
        .limit(1)
    )
    return await session.scalar(stmt)


def corpus_fingerprint(documents: Iterable[RawDocument]) -> str:
    """Content hash of the corpus; an identical corpus fingerprints identically."""
    content = sorted((doc.celex, doc.resolved_celex, doc.sha256) for doc in documents)
    return hashlib.sha256(json.dumps(content).encode()).hexdigest()[:7]


async def next_corpus_version(session: AsyncSession) -> str:
    """Date the corpus last changed plus its fingerprint; unchanged corpora keep their version.

    Fingerprints the whole corpus, not just the topics fetched, so a single-topic run
    cannot mint a version that describes only part of it.
    """
    corpus_docs = await get_raw_documents(session, query=RawDocsQuery())
    fingerprint = corpus_fingerprint(list(corpus_docs.values()))
    previous = await get_latest_corpus_version(session)
    if previous is not None and previous.endswith(f"-{fingerprint}"):
        return previous
    return f"{utc_today()}-{fingerprint}"


async def get_celexes_to_keep(
    session: AsyncSession, *, discovered: Sequence[DiscoveredDocument], topics: Sequence[str]
) -> Collection[str]:
    """The celexes some topic still wants: this run's corpus plus the other topics' documents."""
    discovered_celexes = {document.celex for document in discovered}
    other_topic_celexes = await get_raw_documents(
        session, query=RawDocsQuery(exclude_topics=list(topics))
    )
    return discovered_celexes | set(other_topic_celexes.keys())


async def complete_ingest_run(
    session: AsyncSession,
    run: IngestRun,
    *,
    status: IngestRunStatus,
    result: dict[str, Any] | None = None,
) -> IngestRun:
    """Close out a run with the corpus version it left: a failed or aborted run committed
    what it got through, so it is stamped too."""
    version = await next_corpus_version(session)
    update_in = IngestRunUpdate(
        status=status, completed_at=utc_now(), corpus_version=version, result=result
    )
    return await update_record(session, run, update_in)
