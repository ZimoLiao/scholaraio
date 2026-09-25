"""Citation-related CLI command handlers."""

from __future__ import annotations

import argparse
import logging
import sys

import scholaraio.interfaces.cli.arguments as _dep_arguments
import scholaraio.interfaces.cli.output as _dep_output


def _ui(msg: str = "") -> None:
    from scholaraio.core import log

    log.ui(msg)


def _log_error(msg: str, *args) -> None:
    logging.getLogger(__name__).error(msg, *args)


def _resolve_top(args: argparse.Namespace, default: int) -> int:
    return _dep_arguments._resolve_top(args, default)


def _print_search_result(idx: int, result: dict, extra: str = "") -> None:
    _dep_output._print_search_result(idx, result, extra=extra)


def _print_search_next_steps() -> None:
    _dep_output._print_search_next_steps()


def cmd_top_cited(args: argparse.Namespace, cfg) -> None:
    from scholaraio.services.index import top_cited

    try:
        results = top_cited(
            cfg.index_db,
            top_k=_resolve_top(args, cfg.search.top_k),
            year=args.year,
            journal=args.journal,
            paper_type=args.paper_type,
        )
    except FileNotFoundError as e:
        _log_error("%s", e)
        sys.exit(1)

    if not results:
        _ui("No citation data found in the index. Run `scholaraio refetch --all` first.")
        return

    _ui(f"Top {len(results)} papers: \n")
    for i, r in enumerate(results, start=1):
        _print_search_result(i, r)
    _print_search_next_steps()
