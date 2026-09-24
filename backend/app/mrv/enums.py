"""THETIS-MRV enums."""

from enum import StrEnum


class MrvSheet(StrEnum):
    """Which sheet a report came from: a full year under one company, or part of one."""

    FULL = "full"
    PARTIAL = "partial"


class MrvGrouping(StrEnum):
    """What a query's figures are summed per: report type, company, or ship."""

    REPORT_TYPE = "report_type"
    COMPANY = "company"
    SHIP = "ship"
