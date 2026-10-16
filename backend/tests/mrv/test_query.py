"""THETIS-MRV queries: companies and ships by IMO number, several never summed together."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.mrv.enums import MrvGrouping
from app.mrv.models import MrvQueryArgs
from app.mrv.query import query_reports
from app.mrv.schemas import MrvReport
from tests.mrv.conftest import company_report

pytestmark = pytest.mark.anyio


def build_reports() -> list[MrvReport]:
    return [
        company_report("DFDS A/S", "0310102", imo="9000001", ship_name="A"),
        company_report("DFDS A/S", "0310102", imo="9000002", ship_name="B"),
        company_report("DFDS Iberia S.L.U.", "5245751", imo="9000003", ship_name="C"),
    ]


@pytest.fixture
async def reports(db_session: AsyncSession) -> AsyncSession:
    db_session.add_all(build_reports())
    await db_session.flush()
    return db_session


@pytest.mark.parametrize(
    ("args", "group_reports", "summed_together"),
    [
        pytest.param(
            MrvQueryArgs(period=2024, companies=("0310102",)),
            [2],
            True,
            id="one company sums per report type with its total line",
        ),
        pytest.param(
            MrvQueryArgs(period=2024, companies=("0310102", "5245751")),
            [2, 1],
            False,
            id="several companies sum each on its own, with no line adding them up",
        ),
        pytest.param(
            MrvQueryArgs(period=2024, ships=("9000001", "9000003"), by=MrvGrouping.COMPANY),
            [1, 1],
            False,
            id="several ships grouped per company keep companies apart",
        ),
    ],
)
async def test_named_companies_and_ships_are_never_added_together(
    reports, args, group_reports, summed_together
):
    block = await query_reports(reports, args)

    assert block is not None
    assert [group.reports for group in block.groups] == group_reports
    assert (block.overall.label in block.text) is summed_together
