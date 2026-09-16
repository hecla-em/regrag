"""SSE chat endpoint streaming a cited answer from the chat graph."""

from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.sse import EventSourceResponse, ServerSentEvent

from app.chat.events import ChatEvent
from app.chat.models import ChatQuery
from app.chat.stream import stream_chat_events
from app.core.ratelimit import rate_limit

router = APIRouter(tags=["chat"])

CHAT_RESPONSES: dict[int | str, dict[str, Any]] = {200: {"model": ChatEvent}}
"""What a frame's data holds, for the OpenAPI schema: FastAPI cannot read it from the
yielded ServerSentEvent, and the response class files it under text/event-stream."""


@router.post(
    "/chat",
    response_class=EventSourceResponse,
    responses=CHAT_RESPONSES,
    dependencies=[Depends(rate_limit)],
)
async def chat(query: ChatQuery) -> AsyncIterator[ServerSentEvent]:
    """Stream a cited answer to the question over SSE: steps, sources, tokens, done with the
    thread id; or error."""
    async for event in stream_chat_events(query):
        yield ServerSentEvent(event=event.event, data=event.data)
