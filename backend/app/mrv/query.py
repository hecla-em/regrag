"""THETIS-MRV queries: a period's reports, narrowed to a company or ship, summed per group."""

from collections.abc import Callable
from typing import Any

from sqlalchemy import ColumnElement, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.mrv.enums import MrvGrouping
from app.mrv.models import FIGURE_LABELS, FigureTotals, MrvBlock, MrvQueryArgs
from app.mrv.names import company_key, name_key
from app.mrv.schemas import MrvReport

GROUP_LIMIT = 10
"""The most companies or ships one query lists; the rest count only in the overall line."""

SCOPE_TOLERANCE = 0.01
"""How close the ETS figure must sit to the scope split to count within the reported share."""

SCOPED = (
    func.coalesce(MrvReport.co2_between_ms, 0)
    + 0.5 * func.coalesce(MrvReport.co2_departed_ms, 0)
    + 0.5 * func.coalesce(MrvReport.co2_arrived_ms, 0)
    + func.coalesce(MrvReport.co2_at_berth, 0)
)
"""The ETS scope split: 100% between MS ports and at berth, 50% to or from them."""

HAS_ETS = (MrvReport.co2_ets > 0) & (SCOPED != 0)

FIGURE_SUMS = tuple(
    func.coalesce(func.sum(getattr(MrvReport, name)), 0).label(name) for name in FIGURE_LABELS
)

ETS_CHECK = (
    func.count().filter(HAS_ETS).label("reports_with_ets"),
    func.percentile_cont(0.5)
    .within_group(MrvReport.co2_ets / func.nullif(SCOPED, 0))
    .filter(HAS_ETS)
    .label("median_ets_ratio"),
    func.count()
    .filter(HAS_ETS, func.abs(MrvReport.co2_ets - SCOPED) <= SCOPE_TOLERANCE * MrvReport.co2_ets)
    .label("matching_ets_ratio"),
)
"""How the ETS figure compares with the scope split across reports that carry both."""

GROUPINGS = {
    MrvGrouping.REPORT_TYPE: (MrvReport.sheet, func.format("%s ERs", MrvReport.sheet)),
    MrvGrouping.COMPANY: (
        MrvReport.company_imo,
        func.format(
            "%s (IMO company number %s)", func.max(MrvReport.company_name), MrvReport.company_imo
        ),
    ),
    MrvGrouping.SHIP: (
        MrvReport.imo,
        func.format(
            "%s (IMO %s, %s, %s)",
            func.max(MrvReport.ship_name),
            MrvReport.imo,
            func.max(MrvReport.ship_type),
            func.max(MrvReport.company_name),
        ),
    ),
}
"""What each grouping sums per, an IMO number rather than a name EMSA spells variously, and
the label naming a group, one spelling picked per group."""


def key_or_imo(
    key: InstrumentedAttribute[Any],
    imo: InstrumentedAttribute[Any],
    query: str,
    to_key: Callable[[str], str],
) -> ColumnElement[bool]:
    """Reports whose IMO number is the query, or whose stored key holds the query's."""
    query_key = to_key(query)
    return or_(imo == query.strip(), key.contains(query_key) if query_key else false())


def matched_reports(args: MrvQueryArgs) -> list[ColumnElement[bool]]:
    matched = [MrvReport.period == args.period]
    if args.company:
        matched.append(
            key_or_imo(MrvReport.company_key, MrvReport.company_imo, args.company, company_key)
        )
    if args.ship:
        matched.append(key_or_imo(MrvReport.ship_key, MrvReport.imo, args.ship, name_key))
    return matched


async def query_reports(session: AsyncSession, args: MrvQueryArgs) -> MrvBlock | None:
    """The period's reports matching the query, summed per group and all together, with the
    ETS figure's spread against the scope split; None when the period is not loaded."""
    loaded_stmt = (
        select(MrvReport.version, MrvReport.generated)
        .where(MrvReport.period == args.period)
        .limit(1)
    )
    loaded = (await session.execute(loaded_stmt)).one_or_none()
    if loaded is None:
        return None
    matched = matched_reports(args)
    key, label = GROUPINGS[args.by]
    grouped = (
        select(
            label.label("label"),
            func.count().label("reports"),
            *FIGURE_SUMS,
            func.count().over().label("group_count"),
        )
        .where(*matched)
        .group_by(key)
    )
    ordered = (
        grouped.order_by(key)
        if args.by is MrvGrouping.REPORT_TYPE
        else grouped.order_by(func.sum(MrvReport.co2_ets).desc().nulls_last()).limit(GROUP_LIMIT)
    )
    rows = (await session.execute(ordered)).all()
    overall_stmt = select(func.count().label("reports"), *FIGURE_SUMS, *ETS_CHECK).where(*matched)
    overall = (await session.execute(overall_stmt)).one()
    return MrvBlock(
        period=args.period,
        version=loaded.version,
        generated=loaded.generated,
        subject=args.subject,
        groups=tuple(FigureTotals.model_validate(row) for row in rows),
        group_count=rows[0].group_count if rows else 0,
        overall=FigureTotals(**overall._asdict(), label="all matched reports together"),
        reports_with_ets=overall.reports_with_ets,
        median_ets_ratio=overall.median_ets_ratio or 0.0,
        matching_ets_ratio=overall.matching_ets_ratio,
    )
