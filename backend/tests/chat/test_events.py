"""Sources events: what a retrieved chunk reads as once a stream reports it."""

import pytest

from app.chat.events import ChatSource
from tests.conftest import retrieved_chunk


@pytest.mark.parametrize(
    ("celex", "title", "expected"),
    [
        ("32023R1805", None, "Regulation (EU) 2023/1805"),
        ("32003L0087", "Directive 2003/87/EC of 13 October 2003", "Directive 2003/87/EC"),
        ("31992L0043", None, "31992L0043"),
    ],
)
def test_a_source_names_the_act_it_came_from(celex: str, title: str | None, expected: str) -> None:
    source = ChatSource.from_result(3, retrieved_chunk(celex=celex, act_title=title))
    assert source.celex == celex
    assert source.act == expected
