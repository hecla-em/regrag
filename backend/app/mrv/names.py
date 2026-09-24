"""THETIS-MRV names as keys store and match them: lower-case words, less a corporate ending."""

import re

CORPORATE_SUFFIXES = frozenset(
    {
        "as",
        "sa",
        "ltd",
        "limited",
        "coltd",
        "inc",
        "corp",
        "co",
        "gmbh",
        "spa",
        "srl",
        "llc",
        "plc",
        "bv",
        "nv",
        "ag",
        "sas",
        "ab",
        "oy",
        "pteltd",
        "sl",
        "ltda",
        "ae",
    }
)
"""Endings a company's registered name carries that a question naming it usually drops,
spelled without the breaks punctuation leaves, so 'A/S' and 'AS' are one ending."""
MAX_SUFFIX_WORDS = 3


def name_words(text: str) -> list[str]:
    """A name or question as keys compare it: lower-case words of letters and digits."""
    return re.findall(r"[a-z0-9]+", text.lower())


def name_key(name: str) -> str:
    return " ".join(name_words(name))


def company_key(name: str) -> str:
    """A company name's words less its corporate ending, like 'carras hellas' for
    'Carras (Hellas) S.A.'."""
    words = name_words(name)
    for size in range(MAX_SUFFIX_WORDS, 0, -1):
        if len(words) > size and "".join(words[-size:]) in CORPORATE_SUFFIXES:
            return " ".join(words[:-size])
    return " ".join(words)
