"""Analytics enumerations."""

from enum import IntEnum


class AnalyticsDays(IntEnum):
    """The ranges the analytics endpoints offer, in days back from today."""

    WEEK = 7
    MONTH = 30
    QUARTER = 90
