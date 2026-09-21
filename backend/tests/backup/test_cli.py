"""Backup CLI: exit codes, the upload switch, the Sentry check-in."""

import subprocess

import pytest

from app.backup import cli
from app.backup.cli import main
from app.core.config import BackupR2Config


@pytest.fixture
def fake_backup(monkeypatch) -> list[str]:
    """Replace pg_dump and R2 with stubs recording the steps a run took."""
    steps = []
    monkeypatch.setattr(cli, "get_backup_store", lambda: steps.append("store") or "store")
    monkeypatch.setattr(cli, "dump_database", lambda path: steps.append("dump"))
    monkeypatch.setattr(cli, "upload_dump", lambda store, path: steps.append("upload") or "k")
    return steps


def test_a_run_reads_the_bucket_settings_then_dumps_then_uploads(fake_backup, capsys):
    assert main([]) == 0
    assert fake_backup == ["store", "dump", "upload"]
    assert "backup stored: k" in capsys.readouterr().out


def test_no_upload_leaves_the_dump_where_it_was_written(fake_backup, capsys):
    assert main(["--no-upload"]) == 0
    assert fake_backup == ["dump"]
    assert "backup written: regrag-" in capsys.readouterr().out


def test_missing_bucket_settings_abort_before_anything_is_dumped(fake_backup, monkeypatch, capsys):
    for name in BackupR2Config.model_fields:
        monkeypatch.delenv(f"BACKUP_{name}", raising=False)
    monkeypatch.setattr(cli, "get_backup_store", lambda: BackupR2Config(_env_file=None))

    assert main([]) == 1
    assert fake_backup == []
    assert "backup aborted" in capsys.readouterr().err


def test_a_failed_pg_dump_exits_nonzero(fake_backup, monkeypatch, capsys):
    def _fail(path):
        raise subprocess.CalledProcessError(1, ["pg_dump"])

    monkeypatch.setattr(cli, "dump_database", _fail)

    assert main(["--no-upload"]) == 1
    assert "backup aborted" in capsys.readouterr().err


def test_a_clean_run_checks_in_ok_on_the_workflow_schedule(fake_backup, sentry):
    assert main([]) == 0

    started, finished = sentry.check_ins
    assert (started["status"], finished["status"]) == ("in_progress", "ok")
    assert started["monitor_slug"] == cli.MONITOR_SLUG
    assert started["monitor_config"]["schedule"] == {"type": "crontab", "value": "0 2 * * *"}


def test_a_failed_run_checks_in_as_an_error_and_sends_why(fake_backup, monkeypatch, sentry):
    def _fail(path):
        raise subprocess.CalledProcessError(1, ["pg_dump"])

    monkeypatch.setattr(cli, "dump_database", _fail)

    assert main([]) == 1

    _, finished = sentry.check_ins
    assert finished["status"] == "error"
    [event] = sentry.events
    assert event["exception"]["values"][0]["type"] == "CalledProcessError"
