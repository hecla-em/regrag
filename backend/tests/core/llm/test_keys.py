"""Which key a model call is made with, and the parameters a provider is spared."""

import litellm
import pytest
from litellm.utils import get_optional_params
from pydantic import SecretStr

import app.core.llm  # noqa: F401 — importing the package is what sets litellm's globals
from app.core.config import config
from app.core.llm.keys import api_key_for


@pytest.mark.parametrize(
    ("model", "setting"),
    [
        ("openrouter/google/gemini-2.5-flash", "OPENROUTER_API_KEY"),
        ("openrouter/anthropic/claude-sonnet-5", "OPENROUTER_API_KEY"),
        ("voyage/voyage-4-lite", "VOYAGE_API_KEY"),
        ("voyage/rerank-2.5", "VOYAGE_API_KEY"),
    ],
)
def test_a_model_is_called_with_the_key_of_the_provider_it_names(model, setting, monkeypatch):
    """Which key follows from the model string, so a provider swap is a setting."""
    monkeypatch.setattr(config, setting, SecretStr("sk-for-that-provider"))

    assert api_key_for(model) == "sk-for-that-provider"


def test_an_unset_key_is_passed_as_empty_and_left_for_the_provider_to_refuse(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", SecretStr(""))

    assert api_key_for("openrouter/google/gemini-2.5-flash") == ""


def test_a_provider_with_no_setting_is_a_code_change_and_says_so():
    """Naming a provider directly rather than through OpenRouter needs a key added for it."""
    with pytest.raises(AttributeError, match="ANTHROPIC_API_KEY"):
        api_key_for("anthropic/claude-sonnet-5")


def test_a_parameter_the_model_refuses_is_dropped_rather_than_raised():
    """Without the global, temperature to a frontier Anthropic model raises
    UnsupportedParamsError, so pointing a role there would be a code change."""
    assert litellm.drop_params is True

    sent = get_optional_params(
        model="claude-sonnet-5", custom_llm_provider="anthropic", temperature=0.0, max_tokens=10
    )

    assert sent == {"max_tokens": 10}
