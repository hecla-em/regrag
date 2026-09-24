"""THETIS-MRV: load a reporting period, query its reports, and find what a question names."""

import logging
import re
from typing import Any

import httpx
from sqlalchemy import ColumnElement, Row, delete, false, func, insert, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.core.storage import ObjectStore
from app.mrv.download import MrvFile, fetch_file, list_files
from app.mrv.enums import MrvGrouping
from app.mrv.models import FIGURE_LABELS, FigureTotals, MrvBlock, MrvQueryArgs
from app.mrv.parse import parse_workbook
from app.mrv.schemas import MrvReport
from app.retrieval.search import words_in_corpus

logger = logging.getLogger(__name__)

FIRST_PERIOD = 2024
"""The first reporting period the ETS covers shipping for."""


async def replace_period(session: AsyncSession, period: int, rows: list[dict]) -> None:
    """The period's rows swapped for these, in one transaction."""
    stmt = delete(MrvReport).where(MrvReport.period == period)
    await session.execute(stmt)
    await session.execute(insert(MrvReport), rows)
    await session.commit()


async def load_period(
    session: AsyncSession, client: httpx.AsyncClient, store: ObjectStore, file: MrvFile
) -> int:
    """Fetch, keep and load one period's latest file; the rows it loaded."""
    content = await fetch_file(client, file)
    store.put(f"mrv/{file.period}/v{file.version}.xlsx", content)
    rows = parse_workbook(content, file)
    await replace_period(session, file.period, rows)
    logger.info("loaded %d MRV reports for %d v%d", len(rows), file.period, file.version)
    return len(rows)


async def load_periods(
    session: AsyncSession, client: httpx.AsyncClient, store: ObjectStore, periods: list[int] | None
) -> dict[int, int]:
    """Every requested period from FIRST_PERIOD on, or all of them; rows loaded per period."""
    files = [f for f in await list_files(client) if f.period >= FIRST_PERIOD]
    chosen = [f for f in files if periods is None or f.period in periods]
    return {file.period: await load_period(session, client, store, file) for file in chosen}


async def loaded_versions(session: AsyncSession) -> str:
    """Each loaded period with its file version, like '2024v243,2025v58'; empty when none is."""
    stmt = select(MrvReport.period, MrvReport.version).distinct().order_by(MrvReport.period)
    rows = (await session.execute(stmt)).all()
    return ",".join(f"{period}v{version}" for period, version in rows)


SCOPE_TOLERANCE = 0.01
"""How close the ETS figure must sit to the scope split to count within the reported share."""

SCOPED = (
    func.coalesce(MrvReport.co2_between_ms, 0)
    + 0.5 * func.coalesce(MrvReport.co2_departed_ms, 0)
    + 0.5 * func.coalesce(MrvReport.co2_arrived_ms, 0)
    + func.coalesce(MrvReport.co2_at_berth, 0)
)
"""The ETS scope split: 100% between MS ports and at berth, 50% to or from them."""


CORPORATE_SUFFIXES = (
    "",
    "a s",
    "as",
    "s a",
    "sa",
    "ltd",
    "limited",
    "co ltd",
    "inc",
    "corp",
    "co",
    "gmbh",
    "s p a",
    "spa",
    "s r l",
    "srl",
    "llc",
    "plc",
    "b v",
    "bv",
    "n v",
    "nv",
    "ag",
    "sas",
    "ab",
    "oy",
    "pte ltd",
    "s l",
    "ltda",
    "a e",
)
"""Endings a company's registered name carries that a question naming it usually drops."""
MAX_NAME_WORDS = 5
MENTION_LIMIT = 5
PREFIX_EXAMPLES = 3
IMO_NUMBER = re.compile(r"\b\d{7}\b")


def spaced_name(column: InstrumentedAttribute[Any]) -> ColumnElement[str]:
    """A name as a mention compares it: lower case, words of letters and digits."""
    return func.btrim(func.regexp_replace(func.lower(column), "[^a-z0-9]+", " ", "g"))


def word_runs(question: str) -> list[list[str]]:
    """Every run of up to MAX_NAME_WORDS consecutive words in the question."""
    words = re.findall(r"[a-z0-9]+", question.lower())
    return [
        words[start:end]
        for start in range(len(words))
        for end in range(start + 1, min(start + MAX_NAME_WORDS, len(words)) + 1)
    ]


async def find_named(session: AsyncSession, question: str) -> tuple[str, ...]:
    """The dataset itself and the companies and ships in it the question names: a company by
    its name with or without its corporate ending, a ship by a name of two words or more,
    either by IMO number. With no company named in full, a capitalised word that is no
    ordinary vocabulary names the companies whose name starts with it, as possible matches."""
    runs = word_runs(question)
    single = {run[0] for run in runs if len(run) == 1 and len(run[0]) >= 3}
    names = single - await words_in_corpus(session, sorted(single))
    companies = {
        " ".join([*run, suffix]).strip()
        for run in runs
        if len(run) > 1 or run[0] in names
        for suffix in CORPORATE_SUFFIXES
    }
    ships = {" ".join(run) for run in runs if len(run) >= 2}
    imos = IMO_NUMBER.findall(question)
    company_stmt = (
        select(MrvReport.company_name)
        .distinct()
        .where(
            or_(spaced_name(MrvReport.company_name).in_(companies), MrvReport.company_imo.in_(imos))
        )
    )
    ship_stmt = (
        select(MrvReport.ship_name)
        .distinct()
        .where(or_(spaced_name(MrvReport.ship_name).in_(ships), MrvReport.imo.in_(imos)))
    )
    named = ["THETIS-MRV, the dataset mrv_query reads"] if "thetis" in single else []
    named += [
        f"{name}, a company in THETIS-MRV"
        for name in await session.scalars(company_stmt.limit(MENTION_LIMIT))
    ]
    if len(named) == ("thetis" in single):
        capitalised = {word.lower() for word in re.findall(r"\b[A-Z][A-Za-z0-9]+", question)}
        for word in sorted(names & capitalised):
            starts = (
                select(MrvReport.company_name)
                .distinct()
                .where(spaced_name(MrvReport.company_name).startswith(f"{word} "))
            )
            found = [name for name in await session.scalars(starts.limit(PREFIX_EXAMPLES)) if name]
            if found:
                named.append(
                    f"possibly companies in THETIS-MRV whose name starts with "
                    f"'{word}', such as {'; '.join(found)}"
                )
    named += [
        f"{name}, a ship in THETIS-MRV"
        for name in await session.scalars(ship_stmt.limit(MENTION_LIMIT))
    ]
    return tuple(named[:MENTION_LIMIT])


GROUP_LIMIT = 10
"""The most companies or ships one query lists; the rest count only in the overall line."""


def name_key(text: str) -> str:
    """A name as the match compares it: lower case, letters and digits only."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def name_or_imo(
    name: InstrumentedAttribute[Any], imo: InstrumentedAttribute[Any], query: str
) -> ColumnElement[bool]:
    """Reports whose IMO number is the query, or whose name holds it, punctuation ignored."""
    key = name_key(query)
    by_name = func.regexp_replace(func.lower(name), "[^a-z0-9]", "", "g").contains(key)
    return or_(imo == query.strip(), by_name if key else false())


def describe_query(args: MrvQueryArgs) -> str:
    """The query as the block's heading states it, like 'company matching "Carras", per ship'."""
    parts = [
        f'{kind} matching "{value}"'
        for kind, value in (("company", args.company), ("ship", args.ship))
        if value
    ]
    return ", ".join([*parts, f"per {args.by.value.replace('_', ' ')}"])


def group_label(by: MrvGrouping, row: Row) -> str:
    match by:
        case MrvGrouping.REPORT_TYPE:
            return f"{row.sheet.value} ERs"
        case MrvGrouping.COMPANY:
            return f"{row.company_name} (IMO company number {row.company_imo})"
        case MrvGrouping.SHIP:
            return f"{row.ship_name} (IMO {row.imo}, {row.ship_type}, {row.company_name})"


GROUP_KEYS = {
    MrvGrouping.REPORT_TYPE: MrvReport.sheet,
    MrvGrouping.COMPANY: MrvReport.company_imo,
    MrvGrouping.SHIP: MrvReport.imo,
}
"""What each grouping sums per: an IMO number rather than a name, which EMSA spells variously."""

GROUP_NAMES = {
    MrvGrouping.REPORT_TYPE: (),
    MrvGrouping.COMPANY: (MrvReport.company_name,),
    MrvGrouping.SHIP: (MrvReport.ship_name, MrvReport.ship_type, MrvReport.company_name),
}
"""The columns a group's label names it by, one spelling picked per group."""


async def query_reports(session: AsyncSession, args: MrvQueryArgs) -> MrvBlock | None:
    """The period's reports matching the query, summed per group and all together, with the
    ETS figure's spread against the scope split; None when the period is not loaded."""
    file_stmt = select(MrvReport.version, MrvReport.generated).where(
        MrvReport.period == args.period
    )
    loaded = (await session.execute(file_stmt.limit(1))).one_or_none()
    if loaded is None:
        return None
    matched = [MrvReport.period == args.period]
    if args.company:
        matched.append(name_or_imo(MrvReport.company_name, MrvReport.company_imo, args.company))
    if args.ship:
        matched.append(name_or_imo(MrvReport.ship_name, MrvReport.imo, args.ship))
    sums = [
        func.coalesce(func.sum(getattr(MrvReport, name)), 0).label(name) for name in FIGURE_LABELS
    ]
    key = GROUP_KEYS[args.by]
    names = [func.max(column).label(column.key) for column in GROUP_NAMES[args.by]]
    grouped = (
        select(key, *names, func.count().label("reports"), *sums).where(*matched).group_by(key)
    )
    ordered = (
        grouped.order_by(MrvReport.sheet)
        if args.by is MrvGrouping.REPORT_TYPE
        else grouped.order_by(func.sum(MrvReport.co2_ets).desc().nulls_last()).limit(GROUP_LIMIT)
    )
    rows = (await session.execute(ordered)).all()
    group_count = await session.scalar(select(func.count()).select_from(grouped.subquery()))
    overall_stmt = select(
        func.count().label("reports"),
        *sums,
        func.count().filter(MrvReport.co2_ets > 0, SCOPED != 0).label("with_ets"),
        func.percentile_cont(0.5)
        .within_group(MrvReport.co2_ets / func.nullif(SCOPED, 0))
        .filter(MrvReport.co2_ets > 0)
        .label("median"),
        func.count()
        .filter(
            MrvReport.co2_ets > 0,
            SCOPED != 0,
            func.abs(MrvReport.co2_ets - SCOPED) <= SCOPE_TOLERANCE * MrvReport.co2_ets,
        )
        .label("matching"),
    ).where(*matched)
    overall = (await session.execute(overall_stmt)).one()
    return MrvBlock(
        period=args.period,
        version=loaded.version,
        generated=loaded.generated,
        subject=describe_query(args),
        groups=tuple(
            FigureTotals(**row._asdict(), label=group_label(args.by, row)) for row in rows
        ),
        group_count=group_count or 0,
        overall=FigureTotals(**overall._asdict(), label="all matched reports together"),
        reports_with_ets=overall.with_ets,
        median_ets_ratio=overall.median or 0.0,
        matching_ets_ratio=overall.matching,
    )
