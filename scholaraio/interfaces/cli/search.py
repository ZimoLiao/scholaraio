"""Keyword and author search CLI command handlers."""

from __future__ import annotations

import argparse
import logging
import sys
import time

import scholaraio.interfaces.cli.arguments as _dep_arguments
import scholaraio.interfaces.cli.output as _dep_output
import scholaraio.interfaces.cli.search_metrics as _dep_search_metrics


def _ui(msg: str = "") -> None:
    from scholaraio.core import log

    log.ui(msg)


def _log_error(msg: str, *args) -> None:
    logging.getLogger(__name__).error(msg, *args)


def _resolve_top(args: argparse.Namespace, default: int) -> int:
    return _dep_arguments._resolve_top(args, default)


def _record_search_metrics(store, name: str, query: str, results: list[dict], elapsed: float, args) -> None:
    _dep_search_metrics._record_search_metrics(store, name, query, results, elapsed, args)


def _print_search_result(idx: int, result: dict, extra: str = "") -> None:
    _dep_output._print_search_result(idx, result, extra=extra)


def _print_search_next_steps() -> None:
    _dep_output._print_search_next_steps()


def _print_chunk_result(idx: int, result: dict) -> None:
    display = result.get("dir_name") or result.get("paper_id") or "?"
    title = result.get("title") or "?"
    section = result.get("section_title") or "?"
    start_line = result.get("start_line") or "?"
    end_line = result.get("end_line") or "?"
    snippet = result.get("snippet") or ""

    _ui(f"[{idx}] {display}")
    _ui(f"     {title}")
    _ui(f"     {section} | lines {start_line}-{end_line}")
    if snippet:
        _ui(f"     {snippet}")
    _ui()


def cmd_search_author(args: argparse.Namespace, cfg) -> None:
    from scholaraio.services.index import search_author

    query = " ".join(args.query)
    try:
        results = search_author(
            query,
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
        _ui(f'No papers found for author "{query}".')
        return

    _ui(f'Author search found {len(results)} papers ("{query}"):\n')
    for i, r in enumerate(results, start=1):
        _print_search_result(i, r)
    _print_search_next_steps()


def cmd_search(args: argparse.Namespace, cfg) -> None:
    from scholaraio.services.metrics import get_store

    query = " ".join(args.query)
    t0 = time.monotonic()
    if getattr(args, "chunk", False):
        from scholaraio.services.chunks import chunk_search

        try:
            results = chunk_search(
                query,
                cfg.index_db,
                top_k=_resolve_top(args, cfg.search.top_k),
                year=args.year,
                journal=args.journal,
                paper_type=args.paper_type,
            )
        except FileNotFoundError as e:
            _log_error("%s", e)
            sys.exit(1)

        elapsed = time.monotonic() - t0
        store = get_store()
        _record_search_metrics(store, "chunk-search", query, results, elapsed, args)

        if not results:
            _ui(f'No evidence chunks found for "{query}".')
            return

        _ui(f'Chunk search found {len(results)} evidence chunks ("{query}"):\n')
        for i, r in enumerate(results, start=1):
            _print_chunk_result(i, r)
        _ui("Next: run `scholaraio show <paper-id> --layer 4` and inspect the reported line range.")
        return

    from scholaraio.services.index import search

    try:
        results = search(
            query,
            cfg.index_db,
            top_k=_resolve_top(args, cfg.search.top_k),
            year=args.year,
            journal=args.journal,
            paper_type=args.paper_type,
        )
    except FileNotFoundError as e:
        _log_error("%s", e)
        sys.exit(1)

    elapsed = time.monotonic() - t0
    store = get_store()
    _record_search_metrics(store, "search", query, results, elapsed, args)

    if not results:
        _ui(f'No results found for "{query}".')
        return

    _ui(f'Keyword search found {len(results)} papers ("{query}"):\n')
    for i, r in enumerate(results, start=1):
        _print_search_result(i, r)
    _print_search_next_steps()
