"""The provider error contract: the one error a failed call raises, which failures are
worth retrying, the wrap point that translates a provider's failure into ours, and the
read-back that treats an answer off its schema as a failed call."""

import functools
import logging
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

from fastapi import status
from litellm.exceptions import ServiceUnavailableError
from openai import (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    RateLimitError,
)
from openai import (
    OpenAIError as ProviderError,
)
from pydantic import BaseModel, ValidationError

from app.core.exceptions import DomainError, ErrorCode
from app.core.retry import transient_retry

logger = logging.getLogger(__name__)

TRANSIENT_PROVIDER_ERRORS = (
    RateLimitError,
    APITimeoutError,
    APIConnectionError,
    InternalServerError,
    ServiceUnavailableError,
)
"""Provider failures worth retrying; 400, 401, 403 and 404 never are."""


class LLMError(DomainError):
    """A model provider call failed, or returned a response we cannot trust."""

    status_code = status.HTTP_502_BAD_GATEWAY
    code = ErrorCode.LLM

    def __init__(self, message: str, *, transient: bool = False):
        super().__init__(message)
        self.transient = transient


def _is_transient(exc: BaseException) -> bool:
    """Provider failures the wrap point judged worth another attempt."""
    return isinstance(exc, LLMError) and exc.transient


llm_retry = transient_retry(_is_transient)
"""Decorator retrying transient provider failures with exponential backoff."""


def wrap_provider_errors[**P, R](
    label: str,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Coroutine[Any, Any, R]]]:
    """Translate the wrapped call's provider failure into an LLMError reading
    "<label> failed", with the provider's own text kept to the log."""

    def decorate(fn: Callable[P, Awaitable[R]]) -> Callable[P, Coroutine[Any, Any, R]]:
        @functools.wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            try:
                return await fn(*args, **kwargs)
            except ProviderError as exc:
                logger.warning("%s failed: %s", label, exc)
                raise LLMError(
                    f"{label} failed", transient=isinstance(exc, TRANSIENT_PROVIDER_ERRORS)
                ) from exc

        return wrapper

    return decorate


def parse_model_answer[T: BaseModel](
    output: type[T], text: str, *, label: str, stopped_on: str | None = None
) -> T:
    """The answer in the shape the call bound it to. One off the schema is a failed call
    named for its label, not a value — with why the model stopped, when the caller knows."""
    try:
        return output.model_validate_json(text)
    except ValidationError as exc:
        stopped = f", stopped on {stopped_on}" if stopped_on else ""
        logger.warning("%s answered off its schema%s: %s", label, stopped, exc)
        raise LLMError(f"{label} answered off its schema") from exc
