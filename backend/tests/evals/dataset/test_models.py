"""The golden dataset: what a case must carry, and what the dataset hash covers."""

from typing import Any

import pytest
from pydantic import ValidationError

from app.evals.dataset.enums import EvalKind, EvalTrait
from app.evals.dataset.models import CaseReference, CorpusStamp, EvalDataset
from tests.evals.conftest import eval_case, eval_dataset

STAMPED = CaseReference(celex="32023R1805", article="4", content_hashes=("a" * 12, "b" * 12))
ELSEWHERE = CaseReference(celex="32023R1805", article="9")
CORPUS = CorpusStamp(corpus_version="2026-08-15-2cc038d", stamped_at="2026-08-28")


@pytest.mark.parametrize(
    "fields",
    [
        pytest.param({"references": ()}, id="an in-corpus case needs references"),
        pytest.param({"answer": None}, id="an in-corpus case needs an answer"),
        pytest.param(
            {"kind": EvalKind.OUT_OF_CORPUS, "answer": None},
            id="an out-of-corpus case carries no references",
        ),
        pytest.param(
            {"kind": EvalKind.OUT_OF_CORPUS, "references": ()},
            id="an out-of-corpus case carries no answer",
        ),
    ],
)
def test_a_case_carrying_more_or_less_than_its_kind_is_scored_on_is_rejected(
    fields: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        eval_case(**fields)


@pytest.mark.parametrize(
    ("dataset", "same_hash"),
    [
        pytest.param(eval_dataset(eval_case()), True, id="the same cases built again"),
        pytest.param(eval_dataset(eval_case(answer="b")), False, id="a changed answer moves it"),
        pytest.param(
            eval_dataset(eval_case(references=(ELSEWHERE,))),
            False,
            id="so does citing another division",
        ),
        pytest.param(
            eval_dataset(eval_case(references=(STAMPED,))),
            True,
            id="a reference's stamp does not",
        ),
        pytest.param(
            eval_dataset(eval_case(traits=(EvalTrait.MULTI_PART,))), True, id="nor does a trait"
        ),
        pytest.param(
            eval_dataset(eval_case()).model_copy(update={"corpus": CORPUS}),
            True,
            id="nor the corpus stamp",
        ),
        pytest.param(
            eval_dataset(eval_case(), id_contains="fueleu"),
            True,
            id="nor the subset a run selects",
        ),
    ],
)
def test_the_dataset_hash_follows_what_the_cases_assert_and_nothing_else(
    dataset: EvalDataset, same_hash: bool
) -> None:
    """A re-stamp, a trait or a filter changes nothing a run scores, so each must leave past
    runs of the same cases comparable."""
    assert (dataset.sha256 == eval_dataset(eval_case()).sha256) is same_hash
