"""CELEX ids: the EU's identity scheme for legal acts, read and written in one place."""

import re

from app.core.clock import utc_today

LEGISLATION = "3"
CONSOLIDATED = "0"
CENTURIES = ("19", "20")
LENGTH = 10
KIND_LETTERS = {"regulation": "R", "directive": "L", "decision": "D"}
KIND_NAMES = {letter: kind.capitalize() for kind, letter in KIND_LETTERS.items()}
YEAR_FIRST_KINDS = ("directive", "decision")
"""Numbered year-first in every era; only regulations ever led with the act number."""
YEAR_FIRST_SCHEME = 2015
"""The year from which regulations too are numbered year-first."""
CITED_NAME_RE = re.compile(
    r"^(?:(?:Commission|Council) )?(?:(?:Implementing|Delegated) )?"
    r"(?P<name>(?:Regulation|Directive|Decision) (?:\([^)]+\) )?(?:No )?\d+/\d+(?:/[A-Za-z]+)?)\b"
)
"""The citation an official title opens with, less the author: 'Directive 2003/87/EC'."""


def expand_year(value: str) -> str:
    """Two-digit years in older citations are 20th century: '92' -> '1992'."""
    return f"19{value}" if len(value) == 2 else value


def as_year(value: str) -> int | None:
    """The year a citation fragment denotes, or None if it can only be an act number."""
    year = expand_year(value)
    if len(year) != 4 or year[:2] not in CENTURIES or int(year) > utc_today().year:
        return None
    return int(year)


def order_number_and_year(kind: str, first: str, second: str) -> tuple[str, str]:
    """A '765/2008' pair as (number, year): the half that cannot be a year is the number.

    Where both halves could be years the kind settles it, since only regulations were ever
    number-first, and only until the 2015 scheme. A pair that is neither is left as written
    for build to reject.
    """
    leading, trailing = as_year(first), as_year(second)
    if leading is None or trailing is None:
        return (first, second) if trailing else (second, first)
    if kind.lower() in YEAR_FIRST_KINDS or leading >= YEAR_FIRST_SCHEME:
        return second, first
    return first, second


def build(kind: str, year: str, number: str) -> str:
    """A legislation id: sector, year, kind letter, then zero-padded number."""
    celex = f"{LEGISLATION}{expand_year(year)}{KIND_LETTERS[kind.lower()]}{number.zfill(4)}"
    if as_year(year) is None or not is_legislation(celex):
        raise ValueError(f"not a legislation citation: {kind} {number}/{year}")
    return celex


def is_legislation(celex: str) -> bool:
    """Whether an id names a regulation, directive or decision: sector, year, kind, number."""
    return (
        celex.startswith(LEGISLATION)
        and len(celex) == LENGTH
        and celex[1:5].isdigit()
        and celex[5] in KIND_LETTERS.values()
        and celex[6:].isdigit()
    )


def format_act_name(celex: str, title: str | None = None) -> str:
    """An act as it is cited: 'Regulation (EU) 2023/1805'. Acts numbered before the year-first
    scheme need the treaty era they were made under, so are read off their official title,
    and left as their id without one."""
    if not is_legislation(celex):
        return celex
    if int(celex[1:5]) >= YEAR_FIRST_SCHEME:
        return f"{KIND_NAMES[celex[5]]} (EU) {celex[1:5]}/{int(celex[6:])}"
    cited = CITED_NAME_RE.match(title or "")
    return cited.group("name") if cited else celex


def consolidated_stem(celex: str) -> str:
    """Prefix shared by every consolidated version of an act: 32015R0757 -> 02015R0757-."""
    return f"{CONSOLIDATED}{celex[1:]}-"
