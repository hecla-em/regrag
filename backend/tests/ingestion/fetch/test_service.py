"""The standing-corpus query the fetch diff and the fingerprint read."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.enums import IngestRunStatus
from app.ingestion.fetch.models import RawDocsQuery
from app.ingestion.fetch.service import get_raw_documents
from app.ingestion.schemas import IngestRun

pytestmark = pytest.mark.anyio


async def test_the_corpus_is_each_topics_latest_successful_run(
    db_session: AsyncSession, make_document
):
    """A later run of the same topic retires what it no longer holds. Another topic's does not."""
    superseded = IngestRun(status=IngestRunStatus.SUCCESS)
    db_session.add(make_document(superseded, "32014R0666", topic="mrv"))
    await db_session.flush()
    latest = IngestRun(status=IngestRunStatus.SUCCESS)
    db_session.add(
        make_document(latest, "32015R0757", topic="mrv", resolved_celex="02015R0757-20250101")
    )
    await db_session.flush()
    other_topic = IngestRun(status=IngestRunStatus.SUCCESS)
    db_session.add(make_document(other_topic, "32023R1805", topic="fueleu"))
    await db_session.flush()

    previous = await get_raw_documents(db_session, RawDocsQuery(include_topics=["mrv"]))

    assert set(previous) == {"32015R0757"}
    assert previous["32015R0757"].resolved_celex == "02015R0757-20250101"


async def test_a_topic_with_no_successful_run_still_holds_what_it_downloaded(
    db_session: AsyncSession, make_document
):
    """A topic yet to complete a run has no id to measure against, so every row it has stands.

    Its rows must not be retired on another topic's success: the next run reuses these bytes.
    """
    first_attempt = IngestRun(status=IngestRunStatus.FAILED)
    other_topic = IngestRun(status=IngestRunStatus.SUCCESS)
    db_session.add_all(
        [
            make_document(first_attempt, "32015R0757", topic="mrv"),
            make_document(other_topic, "32023R1805", topic="fueleu"),
        ]
    )
    await db_session.flush()

    assert set(await get_raw_documents(db_session, RawDocsQuery(include_topics=["mrv"]))) == {
        "32015R0757"
    }
    assert set(await get_raw_documents(db_session, RawDocsQuery())) == {
        "32015R0757",
        "32023R1805",
    }


@pytest.mark.parametrize(
    "status",
    [
        pytest.param(IngestRunStatus.FAILED, id="a failed run holds holes"),
        pytest.param(IngestRunStatus.ABORTED, id="an aborted run holds a prefix"),
    ],
)
async def test_an_incomplete_run_adds_its_rows_without_standing_for_the_corpus(
    db_session: AsyncSession, make_document, status: IngestRunStatus
):
    """What it did download is the newest row for that celex, so the next run may reuse it.
    What it did not reach is still held from the last run that finished."""
    complete = IngestRun(status=IngestRunStatus.SUCCESS)
    incomplete = IngestRun(status=status)
    db_session.add_all(
        [
            make_document(complete, "32015R0757", topic="mrv"),
            make_document(complete, "32023R2449", topic="mrv"),
            make_document(complete, "32014R0666", topic="mrv"),
            make_document(
                incomplete, "32015R0757", topic="mrv", resolved_celex="02015R0757-20250101"
            ),
        ]
    )
    await db_session.flush()

    held = await get_raw_documents(db_session, RawDocsQuery(include_topics=["mrv"]))
    unfiltered = await get_raw_documents(db_session, RawDocsQuery(exclude_topics=["fueleu"]))

    assert set(held) == set(unfiltered) == {"32015R0757", "32023R2449", "32014R0666"}
    assert held["32015R0757"].resolved_celex == "02015R0757-20250101"
