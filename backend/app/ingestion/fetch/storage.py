"""Where a fetched document's bytes live: the only module that reads or writes them."""

import hashlib
import re

from app.core.storage import ObjectStore, StorageError
from app.ingestion.exceptions import EmptyDownloadError
from app.ingestion.fetch.schemas import RawDocument


class StoredBytesMismatchError(StorageError):
    """The object at a document's key is not the one the row recorded."""


def document_key(celex: str, resolved_celex: str, sha256: str) -> str:
    """Where a document's bytes live, keyed by content so a new version never overwrites a
    version an earlier parse ran against."""
    return f"{celex}/{resolved_celex}/{sha256}.html"


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
    """Store the document's bytes and return their (sha256, size_bytes), refusing empty
    content so a failed download cannot be recorded as a version.

    What is hashed is what is stored, because read_document re-hashes the object it fetched.
    """
    if not html:
        raise EmptyDownloadError(f"{celex}: download returned an empty body")
    stored = remove_scripts(html)
    sha256 = hashlib.sha256(stored).hexdigest()
    store.put(document_key(celex, resolved_celex, sha256), stored)
    return sha256, len(stored)


def read_document(store: ObjectStore, document: RawDocument) -> bytes:
    """The bytes stored for a document, refusing any that are not the ones the row recorded.

    The row and the object are backed up separately, so a restore can leave them disagreeing;
    the reuse path treats that as bytes it does not have and downloads the version again.
    """
    key = document_key(document.celex, document.resolved_celex, document.sha256)
    html = store.get(key)
    if hashlib.sha256(html).hexdigest() != document.sha256:
        raise StoredBytesMismatchError("verify", key, "stored bytes do not match the recorded hash")
    return html


INLINE_IMAGE = b'src="data:image'
"""How the XHTML inlines a drawn formula; only a version with one needs its Formex."""


def needs_formex(html: bytes) -> bool:
    """Whether the XHTML draws an inline image, whose formula only Formex carries as markup."""
    return INLINE_IMAGE in html


def formex_key(celex: str, resolved_celex: str, sha256: str) -> str:
    """Where a version's Formex zip lives, beside its XHTML and keyed by content the same way."""
    return f"{celex}/{resolved_celex}/{sha256}.fmx4.zip"


def write_formex(store: ObjectStore, celex: str, resolved_celex: str, formex: bytes) -> str:
    """Store a version's Formex zip and return its sha256."""
    sha256 = hashlib.sha256(formex).hexdigest()
    store.put(formex_key(celex, resolved_celex, sha256), formex)
    return sha256


def read_formex(store: ObjectStore, document: RawDocument) -> bytes:
    """The Formex zip stored for a document, refusing any that is not the one the row recorded."""
    assert document.formex_sha256 is not None
    key = formex_key(document.celex, document.resolved_celex, document.formex_sha256)
    formex = store.get(key)
    if hashlib.sha256(formex).hexdigest() != document.formex_sha256:
        raise StoredBytesMismatchError("verify", key, "stored bytes do not match the recorded hash")
    return formex
