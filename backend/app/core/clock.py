"""Clock accessors, kept in one place so tests can pin the current time."""

import time
from datetime import UTC, date, datetime


def utc_now() -> datetime:
    """The current UTC instant."""
    return datetime.now(UTC)


def utc_today() -> date:
    """The current UTC date."""
    return utc_now().date()


def now_ms() -> int:
    """Whole milliseconds since the epoch."""
    return int(time.time() * 1000)


def elapsed_ms(start: float) -> int:
    """Whole milliseconds since a perf_counter reading."""
    return int((time.perf_counter() - start) * 1000)
