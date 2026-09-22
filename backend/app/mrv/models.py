"""THETIS-MRV values: the figures one query read, as a context block."""

from datetime import date
from typing import ClassVar, Literal

from app.core.models import FrozenModel

MRV_URL = "https://mrv.emsa.europa.eu/#public/emission-report"


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
    text: str

    @property
    def citation(self) -> str:
        return f"{self.period}, version {self.version} of {self.generated.isoformat()}"

    @property
    def dedupe_key(self) -> str:
        return f"mrv:{self.period}:{self.version}"

    @property
    def prompt_text(self) -> str:
        return self.text
