"""SSE chat endpoint streaming a cited answer from the chat graph."""

from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, status
from fastapi.sse import EventSourceResponse, ServerSentEvent

from app.chat.events import ChatEvent
from app.chat.models import ChatQuery
from app.chat.stream import stream_chat_events
from app.core.models import ErrorResponse
from app.core.ratelimit import rate_limit
from app.core.turnstile import verify_turnstile

router = APIRouter(tags=["chat"])

CHAT_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_200_OK: {"model": ChatEvent},
    status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
    status.HTTP_429_TOO_MANY_REQUESTS: {"model": ErrorResponse},
}
"""What a frame's data holds, for the OpenAPI schema: FastAPI cannot read it from the
yielded ServerSentEvent, and the response class files it under text/event-stream. The
rate limit and the browser check refuse before the stream opens with a JSON error, which
FastAPI files under the same media type."""


@router.post(
    "/chat",
    response_class=EventSourceResponse,
    responses=CHAT_RESPONSES,
    dependencies=[Depends(rate_limit), Depends(verify_turnstile)],
)
async def chat(query: ChatQuery) -> AsyncIterator[ServerSentEvent]:
    """Stream a cited answer to the question over SSE: steps, sources, tokens, done with the
    thread id; or error. A repeated first question replays sources, the answer and done."""
    async for event in stream_chat_events(query):
        yield ServerSentEvent(event=event.event, data=event.data)
