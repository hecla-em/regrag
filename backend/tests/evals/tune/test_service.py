"""The runner: one case through retrieve alone, and the override-and-measure loop."""

import pytest

from app.chat.enums import ChatNode
from app.core.config import config
from app.evals.service import evaluate_case
from app.evals.tune import service
from app.evals.tune.models import TunableParam
from app.evals.tune.service import retrieve_graph, tune
from tests.conftest import install_search, search_result
from tests.evals.conftest import eval_case, eval_dataset, eval_result

pytestmark = pytest.mark.anyio


@pytest.fixture
def found_context(monkeypatch: pytest.MonkeyPatch) -> None:
    """Search finds the authored reference; expansion is a database walk covered in
    tests/retrieval, so it is switched off."""

    async def fake_search(session, request):
        return (search_result(),)

    monkeypatch.setattr(config, "EXPAND_SECTIONS", False)
    install_search(monkeypatch, fake_search)


async def test_retrieve_graph_drives_the_retrieve_node_alone(found_context: None) -> None:
    result = await evaluate_case(eval_case(), graph=retrieve_graph)

    assert result.state.hits == (search_result(),)
    assert result.state.sources == (search_result(),)
    assert [n.step for n in result.state.steps] == [ChatNode.RETRIEVE]
    assert result.state.usage() is None
    assert result.state.total_ms is not None


async def test_tune_measures_baseline_then_each_value_and_restores_between(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[int, bool]] = []

    async def fake_evaluate(case, graph=None):
        seen.append((config.CHAT_SOURCES, config.RERANK_ENABLED))
        return eval_result(case=case)

    monkeypatch.setattr(service, "evaluate_case", fake_evaluate)
    baseline_sources = config.CHAT_SOURCES
    baseline_rerank = config.RERANK_ENABLED
    dataset = eval_dataset(eval_case(id="one"), eval_case(id="two"))
    params = (
        TunableParam(name="CHAT_SOURCES", values=(baseline_sources + 1,)),
        TunableParam(name="RERANK_ENABLED", values=(not baseline_rerank,)),
    )

    run = await tune(dataset, params)

    assert seen == [
        (baseline_sources, baseline_rerank),
        (baseline_sources, baseline_rerank),
        (baseline_sources + 1, baseline_rerank),
        (baseline_sources + 1, baseline_rerank),
        (baseline_sources, not baseline_rerank),
        (baseline_sources, not baseline_rerank),
    ]
    assert config.CHAT_SOURCES == baseline_sources
    assert config.RERANK_ENABLED == baseline_rerank
    assert run.baseline.counts.cases == 2
    assert [(result.param, result.value) for result in run.results] == [
        ("CHAT_SOURCES", baseline_sources + 1),
        ("RERANK_ENABLED", not baseline_rerank),
    ]
    assert run.dataset_sha == dataset.sha256


async def test_a_value_equal_to_baseline_is_not_measured_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The baseline run already measured it, so a second run would add nothing but time."""
    ran: list[str] = []

    async def fake_evaluate(case, graph=None):
        ran.append(case.id)
        return eval_result(case=case)

    monkeypatch.setattr(service, "evaluate_case", fake_evaluate)
    dataset = eval_dataset(eval_case(id="one"))

    run = await tune(dataset, (TunableParam(name="CHAT_SOURCES", values=(config.CHAT_SOURCES,)),))

    assert ran == ["one"]
    assert run.results == ()


async def test_a_gated_value_is_measured_with_its_companions_applied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A knob read only under a companion setting is measured with that setting on."""
    seen: list[tuple[bool, int]] = []

    async def fake_evaluate(case, graph=None):
        seen.append((config.EXPAND_SECTIONS, config.CHAT_CONTEXT_CHUNKS))
        return eval_result(case=case)

    monkeypatch.setattr(service, "evaluate_case", fake_evaluate)
    baseline_expand = config.EXPAND_SECTIONS
    baseline_chunks = config.CHAT_CONTEXT_CHUNKS
    dataset = eval_dataset(eval_case(id="one"))
    param = TunableParam(
        name="CHAT_CONTEXT_CHUNKS",
        values=(baseline_chunks + 5,),
        requires={"EXPAND_SECTIONS": not baseline_expand},
    )

    run = await tune(dataset, (param,))

    assert seen == [
        (baseline_expand, baseline_chunks),
        (not baseline_expand, baseline_chunks + 5),
    ]
    assert config.EXPAND_SECTIONS is baseline_expand
    assert run.results[0].requires == {"EXPAND_SECTIONS": not baseline_expand}
