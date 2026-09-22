"""The eval endpoints: the stored runs and the live settings come back to a keyed request,
and a request without the key is refused."""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import delete

from app.core.config import EVAL_CONFIG_SECTIONS, config, get_config_snapshot
from app.core.db.session import get_session
from app.evals.schemas import EvalRun
from app.evals.service import create_eval_run
from tests.conftest import assert_error_shape
from tests.evals.conftest import eval_result, eval_run, passed_judgement

KEY = "analytics-key"
HEADERS = {"X-API-Key": KEY}


@pytest.fixture
def keyed_client(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(config, "ANALYTICS_API_KEY", SecretStr(KEY))
    return client


@pytest.fixture
def stored_run(keyed_client: TestClient, test_database: None) -> Generator[EvalRun, None, None]:
    """A judged run committed to eval_runs, as the CLI stores one, and deleted after. Reached
    through test_database so the schema is at head before the first row is written."""
    assert keyed_client.portal is not None

    async def store() -> EvalRun:
        async with get_session() as session:
            run = eval_run(
                eval_result(judgement=passed_judgement()), judged=True, git_commit="12265d6"
            )
            return await create_eval_run(session, run)

    async def clear() -> None:
        async with get_session() as session:
            await session.execute(delete(EvalRun))

    yield keyed_client.portal.call(store)
    keyed_client.portal.call(clear)


def test_the_stored_runs_and_the_live_settings_come_back(
    keyed_client: TestClient, stored_run: EvalRun
):
    runs = keyed_client.get("/analytics/evals/runs", headers=HEADERS)
    assert runs.status_code == 200
    [run] = [r for r in runs.json() if r["id"] == stored_run.id]
    assert run["git_commit"] == "12265d6"
    assert run["model"] == config.CHAT_MODEL
    assert run["judge_model"] == config.EVAL_JUDGE_MODEL
    assert run["retrieval"] is True
    assert run["settings"]["CHAT_MODEL"] == config.CHAT_MODEL
    assert run["metrics"]["judge"]["correctness"] == 1.0
    assert run["metrics"]["usage"]["cost_usd"] == stored_run.metrics["usage"]["cost_usd"]

    settings = keyed_client.get("/analytics/evals/settings", headers=HEADERS)
    assert settings.status_code == 200
    assert settings.json()["build_id"] == config.BUILD_ID
    assert settings.json()["settings"] == run["settings"]
    assert set(settings.json()["settings"]) == set(get_config_snapshot(EVAL_CONFIG_SECTIONS))


def test_a_request_without_the_key_is_refused(keyed_client: TestClient):
    assert_error_shape(keyed_client.get("/analytics/evals/runs"), 401, "UnauthorizedError")
    assert_error_shape(keyed_client.get("/analytics/evals/settings"), 401, "UnauthorizedError")
