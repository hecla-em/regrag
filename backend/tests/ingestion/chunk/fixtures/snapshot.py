"""Dev-time snapshot writer; regenerates the chunk snapshots from the parse fixtures.

Run from backend/: PYTHONPATH=. uv run python tests/ingestion/chunk/fixtures/snapshot.py
"""

import json
from pathlib import Path

from app.ingestion.parse.html.document import parse_eurlex_html
from app.ingestion.parse.models import ParsedDocument
from tests.conftest import PARSE_FIXTURES
from tests.ingestion.chunk.conftest import snapshot_chunks

FIXTURES = Path(__file__).parent
TOPICS: dict[str, str] = {"32023R1805": "fueleu", "32015R0757": "mrv"}


def parse_fixture(celex: str, topic: str) -> ParsedDocument:
    """One trimmed act parsed the way the session fixtures parse it."""
    html = (PARSE_FIXTURES / f"{celex}.html").read_text()
    return ParsedDocument(celex=celex, topic=topic, sections=parse_eurlex_html(html))


def main() -> None:
    for celex, topic in TOPICS.items():
        chunks = snapshot_chunks(parse_fixture(celex, topic))
        body = json.dumps(chunks, indent=2, ensure_ascii=False) + "\n"
        (FIXTURES / f"{celex}.chunks.json").write_text(body, encoding="utf-8")
        print(f"{celex}: {len(chunks)} chunks, {len(body.encode()) // 1024} KB")


if __name__ == "__main__":
    main()
