"""Sentry reporting: what becomes an event, what it is tagged with, and what it leaves out."""

import logging

import pytest
import sentry_sdk
from sentry_sdk.types import MonitorConfig

from app.core.config import config
from app.core.logger import request_id_var
from app.core.sentry import _before_send, configure_sentry, monitor_cron_job

HOURLY: MonitorConfig = {"schedule": {"type": "crontab", "value": "0 * * * *"}}


def test_before_send_tags_the_request_id() -> None:
    token = request_id_var.set("abc123def456")
    try:
        event = _before_send({}, {})
    finally:
        request_id_var.reset(token)
    assert event["tags"] == {"request_id": "abc123def456"}


def test_before_send_leaves_an_event_outside_a_request_untagged() -> None:
    assert _before_send({}, {}) == {}


def test_nothing_is_configured_without_a_dsn(monkeypatch) -> None:
    monkeypatch.setattr(config, "SENTRY_DSN", None)
    configure_sentry()
    assert not sentry_sdk.is_initialized()


def test_a_logged_exception_becomes_an_event_without_a_capture_call(sentry) -> None:
    try:
        raise RuntimeError("pool exhausted")
    except RuntimeError:
        logging.getLogger("app.test").exception("chat stream failed unexpectedly")

    [event] = sentry.events
    assert event["exception"]["values"][0]["type"] == "RuntimeError"


def test_a_warning_sends_nothing(sentry) -> None:
    logging.getLogger("app.test").warning("chat stream failed: %s", "Too many questions")
    assert sentry.events == []


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


def test_a_monitored_job_runs_untouched_without_a_dsn(monkeypatch) -> None:
    monkeypatch.setattr(config, "SENTRY_DSN", None)

    @monitor_cron_job("hourly-job", HOURLY)
    def run_job() -> int:
        return 0

    assert run_job() == 0
