"""What a model call spends: how usages add, and what a run with none reads as."""

import logging

from langchain_core.messages.ai import UsageMetadata

from app.core.llm.models import Usage, price_tokens

MODEL = "anthropic/claude-haiku-4-5"

SMALL = Usage(input_tokens=100, output_tokens=10)
TINY = Usage(input_tokens=5, output_tokens=1)


def test_usages_add_field_by_field() -> None:
    assert SMALL + TINY == Usage(input_tokens=105, output_tokens=11)


def test_the_sum_skips_steps_that_reported_nothing() -> None:
    assert Usage.sum_reported((None, SMALL, None, TINY)) == SMALL + TINY


def test_a_run_that_reported_nothing_is_unmeasured_not_free() -> None:
    assert Usage.sum_reported((None, None)) is None
    assert Usage.sum_reported(()) is None


def test_a_call_usage_is_read_from_the_message_metadata_and_priced_at_its_model() -> None:
    """The real seam: litellm's price table for the default chat model."""
    reported = UsageMetadata(input_tokens=100, output_tokens=10, total_tokens=110)
    usage = Usage.from_metadata(reported, MODEL)
    assert (usage.input_tokens, usage.output_tokens) == (100, 10)
    assert usage.cost_usd is not None
    assert 0 < usage.cost_usd < 0.01


def test_a_reply_that_named_no_model_is_unpriced() -> None:
    reported = UsageMetadata(input_tokens=100, output_tokens=10, total_tokens=110)
    assert Usage.from_metadata(reported, None) == SMALL


def test_output_tokens_cost_more_than_input_tokens() -> None:
    in_only = price_tokens(MODEL, 1000, 0)
    out_only = price_tokens(MODEL, 0, 1000)
    assert in_only is not None and out_only is not None
    assert out_only > in_only > 0


def test_a_model_litellm_cannot_price_is_unmeasured_not_free() -> None:
    assert price_tokens("anthropic/no-such-model", 100, 10) is None


def test_an_unpriced_model_is_warned_about(caplog) -> None:
    """A cap that sums unpriced rows never fires, so the gap has to be visible somewhere."""
    with caplog.at_level(logging.WARNING, logger="app.core.llm.models"):
        price_tokens("anthropic/no-such-model", 100, 10)
    assert any("no price for anthropic/no-such-model" in r.getMessage() for r in caplog.records)


def test_a_sum_counts_only_the_priced_calls() -> None:
    priced = Usage(input_tokens=10, output_tokens=1, cost_usd=0.5)
    assert (priced + SMALL).cost_usd == 0.5
    assert (priced + priced).cost_usd == 1.0
    assert (SMALL + TINY).cost_usd is None
