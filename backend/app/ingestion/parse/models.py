"""Format-neutral parser IR: every parser produces a ParsedDocument section tree."""

from app.core.models import FrozenModel
from app.ingestion.enums import SectionKind


class Section(FrozenModel):
    """One node of a document tree; rows is populated only for TABLE."""

    kind: SectionKind
    number: str | None = None
    title: str | None = None
    text: str = ""
    rows: tuple[tuple[str, ...], ...] = ()
    children: tuple["Section", ...] = ()


class ParsedDocument(FrozenModel):
    """A parsed act: identity from the ingest record, body as a section tree."""

    celex: str
    topic: str
    act_title: str | None = None
    sections: tuple[Section, ...]
