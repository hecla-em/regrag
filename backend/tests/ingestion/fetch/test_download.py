"""The CELLAR document endpoint: which version it holds English text for, and how it denies one."""

from pathlib import Path

import httpx
import pytest

from app.core.config import config
from app.ingestion.discover.stage import discover_topics
from app.ingestion.exceptions import NoFetchableVersionError
from app.ingestion.fetch.download import (
    DOCUMENT_HEADERS,
    DOCUMENT_URL_TEMPLATE,
    _is_version_missing,
    download_fetchable_version,
)
from tests.conftest import discovered_document

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


def doc_response():
    return httpx.Response(200, text=DOC_HTML)


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


def test_404_is_missing():
    assert _is_version_missing(missing_response())


def test_served_document_is_not_missing():
    assert not _is_version_missing(doc_response())


async def test_asks_cellar_for_the_english_xhtml_of_the_version():
    """The URL names the version; the headers pick the English XHTML manifestation."""
    requests: list[httpx.Request] = []

    def handler(request):
        requests.append(request)
        return doc_response()

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await download_fetchable_version(client, discovered_document(celex="32023R2449"))
    (request,) = requests
    assert str(request.url) == DOCUMENT_URL_TEMPLATE.format(celex="32023R2449")
    assert request.url.host == "publications.europa.eu"
    assert request.headers["Accept"] == DOCUMENT_HEADERS["Accept"] == "application/xhtml+xml"
    assert request.headers["Accept-Language"] == DOCUMENT_HEADERS["Accept-Language"] == "eng"


async def test_downloads_candidate_when_html_exists():
    responses = {"02015R0757-20250101": doc_response()}
    async with httpx.AsyncClient(transport=transport(responses)) as client:
        resolved_celex, content = await download_fetchable_version(
            client, discovered_document(candidates=("02015R0757-20250101",))
        )
    assert resolved_celex == "02015R0757-20250101"
    assert content == DOC_HTML.encode()


async def test_the_served_body_comes_back_so_the_caller_need_not_ask_again():
    """The point of the tuple: one GET per document, not one to check and one to download."""
    calls: list[str] = []

    def handler(request):
        calls.append(str(request.url))
        return doc_response()

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        document = discovered_document(celex="32023R2449")
        _, content = await download_fetchable_version(client, document)
    assert content == DOC_HTML.encode()
    assert len(calls) == 1


async def test_falls_back_to_celex_on_404():
    responses = {"02023R2917-20231229": missing_response(), "32023R2917": doc_response()}
    async with httpx.AsyncClient(transport=transport(responses)) as client:
        resolved_celex, _ = await download_fetchable_version(
            client, discovered_document(celex="32023R2917", candidates=("02023R2917-20231229",))
        )
    assert resolved_celex == "32023R2917"


async def test_no_candidate_downloads_the_celex_directly():
    responses = {"32023R2449": doc_response()}
    async with httpx.AsyncClient(transport=transport(responses)) as client:
        document = discovered_document(celex="32023R2449")
        resolved_celex, _ = await download_fetchable_version(client, document)
    assert resolved_celex == "32023R2449"


async def test_raises_when_all_candidates_missing():
    responses = {"02023R2917-20231229": missing_response(), "32023R2917": missing_response()}
    async with httpx.AsyncClient(transport=transport(responses)) as client:
        with pytest.raises(NoFetchableVersionError, match="32023R2917"):
            await download_fetchable_version(
                client, discovered_document(celex="32023R2917", candidates=("02023R2917-20231229",))
            )


async def test_a_denied_candidate_is_not_requested_again_when_a_later_one_retries():
    """The retry covers one request: restarting the loop re-asks for a version already denied."""
    handler, calls = queued([missing_response(), httpx.Response(503), doc_response()])
    async with httpx.AsyncClient(transport=handler) as client:
        resolved_celex, _ = await download_fetchable_version(
            client, discovered_document(celex="32023R2917", candidates=("02023R2917-20231229",))
        )
    assert resolved_celex == "32023R2917"
    assert calls == ["02023R2917-20231229", "32023R2917", "32023R2917"]


async def test_unexpected_error_status_raises():
    responses = {"32023R2449": httpx.Response(503, text="maintenance")}
    async with httpx.AsyncClient(transport=transport(responses)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await download_fetchable_version(client, discovered_document(celex="32023R2449"))


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
