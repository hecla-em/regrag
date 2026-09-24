"""The formulas a Formex zip publishes, one replacement per inline image the XHTML draws."""

import io
import re
import zipfile
from xml.etree import ElementTree

from app.ingestion.exceptions import ParseError
from app.ingestion.parse.formex.latex import formula_to_latex
from app.ingestion.parse.html.text import FORMULA_PLACEHOLDER

MANIFEST_SUFFIX = ".doc.xml"
MANIFEST_FILE_RE = re.compile(r'FILE="([^"]+\.xml)"')
INCLUSIONS_RE = re.compile(r"<INCLUSIONS>.*?</INCLUSIONS>", re.DOTALL)
"""The header's list of every image file, which repeats each image the body places."""
FORMULA_OR_IMAGE_RE = re.compile(r"<FORMULA\b.*?</FORMULA>|<INCL\.ELEMENT\b[^>]*>", re.DOTALL)
FORMULA_IMAGE_RE = re.compile(r'CONTENT="FORMULA"')


def document_files(archive: zipfile.ZipFile) -> list[str]:
    """The zip's body files in the order its manifest lists them."""
    names = set(archive.namelist())
    manifest = next((name for name in names if name.endswith(MANIFEST_SUFFIX)), None)
    if manifest is None:
        raise ParseError("Formex zip has no manifest")
    listed = MANIFEST_FILE_RE.findall(archive.read(manifest).decode("utf-8"))
    return [name for name in listed if name in names and not name.endswith(MANIFEST_SUFFIX)]


def replacement_for(block: str) -> str:
    """What the XHTML's image becomes: its formula as $$latex$$, [formula] for a drawn one, or
    nothing."""
    if block.startswith("<FORMULA"):
        return f"$${formula_to_latex(ElementTree.fromstring(block))}$$"
    return FORMULA_PLACEHOLDER if FORMULA_IMAGE_RE.search(block) else ""


def read_formex_formulas(formex: bytes) -> tuple[str, ...]:
    """One replacement per formula or image in the Formex, in document order."""
    with zipfile.ZipFile(io.BytesIO(formex)) as archive:
        bodies = [archive.read(name).decode("utf-8") for name in document_files(archive)]
    return tuple(
        replacement_for(block)
        for body in bodies
        for block in FORMULA_OR_IMAGE_RE.findall(INCLUSIONS_RE.sub("", body))
    )
