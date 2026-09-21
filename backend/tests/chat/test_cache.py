"""The answer cache: what a question normalizes to, what moves its key, which runs are kept,
and what a run does when the cache cannot or may not serve it."""

from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.cache import (
    answer_key,
    hash_answer_settings,
    normalize_question,
    store_answer,
)
from app.chat.enums import ChatOutcome
from app.chat.events import DoneEvent, TextEvent
from app.chat.models import CachedAnswer, ChatQuery, ChatTurn
from app.core.clock import utc_now
from app.core.config import config
from app.core.db.crud import create_record
from app.core.llm.errors import LLMError
from app.ingestion.enums import IngestRunStatus
from app.ingestion.schemas import IngestRun
from tests.chat.conftest import (
    FUELEU_KEY,
    collect_events,
    fake_chat_model,
    install_versioned_key,
    restated_message,
    search_giving,
)
from tests.conftest import (
    install_chat_model,
    junk_result,
    retrieved_chunk,
    unreachable_redis,
)

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("recorded_requests")]


@pytest.mark.parametrize(
    ("asked", "retyped", "same"),
    [
        pytest.param(
            "What is FuelEU?", "  what   is\nfueleu ", True, id="spacing and case are typing"
        ),
        pytest.param("What is FuelEU?", "WHAT IS FUELEU?!.", True, id="so are trailing marks"),
        pytest.param("What is FuelEU?", "Ｗhat is FuelEU", True, id="and character width"),
        pytest.param(
            "What does Article 5 not require?",
            "What does Article 5 require?",
            False,
            id="every word stays, since a dropped one can flip the answer",
        ),
        pytest.param("Article 5(1)?", "Article 51?", False, id="so does punctuation inside"),
    ],
)
def test_a_question_normalizes_to_what_was_asked_with_only_its_typing_undone(
    asked: str, retyped: str, same: bool
) -> None:
    assert (normalize_question(asked) == normalize_question(retyped)) is same


async def add_ingest_run(
    session: AsyncSession, status: IngestRunStatus, corpus_version: str | None = None
) -> IngestRun:
    completed_at = None if status is IngestRunStatus.RUNNING else utc_now()
    run = IngestRun(status=status, completed_at=completed_at, corpus_version=corpus_version)
    return await create_record(session, run)


async def test_a_question_has_one_key_per_normalized_form_once_a_corpus_version_exists(
    db_session: AsyncSession,
) -> None:
    await add_ingest_run(db_session, IngestRunStatus.RUNNING)
    assert await answer_key(db_session, "What is FuelEU?") is None

    await add_ingest_run(db_session, IngestRunStatus.SUCCESS, "2026-09-17-abc")
    key = await answer_key(db_session, "What is FuelEU?")

    settings = hash_answer_settings()[:12]
    assert key is not None
    assert key.startswith(f"chat:answer:{config.BUILD_ID}:{settings}:2026-09-17-abc:")
    assert key == await answer_key(db_session, "  what is fueleu ")
    assert key != await answer_key(db_session, "What is MRV?")


@pytest.mark.parametrize(
    ("run", "settings", "moves"),
    [
        pytest.param(
            (IngestRunStatus.SUCCESS, "2026-09-17-abc"),
            {},
            False,
            id="a nightly run over an unchanged corpus keeps the key",
        ),
        pytest.param(
            (IngestRunStatus.SUCCESS, "2026-09-18-def"),
            {},
            True,
            id="a new corpus version moves it",
        ),
        pytest.param(
            (IngestRunStatus.RUNNING, None),
            {},
            False,
            id="a run still going keeps it until it finishes",
        ),
        pytest.param(
            None,
            {"BUILD_ID": "registry.fly.io/regrag:deployment-2"},
            True,
            id="a new build moves it, since a deploy can change answers with no ingest",
        ),
    ],
)
async def test_the_key_moves_only_when_the_answer_could(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, run, settings: dict, moves: bool
) -> None:
    await add_ingest_run(db_session, IngestRunStatus.SUCCESS, "2026-09-17-abc")
    before = await answer_key(db_session, "What is FuelEU?")

    if run:
        await add_ingest_run(db_session, *run)
    for name, value in settings.items():
        monkeypatch.setattr(config, name, value)

    assert (await answer_key(db_session, "What is FuelEU?") != before) is moves


@pytest.mark.parametrize(
    ("setting", "value", "moves"),
    [
        pytest.param(
            "CHAT_MODEL",
            "anthropic/claude-sonnet-5",
            True,
            id="an answer setting, which a secrets-only release changes under one build",
        ),
        pytest.param("CHAT_CACHE_TTL_SECONDS", 60, False, id="the cache's own settings stay out"),
    ],
)
def test_the_settings_hash_moves_with_what_shapes_an_answer(
    monkeypatch: pytest.MonkeyPatch, setting: str, value: object, moves: bool
) -> None:
    before = hash_answer_settings()

    monkeypatch.setattr(config, setting, value)

    assert (hash_answer_settings() != before) is moves


@pytest.fixture
def cache_on(monkeypatch, answer_cache):
    """The answer cache on, over an emptied Redis standing in for the shared client."""
    install_versioned_key(monkeypatch)
    monkeypatch.setattr("app.chat.cache.redis_client", answer_cache)
    return answer_cache


FUELEU = ChatQuery(question="What is FuelEU?")
CACHED_ANSWER = CachedAnswer(answer="From the cache [1].", sources=(retrieved_chunk(),))
THREAD_ID = UUID("11111111-2222-3333-4444-555555555555")


class TestCacheStream:
    """The decorator on the graph run: a repeated first question is answered from Redis, and
    recorded by the same stream as any other."""

    async def test_a_hit_is_served_past_the_spend_cap(self, cache_on, answer_model, monkeypatch):
        """An answer that costs nothing to serve is not what the cap guards."""
        await store_answer(cache_on, FUELEU_KEY, CACHED_ANSWER)

        async def spent_the_cap(session, since):
            return config.CHAT_DAILY_SPEND_CAP_USD

        monkeypatch.setattr("app.chat.stream.spent_since", spent_the_cap)

        events = await collect_events(FUELEU)

        assert [event.event for event in events] == ["sources", "text", "done"]

    async def test_a_follow_up_neither_reads_nor_writes_the_cache(
        self, cache_on, two_results, recorded_requests, monkeypatch, rewrite_turns
    ):
        """A follow-up's answer depends on the thread before it, which the key does not hold."""
        await store_answer(cache_on, FUELEU_KEY, CACHED_ANSWER)
        rewrite_turns(restated_message("What is FuelEU, after the earlier question?"))

        async def one_turn(session, thread_id):
            return (ChatTurn(question="Earlier?", answer="Before."),)

        monkeypatch.setattr("app.chat.stream.load_thread_history", one_turn)
        install_chat_model(monkeypatch, fake_chat_model("Fresh [1]."))

        follow_up = ChatQuery(question=FUELEU.question, thread_id=THREAD_ID)
        events = await collect_events(follow_up)

        assert "".join(e.data for e in events if isinstance(e, TextEvent)) == "Fresh [1]."
        assert await cache_on.dbsize() == 1
        [state] = recorded_requests
        assert (state.outcome, state.thread_id) == (ChatOutcome.DONE, THREAD_ID)

    @pytest.mark.parametrize(
        "search_gives",
        [
            pytest.param((junk_result(),), id="a refusal is not kept"),
            pytest.param(LLMError("embedding call failed"), id="nor is a failed run"),
        ],
    )
    async def test_only_an_answer_is_kept(self, cache_on, answer_model, monkeypatch, search_gives):
        search_giving(monkeypatch, search_gives)

        await collect_events(FUELEU)

        assert answer_model.received == []
        assert await cache_on.dbsize() == 0

    async def test_redis_away_runs_the_graph(
        self, cache_on, two_results, answer_model, monkeypatch
    ):
        redis = unreachable_redis()
        monkeypatch.setattr("app.chat.cache.redis_client", redis)

        events = await collect_events(FUELEU)

        assert isinstance(events[-1], DoneEvent)
        assert len(answer_model.received) == 1
        await redis.aclose()
