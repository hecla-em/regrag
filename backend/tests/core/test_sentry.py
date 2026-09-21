"""Sentry reporting: what becomes an event, what it is tagged with, and what it leaves out."""

import logging

import pytest
from sentry_sdk.types import MonitorConfig

from app.core.sentry import monitor_cron_job

HOURLY: MonitorConfig = {"schedule": {"type": "crontab", "value": "0 * * * *"}}


def test_a_warning_sends_nothing(sentry) -> None:
    logging.getLogger("app.test").warning("chat stream failed: %s", "Too many questions")
    assert sentry.events == []


def test_log_lines_before_an_error_are_not_sent_with_it(sentry) -> None:
    """They quote model and provider text, which is written from the question."""
    logger = logging.getLogger("app.test")
    logger.warning("rewrite answered off its schema: %s", "input_value='Jane Example'")
    logger.error("chat stream failed unexpectedly")

    [event] = sentry.events
    assert "Jane Example" not in str(event)


def test_a_monitored_job_checks_in_as_started_then_ok(sentry) -> None:
    @monitor_cron_job("hourly-job", HOURLY)
    def run_job(exit_code: int) -> int:
        return exit_code

    assert run_job(0) == 0

    started, finished = sentry.check_ins
    assert (started["status"], finished["status"]) == ("in_progress", "ok")
    assert started["monitor_slug"] == finished["monitor_slug"] == "hourly-job"
    assert finished["check_in_id"] == started["check_in_id"]
    assert started["monitor_config"]["schedule"] == HOURLY["schedule"]


def test_a_monitored_job_that_exits_nonzero_checks_in_as_an_error(sentry) -> None:
    @monitor_cron_job("hourly-job", HOURLY)
    def run_job() -> int:
        return 1

    assert run_job() == 1

    assert [check_in["status"] for check_in in sentry.check_ins] == ["in_progress", "error"]


def test_a_monitored_job_that_raises_checks_in_as_an_error_and_still_raises(sentry) -> None:
    @monitor_cron_job("hourly-job", HOURLY)
    def run_job() -> int:
        raise RuntimeError("pool exhausted")

    with pytest.raises(RuntimeError):
        run_job()

    assert [check_in["status"] for check_in in sentry.check_ins] == ["in_progress", "error"]
