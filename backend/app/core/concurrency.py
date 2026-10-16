"""Shared fan-out policy: many awaitable calls in flight at once, capped and cancel-safe."""

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager


@asynccontextmanager
async def run_concurrently[T, R](
    items: Sequence[T], fn: Callable[[T], Awaitable[R]], *, limit: int
) -> AsyncGenerator[list[tuple[T, asyncio.Task[R]]], None]:
    """Every item's `fn` call in flight, at most `limit` at once, each task paired with its
    item; leaving the block cancels whatever an abort left running."""
    semaphore = asyncio.Semaphore(limit)

    async def paced(item: T) -> R:
        async with semaphore:
            return await fn(item)

    pairs = [(item, asyncio.create_task(paced(item))) for item in items]
    try:
        yield pairs
    finally:
        for _, task in pairs:
            task.cancel()
