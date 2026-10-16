"""THETIS-MRV queries: a period's reports, narrowed to companies or ships by IMO number, summed
per group."""

from sqlalchemy import ColumnElement, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.mrv.enums import MrvGrouping
from app.mrv.models import FIGURE_LABELS, FigureTotals, MrvBlock, MrvQueryArgs
from app.mrv.schemas import MrvReport

GROUP_LIMIT = 10
"""The most companies or ships one query lists, largest ETS figure first, else largest total
before the ETS; the rest count only in the overall line."""

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
        func.coalesce(MrvReport.company_imo, MrvReport.company_key),
        func.concat(
            func.max(MrvReport.company_name),
            literal(" (IMO company number ") + func.max(MrvReport.company_imo) + ")",
        ),
    ),
    MrvGrouping.SHIP: (
        MrvReport.imo,
        func.concat(
            func.format(
                "%s (IMO %s, %s",
                func.max(MrvReport.ship_name),
                MrvReport.imo,
                func.max(MrvReport.ship_type),
            ),
            literal(", ") + func.max(MrvReport.company_name),
            ")",
        ),
    ),
}
"""What each grouping sums per, an IMO number rather than a name EMSA spells variously (a
company's stored key where it has none), and the label naming a group, one spelling picked."""


def matched_reports(args: MrvQueryArgs) -> list[ColumnElement[bool]]:
    matched = [MrvReport.period == args.period]
    if args.companies:
        matched.append(MrvReport.company_imo.in_(args.companies))
    if args.ships:
        matched.append(MrvReport.imo.in_(args.ships))
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
    key, label = GROUPINGS[args.grouping]
    grouped = (
        select(
            label.label("label"),
            func.count().label("reports"),
            *FIGURE_SUMS,
            func.count().over().label("group_count"),
        )
        .where(*matched, key.is_not(None))
        .group_by(key)
    )
    ordered = (
        grouped.order_by(key)
        if args.grouping is MrvGrouping.REPORT_TYPE
        else grouped.order_by(
            func.sum(MrvReport.co2_ets).desc().nulls_last(), func.sum(MrvReport.co2_total).desc()
        ).limit(GROUP_LIMIT)
    )
    rows = (await session.execute(ordered)).all()
    overall_stmt = select(func.count().label("reports"), *FIGURE_SUMS, *ETS_CHECK).where(*matched)
    overall = (await session.execute(overall_stmt)).one()
    return MrvBlock(
        period=args.period,
        version=loaded.version,
        generated=loaded.generated,
        subject=args.subject,
        names_several=args.names_several,
        groups=tuple(FigureTotals.model_validate(row) for row in rows),
        group_count=rows[0].group_count if rows else 0,
        overall=FigureTotals(**overall._asdict(), label="all matched reports together"),
        reports_with_ets=overall.reports_with_ets,
        median_ets_ratio=overall.median_ets_ratio,
        matching_ets_ratio=overall.matching_ets_ratio,
    )
