"""EMSA's published THETIS-MRV files: which exist, and one file's bytes."""

from datetime import datetime

import httpx

from app.core.http import http_retry
from app.mrv.models import MrvFile

API = "https://mrv.emsa.europa.eu/api/public-emission-report"


@http_retry
async def list_files(client: httpx.AsyncClient) -> list[MrvFile]:
    """The latest published file of every reporting period."""
    response = await client.get(f"{API}/downloadable-files", params={"page": 1, "limit": 50})
    response.raise_for_status()
    return [
        MrvFile(
            period=entry["reportingPeriod"],
            version=entry["version"],
            generated=datetime.strptime(entry["generationDate"], "%d-%m-%Y %H:%M:%S").date(),
        )
        for entry in response.json()["results"]
    ]


@http_retry
async def fetch_file(client: httpx.AsyncClient, file: MrvFile) -> bytes:
    response = await client.get(
        f"{API}/reporting-period-document/binary/{file.period}/{file.version}"
    )
    response.raise_for_status()
    return response.content
