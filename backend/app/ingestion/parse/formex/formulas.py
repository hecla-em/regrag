"""The formulas a Formex zip publishes, one replacement per inline image the XHTML draws."""

import io
import zipfile
import zlib
from collections.abc import Iterator
from xml.etree import ElementTree
from xml.etree.ElementTree import Element

from app.ingestion.exceptions import ParseError
from app.ingestion.parse.formex.latex import formula_to_latex
from app.ingestion.parse.models import FORMULA_PLACEHOLDER

MANIFEST_SUFFIX = ".doc.xml"
INCLUSIONS_TAG = "INCLUSIONS"
"""The header's list of every image file, which repeats each image the body places."""
FORMEX_READ_ERRORS = (
    zipfile.BadZipFile,
    NotImplementedError,
    RuntimeError,
    zlib.error,
    EOFError,
    ElementTree.ParseError,
)


def document_roots(archive: zipfile.ZipFile) -> list[Element]:
    """The zip's body files, parsed, in the order its manifest lists them."""
    names = set(archive.namelist())
    manifest = next((name for name in names if name.endswith(MANIFEST_SUFFIX)), None)
    if manifest is None:
        raise ParseError("Formex zip has no manifest")
    listed = [
        element.get("FILE", "")
        for element in ElementTree.fromstring(archive.read(manifest)).iter()
        if element.get("FILE", "").endswith(".xml")
    ]
    return [
        ElementTree.fromstring(archive.read(name))
        for name in listed
        if name in names and not name.endswith(MANIFEST_SUFFIX)
    ]


def image_replacements(element: Element) -> Iterator[str]:
    """What each of the XHTML's images becomes, in document order: its formula as $$latex$$,
    [formula] for a drawn one, or nothing."""
    for child in element:
        if child.tag == INCLUSIONS_TAG:
            continue
        if child.tag == "FORMULA":
            yield f"$${formula_to_latex(child)}$$"
        elif child.tag == "INCL.ELEMENT":
            yield FORMULA_PLACEHOLDER if child.get("CONTENT") == "FORMULA" else ""
        else:
            yield from image_replacements(child)


def read_formex_formulas(formex: bytes) -> tuple[str, ...]:
    """One replacement per formula or image in the Formex, in document order."""
    try:
        with zipfile.ZipFile(io.BytesIO(formex)) as archive:
            roots = document_roots(archive)
    except FORMEX_READ_ERRORS as exc:
        raise ParseError(f"Formex zip could not be read: {exc}") from exc
    return tuple(replacement for root in roots for replacement in image_replacements(root))
