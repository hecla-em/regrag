"""Chat failures that end a request before the graph runs."""

from fastapi import status

from app.chat.enums import ChatErrorCode
from app.core.exceptions import DomainError


class SpendCapReachedError(DomainError):
    """The last day's recorded spend has reached the cap; nothing runs until it ages out."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = ChatErrorCode.SPEND_CAP_REACHED

    def __init__(self) -> None:
        super().__init__("The service is paused for the day; ask again later")


class ThreadFullError(DomainError):
    """The thread already holds as many answered turns as a thread may; the caller starts
    a new one."""

    status_code = status.HTTP_409_CONFLICT
    code = ChatErrorCode.THREAD_FULL

    def __init__(self, turns: int) -> None:
        super().__init__(
            f"This thread has reached its {turns} turns; start a new thread to keep asking"
        )
