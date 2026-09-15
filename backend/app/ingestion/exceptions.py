"""Ingestion failures: raised in CLI runs, recorded per document on the run report."""

from app.ingestion.enums import Stage


def failure_reason(exc: Exception) -> str:
    """The one format a recorded failure takes: the exception's type, then its message."""
    return f"{type(exc).__name__}: {exc}"


class IngestionError(Exception):
    """Base for failures during a corpus ingest run."""


class DocumentFailed(IngestionError):
    """One document could not get through a stage, so the run rolls it back and moves on."""

    def __init__(self, stage: Stage, celex: str, cause: Exception) -> None:
        super().__init__(f"{celex}: {stage} failed: {failure_reason(cause)}")
        self.stage = stage
        self.celex = celex
        self.cause = cause

    @property
    def reason(self) -> str:
        return failure_reason(self.cause)


class DiscoveryError(IngestionError):
    """Base for failures that make a topic's discovery result unusable."""


class MalformedDiscoveryError(DiscoveryError):
    """The SPARQL response was unreadable, or came back without its base act."""


class CorpusShrankError(DiscoveryError):
    """Discovery lost an implausible share of the previous run, so it is not trusted as a repeal."""


class NoFetchableVersionError(IngestionError):
    """None of a document's candidate celexes served HTML."""


class EmptyDownloadError(IngestionError):
    """A download returned no bytes, which is never a valid source document."""


class ParseError(IngestionError):
    """A document could not be parsed into a section tree."""


class EmptyChunkSetError(IngestionError):
    """A stored document chunked to nothing, which is a bad parse rather than a repeal."""
