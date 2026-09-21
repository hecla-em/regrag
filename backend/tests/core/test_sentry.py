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


def exits_with(code: int):
    return lambda: code


def raises_mid_run() -> int:
    raise RuntimeError("pool exhausted")


@pytest.mark.parametrize(
    ("job", "status"),
    [
        pytest.param(exits_with(0), "ok", id="exit 0"),
        pytest.param(exits_with(1), "error", id="a nonzero exit"),
        pytest.param(raises_mid_run, "error", id="a raise, which still raises"),
    ],
)
def test_a_monitored_job_checks_in_as_started_then_by_how_it_ended(sentry, job, status) -> None:
    run_job = monitor_cron_job("hourly-job", HOURLY)(job)

    if job is raises_mid_run:
        with pytest.raises(RuntimeError):
            run_job()
    else:
        assert run_job() == job()

    started, finished = sentry.check_ins
    assert (started["status"], finished["status"]) == ("in_progress", status)
    assert started["monitor_slug"] == finished["monitor_slug"] == "hourly-job"
    assert finished["check_in_id"] == started["check_in_id"]
    assert started["monitor_config"]["schedule"] == HOURLY["schedule"]
