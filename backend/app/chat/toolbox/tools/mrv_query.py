"""mrv_query: a reporting period's fleet CO2 totals from the THETIS-MRV public dataset."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.blocks import ContextBlock
from app.chat.enums import ToolStep
from app.chat.toolbox.models import ToolSpec
from app.mrv.entities import find_entities
from app.mrv.models import MrvQueryArgs
from app.mrv.query import query_reports


async def run_mrv_query(session: AsyncSession, args: MrvQueryArgs) -> tuple[ContextBlock, ...]:
    """The query's figures as one block, or nothing when the period is not loaded."""
    block = await query_reports(session, args)
    return (block,) if block else ()


MRV_QUERY = ToolSpec(
    name="mrv_query",
    step=ToolStep.MRV_QUERY,
    args_model=MrvQueryArgs,
    run=run_mrv_query,
    description="Read one reporting period of the THETIS-MRV public dataset (2024 onward): "
    "how many emissions reports were filed and their CO2 in tonnes as total, to be reported "
    "under the EU ETS, and split by EU scope (between, departed from, arrived at Member State "
    "ports, at berth), plus how the ETS figure compares with that scope split. Covers the whole "
    "fleet, or one company's or ship's reports when named; sums per report type (Full, Partial), "
    "or per company or ship, largest ETS figure first, to rank them or list a company's ships. "
    "Use whenever the answer needs one of these figures or one worked out from them, or turns "
    "on what they include.",
    card="THETIS-MRV public dataset of ships' reported CO2 emissions: fleet, company and ship "
    "totals per reporting period, a company's or ship's ETS exposure, the largest emitters, the "
    "figure to be reported under the EU ETS, full and partial emissions reports, emissions "
    "between, to and from EU ports and at berth, the MRV download.",
    find_entities=find_entities,
)
