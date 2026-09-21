"""What a model call spends: how usages add, and what a run with none reads as."""

from langchain_core.messages.ai import UsageMetadata

from app.core.llm.models import Usage, price_tokens

MODEL = "anthropic/claude-haiku-4-5"

SMALL = Usage(input_tokens=100, output_tokens=10)
TINY = Usage(input_tokens=5, output_tokens=1)


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


def test_a_model_litellm_cannot_price_is_unmeasured_not_free() -> None:
    assert price_tokens("anthropic/no-such-model", 100, 10) is None


def test_a_sum_counts_only_the_priced_calls() -> None:
    priced = Usage(input_tokens=10, output_tokens=1, cost_usd=0.5)
    assert (priced + SMALL).cost_usd == 0.5
    assert (priced + priced).cost_usd == 1.0
    assert (SMALL + TINY).cost_usd is None
