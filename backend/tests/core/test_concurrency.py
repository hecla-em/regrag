"""The shared fan-out helper: what overlaps, what the cap holds, and what an abort leaves behind."""

import asyncio

import pytest

from app.core.concurrency import run_concurrently

pytestmark = pytest.mark.anyio


def tracker(peaks: list[int]):
    """A call that records how many of its own calls are in flight when each one runs."""
    active = 0

    async def call(item: int) -> int:
        nonlocal active
        active += 1
        await asyncio.sleep(0)
        peaks.append(active)
        active -= 1
        return item * 2

    return call


async def test_no_more_than_the_limit_are_ever_in_flight():
    peaks: list[int] = []

    async with run_concurrently(list(range(6)), tracker(peaks), limit=2) as pending:
        for _, task in pending:
            await task

    assert max(peaks) == 2


async def test_leaving_the_block_early_cancels_what_is_still_running():
    """An abort mid-consumption must not leave provider calls running behind the caller's back."""
    started = asyncio.Event()
    tasks: list[asyncio.Task[int]] = []

    async def never_finishes(item: int) -> int:
        started.set()
        await asyncio.Event().wait()
        return item

    with pytest.raises(RuntimeError):
        async with run_concurrently([1, 2], never_finishes, limit=2) as pending:
            await started.wait()
            tasks.extend(task for _, task in pending)
            raise RuntimeError("caller aborted")

    assert tasks
    await asyncio.gather(*tasks, return_exceptions=True)
    assert all(task.cancelled() for task in tasks)
