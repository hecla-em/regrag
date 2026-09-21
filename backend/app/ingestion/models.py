"""Ingestion values every stage shares: one run's outcome, and the row it closes out."""

from collections import Counter
from datetime import datetime
from typing import Any

from pydantic import Field

from app.core.config import config
from app.core.models import AppModel, FrozenModel
from app.ingestion.chunk.models import ChunkCounts
from app.ingestion.embed.models import EmbedOutcome
from app.ingestion.enums import CITED_TOPIC, DocChange, IngestRunStatus, Stage


class DocumentOutcome(FrozenModel):
    """What one document's pass through the loop committed, or the stage that stopped it."""

    celex: str
    topic: str
    change: DocChange | None = None
    chunks: ChunkCounts = ChunkCounts()
    failed: Stage | None = None
    error: str = ""


class StageReport(AppModel):
    """One stage as its two readers take it: the entry its row stores, and the line it logs."""

    stage: Stage
    unit: str
    """What this stage's counts count, since a run's documents and its chunks read alike."""
    total: int
    counts: dict[str, int]
    failed: dict[str, str]

    def stored(self) -> dict[str, Any]:
        """The stage as its run row holds it, with provider messages capped to fit.

        Leads with the total under its own unit, so a stored run answers what it counted and
        not only how that split: discovery's buckets alone never say how much it found.
        """
        return {
            self.unit: self.total,
            **self.counts,
            "failed": {
                celex: error[: config.MAX_FAILURE_CHARS] for celex, error in self.failed.items()
            },
        }

    def line(self) -> str:
        """The stage on one line: its total in its own unit, then the buckets it split into."""
        buckets = ", ".join(
            f"{value} {label.replace('_', ' ')}" for label, value in self.counts.items()
        )
        return f"[{self.stage}] {self.total} {self.unit}: {buckets}, {len(self.failed)} failed"


class IngestRunResult(AppModel):
    """Outcome of one ingest run: its discovery diff, its documents, and its embedding pass."""

    run_id: int
    corpus_version: str | None = None
    discovered: int = 0
    dropped: list[str] = Field(default_factory=list)
    documents: list[DocumentOutcome] = Field(default_factory=list)
    pruned: int = 0
    embed: EmbedOutcome = Field(default_factory=EmbedOutcome)

    def _failures(self, documents: list[DocumentOutcome]) -> dict[Stage, dict[str, str]]:
        """Why each stage lost what it lost, over whichever documents the caller counts.

        Embed reports for itself because it sweeps the corpus after the loop, so its losses
        are counted in chunks against a document rather than in documents against a stage.
        """
        failed: dict[Stage, dict[str, str]] = {stage: {} for stage in Stage}
        for doc in documents:
            if doc.failed is not None:
                failed[doc.failed][doc.celex] = doc.error
        failed[Stage.EMBED] |= self.embed.failures
        return failed

    @property
    def failures(self) -> dict[Stage, dict[str, str]]:
        """Everything the run lost, which is what it reports and logs."""
        return self._failures(self.documents)

    @property
    def seed_failures(self) -> dict[Stage, dict[str, str]]:
        """The same, less the hop's own losses, which is what the run is judged on.

        A cited act is followed opportunistically, not asked for, so one the corpus cannot
        store is left unfollowed this run rather than made the whole run's failure.
        """
        return self._failures([doc for doc in self.documents if doc.topic != CITED_TOPIC])

    @property
    def committed(self) -> list[DocumentOutcome]:
        """The documents that got all the way through the loop, which are the ones that count."""
        return [doc for doc in self.documents if doc.failed is None]

    @property
    def chunks(self) -> ChunkCounts:
        """Every document's reconciliation, plus the corpus-wide prune that follows the loop."""
        counts = [doc.chunks for doc in self.committed]
        return ChunkCounts(
            added=sum(count.added for count in counts),
            deleted=sum(count.deleted for count in counts) + self.pruned,
            kept=sum(count.kept for count in counts),
            updated=sum(count.updated for count in counts),
        )

    @property
    def corpus_complete(self) -> bool:
        """Every document the topics asked for reached storage, so a celex it lacks is repealed,
        not lost. A hop document discovery still returned is kept whether or not it stored."""
        failures = self.seed_failures
        return not (failures[Stage.FETCH] or failures[Stage.PARSE])

    @property
    def ok(self) -> bool:
        return not any(self.seed_failures.values())

    @property
    def status(self) -> IngestRunStatus:
        return IngestRunStatus.SUCCESS if self.ok else IngestRunStatus.FAILED

    def _stages(self) -> dict[Stage, StageReport]:
        """Every stage written out: what it counted, in what unit, and what it could not."""
        failures, chunks, embed = self.failures, self.chunks, self.embed
        committed = self.committed
        changes = Counter(doc.change for doc in committed)
        fetched = {change.value: changes[change] for change in DocChange}

        def stage(name: Stage, unit: str, total: int, **counts: int) -> StageReport:
            return StageReport(
                stage=name, unit=unit, total=total, counts=counts, failed=failures[name]
            )

        def accounted(name: Stage) -> int:
            """Documents this stage answered for: the ones that got through, plus the ones it lost.

            One that cleared this stage and died in a later one counts towards neither, because
            the loop rolled its whole pass back — so the buckets always sum to the total.
            """
            return len(committed) + len(failures[name])

        reports = [
            stage(Stage.DISCOVER, "documents", self.discovered, dropped=len(self.dropped)),
            stage(Stage.FETCH, "documents", accounted(Stage.FETCH), **fetched),
            stage(Stage.PARSE, "documents", accounted(Stage.PARSE), parsed=len(committed)),
            stage(Stage.CHUNK, "chunks", chunks.total, **chunks.model_dump()),
            stage(Stage.EMBED, "chunks", embed.total, **embed.model_dump(exclude={"failed"})),
        ]
        return {report.stage: report for report in reports}

    def report(self) -> dict[str, Any]:
        """The run as its row stores it: each stage's counts, plus why each document failed."""
        return {stage.value: report.stored() for stage, report in self._stages().items()}

    def line(self, stage: Stage) -> str:
        """One stage on a line, for the log the pipeline writes as that stage finishes."""
        return self._stages()[stage].line()

    def _details(self) -> list[str]:
        """The per-document lines the stage lines are too short to carry."""
        lines: list[str] = []
        if self.dropped:
            lines.append(f"discover dropped: {', '.join(sorted(self.dropped))}")
        for change in (DocChange.NEW, DocChange.UPDATED):
            if celexes := sorted(doc.celex for doc in self.committed if doc.change is change):
                lines.append(f"fetch {change}: {', '.join(celexes)}")
        for stage, failures in self.failures.items():
            lines += [
                f"{stage} failed: {celex} ({error})" for celex, error in sorted(failures.items())
            ]
        return lines

    def summary(self) -> str:
        """The run as the CLI prints it: a line per stage, then the per-document detail."""
        return "\n".join(
            [
                f"run {self.run_id} ({self.corpus_version or 'not stamped'})",
                *(f"  {report.line()}" for report in self._stages().values()),
                *(f"  {line}" for line in self._details()),
            ]
        )


class IngestRunUpdate(AppModel):
    """Partial update body for an ingest run."""

    status: IngestRunStatus | None = None
    corpus_version: str | None = None
    completed_at: datetime | None = None
    result: dict[str, Any] | None = None
