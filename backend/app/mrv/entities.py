"""THETIS-MRV entities: the dataset, companies and ships a question names, found by stored key."""

import re

from sqlalchemy import ColumnElement, Row, Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.mrv.names import name_words
from app.mrv.schemas import MrvReport
from app.retrieval.search import words_in_corpus

MAX_NAME_WORDS = 5
ENTITY_LIMIT = 5
PREFIX_EXAMPLES = 3
IMO_NUMBER = re.compile(r"\b\d{7}\b")
CAPITALISED = re.compile(r"\b[A-Z][A-Za-z0-9]+")


def word_runs(words: list[str]) -> list[list[str]]:
    """Every run of up to MAX_NAME_WORDS consecutive words."""
    return [
        words[start:end]
        for start in range(len(words))
        for end in range(start + 1, min(start + MAX_NAME_WORDS, len(words)) + 1)
    ]


def companies_where(condition: ColumnElement[bool]) -> Select:
    """Each company matching the condition once, under one of the spellings EMSA gives it."""
    return (
        select(func.max(MrvReport.company_name).label("name"), MrvReport.company_imo)
        .where(condition)
        .group_by(MrvReport.company_key, MrvReport.company_imo)
    )


def company_label(row: Row) -> str:
    return f"{row.name} (IMO company number {row.company_imo})" if row.company_imo else row.name


async def named_companies(
    session: AsyncSession, runs: list[list[str]], uncommon: set[str], imos: list[str]
) -> list[str]:
    """Companies named in full, less their corporate ending, by a run of two words or more or
    one word that is no ordinary vocabulary, or by IMO company number."""
    keys = {" ".join(run) for run in runs if len(run) > 1 or run[0] in uncommon}
    stmt = companies_where(
        or_(MrvReport.company_key.in_(keys), MrvReport.company_imo.in_(imos))
    ).limit(ENTITY_LIMIT)
    rows = await session.execute(stmt)
    return [f"{company_label(row)}, a company in THETIS-MRV" for row in rows]


async def company_prefixes(session: AsyncSession, question: str, uncommon: set[str]) -> list[str]:
    """For each capitalised word that is no ordinary vocabulary, the companies whose name
    starts with it, as possible matches."""
    capitalised = {word.lower() for word in CAPITALISED.findall(question)}
    lines = []
    for word in sorted(uncommon & capitalised):
        stmt = companies_where(MrvReport.company_key.startswith(f"{word} ")).limit(PREFIX_EXAMPLES)
        found = [company_label(row) for row in await session.execute(stmt)]
        if found:
            lines.append(
                f"possibly companies in THETIS-MRV whose name starts with '{word}', "
                f"such as {'; '.join(found)}"
            )
    return lines


async def named_ships(session: AsyncSession, runs: list[list[str]], imos: list[str]) -> list[str]:
    """Ships named by a run of two words or more, or by IMO number."""
    keys = {" ".join(run) for run in runs if len(run) > 1}
    stmt = (
        select(func.max(MrvReport.ship_name).label("name"), MrvReport.imo)
        .where(or_(MrvReport.ship_key.in_(keys), MrvReport.imo.in_(imos)))
        .group_by(MrvReport.imo)
        .limit(ENTITY_LIMIT)
    )
    rows = await session.execute(stmt)
    return [f"{row.name} (IMO {row.imo}), a ship in THETIS-MRV" for row in rows]


async def find_entities(session: AsyncSession, question: str) -> tuple[str, ...]:
    """The dataset itself and the companies and ships in it the question names, each with its
    IMO number; with no company named in full, companies a capitalised uncommon word starts."""
    words = name_words(question)
    runs = word_runs(words)
    single = {word for word in words if len(word) >= 3}
    uncommon = single - await words_in_corpus(session, sorted(single))
    imos = IMO_NUMBER.findall(question)
    dataset = ["THETIS-MRV, the dataset mrv_query reads"] if "thetis" in single else []
    companies = await named_companies(session, runs, uncommon, imos) or await company_prefixes(
        session, question, uncommon
    )
    ships = await named_ships(session, runs, imos)
    return tuple([*dataset, *companies, *ships][:ENTITY_LIMIT])
