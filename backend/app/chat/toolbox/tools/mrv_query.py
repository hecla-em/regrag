"""mrv_query: a reporting period's fleet CO2 totals from the THETIS-MRV public dataset."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.blocks import ContextBlock
from app.chat.enums import ToolStep
from app.chat.toolbox.models import ToolSpec
from app.mrv.models import MrvQueryArgs
from app.mrv.service import fleet_totals


async def run_mrv_query(session: AsyncSession, args: MrvQueryArgs) -> tuple[ContextBlock, ...]:
    """The period's figures as one block, or nothing when the period is not loaded."""
    block = await fleet_totals(session, args.period)
    return (block,) if block else ()


MRV_QUERY = ToolSpec(
    name="mrv_query",
    step=ToolStep.MRV_QUERY,
    args_model=MrvQueryArgs,
    run=run_mrv_query,
    description="Read one reporting period's fleet totals from the THETIS-MRV public dataset "
    "(2024 onward): CO2 in tonnes from the Full and Partial emissions reports and both together, "
    "as total, to be reported under the EU ETS, and split by EU scope (between, departed from, "
    "arrived at Member State ports, at berth). Use when the question asks for or quotes such a "
    "figure.",
    card="THETIS-MRV public dataset of ships' reported CO2 emissions: fleet totals per "
    "reporting period, the figure to be reported under the EU ETS, full and partial emissions "
    "reports, emissions between, to and from EU ports and at berth, the MRV download.",
)
