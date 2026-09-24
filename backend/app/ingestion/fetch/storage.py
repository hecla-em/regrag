"""Where a fetched document's bytes live: the only module that reads or writes them."""

import hashlib
import re

from app.core.storage import ObjectStore, StorageError
from app.ingestion.exceptions import EmptyDownloadError
from app.ingestion.fetch.schemas import RawDocument


class StoredBytesMismatchError(StorageError):
    """The object at a document's key is not the one the row recorded."""


HTML_EXTENSION = "html"
FORMEX_EXTENSION = "fmx4.zip"


def object_key(celex: str, resolved_celex: str, sha256: str, extension: str) -> str:
    """Where a version's bytes live, keyed by content so a new version never overwrites a
    version an earlier parse ran against."""
    return f"{celex}/{resolved_celex}/{sha256}.{extension}"


def _store_hashed(
    store: ObjectStore, celex: str, resolved_celex: str, content: bytes, extension: str
) -> str:
    """Store a version's bytes under their content key and return their sha256, refusing empty
    content so a failed download cannot be recorded as a version."""
    if not content:
        raise EmptyDownloadError(f"{celex}: download returned an empty body")
    sha256 = hashlib.sha256(content).hexdigest()
    store.put(object_key(celex, resolved_celex, sha256, extension), content)
    return sha256


def _read_verified(store: ObjectStore, document: RawDocument, sha256: str, extension: str) -> bytes:
    """The bytes stored for a document, refusing any that are not the ones the row recorded."""
    key = object_key(document.celex, document.resolved_celex, sha256, extension)
    content = store.get(key)
    if hashlib.sha256(content).hexdigest() != sha256:
        raise StoredBytesMismatchError("verify", key, "stored bytes do not match the recorded hash")
    return content


SCRIPT_RE = re.compile(rb"<script\b[^>]*>.*?</script\s*>", re.DOTALL | re.IGNORECASE)
"""Cut out rather than parsed out, so every other byte of the document survives untouched;
a parser round trip would rewrite the markup around them. Scripts cannot nest, and an
unescaped </script> inside one is not legal HTML, so the non-greedy match is exact."""


def remove_scripts(html: bytes) -> bytes:
    """Drop script tags: EUR-Lex stamps a per-request analytics id into every response, so the
    same law downloads as different bytes each time and lands under a different content key."""
    return SCRIPT_RE.sub(b"", html)


def write_document(
    store: ObjectStore, celex: str, resolved_celex: str, html: bytes
) -> tuple[str, int]:
    """Store the document's bytes and return their (sha256, size_bytes).

    What is hashed is what is stored, because read_document re-hashes the object it fetched.
    """
    stored = remove_scripts(html)
    return _store_hashed(store, celex, resolved_celex, stored, HTML_EXTENSION), len(stored)


def read_document(store: ObjectStore, document: RawDocument) -> bytes:
    """The bytes stored for a document, refusing any that are not the ones the row recorded.

    The row and the object are backed up separately, so a restore can leave them disagreeing;
    the reuse path treats that as bytes it does not have and downloads the version again.
    """
    return _read_verified(store, document, document.sha256, HTML_EXTENSION)


def write_formex(store: ObjectStore, celex: str, resolved_celex: str, formex: bytes) -> str:
    """Store a version's Formex zip beside its XHTML and return its sha256."""
    return _store_hashed(store, celex, resolved_celex, formex, FORMEX_EXTENSION)


def read_formex(store: ObjectStore, document: RawDocument) -> bytes | None:
    """The Formex zip stored for a document, None where the row records none."""
    if document.formex_sha256 is None:
        return None
    return _read_verified(store, document, document.formex_sha256, FORMEX_EXTENSION)
