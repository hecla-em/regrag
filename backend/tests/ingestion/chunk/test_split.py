from app.ingestion.chunk.split import (
    _pack,
    _split_on_sentences,
    _split_table_rows,
    _split_text,
)


def test_pack_joins_neighbours_until_the_next_one_would_overflow() -> None:
    assert _pack(["aaaa", "bbbb", "cccc"], "\n", 9) == ["aaaa\nbbbb", "cccc"]


def test_pack_counts_the_joiner_against_the_budget() -> None:
    assert _pack(["aaaa", "bbbb"], "\n", 8) == ["aaaa", "bbbb"]


def test_pack_keeps_the_pieces_in_order() -> None:
    assert _pack(["a", "bbbbbbbb", "c"], " ", 4) == ["a", "bbbbbbbb", "c"]


def test_split_on_sentences_hard_cuts_a_sentence_that_still_does_not_fit() -> None:
    assert _split_on_sentences("Supercalifragilistic. Ok.", 10) == [
        "Supercalif",
        "ragilistic",
        ". Ok.",
    ]


def test_split_text_prefers_line_boundaries() -> None:
    assert _split_text("aaaa\nbbbb\ncccc", 9) == ["aaaa\nbbbb", "cccc"]


def test_split_text_falls_back_to_sentence_boundaries_inside_an_overlong_line() -> None:
    assert _split_text("One is here. Two is here. Three.", 26) == [
        "One is here. Two is here.",
        "Three.",
    ]


def test_split_text_falls_back_to_a_hard_cut_when_no_boundary_is_left() -> None:
    assert _split_text("Supercalifragilisticexpialidocious", 20) == [
        "Supercalifragilistic",
        "expialidocious",
    ]


def test_split_text_drops_blank_lines() -> None:
    assert _split_text("aaaa\n\nbbbb", 100) == ["aaaa\nbbbb"]


def test_split_text_stays_within_the_limit_whatever_the_text() -> None:
    assert max(len(piece) for piece in _split_text("word " * 400, 100)) <= 100


def test_split_table_rows_repeats_the_header_on_every_piece() -> None:
    rows = (("Fuel", "Factor"),) + tuple((f"Fuel{n}", f"{n}.0") for n in range(12))
    pieces = _split_table_rows(rows, 60)
    assert len(pieces) > 1
    assert all(piece.startswith("Fuel | Factor\n") for piece in pieces)


def test_split_table_rows_spends_the_repeated_header_out_of_every_piece_budget() -> None:
    """A 13-char header plus its newline leaves 6 of a 20-char budget, so no two rows pair up."""
    rows = (("Fuel", "Factor"), ("A", "1"), ("B", "2"), ("C", "3"))
    assert _split_table_rows(rows, 20) == [
        "Fuel | Factor\nA | 1",
        "Fuel | Factor\nB | 2",
        "Fuel | Factor\nC | 3",
    ]


def test_split_table_rows_falls_back_to_text_when_the_header_leaves_no_budget() -> None:
    rows = (("A" * 30, "B" * 30), ("LNG", "2.75"))
    pieces = _split_table_rows(rows, 20)
    assert max(len(piece) for piece in pieces) <= 20
