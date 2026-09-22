"""Dataset CLI: the `evals check` and `evals stamp` subcommands."""

import argparse
import asyncio
from typing import Any

from app.core.db.session import get_session
from app.evals.dataset.check import check_against_corpus, find_moved_corpus, format_drift
from app.evals.dataset.enums import DriftKind, EvalKind, EvalTrait
from app.evals.dataset.models import CaseSelection, EvalDataset
from app.evals.dataset.stamp import save_dataset, stamp_dataset


def register_dataset_commands(commands: Any) -> None:
    """The read-only check, and the stamp that records a human has re-read the cited text."""
    check = commands.add_parser(
        "check",
        help="confirm every case reference resolves and still says what it was authored against",
        description="Report hard drift (a reference no stored chunk answers to), soft drift "
        "(cited text that changed since the case was stamped), and any case never stamped. "
        "Read-only: repairing a stale case means rewriting its answer, then `evals stamp`.",
    )
    check.add_argument(
        "--fail-on-stale",
        action="store_true",
        help="exit 1 on a stale case too, not only an unresolved one, as the nightly ingest does",
    )
    stamp = commands.add_parser(
        "stamp",
        help="record what the cited text says now, asserting it has been read",
        description="Write the current chunk hashes into the selected cases. Run it on a newly "
        "authored case, or on a stale one whose answer you have just re-reviewed against the "
        "new text. An unfiltered stamp also rewrites the corpus stamp; any selection flag "
        "leaves it alone. "
        "A selected reference the corpus cannot resolve refuses the whole stamp.",
    )
    add_selection_arguments(stamp)


def add_selection_arguments(parser: Any) -> None:
    """The flags every command that scores or stamps a subset takes, narrowing together."""
    parser.add_argument("--case", help="only cases whose id contains this")
    parser.add_argument(
        "--trait",
        type=EvalTrait,
        choices=tuple(EvalTrait),
        help="only cases marked with this trait",
    )
    parser.add_argument(
        "--kind", type=EvalKind, choices=tuple(EvalKind), help="only cases of this kind"
    )


def select_cases_from_args(args: argparse.Namespace) -> CaseSelection:
    """The selection the flags add_selection_arguments registered were given."""
    return CaseSelection(id_contains=args.case, trait=args.trait, kind=args.kind)


def run_check(fail_on_stale: bool = False) -> int:
    """Report every way the dataset has drifted; an unresolved reference fails, and a stale
    one too when asked."""
    dataset = EvalDataset.load()
    drifted, current = asyncio.run(check_against_corpus(dataset))
    lines = format_drift(drifted, find_moved_corpus(dataset, current))
    print("\n".join(lines) if lines else "every case reference resolves and is stamped")
    failing = {DriftKind.UNRESOLVED, DriftKind.STALE} if fail_on_stale else {DriftKind.UNRESOLVED}
    return 1 if any(item.kind in failing for item in drifted) else 0


async def _stamp_against_corpus(dataset: EvalDataset) -> EvalDataset:
    """The dataset restamped in one session against the corpus as it stands."""
    async with get_session(auto_commit=False) as session:
        return await stamp_dataset(session, dataset)


def run_stamp(selection: CaseSelection) -> int:
    """Restamp the selected cases, write the dataset back, and name whose hashes moved."""
    before = EvalDataset.load(selection=selection)
    after = asyncio.run(_stamp_against_corpus(before))
    save_dataset(after)

    changed = [
        case.id
        for case, was in zip(after.cases, before.cases, strict=True)
        if case.references != was.references
    ]
    print(f"stamped {len(after.selected_cases)} cases")
    print(f"hashes changed: {', '.join(changed)}" if changed else "no hashes changed")
    return 0
