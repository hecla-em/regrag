"""What a model call spends: how usages add, and what a run with none reads as."""

import logging

from langchain_core.messages.ai import UsageMetadata

from app.core.llm.models import TokenUsage

SMALL = TokenUsage(input_tokens=100, output_tokens=10)
TINY = TokenUsage(input_tokens=5, output_tokens=1)


def test_usages_add_field_by_field() -> None:
    assert SMALL + TINY == TokenUsage(input_tokens=105, output_tokens=11)


def test_the_sum_skips_steps_that_reported_nothing() -> None:
    assert TokenUsage.sum_reported((None, SMALL, None, TINY)) == SMALL + TINY


def test_a_run_that_reported_nothing_is_unmeasured_not_free() -> None:
    assert TokenUsage.sum_reported((None, None)) is None
    assert TokenUsage.sum_reported(()) is None


def test_a_call_usage_is_read_from_the_message_metadata() -> None:
    reported = UsageMetadata(input_tokens=100, output_tokens=10, total_tokens=110)
    assert TokenUsage.from_metadata(reported) == SMALL


def test_cost_is_the_tokens_at_the_models_listed_prices() -> None:
    """The real seam: litellm's price table for the default chat model."""
    million_in = TokenUsage(input_tokens=1_000_000, output_tokens=0)
    cost = million_in.cost_usd("anthropic/claude-haiku-4-5")
    assert cost is not None
    assert 0.1 < cost < 10


def test_output_tokens_cost_more_than_input_tokens() -> None:
    in_only = TokenUsage(input_tokens=1000, output_tokens=0).cost_usd("anthropic/claude-haiku-4-5")
    out_only = TokenUsage(input_tokens=0, output_tokens=1000).cost_usd("anthropic/claude-haiku-4-5")
    assert in_only is not None and out_only is not None
    assert out_only > in_only > 0


def test_a_model_litellm_cannot_price_is_unmeasured_not_free() -> None:
    assert SMALL.cost_usd("anthropic/no-such-model") is None


def test_an_unpriced_model_is_warned_about(caplog) -> None:
    """A cap that sums unpriced rows never fires, so the gap has to be visible somewhere."""
    with caplog.at_level(logging.WARNING, logger="app.core.llm.models"):
        SMALL.cost_usd("anthropic/no-such-model")
    assert any("no price for anthropic/no-such-model" in r.getMessage() for r in caplog.records)
