"""Helpers over plain nested dicts."""

from app.core.mappings import flatten_dict


def test_nested_dicts_flatten_to_dotted_paths():
    nested = {"a": 1, "b": {"c": None, "d": {"e": True}}, "f": {}}

    assert flatten_dict(nested) == {"a": 1, "b.c": None, "b.d.e": True}
