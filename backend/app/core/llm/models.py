"""What a model call spends."""

import functools
import logging
import operator
from collections.abc import Iterable

import litellm
from langchain_core.messages import AIMessage

from app.core.models import FrozenModel

logger = logging.getLogger(__name__)


def price_tokens(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """What the tokens cost at the model's listed prices, or None for a model missing from
    litellm's table, which it raises the base Exception for: unmeasured rather than free,
    and warned about, since a cap summing unpriced rows never fires."""
    try:
        input_cost, output_cost = litellm.cost_per_token(
            model=model, prompt_tokens=input_tokens, completion_tokens=output_tokens
        )
    except Exception:
        logger.warning("litellm has no price for %s; its usage is recorded unpriced", model)
        return None
    return input_cost + output_cost


class Usage(FrozenModel):
    """What one model call spent, or several spent between them: the tokens, and what they
    cost at the prices they were spent at. cost_usd is None while unpriced, and a sum
    counts only the calls that were priced."""

    input_tokens: int
    output_tokens: int
    cost_usd: float | None = None

    def __add__(self, other: "Usage") -> "Usage":
        priced = [cost for cost in (self.cost_usd, other.cost_usd) if cost is not None]
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cost_usd=sum(priced) if priced else None,
        )

    @classmethod
    def from_reply(cls, reply: AIMessage) -> "Usage | None":
        """What one call spent: the cost litellm reports on the reply, which is what OpenRouter
        billed, else the tokens priced at the model it named; None with no usage reported."""
        usage = reply.usage_metadata
        if usage is None:
            return None
        input_tokens, output_tokens = usage["input_tokens"], usage["output_tokens"]
        cost = reply.response_metadata.get("response_cost")
        model = reply.response_metadata.get("model_name")
        if cost is None and model:
            cost = price_tokens(model, input_tokens, output_tokens)
        return cls(input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=cost)

    @classmethod
    def sum_reported(cls, usages: Iterable["Usage | None"]) -> "Usage | None":
        """The usages summed over the calls that reported one, or None when none did —
        unmeasured rather than free."""
        reported = [usage for usage in usages if usage is not None]
        return functools.reduce(operator.add, reported) if reported else None
