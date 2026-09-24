"""THETIS-MRV values: the figures one query read, as a context block."""

from datetime import date
from typing import ClassVar, Literal

from pydantic import Field

from app.core.models import FrozenModel
from app.mrv.enums import MrvGrouping

MRV_URL = "https://mrv.emsa.europa.eu/#public/emission-report"

FIGURE_LABELS = {
    "co2_total": "total CO2",
    "co2_ets": "EU ETS emissions, to be reported under Directive 2003/87/EC",
    "co2_between_ms": "voyages between MS ports",
    "co2_departed_ms": "voyages departed from MS ports",
    "co2_arrived_ms": "voyages arrived at MS ports",
    "co2_at_berth": "within MS ports at berth",
}
"""Each summed CO2 figure's field, and the label the model reads it under."""

ETS_PHASE_IN = {2024: 0.40, 2025: 0.70}
"""The share of a year's ETS figure surrendered for under Article 3gb of Directive 2003/87/EC;
every later year is surrendered for in full."""


class FigureTotals(FrozenModel):
    """CO2 in tonnes summed over a group of reports: a report type's, a company's, a ship's,
    or every report the query matched."""

    label: str
    reports: int
    co2_total: float
    co2_ets: float
    co2_between_ms: float
    co2_departed_ms: float
    co2_arrived_ms: float
    co2_at_berth: float

    def describe(self, phase_in: float) -> str:
        """The group's figures on labelled lines, closing with what is surrendered for."""
        lines = [f"{self.label} — {self.reports:,} report{'' if self.reports == 1 else 's'}"]
        lines += [
            f"  {label}: {getattr(self, name):,.0f} t" for name, label in FIGURE_LABELS.items()
        ]
        lines.append(
            f"  surrendered for, worked out here and not a dataset column (EU ETS emissions × "
            f"the Article 3gb phase-in of {phase_in:.0%}): {self.co2_ets * phase_in:,.0f} t"
        )
        return "\n".join(lines)


class MrvBlock(FrozenModel):
    """Figures one THETIS-MRV query read from a reporting period, as one numbered context
    block: the groups it summed, every matched report together, and the ETS scope check."""

    site: ClassVar[str] = "THETIS-MRV"
    name: ClassVar[str] = "THETIS-MRV public dataset"
    title: ClassVar[None] = None
    url: ClassVar[str] = MRV_URL

    source: Literal["thetis_mrv"] = "thetis_mrv"
    period: int
    version: int
    generated: date
    subject: str
    groups: tuple[FigureTotals, ...]
    group_count: int
    overall: FigureTotals
    reports_with_ets: int
    median_ets_ratio: float
    matching_ets_ratio: int

    @property
    def citation(self) -> str:
        return f"{self.period}, version {self.version} of {self.generated.isoformat()}"

    @property
    def dedupe_key(self) -> str:
        return f"mrv:{self.period}:{self.version}:{self.subject}"

    @property
    def phase_in(self) -> float:
        return ETS_PHASE_IN.get(self.period, 1.0)

    @property
    def text(self) -> str:
        """The query stated plainly, each group's totals and every matched report's together as
        labelled lines, and how the ETS figure compares with the scope split."""
        heading = (
            f"Emissions reported for reporting period {self.period}, {self.subject}, from the "
            f"THETIS-MRV public dataset (file version {self.version}, generated "
            f"{self.generated.isoformat()}), in tonnes of CO2, not CO2 equivalent."
        )
        if not self.overall.reports:
            return f"{heading}\n\nNo report in this period matches."
        shown = (
            f"The {len(self.groups)} largest by ETS figure of {self.group_count:,} are shown."
            if len(self.groups) < self.group_count
            else ""
        )
        share = self.matching_ets_ratio / self.reports_with_ets if self.reports_with_ets else 0.0
        check = (
            f"Across the {self.reports_with_ets:,} matched reports with an ETS figure, the ETS "
            "figure ÷ (100% between MS ports + 50% departed + 50% arrived + 100% at berth) has a "
            f"median of {self.median_ets_ratio:.2f}, and {share:.0%} of reports sit within 1% of "
            "it."
        )
        totals = [group.describe(self.phase_in) for group in (*self.groups, self.overall)]
        return "\n\n".join(part for part in [heading, shown, *totals, check] if part)

    @property
    def prompt_text(self) -> str:
        return self.text


class MrvQueryArgs(FrozenModel):
    """A THETIS-MRV query: one reporting period's reports, narrowed to a company or ship when
    named, summed per report type, company or ship."""

    period: int = Field(description="Reporting period (calendar year), 2024 or later.")
    company: str | None = Field(
        default=None, description="Only this company's reports: its name or IMO company number."
    )
    ship: str | None = Field(
        default=None, description="Only this ship's reports: its name or IMO number."
    )
    by: MrvGrouping = Field(
        default=MrvGrouping.REPORT_TYPE,
        description="Sum per report type (Full, Partial), or per company or ship, largest ETS "
        "figure first, to rank them or list a company's ships.",
    )
