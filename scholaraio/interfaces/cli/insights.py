"""Insights CLI command handler."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _workspace_root(cfg) -> Path:
    workspace_dir = getattr(cfg, "workspace_dir", None)
    if workspace_dir is not None:
        return Path(workspace_dir)
    return Path(getattr(cfg, "_root", Path.cwd())) / "workspace"


def _ui(msg: str = "") -> None:
    from scholaraio.core import log

    log.ui(msg)


def cmd_insights(args: argparse.Namespace, cfg) -> None:
    from scholaraio.services import insights
    from scholaraio.services.metrics import get_store

    ui = _ui
    store = get_store()
    if not store:
        ui("Not enough data (metrics is not initialized)")
        return

    days = args.days
    if days <= 0:
        ui("--days must be a positive integer")
        return
    since_dt = datetime.now(timezone.utc) - timedelta(days=days)
    since_iso = since_dt.isoformat()

    search_events = store.query(category="search", since=since_iso, limit=10000)
    read_events = store.query(category="read", since=since_iso, limit=10000)

    if not search_events and not read_events:
        ui(f"Not enough data (no search or reading records in the last {days} days)")
        return

    ui(f"=== Research behavior analytics (last {days} days) ===\n")

    ui("【Top 10 search terms】")
    hot_keywords = insights.extract_hot_keywords(search_events, top_k=10)
    if hot_keywords:
        for word, cnt in hot_keywords:
            bar = "█" * min(cnt, 20)
            ui(f"  {word:<20s} {bar} ({cnt})")
    else:
        ui("  No search records")
    ui()

    ui("【Top 10 most-read papers】")
    most_read = insights.aggregate_most_read_titles(read_events, cfg.papers_dir, top_k=10)
    if most_read:
        for rank, (title_key, cnt) in enumerate(most_read, 1):
            label = title_key[:60]
            ui(f"  {rank:2d}. [{cnt} times] {label}")
    else:
        ui("  No reading records")
    ui()

    ui("【Reading trend by week】")
    if read_events:
        week_counts = insights.build_weekly_read_trend(read_events)
        if week_counts:
            max_count = max(cnt for _, cnt in week_counts) or 1
            for week, cnt in week_counts:
                bar_len = round(cnt / max_count * 20)
                bar = "█" * bar_len
                ui(f"  {week}  {bar} {cnt}")
        else:
            ui("  Not enough data")
    else:
        ui("  No reading records")
    ui()

    ui("【Recommendations: nearby papers you may not have read】")
    recent_since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    recent_reads = store.query(category="read", since=recent_since, limit=500)
    recent_paper_ids = insights.recent_unique_read_names(recent_reads, limit=5)

    if not recent_paper_ids:
        ui("  No reading records in the last 7 days; cannot recommend papers")
    else:
        try:
            recommendations = insights.recommend_unread_neighbors(store, cfg, recent_days=7, recent_limit=5, top_k=5)
            if recommendations:
                for rank, (_pid, label, score) in enumerate(recommendations, 1):
                    label = label[:60]
                    ui(f"  {rank}. {label}  (score: {score:.3f})")
            else:
                ui("  No suitable nearby papers found; the vector index may be missing")
        except ImportError:
            ui("  Semantic search is unavailable (install embed dependencies)")
    ui()

    ui("【Active workspaces】")
    try:
        ws_root = _workspace_root(cfg)
        workspaces = insights.list_workspace_counts(ws_root)
        if workspaces:
            for ws_name, count in workspaces:
                ui(f"  {ws_name:<30s} {count} papers")
        else:
            ui("  No workspaces")
    except Exception:
        ui("  Workspace information is unavailable")
    ui()
