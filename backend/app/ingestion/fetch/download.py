"""The CELLAR document endpoint: which version it holds English text for, and its bytes."""

import httpx

from app.core.http import http_retry
from app.ingestion.discover.models import DiscoveredDocument
from app.ingestion.exceptions import NoFetchableVersionError

DOCUMENT_URL_TEMPLATE = "https://publications.europa.eu/resource/celex/{celex}"
DOCUMENT_HEADERS = {"Accept": "application/xhtml+xml", "Accept-Language": "eng"}
"""Content negotiation picks the English XHTML manifestation; CELLAR wants the three-letter code."""

FORMEX_HEADERS = {"Accept": "application/zip;mtype=fmx4", "Accept-Language": "eng"}
"""The same negotiation for the Formex zip, EUR-Lex's XML, which carries formulas as markup."""


def _is_version_missing(response: httpx.Response) -> bool:
    """CELLAR answers 404 for a version it holds no English text for."""
    return response.status_code == httpx.codes.NOT_FOUND


@http_retry
async def download_version(
    client: httpx.AsyncClient, version_celex: str, headers: dict[str, str]
) -> bytes | None:
    """What CELLAR serves for one version under these headers, or None if it has none."""
    response = await client.get(DOCUMENT_URL_TEMPLATE.format(celex=version_celex), headers=headers)
    if _is_version_missing(response):
        return None

    response.raise_for_status()
    return response.content


async def download_fetchable_version(
    client: httpx.AsyncClient, document: DiscoveredDocument
) -> tuple[str, bytes]:
    """The newest version CELLAR will serve, and the XHTML it served for it."""
    for version_celex in document.versions:
        html = await download_version(client, version_celex, DOCUMENT_HEADERS)
        if html is not None:
            return version_celex, html

    raise NoFetchableVersionError(
        f"{document.topic}:{document.celex}: no fetchable HTML, tried {document.versions}"
    )
