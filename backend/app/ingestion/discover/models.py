"""What discovery found: one candidate act, and the document it selects.

An *act* is a regulation, directive or decision — the EU's collective word for a piece of
legislation. Discovery reads acts out of CELLAR; the rest of the pipeline handles documents.
"""

from app.core.models import FrozenModel


class ActsQueryRow(FrozenModel):
    """One line of CELLAR's answer: an act, and one consolidated text including it.

    celex: the act this line is about; an act repeats across one line per consolidation.
    in_force: whether the act is still law; None where there is no flag, as on anything not law.
    consolidation: one consolidated text including the act, or None if it has never been one.
    title: the act's official English title, or None where CELLAR has no English text of it.
    """

    celex: str
    in_force: bool | None = None
    consolidation: str | None = None
    title: str | None = None


class CandidateAct(FrozenModel):
    """One act the topic query returned, before select.py decides whether it is worth fetching.

    celex: the act, folded from every line CELLAR returned for it.
    in_force: the flag those lines repeat; None where the act is not law.
    consolidations: every consolidated text including the act, its own and those of other acts
        that folded it in as an amendment.
    title: the official English title those lines repeat; None where CELLAR has none.
    """

    celex: str
    in_force: bool | None = None
    consolidations: frozenset[str] = frozenset()
    title: str | None = None


class DiscoveredDocument(FrozenModel):
    """One document discovery found: what to fetch, and which version to try first.

    topic: the topic query that returned the act.
    source: the corpus it came from; every act is currently EUR-Lex.
    celex: the act itself, which never changes.
    candidates: every consolidated text CELLAR claims for the act, newest first, empty if it was
        never consolidated. Only candidates because only fetch learns which CELLAR serves: it
        mints an id when the act is published, but no text is rendered until one is amended in.
    title: the act's official English title, what the chat names it by; None where CELLAR
        has none, which leaves the act named by its number alone.
    """

    topic: str
    source: str
    celex: str
    candidates: tuple[str, ...]
    title: str | None = None

    @property
    def versions(self) -> list[str]:
        """This document's versions, newest first: its consolidations, then the original act."""
        return [*self.candidates, self.celex]
