"""Dev-time fixture recorder; the only code here that touches the network.

Run from backend/: PYTHONPATH=. uv run python tests/ingestion/fetch/fixtures/record.py
"""

import asyncio
import json
from pathlib import Path

from app.core.config import config
from app.core.http import http_client
from app.ingestion.discover.models import ActsQueryRow
from app.ingestion.discover.select import select_documents
from app.ingestion.discover.sparql import run_acts_by_topic_query
from app.ingestion.fetch.download import download_fetchable_version

FIXTURES = Path(__file__).parent


def as_binding(row: ActsQueryRow) -> dict:
    """Back into the SPARQL envelope, since test_download replays these as real responses."""
    binding: dict = {"c": {"value": row.celex}}
    if row.in_force is not None:
        binding["force"] = {"value": "1" if row.in_force else "0"}
    if row.consolidation:
        binding["cons"] = {"value": row.consolidation}
    if row.basis_article:
        binding["basis"] = {"value": row.basis_article}
    return binding


async def record() -> None:
    expected: dict[str, str] = {}
    missing: set[str] = set()
    async with http_client(timeout=120, delays=config.CRAWL_DELAYS) as client:
        for topic, base_celex in config.TOPIC_BASE_ACTS.items():
            rows = await run_acts_by_topic_query(client, base_celex)
            payload = {"results": {"bindings": [as_binding(row) for row in rows]}}
            (FIXTURES / f"sparql-{topic}.json").write_text(json.dumps(payload, indent=2) + "\n")
            for spec in select_documents(topic, rows):
                resolved_celex, _ = await download_fetchable_version(client, spec)
                denied = spec.versions[: spec.versions.index(resolved_celex)]
                missing.update(denied)
                expected[f"{topic}:{spec.celex}"] = resolved_celex
    for key, value in sorted(expected.items()):
        print(f'    "{key}": "{value}",')
    print(f"MISSING_HTML = {sorted(missing)!r}")


def main() -> None:
    asyncio.run(record())


if __name__ == "__main__":
    main()
