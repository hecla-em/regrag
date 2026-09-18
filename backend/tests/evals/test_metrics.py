"""Eval scoring: what counts as a retrieved reference, a correct citation, a refusal."""

import pytest

from app.chat.enums import ChatNode
from app.chat.models import ChatStepResult
from app.evals.judge.enums import JudgeVerdict
from app.evals.judge.models import CaseJudgement, CorrectnessVerdict
from app.evals.metrics import (
    compute_assess_refusal_rate,
    compute_cited_references,
    compute_context_metrics,
    compute_correctness,
    compute_expanded_hit_rate,
    compute_expanded_recall,
    compute_faithfulness,
    compute_gate_refusal_rate,
    compute_markers_in_context,
    compute_mean_step_ms,
    compute_metrics,
    compute_model_refusal_rate,
    compute_raw_recall,
    compute_usage,
    count_answers_with_prompt_wording,
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
from app.retrieval.models import ReferenceTarget
from tests.conftest import REPORTED_USAGE, retrieved_chunk, search_result
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


def test_recall_counts_a_gold_article_the_chunks_cover() -> None:
    assert score_reference_recall((ARTICLE_4,), (retrieved_chunk(),)) == 1.0


def test_recall_is_the_share_of_gold_references_retrieved() -> None:
    assert score_reference_recall((ARTICLE_4, ARTICLE_20), (retrieved_chunk(),)) == 0.5


def test_recall_ignores_the_paragraph_a_chunk_sits_in() -> None:
    """Gold cites Article 4; the chunk is Article 4(1). The ticket scores at article grain."""
    chunk = retrieved_chunk(citation="Article 4(1)", article="4")

    assert score_reference_recall((ARTICLE_4,), (chunk,)) == 1.0


def test_recall_matches_an_article_whatever_its_case() -> None:
    gold = ReferenceTarget(celex="32023R1805", article="4a")
    chunk = retrieved_chunk(article="4A")

    assert score_reference_recall((gold,), (chunk,)) == 1.0


def test_recall_matches_an_annex_target_that_has_no_article() -> None:
    chunk = retrieved_chunk(article=None, annex="IV", citation="Annex IV")

    assert score_reference_recall((ANNEX_IV,), (chunk,)) == 1.0


def test_an_unnumbered_annex_does_not_match_a_chunk_outside_every_annex() -> None:
    """Locator documents "" as the act's one unnumbered annex — a different fact from None,
    which no truthiness test may fold together."""
    unnumbered = ReferenceTarget(celex="32023R1805", annex="")
    outside = retrieved_chunk(article=None, annex=None, citation="Preamble")

    assert score_reference_recall((unnumbered,), (outside,)) == 0.0
    assert score_reference_recall((unnumbered,), (retrieved_chunk(article=None, annex=""),)) == 1.0


def test_recall_compares_an_annex_exactly_as_follow_does() -> None:
    """`follow._targeted` case-folds the article but matches the annex exactly, so scoring
    must too — otherwise `check` calls a reference stale that `run` calls recalled."""
    chunk = retrieved_chunk(article=None, annex="iv", citation="Annex iv")

    assert score_reference_recall((ANNEX_IV,), (chunk,)) == 0.0


def test_recall_does_not_match_the_right_division_of_another_act() -> None:
    chunk = retrieved_chunk(celex="32015R0757", article="4")

    assert score_reference_recall((ARTICLE_4,), (chunk,)) == 0.0


def test_recall_is_zero_when_nothing_was_retrieved() -> None:
    assert score_reference_recall((ARTICLE_4,), ()) == 0.0


def test_every_authored_reference_cited_scores_one() -> None:
    sources = (retrieved_chunk(),)

    assert score_reference_citation_rate("Half of it [1].", sources, (ARTICLE_4,)) == 1.0


def test_citing_a_further_relevant_article_is_not_penalised() -> None:
    """The authored set names the references an answer must lean on, not every chunk that
    may support it, so an extra citation must not read as a wrong one."""
    sources = (retrieved_chunk(), retrieved_chunk(id=2, article="99", citation="Article 99"))

    assert score_reference_citation_rate("Both [1][2].", sources, (ARTICLE_4,)) == 1.0


def test_the_reference_citation_rate_is_the_share_of_authored_references_cited() -> None:
    sources = (retrieved_chunk(), retrieved_chunk(id=2, article="20", citation="Article 20"))

    assert score_reference_citation_rate("One [1].", sources, (ARTICLE_4, ARTICLE_20)) == 0.5


def test_an_answer_citing_none_of_the_authored_references_scores_zero() -> None:
    sources = (retrieved_chunk(id=2, article="99", citation="Article 99"),)

    assert score_reference_citation_rate("Elsewhere [1].", sources, (ARTICLE_4,)) == 0.0


def test_the_reference_citation_rate_is_unmeasured_when_a_case_names_no_reference() -> None:
    assert score_reference_citation_rate("Anything [1].", (retrieved_chunk(),), ()) is None


def test_validity_is_one_when_every_marker_addresses_a_given_block() -> None:
    assert score_citation_validity("Half of it [1].", (retrieved_chunk(),)) == 1.0


def test_a_marker_past_the_end_of_the_context_counts_against_validity() -> None:
    """The model cited a block it was never given, so the citation is wrong, not skipped."""
    assert score_citation_validity("Claims [1] and [7].", (retrieved_chunk(),)) == 0.5


def test_citation_validity_is_unmeasured_when_the_answer_cites_nothing() -> None:
    assert score_citation_validity("No markers here.", (retrieved_chunk(),)) is None


# Run metrics: each a plain function over the run's results


OTHER_CHUNK = {"id": 2, "article": "99", "citation": "Article 99"}


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


def test_an_errored_case_is_counted_but_left_out_of_the_scores() -> None:
    """A provider blip must not read as a retrieval regression."""
    results = (eval_result(), eval_result(eval_case(id="boom"), hits=(), sources=(), error="x"))

    assert count_errors(results) == 1
    assert compute_expanded_hit_rate(results) == 1.0


def test_an_errored_case_still_counts_toward_the_kind_it_was_authored_as() -> None:
    """The dataset's shape is what it is; an error is reported beside the counts rather
    than by shrinking them, so a run stays comparable to a clean one."""
    boom = eval_result(eval_case(id="boom"), hits=(), sources=(), error="x")

    counts = compute_metrics((eval_result(), boom)).counts

    assert (counts.cases, counts.in_corpus, counts.out_of_corpus, counts.errors) == (2, 2, 0, 1)


def test_a_kind_absent_from_the_run_scores_none_rather_than_zero() -> None:
    only_ooc = (refused_result(),)

    assert compute_expanded_hit_rate(only_ooc) is None
    assert compute_gate_refusal_rate(only_ooc) == 1.0
    assert compute_gate_refusal_rate((eval_result(),)) is None


def test_a_refusal_is_read_from_the_node_path_not_the_wording() -> None:
    """The graph says which node answered; synthesize ran for the second case, so the model
    declined in its own words — the judge's to score, not the gate's."""
    declined = eval_result(answer="The context provided does not cover ETS allowances.")

    assert compute_gate_refusal_rate((refused_result(),)) == 1.0
    assert count_false_refusals((declined,)) == 0


def test_an_in_corpus_refusal_over_hits_holding_the_reference_is_the_gate_too_tight() -> None:
    too_tight = refused_result(eval_case(), hits=(search_result(),))
    genuine_miss = refused_result(eval_case(id="miss"), hits=(search_result(**OTHER_CHUNK),))

    assert count_false_refusals((too_tight, genuine_miss)) == 2
    assert count_refusals_of_a_found_reference((too_tight, genuine_miss)) == 1


def test_a_run_cut_short_is_read_off_empty_sources_rather_than_a_refusal() -> None:
    """A retrieval-only run stops before the graph routes, so it records no refusal to read;
    the gate's mark is the empty context it left."""
    retrieval_only = refused_result(
        steps=(ChatStepResult(step=ChatNode.RETRIEVE, ms=80),), refusal=None, answer=""
    )

    assert compute_gate_refusal_rate([retrieval_only]) == 1.0


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


def test_a_refusal_after_assess_is_the_loops_not_the_gates() -> None:
    """The gate acts before any model call; a refusal assess asked for is scored apart, so
    the two rates say which of the two shut the question out."""
    results = (assess_refused_result(),)

    assert compute_gate_refusal_rate(results) == 0.0
    assert compute_assess_refusal_rate(results) == 1.0


def test_a_gate_refusal_is_not_the_loops() -> None:
    results = (refused_result(),)

    assert compute_assess_refusal_rate(results) == 0.0
    assert count_assess_false_refusals((refused_result(eval_case()),)) == 0


def test_an_in_corpus_case_assess_refused_is_a_false_refusal_of_the_loops() -> None:
    results = (assess_refused_result(eval_case()),)

    assert count_assess_false_refusals(results) == 1
    assert count_false_refusals(results) == 0


def test_the_loops_refusal_rate_is_unmeasured_without_out_of_corpus_cases() -> None:
    assert compute_assess_refusal_rate((eval_result(),)) is None


def test_citation_metrics_average_over_the_cases_that_measure() -> None:
    """A refusal cites nothing, so it is unmeasured rather than a zero dragging the mean."""
    results = (eval_result(answer="Yes [1] and [9]."), eval_result(), refused_result())

    assert compute_cited_references(results) == 1.0
    assert compute_markers_in_context(results) == 0.75


def test_a_case_that_wrote_no_answer_leaves_the_citation_rate_unmeasured() -> None:
    """A retrieval-only or gate-refused in-corpus case has nothing to cite with, so it is
    unmeasured rather than a zero that reads as an answer citing nothing."""
    retrieval_only = eval_result(steps=(ChatStepResult(step=ChatNode.RETRIEVE, ms=80),), answer="")
    refused = refused_result(eval_case())

    assert compute_cited_references((retrieval_only, refused)) is None
    assert compute_cited_references((retrieval_only, refused, eval_result())) == 1.0


def test_node_ms_is_averaged_over_the_cases_that_ran_the_node() -> None:
    results = (eval_result(), refused_result())

    assert compute_mean_step_ms(results) == {"retrieve": 90, "synthesize": 900, "refuse": 0}


def test_tokens_and_cost_are_summed_over_the_run() -> None:
    results = (eval_result(), eval_result(), refused_result())

    assert compute_usage(results) == REPORTED_USAGE + REPORTED_USAGE


def test_compute_metrics_assembles_every_block_of_the_run() -> None:
    metrics = compute_metrics((eval_result(), refused_result()))

    assert (metrics.counts.cases, metrics.counts.in_corpus, metrics.counts.out_of_corpus) == (
        2,
        1,
        1,
    )
    assert metrics.retrieval.raw_recall == 1.0
    assert metrics.gate.refusal_rate == 1.0
    assert metrics.assess.refusal_rate == 0.0
    assert metrics.latency.mean_total_ms == 542


def test_a_run_that_synthesized_over_empty_sources_is_not_counted_refused() -> None:
    """The metric observes the branch the graph took; recomputing the route would score a
    routing bug as the refusal it should have been."""
    routed_wrong = eval_result(sources=())

    assert count_false_refusals((routed_wrong,)) == 0


def test_a_run_that_refused_over_sources_is_counted_refused() -> None:
    refused_anyway = refused_result(sources=(retrieved_chunk(),))

    assert compute_gate_refusal_rate((refused_anyway,)) == 1.0


def test_context_cost_averages_scored_in_corpus_cases_only() -> None:
    """A refusal builds no context, so it must not drag the mean toward zero."""
    result = eval_result()
    context = compute_context_metrics((result, refused_result()))

    assert context.mean_context_chunks == 1.0
    assert context.mean_context_chars == float(len(result.state.sources[0].text))


def test_no_cases_leaves_the_context_cost_unmeasured() -> None:
    context = compute_context_metrics(())

    assert context.mean_context_chunks is None
    assert context.mean_context_chars is None


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


def test_an_unjudged_run_leaves_the_judged_metrics_unmeasured() -> None:
    judge = compute_metrics((eval_result(), refused_result())).judge

    assert judge.correctness is None
    assert judge.faithfulness is None
    assert judge.refusal_rate is None
    assert judge.judged == 0


def test_an_errored_case_is_not_judged_whatever_it_carries() -> None:
    results = (eval_result(judgement=passed_judgement(), error="TimeoutError"),)

    assert count_judged(results) == 0
    assert compute_correctness(results) is None


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


def test_answers_with_prompt_wording_are_counted_once_each() -> None:
    results = (
        eval_result(answer="The context is silent. The provided context too."),
        eval_result(),
        refused_result(),
    )

    assert count_answers_with_prompt_wording(results) == 1
    assert compute_metrics(results).answers.prompt_wording == 1
