"""Index CLI command handler."""

from __future__ import annotations

import argparse
import logging
import sys


def _ui(msg: str = "") -> None:
    from scholaraio.core import log

    log.ui(msg)


def _log_error(msg: str, *args) -> None:
    logging.getLogger(__name__).error(msg, *args)


def cmd_index(args: argparse.Namespace, cfg) -> None:
    from scholaraio.services.index import build_index

    papers_dir = cfg.papers_dir
    db_path = cfg.index_db

    if not papers_dir.exists():
        _log_error("Papers directory does not exist: %s", papers_dir)
        sys.exit(1)

    if getattr(args, "chunks", False):
        from scholaraio.services.chunks import build_chunk_index

        action = "Rebuild chunk index" if args.rebuild else "Build chunk index"
        _ui(f"{action}: {papers_dir} -> {db_path}")
        count = build_chunk_index(papers_dir, db_path, rebuild=args.rebuild)
        _ui(f"Done: indexed {count} chunks.")
        _ui("Next: run `scholaraio search --chunk <keywords>` to locate evidence snippets.")
        return

    action = "Rebuild index" if args.rebuild else "Build index"
    _ui(f"{action}: {papers_dir} -> {db_path}")
    count = build_index(papers_dir, db_path, rebuild=args.rebuild)
    _ui(f"Done: indexed {count} papers.")
    _ui("Next: run `scholaraio search <keywords>` or `scholaraio usearch <keywords>` to start searching.")
