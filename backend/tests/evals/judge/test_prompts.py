"""The turns each judge dimension is shown."""

from app.evals.judge.prompts import (
    build_correctness_message,
    build_faithfulness_message,
    format_cited_blocks,
)
from tests.conftest import retrieved_chunk


def test_the_correctness_turn_carries_the_reference_and_the_answer() -> None:
    message = build_correctness_message("q?", "Half of it.", "All of it.")

    assert "Question: q?" in message
    assert "Reference answer:\nHalf of it." in message
    assert "Answer:\nAll of it." in message


def test_cited_blocks_keep_the_markers_the_answer_used() -> None:
    """A [3] in the answer must be a [3] in what the judge reads, or the judge cannot tell
    which block a claim leans on; the uncited [2] is left out."""
    sources = (
        retrieved_chunk(id=1, text="first"),
        retrieved_chunk(id=2, text="second"),
        retrieved_chunk(id=3, text="third", citation="Article 5"),
    )

    blocks = format_cited_blocks("So [3] and also [1].", sources)

    assert blocks.startswith("[3] (Regulation (EU) 2023/1805, Article 5)\nthird")
    assert "[1] (" in blocks
    assert "second" not in blocks


def test_a_marker_addressing_no_block_is_skipped() -> None:
    assert format_cited_blocks("See [7].", (retrieved_chunk(),)) == ""


def test_the_faithfulness_turn_puts_the_cited_context_before_the_answer() -> None:
    message = build_faithfulness_message("Yes [1].", (retrieved_chunk(text="the rule"),))

    assert message.index("the rule") < message.index("Answer:\nYes [1].")
