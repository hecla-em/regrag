"""`evals check`: how a drifted reference and a moved corpus are classified."""

from collections.abc import Callable

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.evals.dataset.check import find_drift
from app.evals.dataset.enums import DriftKind
from app.evals.dataset.models import CaseReference, DriftedReference
from app.ingestion.chunk.schemas import DocumentChunk
from app.ingestion.schemas import IngestRun
from tests.evals.conftest import eval_case, eval_dataset, out_of_corpus_case

pytestmark = pytest.mark.anyio

ARTICLE_4 = ("b" * 12,)
"""The first 12 characters of the make_chunk_row default content hash."""

STAMPED = CaseReference(celex="32023R1805", article="4", content_hashes=ARTICLE_4)
MOVED = CaseReference(celex="32023R1805", article="4", content_hashes=("0" * 12,))
UNSTAMPED = CaseReference(celex="32023R1805", article="4")
MISSING = CaseReference(celex="32023R1805", article="999")
STAMPED_BUT_GONE = CaseReference(celex="32023R1805", article="999", content_hashes=ARTICLE_4)


@pytest.fixture
async def article_4(
    db_session: AsyncSession, ingest_run: IngestRun, make_chunk_row: Callable[..., DocumentChunk]
) -> DocumentChunk:
    """One stored chunk covering the division every factory case cites."""
    chunk = make_chunk_row(ingest_run)
    db_session.add(chunk)
    await db_session.flush()
    return chunk


async def test_each_reference_is_classified_by_how_the_corpus_moved_under_it(
    db_session: AsyncSession, article_4: DocumentChunk
) -> None:
    """Hard drift is the louder fact and the one that fails the command, so a stamped
    reference that stopped resolving reads as unresolved, not stale."""
    dataset = eval_dataset(
        eval_case(id="current", references=(STAMPED,)),
        eval_case(id="amended", references=(MOVED,)),
        eval_case(id="new", references=(UNSTAMPED,)),
        eval_case(id="gone", references=(MISSING,)),
        eval_case(id="stamped-but-gone", references=(STAMPED_BUT_GONE,)),
        out_of_corpus_case(),
    )

    drifted = await find_drift(db_session, dataset)

    assert drifted == (
        DriftedReference(case_id="amended", target=MOVED, kind=DriftKind.STALE),
        DriftedReference(case_id="new", target=UNSTAMPED, kind=DriftKind.UNSTAMPED),
        DriftedReference(case_id="gone", target=MISSING, kind=DriftKind.UNRESOLVED),
        DriftedReference(
            case_id="stamped-but-gone", target=STAMPED_BUT_GONE, kind=DriftKind.UNRESOLVED
        ),
    )
