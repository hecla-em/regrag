"""Sentry reporting: every ERROR log line becomes an event, tagged with its request id, and a
scheduled job's run becomes a cron check-in."""

import functools
import logging
from collections.abc import Callable

import sentry_sdk
from sentry_sdk.crons import MonitorStatus, capture_checkin
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.types import Event, Hint, MonitorConfig

from app.core.config import Environment, config
from app.core.logger import request_id_var


def _before_send(event: Event, hint: Hint) -> Event:
    request_id = request_id_var.get()
    if request_id:
        event.setdefault("tags", {})["request_id"] = request_id
    return event


def configure_sentry() -> None:
    """Start Sentry in prod when a DSN is set. The request body, frame locals and the log
    lines before an error can all hold the question, so none of them is sent."""
    if config.ENVIRONMENT != Environment.PROD or not config.SENTRY_DSN:
        return

    sentry_sdk.init(
        dsn=config.SENTRY_DSN,
        environment=config.ENVIRONMENT.value,
        release=config.BUILD_ID,
        send_default_pii=False,
        max_request_body_size="never",
        include_local_variables=False,
        integrations=[
            FastApiIntegration(transaction_style="endpoint"),
            LoggingIntegration(level=None, event_level=logging.ERROR),
        ],
        before_send=_before_send,
    )


def monitor_cron_job[**P](
    slug: str, monitor_config: MonitorConfig
) -> Callable[[Callable[P, int]], Callable[P, int]]:
    """Make each run of a job that returns its exit code a Sentry cron check-in: ok on 0,
    an error on anything else or a raise. Flushed because the process exits straight after."""

    def decorate(run_job: Callable[P, int]) -> Callable[P, int]:
        @functools.wraps(run_job)
        def monitored_run(*args: P.args, **kwargs: P.kwargs) -> int:
            configure_sentry()
            check_in_id = capture_checkin(
                monitor_slug=slug, status=MonitorStatus.IN_PROGRESS, monitor_config=monitor_config
            )
            status = MonitorStatus.ERROR
            try:
                exit_code = run_job(*args, **kwargs)
                if exit_code == 0:
                    status = MonitorStatus.OK
                return exit_code
            finally:
                capture_checkin(monitor_slug=slug, check_in_id=check_in_id, status=status)
                sentry_sdk.flush()

        return monitored_run

    return decorate
