"""Talking to CELLAR: build the topic query, send it, and read the rows it answers with."""

import json
from collections.abc import Sequence
from string import Template

import httpx

from app.core.http import http_retry
from app.ingestion.discover.models import ActsQueryRow
from app.ingestion.exceptions import MalformedDiscoveryError

_SPARQL_ENDPOINT = "https://publications.europa.eu/webapi/rdf/sparql"
_CELEX_RESOURCE = "http://publications.europa.eu/resource/celex/"

_ACTS_BY_TOPIC_QUERY = Template("""PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX ann: <http://publications.europa.eu/ontology/annotation#>
SELECT DISTINCT ?c ?force ?cons ?title ?basis WHERE {
  { ?act cdm:resource_legal_based_on_resource_legal ?base .
    ?base owl:sameAs <http://publications.europa.eu/resource/celex/$celex> .
    OPTIONAL { ?axiom owl:annotatedSource ?act ;
      owl:annotatedProperty cdm:resource_legal_based_on_resource_legal ;
      owl:annotatedTarget ?base ;
      ann:comment_on_legal_basis ?basis } }
  UNION
  { ?act owl:sameAs <http://publications.europa.eu/resource/celex/$celex> . }
  ?act cdm:resource_legal_id_celex ?c .
  OPTIONAL { ?act cdm:resource_legal_in-force ?force }
  OPTIONAL { ?consact cdm:act_consolidated_consolidates_resource_legal ?act .
    ?consact cdm:resource_legal_id_celex ?cons }
  OPTIONAL { ?expr cdm:expression_belongs_to_work ?act ;
    cdm:expression_uses_language <http://publications.europa.eu/resource/authority/language/ENG> ;
    cdm:expression_title ?title }
}""")


def _plain_title(value: str | None) -> str | None:
    """A title as text: CELLAR sets dates and numbers with non-breaking spaces."""
    return value.replace("\xa0", " ") if value is not None else None


_CITED_ACTS_QUERY = Template("""PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
SELECT DISTINCT ?c ?force ?cons ?title WHERE {
  VALUES ?target { $targets }
  ?act owl:sameAs ?target .
  ?act cdm:resource_legal_id_celex ?c .
  OPTIONAL { ?act cdm:resource_legal_in-force ?force }
  OPTIONAL { ?consact cdm:act_consolidated_consolidates_resource_legal ?act .
    ?consact cdm:resource_legal_id_celex ?cons }
  OPTIONAL { ?expr cdm:expression_belongs_to_work ?act ;
    cdm:expression_uses_language <http://publications.europa.eu/resource/authority/language/ENG> ;
    cdm:expression_title ?title }
}""")


async def _run_query(client: httpx.AsyncClient, query: str) -> list[ActsQueryRow]:
    """Send one query to CELLAR and read the acts out of the answer."""
    fmt = "application/sparql-results+json"
    response = await client.get(_SPARQL_ENDPOINT, params={"query": query, "format": fmt})
    response.raise_for_status()
    try:
        bindings = response.json()["results"]["bindings"]
    except (json.JSONDecodeError, KeyError) as exc:
        raise MalformedDiscoveryError(f"malformed SPARQL response: {exc!r}") from exc

    return [
        ActsQueryRow(
            celex=r["c"]["value"],
            in_force=r.get("force", {}).get("value"),
            consolidation=r.get("cons", {}).get("value"),
            title=_plain_title(r.get("title", {}).get("value")),
            basis_article=r.get("basis", {}).get("value"),
        )
        for r in bindings
    ]


@http_retry
async def run_acts_by_topic_query(client: httpx.AsyncClient, celex: str) -> list[ActsQueryRow]:
    """Ask CELLAR for one topic's acts; the query returns the base act too, so it must come back."""
    query = _ACTS_BY_TOPIC_QUERY.substitute(celex=celex)
    rows = await _run_query(client, query)
    if not any(row.celex == celex for row in rows):
        raise MalformedDiscoveryError(f"base act {celex} missing from discovery results")
    return rows


@http_retry
async def run_cited_acts_query(
    client: httpx.AsyncClient, celexes: Sequence[str]
) -> list[ActsQueryRow]:
    """Ask CELLAR for the named acts alone, no legal basis: a cited act was not adopted under
    a base act of ours. A celex it does not know comes back as no rows, which a misparsed
    citation legitimately is."""
    targets = " ".join(f"<{_CELEX_RESOURCE}{celex}>" for celex in celexes)
    return await _run_query(client, _CITED_ACTS_QUERY.substitute(targets=targets))
