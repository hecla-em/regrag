"""Voyage embedding client: call contract, ordering, error sanitisation, and the transience
the wrap point stamps on each failure."""

import json
from types import SimpleNamespace

import httpx
import litellm
import openai
import pytest

from app.core.config import config
from app.core.llm.embed import EmbedInput, embed
from app.core.llm.errors import LLMError
from tests.conftest import provider_error

pytestmark = pytest.mark.anyio


def _response(vectors: list[list[float]]) -> SimpleNamespace:
    return SimpleNamespace(
        data=[{"embedding": vector, "index": i} for i, vector in enumerate(vectors)]
    )


async def test_embed_reorders_shuffled_response_by_index(monkeypatch):
    async def fake_aembedding(**kwargs):
        n = len(kwargs["input"])
        data = [{"embedding": [float(i)], "index": i} for i in reversed(range(n))]
        return SimpleNamespace(data=data)

    monkeypatch.setattr(litellm, "aembedding", fake_aembedding)

    result = await embed(["a", "b", "c"], input_type=EmbedInput.DOCUMENT)

    assert result == [[0.0], [1.0], [2.0]]


async def test_a_response_short_of_its_inputs_is_a_failed_call_not_worth_retrying(monkeypatch):
    async def fake_aembedding(**kwargs):
        return _response([[0.0]])

    monkeypatch.setattr(litellm, "aembedding", fake_aembedding)

    with pytest.raises(LLMError) as caught:
        await embed(["a", "b", "c"], input_type=EmbedInput.DOCUMENT)
    assert caught.value.transient is False


async def test_embed_sends_voyage_request_body_and_auth_header(monkeypatch):
    """One integration-shaped check of the real request litellm builds for Voyage."""
    from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler

    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        n = len(captured["body"]["input"])
        payload = {
            "object": "list",
            "data": [{"object": "embedding", "index": i, "embedding": [0.1]} for i in range(n)],
            "model": captured["body"]["model"],
            "usage": {"total_tokens": 7},
        }
        return httpx.Response(200, json=payload, request=request)

    transport = httpx.MockTransport(handler)
    original_init = AsyncHTTPHandler.__init__

    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.client = httpx.AsyncClient(transport=transport)

    monkeypatch.setattr(AsyncHTTPHandler, "__init__", patched_init)
    litellm.in_memory_llm_clients_cache.flush_cache()

    result = await embed(["alpha", "beta"], input_type=EmbedInput.QUERY)

    assert result == [[0.1], [0.1]]
    assert captured["body"]["input"] == ["alpha", "beta"]
    assert captured["body"]["model"] == "voyage-4-lite"
    assert captured["body"]["output_dimension"] == 1024
    assert captured["body"]["input_type"] == "query"
    assert "num_retries" not in captured["body"]
    assert (
        captured["headers"]["authorization"] == f"Bearer {config.VOYAGE_API_KEY.get_secret_value()}"
    )

    litellm.in_memory_llm_clients_cache.flush_cache()


@pytest.mark.parametrize(
    ("exc_type", "status_code", "transient"),
    [
        (openai.RateLimitError, 429, True),
        (openai.InternalServerError, 500, True),
        (openai.APITimeoutError, None, True),
        (openai.APIConnectionError, None, True),
        (openai.AuthenticationError, 401, False),
        (openai.BadRequestError, 400, False),
        (openai.NotFoundError, 404, False),
    ],
)
async def test_a_provider_failure_is_wrapped_without_its_text_and_flagged_if_worth_retrying(
    monkeypatch, exc_type, status_code, transient
):
    said = None if exc_type is openai.APITimeoutError else "refused by voyageai.com upstream"

    async def fake_aembedding(**kwargs):
        raise provider_error(exc_type, status_code, message=said)

    monkeypatch.setattr(litellm, "aembedding", fake_aembedding)

    with pytest.raises(LLMError) as caught:
        await embed(["a chunk"], input_type=EmbedInput.DOCUMENT)

    assert str(caught.value) == "embedding call failed"
    assert caught.value.transient is transient
