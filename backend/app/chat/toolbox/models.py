"""The tool surface's values: a call the model asked for, and the spec of a tool it may call."""

from collections.abc import Awaitable, Callable
from typing import Any, NamedTuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.blocks import ContextBlock
from app.chat.enums import ToolStep
from app.core.models import FrozenModel


class ToolCall(FrozenModel):
    """One tool call assess asked for, as litellm reports it: the tool, and its arguments."""

    name: str
    args: dict[str, Any] = {}


class ToolSpec(NamedTuple):
    """One tool the model may call: how it is named and described to the model, the
    arguments it takes, what runs it, the step a call to it records, and, for a dataset
    tool, the card the gate matches a question against and how it finds what a question names
    in its data."""

    name: str
    step: ToolStep
    args_model: type[FrozenModel]
    run: Callable[..., Awaitable[tuple[ContextBlock, ...]]]
    description: str
    card: str | None = None
    find_entities: Callable[[AsyncSession, str], Awaitable[tuple[str, ...]]] | None = None

    def definition(self) -> dict:
        """The tool as bind_tools wants it: an openai function-tool dictionary."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.args_model.model_json_schema(),
            },
        }
