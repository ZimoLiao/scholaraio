"""Metadata refetch CLI command handler."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


def _ui(msg: str = "") -> None:
    try:
        from scholaraio.interfaces.cli import compat as cli_mod
    except ImportError:
        from scholaraio.core.log import ui as log_ui

        log_ui(msg)
        return
    cli_mod.ui(msg)


def _log_error(msg: str, *args) -> None:
    try:
        from scholaraio.interfaces.cli import compat as cli_mod
    except ImportError:
        logging.getLogger(__name__).error(msg, *args)
        return
    cli_mod._log.error(msg, *args)


def _resolve_paper(paper_id: str, cfg) -> Path:
    from scholaraio.interfaces.cli import compat as cli_mod

    return cli_mod._resolve_paper(paper_id, cfg)


def cmd_refetch(args: argparse.Namespace, cfg) -> None:
    from scholaraio.services.ingest_metadata import refetch_metadata
    from scholaraio.stores.papers import iter_paper_dirs

    papers_dir = cfg.papers_dir

    if args.all:
        targets = sorted(d / "meta.json" for d in iter_paper_dirs(papers_dir))
    elif args.paper_id:
        targets = [_resolve_paper(args.paper_id, cfg) / "meta.json"]
    else:
        _log_error("Specify <paper-id> or --all")
        sys.exit(1)

    references_only = bool(getattr(args, "references_only", False))

    # Filter: only papers missing citations or bibliographic details (unless --force)
    if args.all and references_only:
        filtered = []
        for jp in targets:
            data = json.loads(jp.read_text(encoding="utf-8"))
            if data.get("doi") and not (data.get("references") or []):
                filtered.append(jp)
        _ui(f"Total {len(targets)} papers, {len(filtered)} papers need reference backfill")
        targets = filtered
    elif args.all and not args.force:
        filtered = []
        for jp in targets:
            data = json.loads(jp.read_text(encoding="utf-8"))
            if not data.get("doi"):
                continue
            missing_cite = not data.get("citation_count")
            missing_bib = not all(data.get(k) for k in ("volume", "publisher"))
            if missing_cite or missing_bib:
                filtered.append(jp)
        _ui(f"Total {len(targets)} papers, {len(filtered)} papers need backfill")
        targets = filtered

    if not targets:
        _ui("No updates needed")
        return

    # Filter out non-existent paths
    valid = []
    fail = 0
    for jp in targets:
        if jp.exists():
            valid.append(jp)
        else:
            _log_error("Paper not found: %s", jp.parent.name)
            fail += 1
    targets = valid
    if not targets:
        if args.all:
            _ui("No updates needed")
            return
        sys.exit(1)

    ok = skip = 0
    total = len(targets)
    workers = min(getattr(args, "jobs", 5) or 5, total)
    _ui(f"Concurrent refetch ({workers} workers, total {total} papers)...")

    def _do_refetch(jp: Path) -> tuple[Path, bool | None]:
        try:
            if references_only:
                return jp, refetch_metadata(jp, references_only=True)
            return jp, refetch_metadata(jp, db_path=cfg.index_db)
        except Exception as e:
            _log_error("refetch failed %s: %s", jp.parent.name, e)
            return jp, None

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_do_refetch, jp): jp for jp in targets}
        for fut in as_completed(futures):
            jp, changed = fut.result()
            done += 1
            name = jp.parent.name
            if changed is None:
                fail += 1
                _ui(f"[{done}/{total}] ✗ {name}")
            elif changed:
                ok += 1
                _ui(f"[{done}/{total}] ✓ {name}")
            else:
                skip += 1
                _ui(f"[{done}/{total}] - {name}")

    _ui(f"\nDone: {ok} updated | {skip} unchanged | {fail} failed")
