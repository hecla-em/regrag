"""Helpers over plain nested dicts."""

from typing import Any


def flatten_dict(nested: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Nested dicts as one level, each leaf named by its dotted path."""
    flat: dict[str, Any] = {}
    for key, value in nested.items():
        if isinstance(value, dict):
            flat |= flatten_dict(value, f"{prefix}{key}.")
        else:
            flat[f"{prefix}{key}"] = value
    return flat
