"""Eval scoring: what counts as a retrieved reference, a correct citation, a refusal."""

import pytest

from app.chat.enums import ChatNode
from app.chat.models import ChatStepResult
from app.evals.judge.enums import JudgeVerdict
from app.evals.judge.models import CaseJudgement, CorrectnessVerdict
from app.evals.metrics import (
    compute_assess_refusal_rate,
    compute_case_counts,
    compute_cited_references,
    compute_context_metrics,
    compute_correctness,
    compute_expanded_hit_rate,
    compute_expanded_recall,
    compute_faithfulness,
    compute_gate_refusal_rate,
    compute_markers_in_context,
    compute_mean_step_ms,
    compute_model_refusal_rate,
    compute_raw_recall,
    count_assess_false_refusals,
    count_errors,
    count_false_refusals,
    count_judged,
    count_refusals_of_a_found_reference,
    find_prompt_wording,
    score_citation_validity,
    score_reference_citation_rate,
    score_reference_recall,
)
from app.evals.models import CaseCounts, EvalCaseResult
from app.retrieval.models import ReferenceTarget
from tests.conftest import retrieved_chunk, search_result
from tests.evals.conftest import (
    assess_refused_result,
    eval_case,
    eval_result,
    failed_judgement,
    out_of_corpus_case,
    passed_judgement,
    refusal_judgement,
    refused_result,
)

ARTICLE_4 = ReferenceTarget(celex="32023R1805", article="4")
ARTICLE_20 = ReferenceTarget(celex="32023R1805", article="20")
ANNEX_IV = ReferenceTarget(celex="32023R1805", annex="IV")
UNNUMBERED_ANNEX = ReferenceTarget(celex="32023R1805", annex="")
OTHER_CHUNK = {"id": 3, "article": "99", "citation": "Article 99"}


@pytest.mark.parametrize(
    ("targets", "chunk", "recall"),
    [
        pytest.param((ARTICLE_4,), {}, 1.0, id="a chunk of the article covers it"),
        pytest.param(
            (ARTICLE_4, ARTICLE_20), {}, 0.5, id="recall is the share of references retrieved"
        ),
        pytest.param(
            (ReferenceTarget(celex="32023R1805", article="4a"),),
            {"article": "4A"},
            1.0,
            id="an article matches whatever its case",
        ),
        pytest.param(
            (ANNEX_IV,), {"article": None, "annex": "IV"}, 1.0, id="an annex needs no article"
        ),
        pytest.param(
            (ANNEX_IV,), {"article": None, "annex": "iv"}, 0.0, id="an annex matches exactly"
        ),
        pytest.param(
            (UNNUMBERED_ANNEX,),
            {"article": None, "annex": ""},
            1.0,
            id="an unnumbered annex matches an unnumbered annex",
        ),
        pytest.param(
            (UNNUMBERED_ANNEX,),
            {"article": None, "annex": None},
            0.0,
            id="an unnumbered annex is not a chunk outside every annex",
        ),
        pytest.param(
            (ARTICLE_4,), {"celex": "32015R0757"}, 0.0, id="the same article of another act"
        ),
    ],
)
def test_recall_matches_a_reference_as_follow_does(
    targets: tuple[ReferenceTarget, ...], chunk: dict, recall: float
) -> None:
    """Article case-folded, annex verbatim and "" apart from None, or `check` calls a
    reference stale that `run` calls recalled."""
    assert score_reference_recall(targets, (retrieved_chunk(**chunk),)) == recall


@pytest.mark.parametrize(
    ("answer", "targets", "rate"),
    [
        pytest.param("Half [1].", (ARTICLE_4,), 1.0, id="every authored reference cited"),
        pytest.param("Both [1][3].", (ARTICLE_4,), 1.0, id="a further citation is not penalised"),
        pytest.param(
            "One [1].", (ARTICLE_4, ARTICLE_20), 0.5, id="the share of authored references cited"
        ),
        pytest.param("Elsewhere [3].", (ARTICLE_4,), 0.0, id="none of them cited"),
        pytest.param("Anything [1].", (), None, id="unmeasured when the case names none"),
    ],
)
def test_the_citation_rate_is_scored_over_the_authored_references(
    answer: str, targets: tuple[ReferenceTarget, ...], rate: float | None
) -> None:
    sources = (
        retrieved_chunk(),
        retrieved_chunk(id=2, article="20", citation="Article 20"),
        retrieved_chunk(**OTHER_CHUNK),
    )

    assert score_reference_citation_rate(answer, sources, targets) == rate


@pytest.mark.parametrize(
    ("answer", "validity"),
    [
        pytest.param("Half of it [1].", 1.0, id="every marker addresses a given block"),
        pytest.param("Claims [1] and [7].", 0.5, id="a marker past the context counts against it"),
        pytest.param("No markers here.", None, id="unmeasured when the answer cites nothing"),
    ],
)
def test_citation_validity_is_the_share_of_markers_addressing_a_given_block(
    answer: str, validity: float | None
) -> None:
    assert score_citation_validity(answer, (retrieved_chunk(),)) == validity


# Run metrics: each a plain function over the run's results


def test_raw_and_expanded_recall_are_scored_apart() -> None:
    """Expansion found the authored reference the raw hits missed; each layer is credited
    with what it found."""
    results = (
        eval_result(
            hits=(search_result(**OTHER_CHUNK),),
            sources=(retrieved_chunk(**OTHER_CHUNK), retrieved_chunk()),
        ),
    )

    assert compute_raw_recall(results) == 0.0
    assert compute_expanded_recall(results) == 1.0


def test_hit_rate_and_recall_diverge_on_a_half_served_multi_reference_case() -> None:
    """The whole reason both are reported: one case found 1 of its 2 authored references."""
    half = eval_result(eval_case(id="two-refs", references=(ARTICLE_4, ARTICLE_20)))
    results = (eval_result(), half)

    assert compute_expanded_hit_rate(results) == 1.0
    assert compute_expanded_recall(results) == 0.75


ERRORED = eval_result(
    eval_case(id="boom"), judgement=failed_judgement(), hits=(), sources=(), error="x"
)


@pytest.mark.parametrize(
    ("measure", "value"),
    [
        pytest.param(count_errors, 1, id="it is counted as an error"),
        pytest.param(
            compute_case_counts,
            CaseCounts(cases=2, in_corpus=2, out_of_corpus=0, errors=1),
            id="it still counts toward the kind it was authored as",
        ),
        pytest.param(compute_expanded_hit_rate, 1.0, id="its empty retrieval is not a miss"),
        pytest.param(count_judged, 1, id="it is not judged whatever it carries"),
        pytest.param(compute_correctness, 1.0, id="its failed verdict is not a failed answer"),
    ],
)
def test_an_errored_case_is_counted_but_left_out_of_the_averages(measure, value) -> None:
    """A provider blip must not read as a regression, and the dataset's shape is what it is."""
    results = (eval_result(judgement=passed_judgement()), ERRORED)

    assert measure(results) == value


def test_a_kind_absent_from_the_run_scores_none_rather_than_zero() -> None:
    only_ooc = (refused_result(),)

    assert compute_expanded_hit_rate(only_ooc) is None
    assert compute_gate_refusal_rate(only_ooc) == 1.0
    assert compute_gate_refusal_rate((eval_result(),)) is None


RETRIEVAL_ONLY = (ChatStepResult(step=ChatNode.RETRIEVE, ms=80),)
"""The path of a run cut short before the graph routes, which records no refusal."""


@pytest.mark.parametrize(
    ("result", "refused"),
    [
        pytest.param(
            eval_result(out_of_corpus_case(), answer="The context does not cover allowances."),
            False,
            id="an answer declining in its own words is the judge's to score",
        ),
        pytest.param(
            eval_result(out_of_corpus_case(), sources=()),
            False,
            id="an answer synthesized over empty sources was not refused",
        ),
        pytest.param(
            refused_result(sources=(retrieved_chunk(),)),
            True,
            id="a recorded refusal over sources was",
        ),
        pytest.param(
            refused_result(steps=RETRIEVAL_ONLY, refusal=None, answer=""),
            True,
            id="a retrieval-only run records none, so its empty sources are the mark",
        ),
    ],
)
def test_a_gate_refusal_is_read_off_the_record_not_the_sources_or_the_wording(
    result: EvalCaseResult, refused: bool
) -> None:
    """The metric observes the branch the graph took, as recomputing the route would score
    a routing bug as the refusal it should have been."""
    assert compute_gate_refusal_rate((result,)) == float(refused)


@pytest.mark.parametrize(
    ("result", "refusal_rates", "false_refusals"),
    [
        pytest.param(
            assess_refused_result(), (0.0, 1.0), (0, 0), id="out of corpus, refused by assess"
        ),
        pytest.param(refused_result(), (1.0, 0.0), (0, 0), id="out of corpus, refused at the gate"),
        pytest.param(
            assess_refused_result(eval_case()), (None, None), (0, 1), id="in corpus, by assess"
        ),
        pytest.param(
            refused_result(eval_case()), (None, None), (1, 0), id="in corpus, at the gate"
        ),
    ],
)
def test_a_refusal_is_scored_to_the_gate_or_to_assess_and_never_both(
    result: EvalCaseResult,
    refusal_rates: tuple[float | None, float | None],
    false_refusals: tuple[int, int],
) -> None:
    """Gate first, assess second in each pair: the two say which of them shut a question out."""
    results = (result,)
    rates = (compute_gate_refusal_rate(results), compute_assess_refusal_rate(results))
    counts = (count_false_refusals(results), count_assess_false_refusals(results))

    assert rates == refusal_rates
    assert counts == false_refusals


def test_an_in_corpus_refusal_over_hits_holding_the_reference_is_the_gate_too_tight() -> None:
    too_tight = refused_result(eval_case(), hits=(search_result(),))
    genuine_miss = refused_result(eval_case(id="miss"), hits=(search_result(**OTHER_CHUNK),))

    assert count_false_refusals((too_tight, genuine_miss)) == 2
    assert count_refusals_of_a_found_reference((too_tight, genuine_miss)) == 1


def test_a_case_answered_without_retrieval_never_met_the_gate_or_the_loop() -> None:
    from_memory = eval_result(
        out_of_corpus_case(),
        steps=(ChatStepResult(step=ChatNode.SYNTHESIZE, ms=900),),
        hits=(),
        sources=(),
        answer="No act covers that.",
    )

    assert compute_gate_refusal_rate((from_memory,)) is None
    assert compute_assess_refusal_rate((from_memory,)) is None


def test_citation_metrics_average_over_the_cases_that_measure() -> None:
    """A refusal cites nothing, so it is unmeasured rather than a zero dragging the mean."""
    results = (eval_result(answer="Yes [1] and [9]."), eval_result(), refused_result())

    assert compute_cited_references(results) == 1.0
    assert compute_markers_in_context(results) == 0.75


def test_a_case_that_wrote_no_answer_leaves_the_citation_rate_unmeasured() -> None:
    """A retrieval-only or gate-refused in-corpus case has nothing to cite with, so it is
    unmeasured rather than a zero that reads as an answer citing nothing."""
    retrieval_only = eval_result(steps=RETRIEVAL_ONLY, answer="")
    refused = refused_result(eval_case())

    assert compute_cited_references((retrieval_only, refused)) is None
    assert compute_cited_references((retrieval_only, refused, eval_result())) == 1.0


def test_node_ms_is_averaged_over_the_cases_that_ran_the_node() -> None:
    results = (eval_result(), refused_result())

    assert compute_mean_step_ms(results) == {"retrieve": 90, "synthesize": 900, "refuse": 0}


def test_context_cost_averages_scored_in_corpus_cases_only() -> None:
    """A refusal builds no context, so it must not drag the mean toward zero."""
    result = eval_result()
    context = compute_context_metrics((result, refused_result()))

    assert context.mean_context_chunks == 1.0
    assert context.mean_context_chars == float(len(result.state.sources[0].text))


# Judged metrics


def test_correctness_is_the_pass_share_of_the_judged_answers() -> None:
    results = (eval_result(judgement=passed_judgement()), eval_result(judgement=failed_judgement()))

    assert compute_correctness(results) == 0.5


def test_a_case_the_judge_could_not_judge_is_left_out_not_failed() -> None:
    undecided = CaseJudgement(
        correctness=CorrectnessVerdict(critique="", verdict=JudgeVerdict.CANNOT_JUDGE)
    )
    results = (eval_result(judgement=passed_judgement()), eval_result(judgement=undecided))

    assert compute_correctness(results) == 1.0
    assert count_judged(results) == 2


def test_faithfulness_is_the_mean_supported_share() -> None:
    results = (eval_result(judgement=passed_judgement()), eval_result(judgement=failed_judgement()))

    assert compute_faithfulness(results) == 0.75


def test_model_refusal_rate_is_scored_over_the_judged_out_of_corpus_answers() -> None:
    results = (
        eval_result(out_of_corpus_case("a"), judgement=refusal_judgement()),
        eval_result(out_of_corpus_case("b"), judgement=refusal_judgement(JudgeVerdict.FAIL)),
        refused_result(),
    )

    assert compute_model_refusal_rate(results) == 0.5
    assert compute_gate_refusal_rate(results) == 1 / 3


@pytest.mark.parametrize(
    "answer",
    [
        "The context does not explain how the plans relate.",
        "The provided context is silent on this.",
        "Based on the context provided, ships must report.",
        "The blocks do not say.",
        "The provided text does not cover it.",
        "If it means something else, the passages provided do not address it.",
    ],
)
def test_an_answer_naming_the_prompts_blocks_is_found(answer: str) -> None:
    assert find_prompt_wording(answer)


@pytest.mark.parametrize(
    "answer",
    [
        "The FuelEU Maritime and MRV texts do not say.[1]",
        "The passages I found do not give the formula, only that Annex IV holds it.[1]",
        "In the context of Article 5, a company must report.[1]",
        "The text of Annex II sets the factors.[2]",
    ],
)
def test_plain_english_is_not_prompt_wording(answer: str) -> None:
    assert find_prompt_wording(answer) == ()
