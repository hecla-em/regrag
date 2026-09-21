"""The golden dataset: what a case must carry, how the file loads and saves, and what
the dataset hash covers."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.evals.dataset.enums import EvalKind, EvalTrait
from app.evals.dataset.models import (
    CaseReference,
    CaseSelection,
    CorpusStamp,
    EvalCase,
    EvalDataset,
)
from app.evals.dataset.stamp import save_dataset
from tests.evals.conftest import REFERENCE, eval_case, eval_dataset

STAMPED = CaseReference(celex="32023R1805", article="4", content_hashes=("a" * 12, "b" * 12))


def test_an_in_corpus_case_needs_an_answer_and_references() -> None:
    with pytest.raises(ValidationError, match="in_corpus"):
        eval_case(references=())
    with pytest.raises(ValidationError, match="in_corpus"):
        eval_case(answer=None)


def test_an_out_of_corpus_case_carries_neither() -> None:
    with pytest.raises(ValidationError, match="out_of_corpus"):
        EvalCase(id="x", kind=EvalKind.OUT_OF_CORPUS, question="q?", references=(REFERENCE,))
    with pytest.raises(ValidationError, match="out_of_corpus"):
        EvalCase(id="x", kind=EvalKind.OUT_OF_CORPUS, question="q?", answer="a")


# What the dataset hash covers


def test_the_hash_follows_the_cases_not_the_file() -> None:
    same = eval_dataset(eval_case()).sha256

    assert same == eval_dataset(eval_case()).sha256
    assert same != eval_dataset(eval_case(answer="b")).sha256


def test_the_hash_ignores_the_stamps() -> None:
    """A re-stamp records which text an answer was read against and changes nothing a run
    scores, so it must leave past runs of the same cases comparable."""
    unstamped = eval_dataset(eval_case(references=(REFERENCE,)))
    stamped = eval_dataset(eval_case(references=(STAMPED,)))

    assert unstamped.sha256 == stamped.sha256


def test_the_hash_ignores_the_traits() -> None:
    """A trait says what a case tests, not what it asserts, so marking one must leave past
    runs of the same cases comparable."""
    plain = eval_dataset(eval_case())
    marked = eval_dataset(eval_case(traits=(EvalTrait.MULTI_PART,)))

    assert plain.sha256 == marked.sha256


def test_the_hash_ignores_the_corpus_stamp() -> None:
    stamped = eval_dataset(eval_case()).model_copy(
        update={"corpus": CorpusStamp(corpus_version="2026-08-15-2cc038d", stamped_at="2026-08-28")}
    )

    assert stamped.sha256 == eval_dataset(eval_case()).sha256


def test_the_hash_still_follows_which_division_a_case_cites() -> None:
    """Only the stamp records the corpus; the target itself is part of what the case asserts."""
    elsewhere = CaseReference(celex="32023R1805", article="9")

    assert (
        eval_dataset(eval_case()).sha256 != eval_dataset(eval_case(references=(elsewhere,))).sha256
    )


# Loading, filtering and saving the dataset file


def _write_dataset(path: Path, *cases: EvalCase) -> Path:
    save_dataset(EvalDataset(cases=cases), path)
    return path


def test_the_hash_names_the_file_not_the_subset_scored(tmp_path: Path) -> None:
    """The hash compares a filtered spot-check against a full run of the same file."""
    file = _write_dataset(
        tmp_path / "golden.json", eval_case(id="fueleu-one"), eval_case(id="mrv-one")
    )

    subset = EvalDataset.load(file, CaseSelection(id_contains="fueleu"))

    assert subset.sha256 == EvalDataset.load(file).sha256
