"""THETIS-MRV values: the figures one query read, as a context block."""

from datetime import date
from typing import ClassVar, Literal

from pydantic import Field

from app.core.models import FrozenModel

MRV_URL = "https://mrv.emsa.europa.eu/#public/emission-report"

FIGURE_LABELS = {
    "co2_total": "total CO2",
    "co2_ets": "to be reported under Directive 2003/87/EC",
    "co2_between_ms": "voyages between MS ports",
    "co2_departed_ms": "voyages departed from MS ports",
    "co2_arrived_ms": "voyages arrived at MS ports",
    "co2_at_berth": "within MS ports at berth",
}
"""Each summed CO2 figure's field, and the label the model reads it under."""


class FigureTotals(FrozenModel):
    """CO2 in tonnes summed over a group of reports: one sheet's, or both sheets'."""

    label: str
    reports: int
    co2_total: float
    co2_ets: float
    co2_between_ms: float
    co2_departed_ms: float
    co2_arrived_ms: float
    co2_at_berth: float

    @property
    def text(self) -> str:
        lines = [f"{self.label} — {self.reports:,} reports"]
        lines += [
            f"  {label}: {getattr(self, name):,.0f} t" for name, label in FIGURE_LABELS.items()
        ]
        return "\n".join(lines)


class DatasetBlock(FrozenModel):
    """Figures read from one THETIS-MRV reporting period, as one numbered context block."""

    site: ClassVar[str] = "THETIS-MRV"
    name: ClassVar[str] = "THETIS-MRV public dataset"
    title: ClassVar[None] = None
    url: ClassVar[str] = MRV_URL

    source: Literal["thetis_mrv"] = "thetis_mrv"
    period: int
    version: int
    generated: date
    sheets: tuple[FigureTotals, ...]
    reports_with_ets: int
    median_ets_ratio: float
    matching_ets_ratio: int

    @property
    def citation(self) -> str:
        return f"{self.period}, version {self.version} of {self.generated.isoformat()}"

    @property
    def dedupe_key(self) -> str:
        return f"mrv:{self.period}:{self.version}"

    @property
    def combined(self) -> FigureTotals:
        return FigureTotals(
            label="both",
            reports=sum(sheet.reports for sheet in self.sheets),
            **{name: sum(getattr(sheet, name) for sheet in self.sheets) for name in FIGURE_LABELS},
        )

    @property
    def text(self) -> str:
        """The period, each sheet's totals and both together as labelled lines, and how the
        ETS figure compares with the scope split."""
        heading = (
            f"Emissions reported for reporting period {self.period}, from the THETIS-MRV public "
            f"dataset (file version {self.version}, generated {self.generated.isoformat()})."
        )
        share = self.matching_ets_ratio / self.reports_with_ets if self.reports_with_ets else 0.0
        check = (
            f"Across the {self.reports_with_ets:,} reports with an ETS figure, the ETS figure ÷ "
            "(100% between MS ports + 50% departed + 50% arrived + 100% at berth) has a median of "
            f"{self.median_ets_ratio:.2f}, and {share:.0%} of reports sit within 1% of it."
        )
        totals = [totals.text for totals in (*self.sheets, self.combined)]
        return "\n\n".join([heading, *totals, check])

    @property
    def prompt_text(self) -> str:
        return self.text


class MrvQueryArgs(FrozenModel):
    """A THETIS-MRV query: one reporting period's fleet totals."""

    period: int = Field(description="Reporting period (calendar year), 2024 or later.")
