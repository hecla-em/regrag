"""The check and stamp subcommands: exit codes and what they print."""

import pytest

from app.evals.cli import main
from app.evals.dataset import cli as dataset_cli
from app.evals.dataset.enums import DriftKind
from app.evals.dataset.models import CaseReference, CorpusStamp, DriftedReference, EvalDataset
from tests.evals.conftest import eval_case, eval_dataset

STAMPED = CaseReference(celex="32023R1805", article="4", content_hashes=("b" * 12,))
STAMPED_AT = "2026-08-15-2cc038d"


def _loading(dataset: EvalDataset):
    """A stand-in for EvalDataset.load returning a fixed dataset."""
    return classmethod(lambda cls, *args, **kwargs: dataset)


# `evals check`


@pytest.fixture
def fake_check(monkeypatch):
    """Replace the DB read with a stub returning chosen drift, against a stamped dataset."""
    state: dict = {"drifted": (), "current": STAMPED_AT}

    dataset = eval_dataset(eval_case()).model_copy(
        update={"corpus": CorpusStamp(corpus_version=STAMPED_AT, stamped_at="2026-08-28")}
    )
    monkeypatch.setattr(EvalDataset, "load", _loading(dataset))

    async def _fake(loaded):
        return state["drifted"], state["current"]

    def _set(*drifted: DriftedReference, moved_to: str | None = None):
        state.update(drifted=drifted, current=moved_to or STAMPED_AT)

    monkeypatch.setattr(dataset_cli, "check_against_corpus", _fake)
    return _set


def _drifted(case_id: str, kind: DriftKind) -> DriftedReference:
    return DriftedReference(case_id=case_id, target=STAMPED, kind=kind)


def test_check_fails_only_on_an_unresolved_reference(fake_check, capsys):
    fake_check(_drifted("gone-case", DriftKind.UNRESOLVED))

    assert main(["check"]) == 1

    out = capsys.readouterr().out
    assert "unresolved (no stored chunk answers to it):" in out
    assert "gone-case  32023R1805 Article 4" in out


def test_check_names_a_stale_case_without_failing_the_command(fake_check, capsys):
    """A stale case needs a human re-review, not a red build."""
    fake_check(_drifted("amended-case", DriftKind.STALE))

    assert main(["check"]) == 0

    out = capsys.readouterr().out
    assert "stale (cited text changed since authoring):" in out
    assert "amended-case" in out


def test_check_names_an_unstamped_case_without_failing_the_command(fake_check, capsys):
    fake_check(_drifted("new-case", DriftKind.UNSTAMPED))

    assert main(["check"]) == 0
    assert "unstamped (nothing recorded to compare against):" in capsys.readouterr().out


# `evals stamp`
