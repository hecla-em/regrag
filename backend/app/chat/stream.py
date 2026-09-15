"""Chat streaming: the graph run, translated into chat events, and recorded when it ends."""

import logging
import time
from collections.abc import AsyncGenerator, AsyncIterator
from datetime import timedelta
from typing import Any
from uuid import uuid4

import anyio
from sqlalchemy.exc import SQLAlchemyError

from app.chat.enums import ChatNode, ChatStepStatus
from app.chat.events import (
    ChatEvent,
    ChatThread,
    DoneEvent,
    ErrorEvent,
    SourcesEvent,
    StepEvent,
    TextEvent,
)
from app.chat.exceptions import SpendCapReachedError, ThreadFullError
from app.chat.graph.service import chat_graph
from app.chat.models import ChatQuery, ChatState, ChatStepResult
from app.chat.service import create_chat_request, load_thread_history, spent_since
from app.chat.toolbox.service import build_call_step
from app.core.clock import elapsed_ms, utc_now
from app.core.config import config
from app.core.db.session import get_session
from app.core.exceptions import DomainError, describe
from app.core.logger import request_id_var
from app.core.models import ErrorResponse

logger = logging.getLogger(__name__)


def _error_event(exc: Exception) -> ErrorEvent:
    """The error event for a failed stream, logged like the JSON handlers log theirs."""
    error, message = describe(exc)
    if isinstance(exc, DomainError):
        logger.warning("chat stream failed: %s", message)
    else:
        logger.exception("chat stream failed unexpectedly")
    body = ErrorResponse(error=error, message=message, request_id=request_id_var.get())
    return ErrorEvent(data=body)


def _starting_steps(entry: ChatState, node: ChatNode) -> list[ChatStepResult]:
    """What a node starting announces: a node handed pending calls is a tool round, and
    announces one step per call it is about to run; every other node is itself. Read off
    the state, not the node's name, so a second tool-calling node needs nothing here."""
    if entry.pending_calls:
        return [
            build_call_step(call, status=ChatStepStatus.RUNNING) for call in entry.pending_calls
        ]
    return [ChatStepResult(step=node, ms=0, status=ChatStepStatus.RUNNING)]


async def _stream_graph_events(state: ChatState) -> AsyncGenerator[ChatEvent, None]:
    """The graph run as chat events. LangGraph provides three streams: 'tasks' - an event as
    each node starts and finishes, 'values' - a snapshot of the state after each node, and
    'messages' - the tokens a node's model call produces. Finished steps come from the
    'tasks' event, which a cached node never sends. Nothing here is cached."""
    sources_sent = False
    graph_stream: AsyncIterator[Any] = chat_graph.astream(
        state, stream_mode=["tasks", "values", "messages"]
    )
    async for mode, payload in graph_stream:
        # Starting carries the node's input, finished what it returned — nothing if it raised
        if mode == "tasks":
            if "input" in payload:
                for step in _starting_steps(payload["input"], ChatNode(payload["name"])):
                    yield StepEvent(data=step)
            else:
                for step in payload["result"].get("steps", ()):
                    yield StepEvent(data=step)
            continue
        # The full state after each node
        if mode == "values":
            state.sync_from_snapshot(payload)

            if not sources_sent and state.context_settled:
                sources_sent = True
                yield SourcesEvent.from_results(state.sources)

            if state.last_step is ChatNode.REFUSE:
                yield TextEvent(data=state.answer)
        # Node running
        else:
            chunk, metadata = payload
            if metadata.get("langgraph_node") != ChatNode.SYNTHESIZE:
                continue
            # Stream answer text
            if text := chunk.text:
                yield TextEvent(data=text)

    yield DoneEvent(data=ChatThread(thread_id=state.thread_id))


async def check_spend_cap() -> None:
    """Refuse the question once the last day's recorded spend has reached the cap, logging
    where the day stands either way — the burn is read off these lines, not a dashboard."""
    cap = config.CHAT_DAILY_SPEND_CAP_USD
    async with get_session(auto_commit=False) as session:
        spent = await spent_since(session, utc_now() - timedelta(days=1))
    logger.info(
        "chat spend %.4f of %.2f USD in the last day",
        spent,
        cap,
        extra={"spent_usd": spent, "cap_usd": cap},
    )
    if spent >= cap:
        raise SpendCapReachedError()


async def open_thread(query: ChatQuery) -> ChatState:
    """The state a question starts from: on a fresh thread, one minted here and no history;
    on a continued one, its answered turns — or a refusal to add another once it is full."""
    if query.thread_id is None:
        return ChatState(question=query.question)
    async with get_session(auto_commit=False) as session:
        history = await load_thread_history(session, query.thread_id)
    if len(history) >= config.CHAT_THREAD_TURNS:
        raise ThreadFullError(config.CHAT_THREAD_TURNS)
    return ChatState(question=query.question, thread_id=query.thread_id, history=history)


async def stream_chat_events(query: ChatQuery) -> AsyncGenerator[ChatEvent, None]:
    """One question's events, ended by an error event if the day's spend is capped, the
    thread is full or the run raises; however it ends — done, refused, error, or the client
    leaving, which cancels this task — it is recorded as one chat request, in its own
    session, shielded from that cancellation. A failed write is logged, not raised: the
    answer already went out."""
    state = ChatState(question=query.question, thread_id=query.thread_id or uuid4())
    start = time.perf_counter()
    try:
        await check_spend_cap()
        state = await open_thread(query)
        async for event in _stream_graph_events(state):
            yield event
    except Exception as exc:
        state.record_error(exc)
        yield _error_event(exc)
    finally:
        state.total_ms = elapsed_ms(start)
        with anyio.CancelScope(shield=True):
            try:
                async with get_session(auto_commit=False) as session:
                    await create_chat_request(session, state)
            except SQLAlchemyError:
                logger.exception("chat request not recorded")
