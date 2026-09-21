"""`evals stamp`: what it records, what it leaves alone, and how it writes the file."""

from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import config
from app.evals.dataset.check import find_drift
from app.evals.dataset.enums import EvalKind, EvalTrait
from app.evals.dataset.exceptions import UnresolvedReferenceError
from app.evals.dataset.models import CaseReference, CorpusStamp, EvalDataset
from app.evals.dataset.stamp import save_dataset, stamp_dataset
from app.ingestion.chunk.schemas import DocumentChunk
from app.ingestion.enums import IngestRunStatus
from app.ingestion.schemas import IngestRun
from tests.evals.conftest import eval_case, eval_dataset, out_of_corpus_case

pytestmark = pytest.mark.anyio

ARTICLE_4 = ("b" * 12,)
"""The first 12 characters of the make_chunk_row default content hash."""

MOVED = CaseReference(celex="32023R1805", article="4", content_hashes=("0" * 12,))
NOW = "2026-09-02-4e81a90"
"""The corpus version the stored chunk's ingest run stands at."""


@pytest.fixture
async def article_4(
    db_session: AsyncSession, make_chunk_row: Callable[..., DocumentChunk]
) -> DocumentChunk:
    """One stored chunk covering the division every factory case cites, under a run the
    corpus version can be read off."""
    run = IngestRun(status=IngestRunStatus.SUCCESS, corpus_version=NOW)
    db_session.add(run)
    await db_session.flush()
    chunk = make_chunk_row(run)
    db_session.add(chunk)
    await db_session.flush()
    return chunk


async def test_stamping_records_what_each_cited_division_hashes_to_now_which_clears_its_drift(
    db_session: AsyncSession, article_4: DocumentChunk
) -> None:
    dataset = eval_dataset(eval_case(references=(MOVED,)))

    stamped = await stamp_dataset(db_session, dataset)

    assert stamped.cases[0].references[0].content_hashes == ARTICLE_4
    assert stamped.corpus is not None
    assert stamped.corpus.corpus_version == NOW
    assert await find_drift(db_session, stamped) == ()


async def test_a_filtered_stamp_leaves_the_cases_it_did_not_select_alone(
    db_session: AsyncSession, article_4: DocumentChunk
) -> None:
    """Repairing one case must not silently clear the staleness of every other one."""
    dataset = eval_dataset(
        eval_case(id="fueleu-repaired", references=(MOVED,)),
        eval_case(id="mrv-untouched", references=(MOVED,)),
        id_contains="fueleu",
    )

    stamped = await stamp_dataset(db_session, dataset)

    assert stamped.cases[0].references[0].content_hashes == ARTICLE_4
    assert stamped.cases[1].references[0].content_hashes == ("0" * 12,)


WAS = CorpusStamp(corpus_version="2026-08-15-2cc038d", stamped_at="2026-08-28")


@pytest.mark.parametrize(
    ("filters", "corpus_version"),
    [
        pytest.param({"id_contains": "kept"}, WAS.corpus_version, id="a cited case skipped by id"),
        pytest.param(
            {"trait": EvalTrait.MULTI_HOP}, WAS.corpus_version, id="a cited case skipped by trait"
        ),
        pytest.param({"kind": EvalKind.IN_CORPUS}, NOW, id="only uncited cases skipped"),
    ],
)
async def test_the_corpus_stamp_is_rewritten_only_when_no_cited_case_was_skipped(
    db_session: AsyncSession, article_4: DocumentChunk, filters: dict, corpus_version: str
) -> None:
    """The stamp covers every reference, so a selection that skipped one cannot claim it."""
    kept = eval_case(id="kept-case", traits=(EvalTrait.MULTI_HOP,))
    skipped = eval_case(id="skipped-case", references=(MOVED,))
    dataset = eval_dataset(kept, skipped, out_of_corpus_case(), **filters).model_copy(
        update={"corpus": WAS}
    )

    stamped = await stamp_dataset(db_session, dataset)

    assert stamped.corpus is not None
    assert stamped.corpus.corpus_version == corpus_version


async def test_a_reference_the_corpus_cannot_resolve_refuses_the_whole_stamp(
    db_session: AsyncSession, article_4: DocumentChunk
) -> None:
    """Stamping it empty would erase the recorded hashes, leaving the drift undetectable."""
    absent = CaseReference(celex="32023R9999", article="1", content_hashes=("0" * 12,))
    dataset = eval_dataset(eval_case(id="fine"), eval_case(id="broken", references=(absent,)))

    with pytest.raises(UnresolvedReferenceError, match="broken  32023R9999 Article 1"):
        await stamp_dataset(db_session, dataset)


# Writing the file back out


def test_the_committed_dataset_is_what_the_writer_produces(tmp_path: Path) -> None:
    """Otherwise the next stamp reformats the whole file and buries what actually moved."""
    file = tmp_path / "golden.json"
    save_dataset(EvalDataset.load(), file)
    assert file.read_text() == config.EVAL_DATASET_PATH.read_text()
