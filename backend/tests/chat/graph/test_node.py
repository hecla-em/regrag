"""The client every chat node calls through."""

from app.chat.graph.node import chat_model
from app.core.config import config


def test_a_thinking_client_reasons_within_its_budget_on_top_of_the_answer_cap(monkeypatch):
    """The provider rejects thinking at any temperature but 1, and counts the reasoning
    against max_tokens, so the answer keeps its own cap."""
    monkeypatch.setattr(config, "CHAT_MAX_TOKENS", 2048)
    monkeypatch.setattr(config, "CHAT_THINKING_BUDGET", 1024)

    client = chat_model(thinking=True)

    assert client.max_tokens == 3072
    assert client.temperature == 1.0
    assert client.model_kwargs == {"thinking": {"type": "enabled", "budget_tokens": 1024}}
