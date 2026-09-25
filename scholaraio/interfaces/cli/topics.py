"""Topic-model CLI command handler."""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import scholaraio.interfaces.cli.arguments as _dep_arguments
import scholaraio.interfaces.cli.dependencies as _dep_dependencies


def _ui(msg: str = "") -> None:
    from scholaraio.core import log

    log.ui(msg)


def _log_debug(msg: str, *args) -> None:
    logging.getLogger(__name__).debug(msg, *args)


def _log_error(msg: str, *args) -> None:
    logging.getLogger(__name__).error(msg, *args)


def _check_import_error(exc: ImportError) -> None:
    _dep_dependencies._check_import_error(exc)


def _resolve_result_limit(args: argparse.Namespace, default: int) -> int:
    return _dep_arguments._resolve_result_limit(args, default)


def _write_all_viz(model, viz_dir: Path) -> None:
    """Write 6 BERTopic HTML visualizations to *viz_dir*."""
    from scholaraio.services.topics import (
        visualize_barchart,
        visualize_heatmap,
        visualize_term_rank,
        visualize_topic_hierarchy,
        visualize_topics_2d,
        visualize_topics_over_time,
    )

    viz_dir.mkdir(parents=True, exist_ok=True)
    _log_debug("generating visualizations")

    charts: list[tuple[str, str, Callable[[Any], str]]] = [
        ("topics_2d", "2D scatter", visualize_topics_2d),
        ("barchart", "Keywords  ", visualize_barchart),
        ("hierarchy", "Hierarchy ", visualize_topic_hierarchy),
        ("heatmap", "Heatmap   ", visualize_heatmap),
        ("term_rank", "Term rank ", visualize_term_rank),
    ]
    for fname, label, func in charts:
        html = func(model)
        (viz_dir / f"{fname}.html").write_text(html, encoding="utf-8")
        _ui(f"  {label} -> {viz_dir / f'{fname}.html'}")

    try:
        html = visualize_topics_over_time(model)
        (viz_dir / "topics_over_time.html").write_text(html, encoding="utf-8")
        _ui(f"  Over time  -> {viz_dir / 'topics_over_time.html'}")
    except Exception as e:
        _log_error("Topics-over-time failed: %s", e)


def cmd_topics(args: argparse.Namespace, cfg) -> None:
    try:
        from scholaraio.services.topics import (
            build_topics,
            get_outliers,
            get_topic_overview,
            get_topic_papers,
            load_model,
            reduce_topics_to,
        )
    except ImportError as e:
        _check_import_error(e)

    model_dir = cfg.topics_model_dir

    # Resolve nr_topics: CLI --nr-topics overrides config
    def _resolve_nr_topics():
        raw = args.nr_topics if args.nr_topics is not None else cfg.topics.nr_topics
        return {0: "auto", -1: None}.get(raw, raw)

    if args.build or args.rebuild:
        min_ts = args.min_topic_size if args.min_topic_size is not None else cfg.topics.min_topic_size
        if args.rebuild and model_dir.exists():
            shutil.rmtree(model_dir, ignore_errors=True)
        _ui(f"{'Rebuild' if args.rebuild else 'Build'}topic model...")
        try:
            model = build_topics(
                cfg.index_db,
                cfg.papers_dir,
                min_topic_size=min_ts,
                nr_topics=_resolve_nr_topics(),
                save_path=model_dir,
                cfg=cfg,
            )
        except FileNotFoundError as e:
            _log_error("%s", e)
            sys.exit(1)
    else:
        try:
            model = load_model(model_dir)
        except FileNotFoundError as e:
            _log_error("%s", e)
            sys.exit(1)

    # Quick reduce (no rebuild)
    if args.reduce is not None:
        _ui(f"Reducing to {args.reduce} topics...")
        model = reduce_topics_to(model, args.reduce, save_path=model_dir, cfg=cfg)

    # Manual merge
    if args.merge:
        from scholaraio.services.topics import merge_topics_by_ids

        # Parse "1,6,14+3,5" -> [[1,6,14],[3,5]]
        groups = []
        for group_str in args.merge.split("+"):
            ids = [int(x.strip()) for x in group_str.split(",") if x.strip()]
            if len(ids) >= 2:
                groups.append(ids)
        if groups:
            _ui(f"Merging {len(groups)} topic groups: {groups}")
            model = merge_topics_by_ids(model, groups, save_path=model_dir, cfg=cfg)
        else:
            _log_error("Invalid --merge format; example: --merge 1,6,14+3,5")

    # Show specific topic
    if args.topic is not None:
        tid = args.topic
        top_n = _resolve_result_limit(args, 0) or 0  # 0 = show all
        if tid == -1:
            papers = get_outliers(model)
            _ui(f"Outlier papers: {len(papers)}\n")
        else:
            topic_words = model.get_topic(tid)
            if topic_words is False or topic_words is None:
                _log_error("Topic %d does not exist", tid)
                sys.exit(1)
            keywords = [w for w, _ in topic_words[:10]]
            papers = get_topic_papers(model, tid)
            _ui(f"Topic {tid}: {', '.join(keywords)}")
            _ui(f"{len(papers)} papers\n")

        if top_n:
            papers = papers[:top_n]
        for i, p in enumerate(papers, 1):
            cc = p.get("citation_count", {})
            best = max((v for v in (cc or {}).values() if isinstance(v, (int, float))), default=0)
            cite_str = f"  [cited: {best}]" if best else ""
            authors = p.get("authors", "")
            first_author = authors.split(",")[0].strip() if authors else ""
            _ui(f"  {i:2d}. [{p.get('year', '?')}] {p.get('title', p['paper_id'])}")
            _ui(f"      {first_author} | {p.get('journal', '')}{cite_str}")
        return

    # Generate visualizations (6 charts, same as explore)
    if args.viz:
        _write_all_viz(model, model_dir / "viz")
        return

    # Default: show overview
    overview = get_topic_overview(model)
    if not overview:
        _ui("No topics are available. Try reducing topics.min_topic_size or adding more papers.")
        return

    outliers = get_outliers(model)
    total = sum(t["count"] for t in overview) + len(outliers)
    _ui(f"Library overview: {total} papers, {len(overview)} topics, {len(outliers)} outlier papers\n")

    for t in overview:
        kw = ", ".join(t["keywords"][:6])
        _ui(f"Topic {t['topic_id']:2d} ({t['count']:3d} papers): {kw}")
        for p in t["representative_papers"][:3]:
            year = p.get("year", "?")
            title = p.get("title", "")
            if len(title) > 70:
                title = title[:67] + "..."
            _ui(f"    [{year}] {title}")
        _ui()
