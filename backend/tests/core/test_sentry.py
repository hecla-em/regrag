"""Sentry reporting: what becomes an event, what it is tagged with, and what it leaves out."""

import logging

import sentry_sdk

from app.core.config import config
from app.core.logger import request_id_var
from app.core.sentry import _before_send, configure_sentry


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
