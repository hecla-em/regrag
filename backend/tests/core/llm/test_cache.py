"""What the call cache caches, and the request parameters it keys on."""

from pathlib import Path

import litellm
import pytest
from litellm.caching import Cache

from app.core.llm.cache import enable_call_cache


@pytest.fixture(autouse=True)
def cache_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point the cache at a throwaway directory and leave litellm as it was found: enabling
    a cache registers callbacks as well as setting one, and neither may outlive its test."""
    directory = tmp_path / "cache"
    monkeypatch.setattr(litellm, "cache", None)
    monkeypatch.setattr(litellm, "enable_caching_on_provider_specific_optional_params", False)
    for callbacks in ("input_callback", "success_callback", "_async_success_callback"):
        monkeypatch.setattr(litellm, callbacks, list(getattr(litellm, callbacks)))
    return directory


@pytest.fixture
def cache(cache_dir: Path) -> Cache:
    """A cache installed as the evals CLI installs one."""
    enable_call_cache(cache_dir)
    assert isinstance(litellm.cache, Cache)
    return litellm.cache


EMBED_CALL = {
    "model": "voyage/voyage-4-lite",
    "input": ["which vessels?"],
    "dimensions": 1024,
    "input_type": "query",
    "timeout": 5,
}


@pytest.mark.parametrize(
    "changed",
    [
        pytest.param({"input": ["another question"]}, id="query"),
        pytest.param({"model": "voyage/voyage-3"}, id="model"),
        pytest.param({"input_type": "document"}, id="input-type"),
    ],
)
def test_an_embed_key_covers_the_model_the_query_and_the_input_type(
    changed: dict[str, object], cache: Cache
) -> None:
    """input_type is Voyage's own parameter, and litellm leaves those out of the key unless
    told otherwise: without it a document vector would answer for an identical query."""
    assert cache.get_cache_key(**EMBED_CALL) != cache.get_cache_key(**{**EMBED_CALL, **changed})
