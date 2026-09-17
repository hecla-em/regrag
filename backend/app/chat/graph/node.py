"""What every chat node is built from: the contract a node fulfils, the wrapper that times
it, and the model client its call is made with."""

import functools
import time
from collections.abc import Awaitable
from typing import Any, Protocol

from langchain_litellm import ChatLiteLLM

from app.chat.enums import ChatNode
from app.chat.models import ChatState, ChatStepResult
from app.core.clock import elapsed_ms
from app.core.config import config
from app.core.llm.keys import api_key_for


class NodeFn(Protocol):
    """A node: the state so far in, the fields it sets out — plus `reply`, the message if it
    called a model, whose spend its step carries rather than the state. Named for the
    ChatNode it is."""

    __name__: str

    def __call__(self, state: ChatState) -> Awaitable[dict[str, Any]]: ...


def traced(run: NodeFn) -> NodeFn:
    """The node as the graph runs it, appending one step — how long it took, and the usage
    it reported — to the path. Outermost on a node, so a retried call is traced as a whole."""
    node = ChatNode(run.__name__)

    @functools.wraps(run)
    async def traced_run(state: ChatState) -> dict[str, Any]:
        start = time.perf_counter()
        update = await run(state)
        ms = elapsed_ms(start)
        reply = update.pop("reply", None)
        step = (
            ChatStepResult.from_reply(node, ms, reply)
            if reply is not None
            else ChatStepResult(step=node, ms=ms)
        )
        return update | {"steps": (step,)}

    return traced_run


def chat_model(*, streaming: bool = True, thinking: bool = False) -> ChatLiteLLM:
    """A chat client built per call, so config is read at call time like embed's. Every node
    calls CHAT_MODEL — they are steps of one answer, not jobs tuned apart — with the key of
    whichever provider it names.

    Streaming is set for the answer, or litellm answers in one blocking call — even under
    the graph's messages stream — and the SSE stream carries the whole answer in a single
    token event; assess wants that one blocking call, so it turns streaming off.
    Usage is asked for, or litellm strips it from every streamed chunk and the run's
    tokens are never reported for a non-OpenAI model; it is read on the streamed path only.
    Thinking gives the call its budget on top of the answer's cap, at the temperature of 1
    the provider requires alongside it.
    """
    sampling: dict[str, Any] = {
        "max_tokens": config.CHAT_MAX_TOKENS,
        "temperature": config.CHAT_TEMPERATURE,
    }
    if thinking:
        budget = config.CHAT_THINKING_BUDGET
        sampling = {
            "max_tokens": config.CHAT_MAX_TOKENS + budget,
            "temperature": 1.0,
            "model_kwargs": {"thinking": {"type": "enabled", "budget_tokens": budget}},
        }
    return ChatLiteLLM(
        model=config.CHAT_MODEL,
        api_key=api_key_for(config.CHAT_MODEL),
        request_timeout=config.CHAT_TIMEOUT,
        streaming=streaming,
        stream_options={"include_usage": True},
        **sampling,
    )
