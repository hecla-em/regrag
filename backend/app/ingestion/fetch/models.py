"""Fetch-stage values: how to filter the standing corpus, and what one fetch settled on."""

from typing import NamedTuple

from app.core.models import FrozenModel
from app.ingestion.enums import DocChange
from app.ingestion.fetch.schemas import RawDocument


class RawDocsQuery(FrozenModel):
    """Filters for the standing corpus; None leaves a filter off, [] genuinely matches nothing."""

    include_topics: list[str] | None = None
    exclude_topics: list[str] | None = None


class FetchedDocument(NamedTuple):
    """One document as fetch left it: the row it recorded, its bytes, and how it moved.

    change compares the version this run resolved against the one the previous run did, so a
    document whose bytes were reused and one re-downloaded to the same version read alike.
    formex is the version's Formex zip, None where it needs none or CELLAR had none.
    """

    raw: RawDocument
    html: bytes
    formex: bytes | None
    change: DocChange
