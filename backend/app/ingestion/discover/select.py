"""Reducing the query's answer to documents: which acts to fetch, and at what version."""

import re
from itertools import groupby

from app.ingestion import celex
from app.ingestion.discover.models import ActsQueryRow, CandidateAct, DiscoveredDocument


def filter_legislative_acts(rows: list[ActsQueryRow]) -> list[ActsQueryRow]:
    """Half of every answer is resolutions and communications: they cite a law but are not one."""
    return [row for row in rows if celex.is_legislation(row.celex)]


def _candidate_act(act_celex: str, rows: list[ActsQueryRow]) -> CandidateAct:
    """Every row for an act repeats its in-force flag and title and carries one of its
    consolidations and one of its basis articles."""
    return CandidateAct(
        celex=act_celex,
        in_force=rows[0].in_force,
        consolidations=frozenset(row.consolidation for row in rows if row.consolidation),
        title=rows[0].title,
        basis_articles=frozenset(row.basis_article for row in rows if row.basis_article),
    )


def extract_candidate_acts(rows: list[ActsQueryRow]) -> list[CandidateAct]:
    """One act per celex, folded from the rows the query exploded it into."""
    by_celex = sorted(rows, key=lambda row: row.celex)
    return [
        _candidate_act(act_celex, list(act_rows))
        for act_celex, act_rows in groupby(by_celex, key=lambda row: row.celex)
    ]


def _extract_consolidations_of_this_act(act: CandidateAct) -> set[str]:
    """The consolidated texts this act is the base of, rather than an amendment folded into."""
    stem = celex.consolidated_stem(act.celex)
    return {version for version in act.consolidations if version.startswith(stem)}


def _is_in_force(act: CandidateAct) -> bool:
    """Repealed acts are flagged false; anything that is not law carries no flag at all."""
    return act.in_force is True


def _is_folded_into_another_act(act: CandidateAct) -> bool:
    """Every consolidation of this act belongs to another act, which now supersedes it."""
    return bool(act.consolidations) and not _extract_consolidations_of_this_act(act)


def filter_fetchable_acts(acts: list[CandidateAct]) -> list[CandidateAct]:
    """A repealed act is not law; a folded one's text lives in the act that absorbed it."""
    return [act for act in acts if _is_in_force(act) and not _is_folded_into_another_act(act)]


def _is_adopted_under(act: CandidateAct, articles: str) -> bool:
    """Whether any article the act was adopted under starts the way the pattern does."""
    return any(re.match(articles, article) for article in act.basis_articles)


def filter_acts_by_basis_article(
    acts: list[CandidateAct], base_celex: str, articles: str
) -> list[CandidateAct]:
    """The base act, and the acts adopted under an article the pattern matches."""
    return [act for act in acts if act.celex == base_celex or _is_adopted_under(act, articles)]


def exclude_acts_by_basis_article(acts: list[CandidateAct], articles: str) -> list[CandidateAct]:
    """The acts left once those adopted under an article the pattern matches are turned away."""
    return [act for act in acts if not _is_adopted_under(act, articles)]


def _consolidations_newest_first(act: CandidateAct) -> tuple[str, ...]:
    """Every consolidated text of this act, newest first; the date suffix makes that a sort."""
    return tuple(sorted(_extract_consolidations_of_this_act(act), reverse=True))


def select_documents(
    topic: str,
    rows: list[ActsQueryRow],
    *,
    base_celex: str | None = None,
    kept_basis: str | None = None,
    excluded_basis: str | None = None,
) -> list[DiscoveredDocument]:
    """The query's rows, reduced to the documents this topic wants fetched: with a kept
    basis pattern, only the base act and the acts adopted under a matching article."""
    legislation = filter_legislative_acts(rows)
    acts = extract_candidate_acts(legislation)
    fetchable = filter_fetchable_acts(acts)
    if kept_basis and base_celex:
        fetchable = filter_acts_by_basis_article(fetchable, base_celex, kept_basis)
    if excluded_basis:
        fetchable = exclude_acts_by_basis_article(fetchable, excluded_basis)
    return [
        DiscoveredDocument(
            topic=topic,
            source="eurlex",
            celex=act.celex,
            candidates=_consolidations_newest_first(act),
            title=act.title,
        )
        for act in fetchable
    ]
