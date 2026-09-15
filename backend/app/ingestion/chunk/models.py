"""Chunk-stage values: the locator a chunk inherits, and the chunk itself."""

import hashlib
import json
from typing import ClassVar

from pydantic import computed_field

from app.core.models import FrozenModel
from app.ingestion.enums import SectionKind


def format_citation(
    *,
    article: str | None = None,
    paragraph: str | None = None,
    point: str | None = None,
    annex: str | None = None,
) -> str:
    """A division as a lawyer would cite it: 'Article 6(2)', 'Article 3, point (e)', 'Annex I';
    empty outside any."""
    tail = f", point ({point})" if point else ""
    if article is not None:
        suffix = f"({paragraph})" if paragraph else ""
        return f"Article {article}{suffix}{tail}"
    if annex is not None:
        return f"Annex {annex}".rstrip() + tail
    return ""


class Reference(FrozenModel):
    """One cross-reference; instrument is None when the target is this document."""

    raw: str
    instrument: str | None = None
    article: str | None = None
    paragraph: str | None = None
    point: str | None = None
    annex: str | None = None


class Locator(FrozenModel):
    """Where a chunk sits: the division it belongs to, under the headings above it."""

    article: str | None = None
    annex: str | None = None
    """The annex's number, "" where its act has only one and labels it without a number;
    None is the different fact that the chunk sits outside any annex."""
    title: str | None = None
    heading_path: tuple[str, ...] = ()


class Chunk(Locator):
    """One retrievable unit of a regulation, with its citation, the points it lists, and its
    cross-references."""

    METADATA: ClassVar[set[str]] = {
        "act_title",
        "citation",
        "points",
        "position",
        "references",
        "topic",
    }
    """Fields outside content_hash: topic and act_title record where the chunk came from,
    position is placement, the rest derive from what is hashed."""

    celex: str
    topic: str
    act_title: str | None = None
    kind: SectionKind
    text: str
    paragraph: str | None = None
    part: int = 1
    parts: int = 1
    position: int = 0
    points: tuple[str, ...] = ()
    references: tuple[Reference, ...] = ()

    @computed_field
    @property
    def citation(self) -> str:
        """The locator as a lawyer would cite it, or its title outside any division."""
        return (
            format_citation(article=self.article, paragraph=self.paragraph, annex=self.annex)
            or self.title
            or ""
        )

    @property
    def content_hash(self) -> str:
        """Hash of every field bar the exclusions, so a new field counts towards identity."""
        return self._digest(self.model_dump(mode="json", exclude=self.METADATA))

    @property
    def metadata_hash(self) -> str:
        """Hash of the metadata fields, so drift detection compares one string per row."""
        return self._digest(self.model_dump(mode="json", include=self.METADATA))

    @staticmethod
    def _digest(payload: dict[str, object]) -> str:
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


class ChunkQuery(FrozenModel):
    """Which chunks to select: by vector presence, keyset-paged for the embed sweep."""

    has_embedding: bool
    after: tuple[str, int] | None = None
    limit: int


class ChunkCounts(FrozenModel):
    """What reconciling chunks changed, for one document or summed across a run."""

    added: int = 0
    deleted: int = 0
    kept: int = 0
    updated: int = 0

    @property
    def total(self) -> int:
        """Every chunk the reconciliation accounted for, whichever bucket it fell in."""
        return self.added + self.deleted + self.kept + self.updated
