"""The client every chat node calls through."""

from pydantic import SecretStr

from app.chat.graph.node import chat_model
from app.core.config import config


def test_the_client_carries_the_chat_settings(monkeypatch):
    monkeypatch.setattr(config, "CHAT_MODEL", "openrouter/openai/gpt-5")
    monkeypatch.setattr(config, "CHAT_MAX_TOKENS", 321)
    monkeypatch.setattr(config, "CHAT_TIMEOUT", 21)

    client = chat_model(streaming=False)

    assert client.model == "openrouter/openai/gpt-5"
    assert client.max_tokens == 321
    assert client.request_timeout == 21
    assert client.temperature == config.CHAT_TEMPERATURE
    assert client.streaming is False


def test_the_client_carries_the_key_of_the_provider_the_model_names(monkeypatch):
    """A model at another provider must work as a setting, so the key is looked up from the
    model rather than pinned to one provider's variable."""
    monkeypatch.setattr(config, "CHAT_MODEL", "openrouter/openai/gpt-5")
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", SecretStr("sk-openrouter"))

    assert chat_model().api_key == "sk-openrouter"


def test_the_answer_streams_and_asks_for_its_usage():
    """litellm strips usage from every streamed chunk unless asked, and the run's tokens
    then go unreported for any model but an OpenAI one."""
    client = chat_model()

    assert client.streaming is True
    assert client.stream_options == {"include_usage": True}


def test_a_thinking_client_reasons_within_its_budget_on_top_of_the_answer_cap(monkeypatch):
    """The provider rejects thinking at any temperature but 1, and counts the reasoning
    against max_tokens, so the answer keeps its own cap."""
    monkeypatch.setattr(config, "CHAT_MAX_TOKENS", 2048)
    monkeypatch.setattr(config, "CHAT_THINKING_BUDGET", 1024)

    client = chat_model(thinking=True)

    assert client.max_tokens == 3072
    assert client.temperature == 1.0
    assert client.model_kwargs == {"thinking": {"type": "enabled", "budget_tokens": 1024}}


def test_a_client_without_thinking_asks_for_none():
    assert "thinking" not in chat_model().model_kwargs
