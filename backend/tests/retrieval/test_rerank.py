"""Rerank client: call contract, ordering, and degradation to the fused order."""

import openai
import pytest

from app.retrieval import rerank as rerank_module
from app.retrieval.models import SearchResult
from app.retrieval.rerank import rerank_results
from tests.conftest import search_result

pytestmark = pytest.mark.anyio


def _result(chunk_id: int) -> SearchResult:
    """The chunk_id-th hit of a fused ranking, its score falling with its rank."""
    return search_result(
        id=chunk_id,
        citation=f"Article {chunk_id}",
        article=str(chunk_id),
        text=f"text of chunk {chunk_id}",
        position=chunk_id,
        rrf_score=1.0 / chunk_id,
        vector_rank=chunk_id,
        text_rank=None,
    )


async def test_a_provider_failure_degrades_to_the_fused_order(monkeypatch):
    async def fake_arerank(**kwargs):
        raise openai.OpenAIError("provider rejected the request")

    monkeypatch.setattr(rerank_module.litellm, "arerank", fake_arerank)
    fused = (_result(1), _result(2), _result(3))

    degraded = await rerank_results("q", fused, limit=2)

    assert degraded == fused[:2]
    assert all(result.reranker_relevance is None for result in degraded)
