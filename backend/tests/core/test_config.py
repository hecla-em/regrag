"""Settings: the database URI a connection is made with, and the snapshot a run records."""

import certifi
from pydantic import SecretStr
from sqlalchemy import make_url

from app.core.config import (
    EVAL_CONFIG_SECTIONS,
    PostgresConfig,
    SslMode,
    config,
    get_config_snapshot,
)


def test_a_set_sslmode_reaches_the_database_uri_with_a_root_certificate():
    """In the URI, which alembic and the app engine both connect with."""
    url = PostgresConfig(DB_SSLMODE=SslMode.VERIFY_FULL).SQLALCHEMY_DATABASE_URI
    assert url.query == {"sslmode": "verify-full", "sslrootcert": certifi.where()}


def test_outside_prod_the_database_is_reached_without_tls():
    """The compose Postgres serves none."""
    assert PostgresConfig().SQLALCHEMY_DATABASE_URI.query == {}


def test_the_database_password_reaches_the_driver_whole_and_is_masked_when_printed():
    password = "p@ss/w?rd#%"
    url = PostgresConfig(DB_PASS=SecretStr(password)).SQLALCHEMY_DATABASE_URI
    assert url.password == password
    assert password not in str(url)
    assert make_url(url.render_as_string(hide_password=False)).password == password


# What a run records about the settings it read


def test_a_snapshot_records_the_requested_sections_whole(monkeypatch):
    """Taken from the config sections whole, so a knob added later is recorded without
    anyone editing a list."""
    monkeypatch.setattr(config, "CHAT_CONTEXT_CHUNKS", 7)

    settings = get_config_snapshot(EVAL_CONFIG_SECTIONS)

    expected = {name for section in EVAL_CONFIG_SECTIONS for name in section.model_fields}
    assert set(settings) == expected
    assert settings["CHAT_CONTEXT_CHUNKS"] == 7
    assert settings["RERANK_POOL"] == config.RERANK_POOL


def test_a_snapshot_leaves_out_the_secrets(monkeypatch):
    """The snapshot is printed and pasted around; a secret is not a knob a run reproduces."""
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", SecretStr("sk-never-recorded"))

    snapshot = get_config_snapshot()

    assert "sk-never-recorded" not in str(snapshot.values())
    assert not any("API_KEY" in name for name in snapshot)
    assert "DB_PASS" not in snapshot
