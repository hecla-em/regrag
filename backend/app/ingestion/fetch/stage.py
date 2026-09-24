"""Fetch stage: version-diff against the previous run, download only what changed."""

from collections.abc import Sequence

import httpx
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utc_now
from app.core.storage import ObjectNotFoundError, ObjectStore, StorageError
from app.ingestion.discover.models import DiscoveredDocument
from app.ingestion.enums import DocChange, Stage
from app.ingestion.exceptions import DocumentFailed, IngestionError
from app.ingestion.fetch.download import download_fetchable_version, download_version_formex
from app.ingestion.fetch.models import FetchedDocument, RawDocsQuery
from app.ingestion.fetch.schemas import RawDocument
from app.ingestion.fetch.service import get_raw_documents
from app.ingestion.fetch.storage import (
    StoredBytesMismatchError,
    needs_formex,
    read_document,
    read_formex,
    write_document,
    write_formex,
)
from app.ingestion.schemas import IngestRun


async def previous_corpus(session: AsyncSession, topics: Sequence[str]) -> dict[str, RawDocument]:
    """The standing rows for these topics, keyed by celex: the corpus the last run left behind."""
    return await get_raw_documents(session, query=RawDocsQuery(include_topics=list(topics)))


def _reuse_previous_version(
    store: ObjectStore,
    discovered: DiscoveredDocument,
    previous: RawDocument | None,
    run: IngestRun,
) -> tuple[RawDocument, bytes, bytes | None] | None:
    """This run's row over the version the previous run stored, if the download would land there.

    Discovery offering the same candidates is what settles that: the version CELLAR served
    for them is the one it will serve again, whether that was a candidate or the original act.
    A version whose XHTML needs Formex it has none stored for is downloaded again, which is
    how rows from before Formex gain it.
    """
    if previous is None or tuple(previous.candidates) != discovered.candidates:
        return None
    try:
        html = read_document(store, previous)
        if needs_formex(html) != (previous.formex_sha256 is not None):
            return None
        formex = read_formex(store, previous) if previous.formex_sha256 else None
    except (ObjectNotFoundError, StoredBytesMismatchError):
        return None
    raw = RawDocument(
        **discovered.model_dump(),
        run=run,
        resolved_celex=previous.resolved_celex,
        sha256=previous.sha256,
        size_bytes=previous.size_bytes,
        formex_sha256=previous.formex_sha256,
        fetched_at=previous.fetched_at,
    )
    return raw, html, formex


async def _download_new_version(
    client: httpx.AsyncClient,
    store: ObjectStore,
    discovered: DiscoveredDocument,
    run: IngestRun,
) -> tuple[RawDocument, bytes, bytes | None]:
    """Download the version CELLAR will serve, store its bytes, and stamp the fetch time."""
    resolved_celex, html = await download_fetchable_version(client, discovered)
    sha256, size_bytes = write_document(store, discovered.celex, resolved_celex, html)
    formex = await download_version_formex(client, resolved_celex) if needs_formex(html) else None
    formex_sha256 = (
        write_formex(store, discovered.celex, resolved_celex, formex) if formex else None
    )
    raw = RawDocument(
        **discovered.model_dump(),
        run=run,
        resolved_celex=resolved_celex,
        sha256=sha256,
        size_bytes=size_bytes,
        formex_sha256=formex_sha256,
        fetched_at=utc_now(),
    )
    return raw, html, formex


async def fetch_document(
    session: AsyncSession,
    *,
    client: httpx.AsyncClient,
    discovered: DiscoveredDocument,
    previous: RawDocument | None,
    run: IngestRun,
    store: ObjectStore,
) -> FetchedDocument:
    """Record one document's row, hand back its bytes and how it moved, or say why it failed."""
    try:
        reused = _reuse_previous_version(store, discovered, previous, run)
        raw, html, formex = reused or await _download_new_version(client, store, discovered, run)
        session.add(raw)
        await session.flush()
    except (IngestionError, StorageError, httpx.HTTPError, SQLAlchemyError) as exc:
        raise DocumentFailed(Stage.FETCH, discovered.celex, exc) from exc
    change = DocChange.between(previous.resolved_celex if previous else None, raw.resolved_celex)
    return FetchedDocument(raw, html, formex, change)
