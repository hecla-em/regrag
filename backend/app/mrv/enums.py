"""THETIS-MRV enums."""

from enum import StrEnum


class MrvSheet(StrEnum):
    """Which sheet a report came from: a full year under one company, or part of one."""

    FULL = "full"
    PARTIAL = "partial"
