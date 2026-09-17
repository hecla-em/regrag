"""Ingestion enumerations."""

from enum import StrEnum


class IngestRunStatus(StrEnum):
    """How a run ended, and so how much of its report can be trusted.

    RUNNING: open, and its rows are already visible to readers.
    SUCCESS: cleared every stage.
    FAILED: ran to the end with documents failing along the way, so the report names every one.
    ABORTED: died partway, so the report covers only what had committed by then.

    No query separates FAILED from ABORTED — they differ only to whoever reads the run table.
    """

    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    ABORTED = "aborted"


class Stage(StrEnum):
    """The stages of an ingest run, in the order the pipeline runs them."""

    DISCOVER = "discover"
    FETCH = "fetch"
    PARSE = "parse"
    CHUNK = "chunk"
    EMBED = "embed"


class DocChange(StrEnum):
    """What a run did with a discovered document, against the version the last run resolved."""

    NEW = "new"
    UPDATED = "updated"
    REUSED = "reused"

    @classmethod
    def between(cls, previous: str | None, current: str) -> "DocChange":
        """How this run's resolved celex compares to the previous run's, if there was one."""
        if previous is None:
            return cls.NEW
        return cls.UPDATED if previous != current else cls.REUSED


class SectionKind(StrEnum):
    """Node types in a parsed document tree."""

    ARTICLE = "article"
    PARAGRAPH = "paragraph"
    ANNEX = "annex"
    HEADING = "heading"
    TABLE = "table"
