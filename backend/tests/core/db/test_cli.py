"""Database shell: what psql is started with, and that sessions are read-only unless asked."""

import os

import pytest

from app.core.config import config
from app.core.db import cli
from app.core.db.cli import READ_ONLY_OPTIONS, build_shell_environment, main


@pytest.fixture
def started(monkeypatch) -> list[tuple[str, list[str], dict[str, str]]]:
    """What would have replaced the process, recorded instead."""
    calls = []
    monkeypatch.setattr(os, "execvpe", lambda file, args, env: calls.append((file, args, env)))
    return calls


def test_psql_is_started_on_the_configured_database(started):
    main([])

    [(file, args, env)] = started
    assert (file, args) == ("psql", ["psql"])
    assert env["PGDATABASE"] == config.DB_NAME


def test_a_session_is_read_only_unless_asked(started):
    main([])
    main(["--writable"])

    (_, _, read_only), (_, _, writable) = started
    assert read_only["PGOPTIONS"] == READ_ONLY_OPTIONS
    assert "PGOPTIONS" not in writable


def test_options_already_in_the_environment_are_kept(monkeypatch):
    monkeypatch.setenv("PGOPTIONS", "-c statement_timeout=5s")
    options = build_shell_environment(writable=False)["PGOPTIONS"]
    assert options == f"{READ_ONLY_OPTIONS} -c statement_timeout=5s"


def test_every_other_argument_reaches_psql(started):
    main(["--writable", "-tAc", "select 1"])

    [(_, args, _)] = started
    assert args == ["psql", "-tAc", "select 1"]


def test_the_banner_goes_to_stderr_so_query_output_stays_pipeable(started, capsys):
    main(["-c", "select 1"])

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "read-only" in captured.err


def test_a_missing_psql_is_reported_rather_than_raised(monkeypatch, capsys):
    def _missing(file, args, env):
        raise FileNotFoundError(2, "No such file or directory", "psql")

    monkeypatch.setattr(cli.os, "execvpe", _missing)

    assert main([]) == 1
    assert "psql could not be started" in capsys.readouterr().err
