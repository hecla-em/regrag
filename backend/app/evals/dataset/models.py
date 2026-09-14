"""Dataset values: the authored cases, and the corpus they were authored against."""

import hashlib
from collections import Counter
from datetime import date
from pathlib import Path

from pydantic import model_validator

from app.core.config import config
from app.core.models import FrozenModel
from app.evals.dataset.enums import DriftKind, EvalKind, EvalTrait
from app.evals.dataset.exceptions import EmptyDatasetError
from app.retrieval.models import ReferenceTarget

UNSCORED_FIELDS = {
    "cases": {"__all__": {"traits": True, "references": {"__all__": {"content_hashes"}}}}
}
"""What the dataset hash leaves out: the stamps record the corpus and the traits say what a
case tests, and neither is anything a run scores."""


class CaseReference(ReferenceTarget):
    """A cited division, stamped with the chunks that covered it when the case was authored.
    No hashes means unstamped, which is a different fact from stamped and unchanged."""

    content_hashes: tuple[str, ...] = ()


class DriftedReference(FrozenModel):
    """A case reference the corpus no longer answers to as it did when the case was authored."""

    case_id: str
    target: CaseReference
    kind: DriftKind


class CorpusStamp(FrozenModel):
    """The corpus the cases were authored against, so a run says which text it scored."""

    corpus_version: str | None = None
    stamped_at: date


class EvalCase(FrozenModel):
    """A question, what a right answer must say, and where in the corpus it comes from."""

    id: str
    kind: EvalKind
    traits: tuple[EvalTrait, ...] = ()
    question: str
    answer: str | None = None
    references: tuple[CaseReference, ...] = ()

    @model_validator(mode="after")
    def _kind_matches_fields(self) -> "EvalCase":
        """An in-corpus case is scored against its answer and references; an out-of-corpus case
        is scored on refusal alone, so carrying either would be a mislabelled case."""
        has_evidence = bool(self.references) and self.answer is not None
        if self.kind is EvalKind.IN_CORPUS and not has_evidence:
            raise ValueError(f"{self.id}: an in_corpus case needs an answer and references")
        if self.kind is EvalKind.OUT_OF_CORPUS and (self.references or self.answer):
            raise ValueError(f"{self.id}: an out_of_corpus case has neither answer nor references")
        return self


class CaseSelection(FrozenModel):
    """Which cases a run scores: every case, or those matching every criterion given."""

    id_contains: str | None = None
    trait: EvalTrait | None = None
    kind: EvalKind | None = None

    def selects(self, case: EvalCase) -> bool:
        """Whether the case meets every criterion set."""
        return (
            (self.id_contains is None or self.id_contains in case.id)
            and (self.trait is None or self.trait in case.traits)
            and (self.kind is None or self.kind is case.kind)
        )

    def describe(self) -> str:
        """The criteria set as `name=value` pairs, or 'every case' when none is."""
        criteria = {name: value for name, value in self.model_dump().items() if value is not None}
        if not criteria:
            return "every case"
        return " ".join(f"{name}={value}" for name, value in criteria.items())


class EvalDataset(FrozenModel):
    """The golden dataset: every authored case, the corpus stamp they share, and the
    selection naming the subset a run scores."""

    corpus: CorpusStamp | None = None
    cases: tuple[EvalCase, ...]
    selection: CaseSelection = CaseSelection()
    """Chosen per run rather than read from the file, so it is not written back out."""

    @classmethod
    def load(
        cls, path: Path = config.EVAL_DATASET_PATH, selection: CaseSelection | None = None
    ) -> "EvalDataset":
        """Read and validate the JSON file at path, selecting every case unless told which."""
        dataset = cls.model_validate_json(path.read_bytes())
        if not dataset.cases:
            raise EmptyDatasetError("The dataset has no cases")

        selection = selection or CaseSelection()
        dataset = dataset.model_copy(update={"selection": selection})
        if not dataset.selected_cases:
            raise EmptyDatasetError(f"No cases found matching selection: {selection.describe()}")
        return dataset

    @property
    def selected_cases(self) -> tuple[EvalCase, ...]:
        """The cases a run scores: those the selection selects, which is every case by default."""
        return tuple(case for case in self.cases if self.selection.selects(case))

    @property
    def sha256(self) -> str:
        """Hash of what the cases assert — the whole dataset however a run filters it, with
        the stamps and untouched defaults left out, so neither a re-stamp nor a new optional
        field can break comparability with past runs."""
        scored = self.model_dump_json(
            include={"cases"}, exclude=UNSCORED_FIELDS, exclude_defaults=True
        )
        return hashlib.sha256(scored.encode()).hexdigest()

    @model_validator(mode="after")
    def _ids_are_unique(self) -> "EvalDataset":
        """A case id is how a result names its case, so two cases cannot share one."""
        counts = Counter(case.id for case in self.cases)
        duplicates = sorted(id for id, seen in counts.items() if seen > 1)
        if duplicates:
            raise ValueError(f"duplicate case ids: {', '.join(duplicates)}")
        return self
