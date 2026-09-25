"""Citation-check CLI command handler."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import scholaraio.interfaces.cli.paths as _dep_paths


def _ui(msg: str = "") -> None:
    from scholaraio.core import log

    log.ui(msg)


def _log_error(msg: str, *args) -> None:
    logging.getLogger(__name__).error(msg, *args)


def _resolve_ws_paper_ids(args: argparse.Namespace, cfg) -> set[str] | None:
    return _dep_paths._resolve_ws_paper_ids(args, cfg)


def cmd_citation_check(args: argparse.Namespace, cfg) -> None:
    from scholaraio.services.citation_check import check_citations, extract_citations

    if args.file:
        p = Path(args.file)
        if not p.exists():
            _log_error("File does not exist: %s", p)
            sys.exit(1)
        text = p.read_text(encoding="utf-8")
    else:
        text = sys.stdin.read()

    if not text.strip():
        _ui("Input text is empty.")
        return

    citations = extract_citations(text)
    if not citations:
        _ui("No citations found in the text.")
        return

    _ui(f"Extracted {len(citations)} citations, verifying...\n")

    try:
        paper_ids = _resolve_ws_paper_ids(args, cfg)
    except ValueError as e:
        _ui(str(e))
        return

    results = check_citations(
        citations,
        cfg.index_db,
        paper_ids=paper_ids,
    )

    counts = {"VERIFIED": 0, "NOT_IN_LIBRARY": 0, "AMBIGUOUS": 0}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1

    status_labels = {
        "VERIFIED": "verified",
        "NOT_IN_LIBRARY": "not in library",
        "AMBIGUOUS": "ambiguous",
    }

    for r in results:
        status_icon = {"VERIFIED": "✓", "NOT_IN_LIBRARY": "✗", "AMBIGUOUS": "?"}.get(r["status"], " ")
        status_text = status_labels.get(r["status"], r["status"])
        _ui(f"  [{status_icon}] {status_text:8s}  {r['raw']}  ({r['author']}, {r['year']})")
        if r["matches"]:
            for m in r["matches"][:3]:
                display_id = m.get("dir_name") or m.get("paper_id", "?")
                _ui(f"       -> {display_id}")
                _ui(f"         {m.get('title', '?')}")

    _ui()
    _ui(
        f"Verification result: verified {counts['VERIFIED']} / "
        f"ambiguous {counts['AMBIGUOUS']} / "
        f"not in library {counts['NOT_IN_LIBRARY']}"
    )
