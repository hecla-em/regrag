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


@pytest.mark.parametrize(
    ("answers", "calls_made", "succeeds"),
    [
        pytest.param([503, 200], 2, True, id="a retryable status is retried"),
        pytest.param([httpx.ConnectError("refused"), 200], 2, True, id="so is a transport error"),
        pytest.param([503, 503, 503], 3, False, id="three attempts and no more"),
        pytest.param([404], 1, False, id="a client error is not retried"),
    ],
)
def test_which_failures_are_retried(get, answers, calls_made, succeeds):
    queued = [a if isinstance(a, Exception) else httpx.Response(a, text="ok") for a in answers]
    client, calls = flaky_client(queued)

    if succeeds:
        assert get(client).text == "ok"
    else:
        with pytest.raises(httpx.HTTPStatusError):
            get(client)
    assert len(calls) == calls_made


def paced_client(delays: dict[str, float]) -> httpx.AsyncClient:
    """A client whose requests are paced per host and answered locally."""
    return httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200)),
        event_hooks={"request": [pace_requests(delays)]},
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("gaps", "slept"),
    [
        pytest.param([], [], id="the first request goes straight through"),
        pytest.param([0.0, 0.0], [1.0, 1.0], id="every request waits, not every document"),
        pytest.param([0.4], [0.6], id="only what is left of the interval is waited"),
        pytest.param([5.0], [], id="an interval already passed is not waited"),
    ],
)
async def test_pacing_waits_out_the_interval_between_requests_to_a_host(
    clock: FakeClock, gaps: list[float], slept: list[float]
) -> None:
    client = paced_client({"example.test": 1.0})
    await client.get("https://example.test/doc")
    for gap in gaps:
        clock.now += gap
        await client.get("https://example.test/doc")

    assert clock.slept == pytest.approx(slept)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("hosts", "clients"),
    [
        pytest.param(["slow.test", "slow.test"], 2, id="one client never delays another"),
        pytest.param(["slow.test", "fast.test"], 1, id="one host never delays another"),
        pytest.param(["other.test", "other.test"], 1, id="a host with no published delay"),
    ],
)
async def test_pacing_is_kept_per_client_and_per_listed_host(
    clock: FakeClock, hosts: list[str], clients: int
) -> None:
    paced = [paced_client({"slow.test": 10.0, "fast.test": 1.0}) for _ in range(clients)]

    for index, host in enumerate(hosts):
        await paced[index % clients].get(f"https://{host}/doc")

    assert clock.slept == []
