"""Formex formula markup as LaTeX: the tags EUR-Lex uses for maths it publishes as text."""

import re
import unicodedata
from itertools import pairwise
from xml.etree.ElementTree import Element

from app.ingestion.exceptions import ParseError

BRACKETS = {
    "BRACKET": ("\\left(", "\\right)"),
    "SQBRACKET": ("\\left[", "\\right]"),
    "BRACE": ("\\left\\{", "\\right\\}"),
    "BAR": ("\\left|", "\\right|"),
}
OPERATORS = {"CARTPROD": "\\times", "PLUS": "+", "MINUS": "-", "MULT": "\\cdot", "DIV": "/"}
COMPARISONS = {"EQ": "=", "LE": "\\leq", "GE": "\\geq", "GT": ">", "LT": "<"}
SYMBOLS = {"∑": "\\sum ", "–": "-", "−": "-", " ": " "}
ESCAPES = {"%": "\\%", "&": "\\&", "#": "\\#", "_": "\\_", "$": "\\$", "{": "\\{", "}": "\\}"}
SCRIPTS = {("IND", ""): "_", ("EXPONENT", ""): "^", ("HT", "SUB"): "_", ("HT", "SUP"): "^"}
PASSTHROUGH_TAGS = {"FORMULA", "DIVIDEND", "DIVISOR", "UNDER", "OVER", "FMT.VALUE"}
PASSTHROUGH_TYPED_TAGS = {("EXPR", ""), ("HT", "ITALIC")}
GREEK_CAPITAL_COMMANDS = {
    "gamma",
    "delta",
    "theta",
    "lambda",
    "xi",
    "pi",
    "sigma",
    "upsilon",
    "phi",
    "psi",
    "omega",
}
GREEK_CAPITAL_LOOKALIKES = {
    "alpha": "A",
    "beta": "B",
    "epsilon": "E",
    "zeta": "Z",
    "eta": "H",
    "iota": "I",
    "kappa": "K",
    "mu": "M",
    "nu": "N",
    "omicron": "O",
    "rho": "P",
    "tau": "T",
    "chi": "X",
}
GREEK_NAME_RE = re.compile(r"GREEK (SMALL|CAPITAL) LETTER (\w+)")
TOKEN_RE = re.compile(r"[A-Za-z]+(?: [A-Za-z]+)*|.", re.DOTALL)
"""A run of words, which LaTeX would set as a product of italic letters, or any one character."""


def greek_command(char: str) -> str | None:
    """The LaTeX command (or Latin look-alike) for a Greek letter, or None for any other
    character, including an accented Greek letter."""
    match = GREEK_NAME_RE.fullmatch(unicodedata.name(char, ""))
    if match is None:
        return None
    case, letter = match[1], match[2].lower().replace("lamda", "lambda")
    if case == "SMALL":
        return letter if letter == "omicron" else "\\" + letter + " "
    if letter in GREEK_CAPITAL_COMMANDS:
        return "\\" + letter.capitalize() + " "
    return GREEK_CAPITAL_LOOKALIKES.get(letter)


def text_to_latex(text: str) -> str:
    """Formex text as LaTeX: words upright in \\text{}, symbols and Greek letters as commands."""
    parts = []
    for token in TOKEN_RE.findall(text):
        if len(token) > 1:
            parts.append(f"\\text{{{token}}}")
        elif token in SYMBOLS:
            parts.append(SYMBOLS[token])
        elif command := greek_command(token):
            parts.append(command)
        elif token in ESCAPES:
            parts.append(ESCAPES[token])
        else:
            parts.append(token)
    return "".join(parts)


def script_symbol(element: Element) -> str | None:
    """The `_`/`^` an IND, EXPONENT, or HT SUP/SUB element sets its children as, or None."""
    return SCRIPTS.get((element.tag, element.get("TYPE", "")))


def element_to_latex(element: Element) -> str:
    """One markup element as LaTeX, subscripts and exponents excepted: children_to_latex
    merges those. Raises ParseError for any tag or TYPE this converter does not know."""
    tag, kind = element.tag, element.get("TYPE", "")
    if tag == "FRACTION":
        dividend = children_to_latex(element.find("DIVIDEND"))
        divisor = children_to_latex(element.find("DIVISOR"))
        return f"\\frac{{{dividend}}}{{{divisor}}}"
    if tag == "SUM":
        under, over = element.find("UNDER"), element.find("OVER")
        lower = f"_{{{children_to_latex(under)}}}" if under is not None else ""
        upper = f"^{{{children_to_latex(over)}}}" if over is not None else ""
        return f"\\sum{lower}{upper}"
    if tag == "OP.MATH" and kind in OPERATORS:
        return f" {OPERATORS[kind]} "
    if tag == "OP.CMP" and kind in COMPARISONS:
        return f" {COMPARISONS[kind]} "
    if tag == "EXPR" and kind in BRACKETS:
        left, right = BRACKETS[kind]
        return f"{left}{children_to_latex(element)}{right}"
    if tag in PASSTHROUGH_TAGS or (tag, kind) in PASSTHROUGH_TYPED_TAGS:
        return children_to_latex(element)
    raise ParseError(f"unknown Formex {tag} type {kind!r}")


def script_runs(element: Element) -> list[list[Element]]:
    """An element's children in runs: adjacent subscripts (or exponents) with only whitespace
    between them share a run, every other child stands alone."""
    runs: list[list[Element]] = []
    for child in element:
        symbol = script_symbol(child)
        previous = runs[-1][-1] if runs else None
        if (
            previous is not None
            and symbol is not None
            and script_symbol(previous) == symbol
            and not (previous.tail or "").strip()
        ):
            runs[-1].append(child)
        else:
            runs.append([child])
    return runs


def children_to_latex(element: Element | None) -> str:
    """An element's text and children as LaTeX, adjacent subscripts (or exponents) merged
    into one."""
    if element is None:
        return ""
    parts = [text_to_latex(element.text or "")]
    for run in script_runs(element):
        symbol = script_symbol(run[0])
        if symbol is None:
            parts.append(element_to_latex(run[0]))
        else:
            body = children_to_latex(run[0]) + "".join(
                ("\\," if previous.tail else "") + children_to_latex(child)
                for previous, child in pairwise(run)
            )
            parts.append(symbol + "{" + body + "}")
        parts.append(text_to_latex(run[-1].tail or ""))
    return "".join(parts).strip()


def formula_to_latex(formula: Element) -> str:
    """A Formex <FORMULA> as one line of LaTeX, without delimiters."""
    return " ".join(children_to_latex(formula).split())
