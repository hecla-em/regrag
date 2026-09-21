"""Shared HTTP client policy and the transient-retry decorator."""

import httpx
import pytest

from app.core.http import http_retry, pace_requests


class FakeClock:
    """A monotonic clock that only moves when something sleeps, or a test advances it."""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    """Pacing's view of time, so tests assert on waits instead of serving them."""
    fake = FakeClock()
    monkeypatch.setattr("app.core.http.time.monotonic", fake.monotonic)
    monkeypatch.setattr("app.core.http.asyncio.sleep", fake.sleep)
    return fake


def flaky_client(responses):
    """Client whose handler pops one queued response (or raises one queued error) per request."""
    calls = []

    def handler(request):
        calls.append(str(request.url))
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    return httpx.Client(transport=httpx.MockTransport(handler)), calls


@pytest.fixture
def get(defuse_retry):
    """The decorated unit under test, with tenacity's waits stripped."""

    @http_retry
    def _get(client, url="https://example.eu/doc"):
        response = client.get(url)
        response.raise_for_status()
        return response

    return defuse_retry(_get)


def test_retries_retryable_status(get):
    client, calls = flaky_client([httpx.Response(503), httpx.Response(200, text="ok")])
    assert get(client).text == "ok"
    assert len(calls) == 2


def test_gives_up_after_max_attempts(get):
    client, calls = flaky_client([httpx.Response(503)] * 3)
    with pytest.raises(httpx.HTTPStatusError):
        get(client)
    assert len(calls) == 3


def test_does_not_retry_client_errors(get):
    client, calls = flaky_client([httpx.Response(404)])
    with pytest.raises(httpx.HTTPStatusError):
        get(client)
    assert len(calls) == 1


def test_retries_transport_errors(get):
    client, calls = flaky_client([httpx.ConnectError("refused"), httpx.Response(200, text="ok")])
    assert get(client).text == "ok"
    assert len(calls) == 2


def paced_client(delays: dict[str, float]) -> httpx.AsyncClient:
    """A client whose requests are paced per host and answered locally."""
    return httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200)),
        event_hooks={"request": [pace_requests(delays)]},
    )


ONE_SECOND = {"example.test": 1.0}


@pytest.mark.anyio
async def test_pacing_lets_the_first_request_straight_through(clock: FakeClock) -> None:
    await paced_client(ONE_SECOND).get("https://example.test/doc")
    assert clock.slept == []


@pytest.mark.anyio
async def test_pacing_waits_between_every_request_not_every_document(clock: FakeClock) -> None:
    """Pacing is per request: falling back to the original act costs two, and both wait."""
    client = paced_client(ONE_SECOND)
    for _ in range(3):
        await client.get("https://example.test/doc")
    assert clock.slept == [1.0, 1.0]


@pytest.mark.anyio
async def test_pacing_waits_only_for_what_is_left_of_the_interval(clock: FakeClock) -> None:
    client = paced_client(ONE_SECOND)
    await client.get("https://example.test/doc")
    clock.now += 0.4
    await client.get("https://example.test/doc")
    assert clock.slept == [pytest.approx(0.6)]


@pytest.mark.anyio
async def test_pacing_does_not_wait_when_the_interval_has_already_passed(clock: FakeClock) -> None:
    client = paced_client(ONE_SECOND)
    await client.get("https://example.test/doc")
    clock.now += 5.0
    await client.get("https://example.test/doc")
    assert clock.slept == []


@pytest.mark.anyio
async def test_each_client_paces_on_its_own_last_request(clock: FakeClock) -> None:
    """State lives with the client, so one client's requests never delay another's."""
    first, second = paced_client(ONE_SECOND), paced_client(ONE_SECOND)
    await first.get("https://example.test/doc")
    await second.get("https://example.test/doc")
    assert clock.slept == []


@pytest.mark.anyio
async def test_pacing_is_tracked_per_host(clock: FakeClock) -> None:
    """A slow crawl delay on one host must not throttle the first request to another."""
    client = paced_client({"slow.test": 10.0, "fast.test": 1.0})
    await client.get("https://slow.test/doc")
    await client.get("https://fast.test/doc")
    assert clock.slept == []


@pytest.mark.anyio
async def test_a_host_with_no_published_delay_is_not_paced(clock: FakeClock) -> None:
    client = paced_client({"slow.test": 10.0})
    await client.get("https://other.test/doc")
    await client.get("https://other.test/doc")
    assert clock.slept == []
