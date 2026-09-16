"""SSE chat endpoint streaming a cited answer from the chat graph."""

from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent

from app.chat.events import ChatEvent
from app.chat.models import ChatQuery
from app.chat.stream import stream_chat_events
from app.core.ratelimit import ClientIdHeader, rate_limit
from app.core.redis import RedisDep

router = APIRouter(tags=["chat"])

CHAT_RESPONSES: dict[int | str, dict[str, Any]] = {200: {"model": ChatEvent}}
"""What a frame's data holds, for the OpenAPI schema: FastAPI cannot read it from the
yielded ServerSentEvent, and the response class files it under text/event-stream."""


async def rate_limit_question(
    query: ChatQuery, request: Request, redis: RedisDep, x_client_id: ClientIdHeader = None
) -> None:
    """Rate limit once the question has parsed, so a malformed one costs no slot: FastAPI
    resolves route dependencies before the body, and a raise inside the stream is too late."""
    await rate_limit(request, redis, x_client_id)


@router.post(
    "/chat",
    response_class=EventSourceResponse,
    responses=CHAT_RESPONSES,
    dependencies=[Depends(rate_limit_question)],
)
async def chat(query: ChatQuery) -> AsyncIterator[ServerSentEvent]:
    """Stream a cited answer to the question over SSE: steps, sources, tokens, done with the
    thread id; or error."""
    async for event in stream_chat_events(query):
        yield ServerSentEvent(event=event.event, data=event.data)
