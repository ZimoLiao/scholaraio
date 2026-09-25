"""Embedding and retrieval CLI command handlers."""

from __future__ import annotations

import argparse
import logging
import sys
import time

import scholaraio.interfaces.cli.arguments as _dep_arguments
import scholaraio.interfaces.cli.dependencies as _dep_dependencies
import scholaraio.interfaces.cli.output as _dep_output
import scholaraio.interfaces.cli.search_metrics as _dep_search_metrics


def _ui(msg: str = "") -> None:
    from scholaraio.core import log

    log.ui(msg)


def _log_error(msg: str, *args) -> None:
    logging.getLogger(__name__).error(msg, *args)


def _check_import_error(exc: ImportError) -> None:
    _dep_dependencies._check_import_error(exc)


def _resolve_top(args: argparse.Namespace, default: int) -> int:
    return _dep_arguments._resolve_top(args, default)


def _record_search_metrics(store, name: str, query: str, results: list[dict], elapsed: float, args) -> None:
    _dep_search_metrics._record_search_metrics(store, name, query, results, elapsed, args)


def _print_search_result(idx: int, result: dict, extra: str = "") -> None:
    _dep_output._print_search_result(idx, result, extra=extra)


def _print_search_next_steps() -> None:
    _dep_output._print_search_next_steps()


def _format_match_tag(match: str) -> str:
    return _dep_output._format_match_tag(match)


def cmd_embed(args: argparse.Namespace, cfg) -> None:
    try:
        from scholaraio.services.vectors import build_vectors
    except ImportError as e:
        _check_import_error(e)

    papers_dir = cfg.papers_dir
    if not papers_dir.exists():
        _log_error("Papers directory does not exist: %s", papers_dir)
        sys.exit(1)

    provider = (getattr(cfg.embed, "provider", "local") or "local").strip().lower()
    action = "Rebuild vector index" if args.rebuild else "Update vector index"
    _ui(f"{action}: {papers_dir} -> {cfg.index_db}")
    count = build_vectors(papers_dir, cfg.index_db, rebuild=args.rebuild, cfg=cfg)
    if provider == "none":
        _ui("Current embed.provider=none: vector generation is disabled; keyword search will be used.")
        _ui("For semantic search, set embed.provider to local or openai-compat and rerun `scholaraio embed`.")
        return
    label = "total" if args.rebuild else "added"
    _ui(f"Done: {label} {count} vectors.")
    _ui("Next: run `scholaraio vsearch <query>` or `scholaraio usearch <query>` to try retrieval.")


def cmd_vsearch(args: argparse.Namespace, cfg) -> None:
    try:
        from scholaraio.services.vectors import vsearch
    except ImportError as e:
        _check_import_error(e)

    from scholaraio.services.metrics import get_store

    query = " ".join(args.query)
    t0 = time.monotonic()
    try:
        results = vsearch(
            query,
            cfg.index_db,
            top_k=_resolve_top(args, cfg.embed.top_k),
            cfg=cfg,
            year=args.year,
            journal=args.journal,
            paper_type=args.paper_type,
        )
    except FileNotFoundError as e:
        _log_error("%s", e)
        sys.exit(1)

    elapsed = time.monotonic() - t0
    store = get_store()
    _record_search_metrics(store, "vsearch", query, results, elapsed, args)

    if not results:
        _ui(f'No results found for "{query}".')
        return

    _ui(f'Semantic search results for "{query}" ({len(results)} records)\n')
    for i, r in enumerate(results, start=1):
        score = r.get("score", 0.0)
        _print_search_result(i, r, extra=f"score: {score:.3f}")
    _print_search_next_steps()


def cmd_usearch(args: argparse.Namespace, cfg) -> None:
    from scholaraio.services.index import unified_search
    from scholaraio.services.metrics import get_store

    query = " ".join(args.query)
    t0 = time.monotonic()
    results, diagnostics = unified_search(
        query,
        cfg.index_db,
        top_k=_resolve_top(args, cfg.search.top_k),
        cfg=cfg,
        year=args.year,
        journal=args.journal,
        paper_type=args.paper_type,
        return_diagnostics=True,
    )
    elapsed = time.monotonic() - t0
    store = get_store()
    _record_search_metrics(store, "usearch", query, results, elapsed, args)

    if not results:
        _ui(f'No results found for "{query}".')
        return

    if diagnostics.get("vector_degraded"):
        _ui("Hint: Vector search is unavailable; falling back to keyword search.\n")
    _ui(f'Unified search results for "{query}" ({len(results)} records)\n')
    for i, r in enumerate(results, start=1):
        score = r.get("score", 0.0)
        match = r.get("match", "?")
        _print_search_result(i, r, extra=f"{_format_match_tag(match)} {score:.3f}")
    _print_search_next_steps()
