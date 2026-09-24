"""Formex formula markup as LaTeX: the tags EUR-Lex uses for maths it publishes as text."""

import re
import unicodedata
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
SCRIPTS = {"IND": "_", "EXPONENT": "^"}
TOKEN_RE = re.compile(r"[A-Za-z]+(?: [A-Za-z]+)*|.", re.DOTALL)
"""A run of words, which LaTeX would set as a product of italic letters, or any one character."""


def greek_command(char: str) -> str | None:
    """The LaTeX command for a Greek letter, or None for any other character."""
    if len(char) != 1:
        return None
    name = unicodedata.name(char, "")
    for prefix, capital in (("GREEK SMALL LETTER ", False), ("GREEK CAPITAL LETTER ", True)):
        if name.startswith(prefix):
            letter = name.removeprefix(prefix).lower().replace("lamda", "lambda")
            return "\\" + (letter.capitalize() if capital else letter) + " "
    return None


def text_to_latex(text: str) -> str:
    """Formex text as LaTeX: words upright in \\text{}, symbols and Greek letters as commands."""
    parts = []
    for token in TOKEN_RE.findall(text):
        if token in SYMBOLS:
            parts.append(SYMBOLS[token])
        elif command := greek_command(token):
            parts.append(command)
        elif token in ESCAPES:
            parts.append(ESCAPES[token])
        elif len(token) > 1:
            parts.append(f"\\text{{{token}}}")
        else:
            parts.append(token)
    return "".join(parts)


def element_to_latex(element: Element) -> str:
    """One markup element as LaTeX, subscripts and exponents excepted: children_to_latex
    merges those."""
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
    if tag == "OP.MATH":
        if kind not in OPERATORS:
            raise ParseError(f"unknown Formex {tag} type {kind}")
        return f" {OPERATORS[kind]} "
    if tag == "OP.CMP":
        if kind not in COMPARISONS:
            raise ParseError(f"unknown Formex {tag} type {kind}")
        return f" {COMPARISONS[kind]} "
    if tag == "EXPR" and kind in BRACKETS:
        left, right = BRACKETS[kind]
        return f"{left}{children_to_latex(element)}{right}"
    return children_to_latex(element)


def children_to_latex(element: Element | None) -> str:
    """An element's text and children as LaTeX, adjacent subscripts (or exponents) merged
    into one."""
    if element is None:
        return ""
    parts = [text_to_latex(element.text or "")]
    children = list(element)
    index = 0
    while index < len(children):
        child = children[index]
        if child.tag in SCRIPTS:
            body = children_to_latex(child)
            while (
                not (child.tail or "").strip()
                and index + 1 < len(children)
                and children[index + 1].tag == child.tag
            ):
                separator = "\\," if child.tail else ""
                index += 1
                child = children[index]
                body += separator + children_to_latex(child)
            parts.append(SCRIPTS[child.tag] + "{" + body + "}")
        else:
            parts.append(element_to_latex(child))
        parts.append(text_to_latex(child.tail or ""))
        index += 1
    return "".join(parts).strip()


def formula_to_latex(formula: Element) -> str:
    """A Formex <FORMULA> as one line of LaTeX, without delimiters."""
    return " ".join(children_to_latex(formula).split())
