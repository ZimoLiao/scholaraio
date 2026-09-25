"""Metrics CLI command handler."""

from __future__ import annotations

import argparse
import logging


def _ui(msg: str = "") -> None:
    from scholaraio.core import log

    log.ui(msg)


def _log_error(msg: str) -> None:
    logging.getLogger(__name__).error(msg)


def cmd_metrics(args: argparse.Namespace, cfg) -> None:
    from scholaraio.services.metrics import get_store

    ui = _ui
    store = get_store()
    if not store:
        _log_error("Metrics database is not initialized.")
        return

    if args.summary:
        s = store.summary()
        ui("LLM call statistics (all sessions): ")
        ui(f"  Call count:      {s['call_count']}")
        ui(f"  Input tokens:   {s['total_tokens_in']:,}")
        ui(f"  Output tokens:   {s['total_tokens_out']:,}")
        ui(f"  Total tokens:     {s['total_tokens_in'] + s['total_tokens_out']:,}")
        ui(f"  Total duration:        {s['total_duration_s']:.1f}s")
        return

    rows = store.query(
        category=args.category,
        since=args.since,
        limit=args.last,
    )
    if not rows:
        ui("No records.")
        return

    if args.category == "llm":
        ui(f"{'time':<20s} {'purpose':<24s} {'prompt':>8s} {'compl':>8s} {'total':>8s} {'time':>7s} {'status':<5s}")
        ui("-" * 82)
        total_in = total_out = 0
        for r in reversed(rows):
            ts = r["timestamp"][:19].replace("T", " ")
            name = r["name"][:24]
            t_in = r["tokens_in"] or 0
            t_out = r["tokens_out"] or 0
            dur = r["duration_s"] or 0
            total_in += t_in
            total_out += t_out
            ui(f"{ts:<20s} {name:<24s} {t_in:>8,d} {t_out:>8,d} {t_in + t_out:>8,d} {dur:>6.1f}s {r['status']:<5s}")
        ui("-" * 82)
        ui(f"{'total':<20s} {'':<24s} {total_in:>8,d} {total_out:>8,d} {total_in + total_out:>8,d}")
    else:
        ui(f"{'time':<20s} {'name':<32s} {'time':>7s} {'status':<5s}")
        ui("-" * 66)
        for r in reversed(rows):
            ts = r["timestamp"][:19].replace("T", " ")
            name = r["name"][:32]
            dur = r["duration_s"] or 0
            ui(f"{ts:<20s} {name:<32s} {dur:>6.1f}s {r['status']:<5s}")
