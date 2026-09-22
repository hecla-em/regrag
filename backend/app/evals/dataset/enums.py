"""Dataset enumerations."""

from enum import StrEnum


class EvalKind(StrEnum):
    """What a case tests: that the corpus answers it, or that the graph refuses it."""

    IN_CORPUS = "in_corpus"
    OUT_OF_CORPUS = "out_of_corpus"


class EvalTrait(StrEnum):
    """What makes a case a test of something beyond plain retrieval; a case may hold several,
    and references, not traits, decide what is scored.

    MULTI_HOP: the answer sits a chain of citations away from where search lands.
    MULTI_PART: the question asks more than one thing.
    DATASET: the answer needs a figure from a dataset tool, so a case may name no corpus reference.
    """

    MULTI_HOP = "multi_hop"
    MULTI_PART = "multi_part"
    DATASET = "dataset"


class DriftKind(StrEnum):
    """How far a case reference has come adrift of the corpus it was authored against.

    UNRESOLVED: hard drift — no stored chunk answers to it, so a run scores a retrieval miss.
    STALE: soft drift — the cited text changed, so a run scores green against an unreviewed answer.
    UNSTAMPED: nothing recorded to compare against, so drift cannot be seen on it at all.
    """

    UNRESOLVED = "unresolved"
    STALE = "stale"
    UNSTAMPED = "unstamped"
