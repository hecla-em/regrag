"""Model capabilities: what a run checks of the selected model before it pays for a case."""

import pytest
from langchain_core.messages import AIMessage

from app.core.config import config
from app.evals.capabilities import (
    CapabilityCheck,
    ModelCapability,
    check_listed_price,
    check_model_capabilities,
    check_structured_answer,
    check_tool_calls,
    format_capabilities,
    unsupported_capabilities,
)
from tests.chat.conftest import RecordingChatModel, tool_call_message
from tests.conftest import USAGE

pytestmark = pytest.mark.anyio


def probing(monkeypatch: pytest.MonkeyPatch, **turns: AIMessage) -> dict[str, RecordingChatModel]:
    """Stand a fake in for each named node's bound model, as the assess tests do: the
    binding is what a probe calls, so the fake replaces it whole rather than the model
    under it, which could not bind tools."""
    models = {}
    for name, message in turns.items():
        model = RecordingChatModel(messages=iter([message]), usage=USAGE)
        monkeypatch.setattr(f"app.evals.capabilities.{name}", lambda model=model: model)
        models[name] = model
    return models


SPLIT = AIMessage(content='{"queries": ["the sulphur limit", "how EEXI is calculated"]}')
FOLLOWED = tool_call_message("follow_reference", {"celex": "32014L0094", "citation": "Article 4"})


def test_a_model_litellm_prices_is_supported():
    assert check_listed_price().supported


def test_a_model_litellm_does_not_price_is_missing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "CHAT_MODEL", "openrouter/nobody/nothing-1")
    check = check_listed_price()
    assert not check.supported
    assert "spend cap" in check.detail


async def test_an_answer_in_the_bound_shape_is_supported(monkeypatch: pytest.MonkeyPatch):
    probing(monkeypatch, decompose_model=SPLIT)
    check = await check_structured_answer()
    assert check.supported
    assert check.detail == "split the probe into 2"


async def test_an_answer_off_the_bound_shape_is_missing(monkeypatch: pytest.MonkeyPatch):
    probing(monkeypatch, decompose_model=AIMessage(content="Here are the two parts:"))
    check = await check_structured_answer()
    assert not check.supported
    assert check.detail == "answered off the bound schema"


async def test_one_query_back_is_still_supported(monkeypatch: pytest.MonkeyPatch):
    """How the model splits the probe is a score, not a capability: only the shape is judged."""
    probing(monkeypatch, decompose_model=AIMessage(content='{"queries": ["the limit"]}'))
    assert (await check_structured_answer()).supported


async def test_a_tool_the_model_asked_for_is_supported(monkeypatch: pytest.MonkeyPatch):
    probing(monkeypatch, assess_model=FOLLOWED)
    check = await check_tool_calls()
    assert check.supported
    assert check.detail == "follow_reference"


async def test_no_tool_asked_for_is_missing(monkeypatch: pytest.MonkeyPatch):
    probing(monkeypatch, assess_model=AIMessage(content="The context already answers it."))
    check = await check_tool_calls()
    assert not check.supported
    assert "no tool" in check.detail


async def test_a_node_switched_off_is_never_probed(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "DECOMPOSE_ENABLED", False)
    monkeypatch.setattr(config, "ASSESS_ENABLED", False)
    models = probing(monkeypatch, decompose_model=SPLIT, assess_model=FOLLOWED)

    checks = await check_model_capabilities()

    assert [check.capability for check in checks] == [ModelCapability.LISTED_PRICE]
    assert [model.received for model in models.values()] == [[], []]


async def test_a_run_answering_from_memory_probes_nothing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "DECOMPOSE_ENABLED", True)
    monkeypatch.setattr(config, "ASSESS_ENABLED", True)
    models = probing(monkeypatch, decompose_model=SPLIT, assess_model=FOLLOWED)

    checks = await check_model_capabilities(retrieval=False)

    assert [check.capability for check in checks] == [ModelCapability.LISTED_PRICE]
    assert [model.received for model in models.values()] == [[], []]


async def test_every_node_that_runs_is_probed(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "DECOMPOSE_ENABLED", True)
    monkeypatch.setattr(config, "ASSESS_ENABLED", True)
    probing(monkeypatch, decompose_model=SPLIT, assess_model=FOLLOWED)

    checks = await check_model_capabilities()

    assert [check.capability for check in checks] == [
        ModelCapability.LISTED_PRICE,
        ModelCapability.STRUCTURED_ANSWER,
        ModelCapability.TOOL_CALLS,
    ]
    assert not unsupported_capabilities(checks)


def test_only_what_the_model_dropped_holds_a_run_back():
    checks = (
        CapabilityCheck(capability=ModelCapability.LISTED_PRICE, supported=True),
        CapabilityCheck(capability=ModelCapability.TOOL_CALLS, supported=False),
    )
    assert unsupported_capabilities(checks) == (ModelCapability.TOOL_CALLS,)


def test_the_printed_lines_name_the_model_and_what_it_showed():
    checks = (
        CapabilityCheck(capability=ModelCapability.LISTED_PRICE, supported=True),
        CapabilityCheck(
            capability=ModelCapability.TOOL_CALLS, supported=False, detail="asked for no tool"
        ),
    )
    lines = format_capabilities(checks)
    assert lines[0] == f"{config.CHAT_MODEL}:"
    assert "listed_price" in lines[1] and "ok" in lines[1]
    assert "missing" in lines[2] and "(asked for no tool)" in lines[2]
