"""The chat endpoints: the SSE stream of a cited answer, and the reader's vote on one."""

from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, status
from fastapi.sse import EventSourceResponse, ServerSentEvent

from app.chat.events import ChatEvent
from app.chat.models import ChatQuery, ChatVote
from app.chat.service import record_vote
from app.chat.stream import stream_chat_events
from app.core.db.session import SessionDep
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
    dependencies=[Depends(rate_limit("question")), Depends(verify_turnstile)],
)
async def chat(query: ChatQuery) -> AsyncIterator[ServerSentEvent]:
    """Stream a cited answer to the question over SSE: steps, sources, tokens, done with the
    thread and request ids; or error. A repeated first question replays sources, the answer
    and done."""
    async for event in stream_chat_events(query):
        yield ServerSentEvent(event=event.event, data=event.data)


@router.put(
    "/chat/{request_id}/vote",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_429_TOO_MANY_REQUESTS: {"model": ErrorResponse},
    },
    dependencies=[Depends(rate_limit("vote"))],
)
async def vote_on_answer(request_id: str, body: ChatVote, session: SessionDep) -> None:
    """Record the reader's vote on the answer the request gave, the one its done frame named,
    in place of any earlier vote; a null vote takes it back."""
    await record_vote(session, request_id, body.vote)
