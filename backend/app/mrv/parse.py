"""THETIS-MRV workbook → report rows: the columns kept, read by position under a checked header."""

from io import BytesIO
from typing import Any

from openpyxl import load_workbook

from app.mrv.download import MrvFile
from app.mrv.enums import MrvSheet
from app.mrv.models import FIGURE_LABELS

HEADER_ROW = 3
COLUMNS = {
    "imo": 0,
    "ship_name": 1,
    "ship_type": 2,
    "period_label": 3,
    "company_imo": 8,
    "company_name": 9,
    "co2_total": 28,
    "co2_between_ms": 29,
    "co2_departed_ms": 30,
    "co2_arrived_ms": 31,
    "co2_at_berth": 32,
    "co2_ets": 37,
}
ETS_HEADER = "CO2 emissions to be reported under Directive 2003/87/EC [m tonnes]"


class MrvLayoutError(ValueError):
    """The workbook's columns are not where the parser reads them."""


def sheet_kind(title: str) -> MrvSheet:
    return MrvSheet.PARTIAL if "Partial" in title else MrvSheet.FULL


def to_figure(value: Any) -> float | None:
    """A cell as tonnes, or None when EMSA left it blank or wrote text."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_workbook(content: bytes, file: MrvFile) -> list[dict[str, Any]]:
    """Every report in both sheets as a row for mrv_reports."""
    workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
    rows: list[dict[str, Any]] = []
    for sheet in workbook.worksheets:
        header = next(sheet.iter_rows(min_row=HEADER_ROW, max_row=HEADER_ROW, values_only=True))
        if header[COLUMNS["co2_ets"]] != ETS_HEADER:
            raise MrvLayoutError(
                f"{sheet.title}: column {COLUMNS['co2_ets']} is {header[COLUMNS['co2_ets']]!r}"
            )
        for cells in sheet.iter_rows(min_row=HEADER_ROW + 1, values_only=True):
            if not cells[COLUMNS["imo"]]:
                continue
            row = {name: cells[index] for name, index in COLUMNS.items()}
            rows.append(
                row
                | {name: to_figure(row[name]) for name in FIGURE_LABELS}
                | {
                    "imo": str(row["imo"]),
                    "period_label": str(row["period_label"]),
                    "company_imo": str(row["company_imo"]) if row["company_imo"] else None,
                    "sheet": sheet_kind(sheet.title),
                    "period": file.period,
                    "version": file.version,
                    "generated": file.generated,
                }
            )
    return rows
