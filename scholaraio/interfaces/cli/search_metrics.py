"""Shared CLI search metrics recording helper."""

from __future__ import annotations

import argparse
import logging

_log = logging.getLogger(__name__)


def _record_search_metrics(
    store,
    name: str,
    query: str,
    results: list[dict],
    elapsed: float,
    args: argparse.Namespace,
) -> None:
    """Record a search event to the metrics store, silently ignoring failures."""
    if not store:
        return
    try:
        store.record(
            category="search",
            name=name,
            duration_s=elapsed,
            detail={
                "query": query,
                "result_count": len(results),
                "top_dois": [r["doi"] for r in results[:5] if r.get("doi")],
                "filters": {
                    "year": getattr(args, "year", None),
                    "journal": getattr(args, "journal", None),
                    "paper_type": getattr(args, "paper_type", None),
                },
            },
        )
    except Exception as _e:
        logger = _log
        logger.debug("metrics record failed: %s", _e)
