"""Evals CLI: `uv run evals check | stamp | run [--case ID] [--trait TRAIT] [--verbose]
[--no-store] | compare BASE OTHER | tune`."""

import argparse
import asyncio
from typing import Any

from app.core.config import config
from app.core.db.session import get_session
from app.core.exceptions import NotFoundError
from app.core.llm.cache import enable_call_cache
from app.core.logger import setup_logging
from app.evals.dataset.check import check_against_corpus, stale_case_ids
from app.evals.dataset.cli import (
    add_selection_arguments,
    register_dataset_commands,
    run_check,
    run_stamp,
    select_cases_from_args,
)
from app.evals.dataset.exceptions import DatasetError
from app.evals.dataset.models import CaseSelection, EvalDataset
from app.evals.models import EvalRun
from app.evals.report import format_case_lines, format_run_comparison
from app.evals.schemas import EvalRunRecord
from app.evals.service import create_eval_run, evaluate_all_cases, get_eval_run
from app.evals.tune.cli import register_tune_command, run_tune


def register_run_command(commands: Any) -> None:
    """The run subparser: drive the selected cases through the graph and print one summary."""
    run = commands.add_parser(
        "run",
        help="score the dataset against the current chat graph",
        description="Drive every selected case through the chat graph and print the run "
        "summary: which corpus and settings it scored against, what it measured, then any "
        "case owed a re-review or that raised. A stale case is reported, never failed.",
    )
    add_selection_arguments(run)
    run.add_argument("--verbose", action="store_true", help="list every case with its own scores")
    run.add_argument(
        "--no-judge",
        action="store_true",
        help="skip the LLM judge, leaving the judged metrics unmeasured",
    )
    run.add_argument(
        "--no-cache",
        action="store_true",
        help="pay for every embed and rerank again instead of replaying the cached ones",
    )
    run.add_argument(
        "--no-store",
        action="store_true",
        help="print the run without storing it in eval_runs",
    )


def register_compare_command(commands: Any) -> None:
    """The compare subparser: two stored runs, metric by metric."""
    compare = commands.add_parser(
        "compare",
        help="print two stored runs side by side",
        description="Print two stored eval runs metric by metric, with the other's delta "
        "from the base, then the settings they differ on.",
    )
    compare.add_argument("base", type=int, help="the eval run id to measure from")
    compare.add_argument("other", type=int, help="the eval run id to measure against it")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="evals", description="RegRag evals")
    commands = parser.add_subparsers(dest="command", required=True)
    register_dataset_commands(commands)
    register_run_command(commands)
    register_compare_command(commands)
    register_tune_command(commands)
    return parser


async def store_eval_run(run: EvalRun) -> int:
    async with get_session() as session:
        record = await create_eval_run(session, run)
    return record.id


def run_evals(
    selection: CaseSelection,
    verbose: bool = False,
    cached: bool = True,
    judge: bool = True,
    store: bool = True,
) -> int:
    """Score the dataset, print what it measured, the cases first when asked for, and store
    the run unless told not to."""
    dataset = EvalDataset.load(selection=selection)
    drifted, corpus_version = asyncio.run(check_against_corpus(dataset))

    if cached:
        enable_call_cache(config.EVAL_CACHE_DIR)

    run = asyncio.run(
        evaluate_all_cases(dataset, corpus_version, stale_case_ids(drifted), judge=judge)
    )
    if verbose:
        print("\n".join(format_case_lines(run.results)), end="\n\n")

    print(run.summary())
    if store:
        print(f"\nstored as eval run {asyncio.run(store_eval_run(run))}")
    return 1 if run.metrics.counts.errors or run.judge_never_answered else 0


async def load_eval_runs(*run_ids: int) -> list[EvalRunRecord]:
    async with get_session() as session:
        return [await get_eval_run(session, run_id) for run_id in run_ids]


def run_compare(base_id: int, other_id: int) -> int:
    """Print two stored runs side by side."""
    try:
        base, other = asyncio.run(load_eval_runs(base_id, other_id))
    except NotFoundError as exc:
        print(exc)
        return 1
    print(format_run_comparison(base, other))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging()

    try:
        if args.command == "run":
            selection = select_cases_from_args(args)
            return run_evals(
                selection,
                args.verbose,
                cached=not args.no_cache,
                judge=not args.no_judge,
                store=not args.no_store,
            )

        if args.command == "compare":
            return run_compare(args.base, args.other)

        if args.command == "tune":
            return run_tune(select_cases_from_args(args), cached=not args.no_cache)

        if args.command == "stamp":
            return run_stamp(select_cases_from_args(args))

        return run_check()
    except DatasetError as exc:
        print(exc)
        return 1
