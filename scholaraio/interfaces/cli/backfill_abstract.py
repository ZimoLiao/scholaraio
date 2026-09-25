"""Abstract backfill CLI command handler."""

from __future__ import annotations

import argparse
import logging
import sys


def _ui(msg: str = "") -> None:
    from scholaraio.core import log

    log.ui(msg)


def _log_debug(msg: str, *args) -> None:
    logging.getLogger(__name__).debug(msg, *args)


def _log_error(msg: str, *args) -> None:
    logging.getLogger(__name__).error(msg, *args)


def cmd_backfill_abstract(args: argparse.Namespace, cfg) -> None:
    from scholaraio.services.ingest_metadata import backfill_abstracts

    papers_dir = cfg.papers_dir
    if not papers_dir.exists():
        _log_error("Papers directory does not exist: %s", papers_dir)
        sys.exit(1)

    action = "Preview backfill" if args.dry_run else "Backfill abstracts"
    doi_fetch = getattr(args, "doi_fetch", False)
    source = "official DOI sources" if doi_fetch else "local .md plus LLM fallback"
    _ui(f"{action}abstracts ({source})...\n")
    stats = backfill_abstracts(papers_dir, dry_run=args.dry_run, doi_fetch=doi_fetch, cfg=cfg)
    parts = [f"{stats['filled']} filled", f"{stats['skipped']} skipped", f"{stats['failed']} failed"]
    if stats.get("updated"):
        parts.insert(1, f"{stats['updated']} updated with official abstracts")
    _ui(f"\nDone: {' | '.join(parts)}")
    if stats["filled"] and not args.dry_run:
        _log_debug("consider rebuilding vector index: scholaraio embed --rebuild")
