"""Retrieval values: what a caller asks for, and what comes back."""

from pydantic import Field, model_validator

from app.core.models import FrozenModel
from app.ingestion.chunk.models import Reference, format_citation
from app.ingestion.chunk.schemas import DocumentChunk

SNIPPET = 160
"""How much of a chunk's text a printed line carries before it is cut."""


def _signal(value: float | None) -> str:
    """A signal as a fixed-width figure, or a dash holding its place when it is absent.

    Width 7, so a negative similarity keeps the columns after it in line.
    """
    return f"{value:>7.4f}" if value is not None else f"{'-':>7}"


class SearchFilters(FrozenModel):
    """Which slice of the corpus a search may draw from."""

    celex: str | None = None
    topic: str | None = None


class SearchRequest(FrozenModel):
    """What to search the corpus for, where, and how many answers to bring back."""

    query: str
    filters: SearchFilters = SearchFilters()
    limit: int | None = Field(default=None, ge=1)
    """None leaves the count to SEARCH_DEFAULT_LIMIT, read when the search runs."""


class ReferenceTarget(FrozenModel):
    """Which division of which act to look up, named as a citation names it."""

    celex: str
    article: str | None = None
    paragraph: str | None = None
    point: str | None = None
    annex: str | None = None

    @classmethod
    def from_reference(cls, reference: Reference, *, citing: str) -> "ReferenceTarget":
        """The division a stored reference names, in the citing act unless it names another."""
        return cls(
            celex=reference.instrument or citing,
            article=reference.article,
            paragraph=reference.paragraph,
            point=reference.point,
            annex=reference.annex,
        )

    @property
    def citation(self) -> str:
        """The division as a citation names it: 'Article 6(2)', 'Article 3, point (e)',
        'Annex I'."""
        return format_citation(
            article=self.article, paragraph=self.paragraph, point=self.point, annex=self.annex
        )

    @model_validator(mode="after")
    def _addresses_a_division(self) -> "ReferenceTarget":
        """Following a whole act is a filtered search, not a lookup, so an act alone is refused."""
        if self.article is None and self.annex is None:
            raise ValueError(f"following {self.celex} needs an article or annex, not the act alone")
        return self


class RetrievedChunk(FrozenModel):
    """A chunk as a caller sees it, without the vectors it is found by."""

    id: int
    celex: str
    topic: str
    citation: str
    article: str | None
    annex: str | None = None
    title: str | None
    text: str
    references: tuple[Reference, ...] = ()
    position: int
    part: int
    parts: int


CHUNK_COLUMNS = tuple(getattr(DocumentChunk, name) for name in RetrievedChunk.model_fields)
"""The columns a RetrievedChunk is built from: a chunk without the vectors it is found by."""


class SearchResult(RetrievedChunk):
    """A retrieved chunk and how it ranked: per leg, fused, and as the cross-encoder judged it.

    rrf_score: the two legs' ranks fused by 1/(k + rank), an ordering rather than a measurement.
    vector_rank: its 1-based place in the vector leg; None when only the text leg found it.
    text_rank: its 1-based place in the text leg; None when only the vector leg found it.
    cosine_similarity: how near the query vector this chunk's vector sat, the vector leg's one
        absolute measure; None when only the text leg found it.
    reranker_relevance: the cross-encoder's relevance to the query; None when it did not run
        or degraded.
    """

    rrf_score: float
    vector_rank: int | None
    text_rank: int | None
    cosine_similarity: float | None
    reranker_relevance: float | None = None

    def line(self) -> str:
        """One hit on one line: its three retrieval signals, then what and where it is."""
        return (
            f"rrf {self.rrf_score:.4f}  cos {_signal(self.cosine_similarity)}  "
            f"rel {_signal(self.reranker_relevance)}  {self.citation:<16} {self.celex}  "
            f"{self.text[:SNIPPET]}"
        )
