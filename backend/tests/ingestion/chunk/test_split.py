"""Text sizing: the cheapest break that fits is tried first, and every piece fits the budget."""

import pytest

from app.ingestion.chunk.split import _pack, _split_table_rows, _split_text


@pytest.mark.parametrize(
    ("pieces", "joiner", "max_chars", "packed"),
    [
        pytest.param(
            ["aaaa", "bbbb", "cccc"],
            "\n",
            9,
            ["aaaa\nbbbb", "cccc"],
            id="neighbours join until the next one would overflow",
        ),
        pytest.param(
            ["aaaa", "bbbb"], "\n", 8, ["aaaa", "bbbb"], id="the joiner counts against the budget"
        ),
        pytest.param(
            ["a", "bbbbbbbb", "c"],
            " ",
            4,
            ["a", "bbbbbbbb", "c"],
            id="the pieces stay in order around one that cannot join",
        ),
    ],
)
def test_pack_joins_neighbours_into_as_few_pieces_as_the_budget_allows(
    pieces: list[str], joiner: str, max_chars: int, packed: list[str]
) -> None:
    assert _pack(pieces, joiner, max_chars) == packed


@pytest.mark.parametrize(
    ("text", "max_chars", "pieces"),
    [
        pytest.param(
            "aaaa\nbbbb\ncccc", 9, ["aaaa\nbbbb", "cccc"], id="line boundaries come first"
        ),
        pytest.param("aaaa\n\nbbbb", 100, ["aaaa\nbbbb"], id="a blank line is dropped"),
        pytest.param(
            "One is here. Two is here. Three.",
            26,
            ["One is here. Two is here.", "Three."],
            id="an overlong line breaks at its sentences",
        ),
        pytest.param(
            "Supercalifragilistic. Ok.",
            10,
            ["Supercalif", "ragilistic", ". Ok."],
            id="a sentence that still does not fit is hard cut",
        ),
        pytest.param(
            "Supercalifragilisticexpialidocious",
            20,
            ["Supercalifragilistic", "expialidocious"],
            id="with no boundary left the text is hard cut",
        ),
    ],
)
def test_text_breaks_at_a_line_then_a_sentence_then_a_hard_cut(
    text: str, max_chars: int, pieces: list[str]
) -> None:
    assert _split_text(text, max_chars) == pieces


@pytest.mark.parametrize(
    ("rows", "max_chars", "pieces"),
    [
        pytest.param(
            (("Fuel", "Factor"), ("A", "1"), ("B", "2"), ("C", "3")),
            20,
            ["Fuel | Factor\nA | 1", "Fuel | Factor\nB | 2", "Fuel | Factor\nC | 3"],
            id="the header leads every piece and is paid for out of each budget",
        ),
        pytest.param(
            (("A" * 30, "B" * 30), ("LNG", "2.75")),
            20,
            ["A" * 20, "A" * 10 + " | " + "B" * 7, "B" * 20, "BBB\nLNG | 2.75"],
            id="a header that eats the budget falls back to splitting as text",
        ),
    ],
)
def test_table_rows_break_on_row_boundaries_under_a_repeated_header(
    rows: tuple[tuple[str, ...], ...], max_chars: int, pieces: list[str]
) -> None:
    assert _split_table_rows(rows, max_chars) == pieces
