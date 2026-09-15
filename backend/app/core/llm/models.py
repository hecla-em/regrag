"""What a model call spends."""

import functools
import operator
from collections.abc import Iterable

import litellm
from langchain_core.messages.ai import UsageMetadata

from app.core.models import FrozenModel


class TokenUsage(FrozenModel):
    """The tokens one model call spent, or several calls spent between them."""

    input_tokens: int
    output_tokens: int

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
        )

    def cost_usd(self, model: str) -> float | None:
        """What the tokens cost at the model's listed prices, or None for a model litellm
        cannot price — unmeasured rather than free, like a usage nobody reported."""
        try:
            input_cost, output_cost = litellm.cost_per_token(
                model=model, prompt_tokens=self.input_tokens, completion_tokens=self.output_tokens
            )
        except Exception:  # litellm raises the base class for a model missing from its table
            return None
        return input_cost + output_cost

    @classmethod
    def from_metadata(cls, usage: UsageMetadata) -> "TokenUsage":
        """What one call spent, as langchain reports it on the message."""
        return cls(input_tokens=usage["input_tokens"], output_tokens=usage["output_tokens"])

    @classmethod
    def sum_reported(cls, usages: Iterable["TokenUsage | None"]) -> "TokenUsage | None":
        """The usages summed over the calls that reported one, or None when none did —
        unmeasured rather than free."""
        reported = [usage for usage in usages if usage is not None]
        return functools.reduce(operator.add, reported) if reported else None
