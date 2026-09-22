"""The judge's fixed wording: one rubric per dimension, and the turn each is shown."""

from collections.abc import Sequence

from app.chat.blocks import ContextBlock
from app.chat.citations import find_cited_sources
from app.chat.prompts import format_context_block

CORRECTNESS_PROMPT = (
    "You grade an answer to a question about EU maritime regulation against a reference "
    "answer written by a domain expert. The reference is the standard. Judge whether the "
    "answer conveys the same facts: the same rule, the same figures, dates and thresholds, "
    "and the same act or article wherever the reference names one. Judge meaning, not "
    "wording; a paraphrase that keeps the facts passes. Extra correct detail is not a "
    "fault. The answer fails when it misses a fact the reference treats as the point of "
    "the answer, states a wrong figure or date, contradicts the reference, or names an act "
    "or article the reference does not support. Write the critique first: what the answer "
    "gets right, then what it misses or gets wrong. Then give the verdict: pass, fail, or "
    "cannot_judge when the reference itself does not settle the question. On a fail, name "
    "the failure: missing_fact, wrong_figure, contradicts_reference, invented_name, or other."
)

FAITHFULNESS_PROMPT = (
    "You check an answer about EU maritime regulation against the numbered context blocks "
    "it cites. List every factual claim the answer makes, one claim per statement of a "
    "rule, figure, date, scope or obligation, and mark each supported only when a cited "
    "block states it or it follows directly from one. A claim the blocks do not cover is "
    "unsupported however plausible it is. Do not judge whether a claim is true, only "
    "whether the cited context backs it. Two things are not claims to check: a sentence "
    "saying the context does not cover something, and a fact the question itself supplies "
    "or that is common knowledge, such as which country a named port is in, used only to "
    "apply a cited rule to the question's own case. Write the critique first, then the "
    "claims."
)

REFUSAL_PROMPT = (
    "You check whether an assistant declined to answer a question. The assistant answers "
    "only from a corpus of EU maritime regulation, and the question here is one that "
    "corpus does not cover. Pass when the answer says, in its own words, that it cannot "
    "answer or that the material does not cover the question, even if it adds what it can "
    "say. Fail when it answers the question as asked, from general knowledge. Give "
    "cannot_judge only when the answer is unreadable. Write the critique first, then the "
    "verdict."
)


def build_correctness_message(question: str, reference: str, answer: str) -> str:
    return f"Question: {question}\n\nReference answer:\n{reference}\n\nAnswer:\n{answer}"


def format_cited_blocks(answer: str, sources: Sequence[ContextBlock]) -> str:
    """The blocks the answer cited, under the markers the answer used for them, so a [3]
    in the answer is a [3] in the context; a marker addressing no block is skipped."""
    return "\n\n".join(
        format_context_block(marker, source)
        for marker, source in find_cited_sources(answer, sources)
    )


def build_faithfulness_message(answer: str, sources: Sequence[ContextBlock]) -> str:
    return f"Cited context:\n\n{format_cited_blocks(answer, sources)}\n\nAnswer:\n{answer}"


def build_refusal_message(question: str, answer: str) -> str:
    return f"Question: {question}\n\nAnswer:\n{answer}"
