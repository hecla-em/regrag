"""The CELLAR document endpoint: which version it holds English text for, and how it denies one."""

from pathlib import Path

import httpx
import pytest

from app.core.config import config
from app.ingestion.discover.stage import discover_topics
from app.ingestion.fetch.download import (
    download_fetchable_version,
)

pytestmark = pytest.mark.anyio

FIXTURES = Path(__file__).parent / "fixtures"
DOC_HTML = (FIXTURES / "doc.html").read_text()


def celex_of(request: httpx.Request) -> str:
    """The celex a document request names: the last segment of CELLAR's resource path."""
    return request.url.path.rsplit("/", 1)[-1]


def transport(responses):
    def handler(request):
        return responses[celex_of(request)]

    return httpx.MockTransport(handler)


def missing_response():
    """What CELLAR answers for a version it holds no English text for: a bare 404."""
    return httpx.Response(404, text="")


def queued(responses):
    """Transport answering each request with the next queued response, recording the celexes."""
    calls: list[str] = []

    def handler(request):
        calls.append(celex_of(request))
        return responses.pop(0)

    return httpx.MockTransport(handler), calls


EXPECTED_RESOLVED = {
    "ets:32003L0087": "02003L0087-20240301",
    "ets:32023D2895": "02023D2895-20250101",
    "ets:32023R2297": "32023R2297",
    "ets:32023R2599": "32023R2599",
    "fueleu:32023R1805": "32023R1805",
    "fueleu:32024R2027": "32024R2027",
    "fueleu:32024R2031": "32024R2031",
    "fueleu:32025R0192": "32025R0192",
    "fueleu:32025R1127": "32025R1127",
    "fueleu:32026R0394": "32026R0394",
    "mrv:32015R0757": "02015R0757-20250101",
    "mrv:32016R1928": "32016R1928",
    "mrv:32023R2449": "32023R2449",
    "mrv:32023R2849": "32023R2849",
    "mrv:32023R2917": "32023R2917",
}

MISSING_HTML = {"02023R1805-20230922", "02023R2917-20231229", "02024R2027-20240729"}


def corpus_sparql() -> dict[str, httpx.Response]:
    """The recorded SPARQL response for every topic."""
    return {
        topic: httpx.Response(200, text=(FIXTURES / f"sparql-{topic}.json").read_text())
        for topic in config.TOPIC_BASE_ACTS
    }


def corpus_docs() -> dict[str, httpx.Response]:
    """A 200 for every version CELLAR holds English text for, a 404 for the ids it does not."""
    return {celex: httpx.Response(200, text=DOC_HTML) for celex in EXPECTED_RESOLVED.values()} | {
        celex: missing_response() for celex in MISSING_HTML
    }


@pytest.mark.parametrize("topic", sorted(config.TOPIC_BASE_ACTS))
async def test_every_discovered_document_resolves_to_the_version_cellar_serves(
    topic, corpus_client
):
    """The handshake between the two packages: what discovery points at is what download gets."""
    client, _ = corpus_client(corpus_sparql(), corpus_docs())
    discovered = await discover_topics(client, [topic])
    resolved = {
        f"{topic}:{d.celex}": (await download_fetchable_version(client, d))[0] for d in discovered
    }
    expected = {k: v for k, v in EXPECTED_RESOLVED.items() if k.startswith(f"{topic}:")}
    assert resolved == expected
