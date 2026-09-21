"""The check subcommand: which drift it names, and which fails it."""

import pytest

from app.evals.cli import main
from app.evals.dataset import cli as dataset_cli
from app.evals.dataset.enums import DriftKind
from app.evals.dataset.models import CaseReference, DriftedReference, EvalDataset
from tests.evals.conftest import eval_case, eval_dataset

STAMPED = CaseReference(celex="32023R1805", article="4", content_hashes=("b" * 12,))


def _loading(dataset: EvalDataset):
    """A stand-in for EvalDataset.load returning a fixed dataset."""
    return classmethod(lambda cls, *args, **kwargs: dataset)


@pytest.fixture
def fake_check(monkeypatch):
    """Replace the dataset file and the DB read with a stub returning the drift a test adds."""
    found: list[DriftedReference] = []

    async def _fake(loaded):
        return tuple(found), None

    monkeypatch.setattr(EvalDataset, "load", _loading(eval_dataset(eval_case())))
    monkeypatch.setattr(dataset_cli, "check_against_corpus", _fake)
    return found


@pytest.mark.parametrize(
    ("kind", "exit_code"),
    [
        pytest.param(DriftKind.UNRESOLVED, 1, id="an unresolved reference fails the command"),
        pytest.param(DriftKind.STALE, 0, id="a stale case needs a re-review, not a red build"),
        pytest.param(DriftKind.UNSTAMPED, 0, id="an unstamped case is named without failing"),
    ],
)
def test_check_names_every_drifted_case_and_fails_only_on_an_unresolved_one(
    fake_check, capsys, kind: DriftKind, exit_code: int
) -> None:
    fake_check.append(DriftedReference(case_id="drifted-case", target=STAMPED, kind=kind))

    assert main(["check"]) == exit_code
    assert "drifted-case  32023R1805 Article 4" in capsys.readouterr().out
