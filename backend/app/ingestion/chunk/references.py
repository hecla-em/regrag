"""Cross-reference extraction: find the mentions, then attribute each division to its instrument.

"Article 7 of Regulation X" is two mentions, not one: a division ("Article 7") and the
instrument that qualifies it. Divisions no instrument qualifies belong to this document.
The points a text lists are the other end of a point citation, so they are read here too.
"""

import re
from collections.abc import Iterator, Sequence

from app.core.models import FrozenModel
from app.ingestion import celex
from app.ingestion.chunk.models import Reference, format_citation

ORDINALS = ("first", "second", "third", "fourth", "fifth", "last")
SUBDIVISION = rf"point\s+\((?P<point>[0-9a-z]+)\)|(?:{'|'.join(ORDINALS)})\s+subparagraph"
"""A part named after the division it belongs to: 'point (e)', 'second subparagraph'. The point
is kept, since it is how one act borrows a definition from another."""

QUALIFIER = re.compile(rf"^(?:,\s*(?:{SUBDIVISION}),?)?\s+(?:of|to|in)\s+(?:that\s+|the\s+)?$")
"""What may sit between a division and the instrument qualifying it: the qualifier alone, or
a point or subparagraph of the division first — 'Article 3, point (e), of Regulation X'."""


class Mention(FrozenModel):
    """Where in the text one reference was found."""

    start: int
    end: int

    def qualifier_before(self, other: "Mention", text: str) -> re.Match[str] | None:
        """The qualifier ('of', 'to', 'in', with a point or subparagraph first) that alone
        separates this mention from the other, or None when more than that does."""
        if other.start < self.end:
            return None
        return QUALIFIER.match(text[self.end : other.start])


ARTICLE_REF = re.compile(r"Articles?\s+(\d+[a-z]?)(?:\((\d+[a-z]?)\))?")
ARTICLE_TAIL = re.compile(r"\s*(?:,|and)\s+(\d{1,3}[a-z]?)\b(?:\((\d+[a-z]?)\))?")
ANNEX_REF = re.compile(r"Annexe?s?\s+([IVXLC]+|\d+)")
ANNEX_TAIL = re.compile(r"\s*(?:,|and)\s+([IVXLC]{1,4}|\d{1,2})\b")


class DivisionMention(Mention):
    """A part of a law named in the text — 'Article 7', 'Article 7(2)', 'Annex I' — ending
    where its enumeration does."""

    reference: Reference


def _find_division_mentions(text: str) -> list[DivisionMention]:
    """Article and annex mentions in order of appearance."""
    found = _find_article_mentions(text) + _find_annex_mentions(text)
    return sorted(found, key=lambda division: division.start)


def _find_article_mentions(text: str) -> list[DivisionMention]:
    """One mention per article, each carrying the paragraph cited with it."""
    return [
        DivisionMention(
            start=member.start(),
            end=run_end,
            reference=Reference(
                raw=format_citation(article=member.group(1), paragraph=member.group(2)),
                article=member.group(1),
                paragraph=member.group(2),
            ),
        )
        for member, run_end in _find_enumerated_members(text, ARTICLE_REF, ARTICLE_TAIL)
    ]


def _find_annex_mentions(text: str) -> list[DivisionMention]:
    """One mention per annex; an annex is cited whole, so it carries no paragraph."""
    return [
        DivisionMention(
            start=member.start(),
            end=run_end,
            reference=Reference(raw=format_citation(annex=member.group(1)), annex=member.group(1)),
        )
        for member, run_end in _find_enumerated_members(text, ANNEX_REF, ANNEX_TAIL)
    ]


def _find_enumerated_members(
    text: str, head: re.Pattern[str], tail: re.Pattern[str]
) -> Iterator[tuple[re.Match[str], int]]:
    """Every member of every 'Articles 6, 7 and 8' run, with the offset its whole run ends at.

    Members share that offset because the instrument qualifying the run follows all of them.
    """
    for first in head.finditer(text):
        members = [first]
        while member := tail.match(text, members[-1].end()):
            members.append(member)
        for member in members:
            yield member, members[-1].end()


INSTRUMENT_REF = re.compile(
    r"(Regulation|Directive|Decision)\s*(?:\((?:EU|EC|EEC|Euratom)\)\s*)?(?:No\s*)?"
    r"(\d{1,4})/(\d{1,4})(?:/\w{2,7})?",
    re.IGNORECASE,
)

INSTITUTION_WORDS = (
    "Council",
    "Commission",
    "European",
    "Parliament",
    "Implementing",
    "Delegated",
    "Framework",
)
INSTITUTION_RUN = re.compile(
    rf"(?:(?:{'|'.join(INSTITUTION_WORDS)})(?:\s+(?:and|of|the))?\s+)+$", re.IGNORECASE
)


class InstrumentMention(Mention):
    """A whole law named in the text — 'Regulation (EU) 2015/757', 'Directive 2003/87/EC';
    celex is None where the citation cannot resolve to an id."""

    celex: str | None


def _mention_start(text: str, match: re.Match[str]) -> int:
    """Where the institution naming an act begins: 'Council Implementing Regulation ...'.

    Institution words combine freely, so a run of them leading into a citation belongs to
    it however the form is styled; the first word that names no institution ends the run.
    """
    run = INSTITUTION_RUN.search(text, 0, match.start())
    return run.start() if run else match.start()


def _find_instrument_mentions(text: str) -> list[InstrumentMention]:
    """Every instrument mention in order of appearance."""
    found: list[InstrumentMention] = []
    for match in INSTRUMENT_REF.finditer(text):
        kind = match.group(1)
        number, year = celex.order_number_and_year(kind, match.group(2), match.group(3))
        try:
            resolved = celex.build(kind, year, number)
        except ValueError:
            resolved = None
        start = _mention_start(text, match)
        found.append(InstrumentMention(start=start, end=match.end(), celex=resolved))
    return found


def _attribute_division(
    text: str, division: DivisionMention, owner: InstrumentMention, qualifier: re.Match[str]
) -> Reference:
    """A division re-pointed at the instrument qualifying it, its raw text stretched forward
    over the qualifier to cover that instrument, and carrying the point the qualifier named."""
    raw = division.reference.raw + text[division.end : owner.end]
    return division.reference.model_copy(
        update={"raw": raw, "instrument": owner.celex, "point": qualifier.group("point")}
    )


def _cite_unclaimed_instruments(
    text: str, instruments: Sequence[InstrumentMention], claimed: set[InstrumentMention]
) -> list[Reference]:
    """Instruments cited in their own right: the resolvable ones no division was attributed to."""
    return [
        Reference(raw=text[instrument.start : instrument.end], instrument=instrument.celex)
        for instrument in instruments
        if instrument.celex is not None and instrument not in claimed
    ]


def _find_owner(
    text: str, division: DivisionMention, instruments: Sequence[InstrumentMention]
) -> tuple[InstrumentMention, re.Match[str]] | None:
    """The first instrument a qualifier joins the division to, with that qualifier."""
    for owner in instruments:
        qualifier = division.qualifier_before(owner, text)
        if qualifier is not None:
            return owner, qualifier
    return None


def _references_from_mentions(
    text: str, divisions: Sequence[DivisionMention], instruments: Sequence[InstrumentMention]
) -> list[Reference]:
    """Every division under the instrument qualifying it, then the instruments none claimed.

    A division qualified by an unresolvable instrument is dropped: it is not this document's.
    """
    attributed: list[Reference] = []
    claimed: set[InstrumentMention] = set()
    for division in divisions:
        found = _find_owner(text, division, instruments)
        if found is None:
            attributed.append(division.reference)
            continue
        owner, qualifier = found
        if owner.celex is not None:
            claimed.add(owner)
            attributed.append(_attribute_division(text, division, owner, qualifier))
    return attributed + _cite_unclaimed_instruments(text, instruments, claimed)


POINT_LINE = re.compile(r"^\(([0-9a-z]+)\) ", re.MULTILINE)
"""A line opening with a point's label, '(e) ' or '(15) ', the way a definitions article
lists its terms."""


def list_points(text: str) -> tuple[str, ...]:
    """The points the text opens lines with: what a citation by point reaches."""
    return tuple(POINT_LINE.findall(text))


def extract_references(text: str) -> tuple[Reference, ...]:
    """Structured cross-references found in the text, deduplicated."""
    divisions = _find_division_mentions(text)
    instruments = _find_instrument_mentions(text)
    return tuple(dict.fromkeys(_references_from_mentions(text, divisions, instruments)))
