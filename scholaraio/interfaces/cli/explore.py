"""Explore CLI command handler."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import scholaraio.interfaces.cli.arguments as _dep_arguments
import scholaraio.interfaces.cli.dependencies as _dep_dependencies


def _ui(msg: str = "") -> None:
    from scholaraio.core import log

    log.ui(msg)


def _log_error(msg: str, *args) -> None:
    logging.getLogger(__name__).error(msg, *args)


def _check_import_error(exc: ImportError) -> None:
    _dep_dependencies._check_import_error(exc)


def _resolve_top(args: argparse.Namespace, default: int) -> int:
    return _dep_arguments._resolve_top(args, default)


def _explore_root(cfg) -> Path:
    explore_root = getattr(cfg, "explore_root", None)
    if explore_root is not None:
        return Path(explore_root)
    return Path(getattr(cfg, "_root", Path.cwd())) / "data" / "explore"


def cmd_explore(args: argparse.Namespace, cfg) -> None:
    action = args.explore_action

    if action == "fetch":
        if args.limit is not None and args.limit <= 0:
            _ui(f"--limit must be a positive integer; current value: {args.limit}")
            return
        # Determine name: explicit --name, or derive from filters
        name = args.name
        if not name:
            if args.issn:
                name = args.issn.replace("-", "")
            elif args.concept:
                name = f"concept-{args.concept}"
            elif args.author:
                name = f"author-{args.author}"
            elif args.keyword:
                name = args.keyword.replace(" ", "-")[:30]
            else:
                _ui("Provide --name or at least one filter")
                return
        from scholaraio.stores.explore import fetch_explore

        total = fetch_explore(
            name,
            issn=getattr(args, "issn", None),
            concept=getattr(args, "concept", None),
            topic=getattr(args, "topic_id", None),
            author=getattr(args, "author", None),
            institution=getattr(args, "institution", None),
            keyword=getattr(args, "keyword", None),
            source_type=getattr(args, "source_type", None),
            year_range=getattr(args, "year_range", None),
            min_citations=getattr(args, "min_citations", None),
            oa_type=getattr(args, "oa_type", None),
            incremental=getattr(args, "incremental", False),
            limit=getattr(args, "limit", None),
            cfg=cfg,
        )
        _ui(f"\nFetched {total} papers")

    elif action == "embed":
        try:
            from scholaraio.stores.explore import build_explore_vectors
        except ImportError as e:
            _check_import_error(e)
        n = build_explore_vectors(args.name, rebuild=args.rebuild, cfg=cfg)
        provider = (getattr(cfg.embed, "provider", "local") or "local").strip().lower()
        if provider == "none":
            _ui(
                "Current embed.provider=none: skipping explore-library vector generation; keyword search remains available."
            )
            return
        _ui(f"Done: added {n} vector embeddings")

    elif action == "topics":
        try:
            from scholaraio.stores.explore import _explore_dir, build_explore_topics
        except ImportError as e:
            _check_import_error(e)
        try:
            from scholaraio.services.topics import get_topic_overview, get_topic_papers, load_model
        except ImportError as e:
            _check_import_error(e)

        model_dir = _explore_dir(args.name, cfg) / "topic_model"

        if args.build or args.rebuild:
            nr_topics = args.nr_topics
            try:
                info = build_explore_topics(
                    args.name,
                    rebuild=args.rebuild,
                    min_topic_size=args.min_topic_size or 30,
                    nr_topics=nr_topics,
                    cfg=cfg,
                )
            except FileNotFoundError as e:
                _log_error("%s", e)
                sys.exit(1)
            _ui(
                f"\nClustering completed: {info['n_topics']} topics, {info['n_outliers']} outlier papers, {info['n_papers']} papers"
            )

        try:
            model = load_model(model_dir)
        except FileNotFoundError:
            _ui("No topic model exists yet. Run `scholaraio explore topics --name <name> --build` first.")
            return

        if args.topic is not None:
            papers = get_topic_papers(model, args.topic)
            top_n = _resolve_top(args, 20)
            papers = papers[:top_n]
            _ui(f"Topic {args.topic}: {len(papers)} papers\n")
            for i, p in enumerate(papers, 1):
                cc = p.get("citation_count", {})
                best = max((v for v in (cc or {}).values() if isinstance(v, (int, float))), default=0)
                cite_str = f"  [cited: {best}]" if best else ""
                authors = p.get("authors", "")
                first_author = authors.split(",")[0].strip() if authors else ""
                title = p.get("title", "")
                if len(title) > 70:
                    title = title[:67] + "..."
                _ui(f"  {i:3d}. [{p.get('year', '?')}] {title}")
                _ui(f"       {first_author} | {p.get('paper_id', '')}{cite_str}")
            return

        overview = get_topic_overview(model)
        if not overview:
            _ui("No topics are available. Run `scholaraio explore topics --name <name> --build` first.")
            return
        from scholaraio.services.topics import get_outliers

        outliers = get_outliers(model)
        total = sum(t["count"] for t in overview) + len(outliers)
        _ui(f"\n{len(overview)} topics, {total} papers, {len(outliers)} outlier papers\n")
        for t in overview:
            kw = ", ".join(t["keywords"][:6])
            _ui(f"Topic {t['topic_id']:2d} ({t['count']:3d} papers): {kw}")
            for p in t["representative_papers"][:3]:
                title = p.get("title", "")
                if len(title) > 65:
                    title = title[:62] + "..."
                cc = p.get("citation_count", {})
                best = max((v for v in (cc or {}).values() if isinstance(v, (int, float))), default=0)
                cite_str = f"  [cited: {best}]" if best else ""
                _ui(f"    [{p.get('year', '?')}] {title}{cite_str}")
            _ui()

    elif action == "search":
        query = " ".join(args.query)
        mode = getattr(args, "mode", "semantic") or "semantic"
        top_k = _resolve_top(args, 10)
        if mode == "keyword":
            from scholaraio.stores.explore import explore_search

            results = explore_search(args.name, query, top_k=top_k, cfg=cfg)
        elif mode == "unified":
            try:
                from scholaraio.stores.explore import explore_unified_search
            except ImportError as e:
                _check_import_error(e)
            results = explore_unified_search(args.name, query, top_k=top_k, cfg=cfg)
        else:
            try:
                from scholaraio.stores.explore import explore_vsearch
            except ImportError as e:
                _check_import_error(e)
            try:
                results = explore_vsearch(args.name, query, top_k=top_k, cfg=cfg)
            except FileNotFoundError as e:
                _log_error("%s", e)
                sys.exit(1)
        if not results:
            _ui("No results found.")
            return
        for i, r in enumerate(results, 1):
            authors = r.get("authors", [])
            first = authors[0] if authors else ""
            cited = r.get("cited_by_count", 0)
            cite_str = f"  [cited: {cited}]" if cited else ""
            _ui(f"[{i}] [{r.get('year', '?')}] {r.get('title', '')}")
            _ui(f"     {first} | {r.get('doi', '')}  (score: {r['score']:.3f}){cite_str}")
            _ui()

    elif action == "viz":
        try:
            from scholaraio.services.topics import load_model
            from scholaraio.stores.explore import _explore_dir
        except ImportError as e:
            _check_import_error(e)
        model_dir = _explore_dir(args.name, cfg) / "topic_model"
        try:
            model = load_model(model_dir)
        except FileNotFoundError:
            _ui("No topic model exists yet. Run `scholaraio explore topics --name <name> --build` first.")
            return
        from scholaraio.interfaces.cli.topics import _write_all_viz

        _write_all_viz(model, model_dir / "viz")

    elif action == "list":
        explore_root = _explore_root(cfg)
        if not explore_root.exists():
            _ui("No explore libraries yet. Run `scholaraio explore fetch --issn <ISSN>` first.")
            return
        for d in sorted(explore_root.iterdir()):
            if not d.is_dir():
                continue
            meta_file = d / "meta.json"
            if meta_file.exists():
                try:
                    meta = json.loads(meta_file.read_text("utf-8"))
                except (OSError, json.JSONDecodeError) as e:
                    _ui(f"  {d.name}: meta.json read failed; skipped ({e})")
                    continue
                query = meta.get("query", {})
                if query:
                    qinfo = ", ".join(f"{k}={v}" for k, v in query.items())
                elif meta.get("issn"):
                    qinfo = f"ISSN {meta['issn']}"
                else:
                    qinfo = "?"
                _ui(f"  {d.name}: {meta.get('count', '?')} papers ({qinfo}, fetched_at {meta.get('fetched_at', '?')})")
        return

    elif action == "info":
        if not args.name:
            # List all explore libraries
            explore_root = _explore_root(cfg)
            if not explore_root.exists():
                _ui("No explore libraries yet. Run `scholaraio explore fetch --issn <ISSN>` first.")
                return
            for d in sorted(explore_root.iterdir()):
                if not d.is_dir():
                    continue
                meta_file = d / "meta.json"
                if meta_file.exists():
                    try:
                        meta = json.loads(meta_file.read_text("utf-8"))
                    except (OSError, json.JSONDecodeError) as e:
                        _ui(f"  {d.name}: meta.json read failed; skipped ({e})")
                        continue
                    # Show query info (backward compatible with old ISSN-only format)
                    query = meta.get("query", {})
                    if query:
                        qinfo = ", ".join(f"{k}={v}" for k, v in query.items())
                    elif meta.get("issn"):
                        qinfo = f"ISSN {meta['issn']}"
                    else:
                        qinfo = "?"
                    _ui(
                        f"  {d.name}: {meta.get('count', '?')} papers ({qinfo}, fetched_at {meta.get('fetched_at', '?')})"
                    )
            return
        from scholaraio.stores.explore import count_papers

        explore_root = _explore_root(cfg)
        meta_file = explore_root / args.name / "meta.json"
        if meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text("utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                _ui(f"Read {meta_file} failed: {e}")
                return
            _ui(f"Explore library: {args.name}")
            for k, v in meta.items():
                _ui(f"  {k}: {v}")
        else:
            n = count_papers(args.name, cfg=cfg)
            _ui(f"Explore library {args.name}: {n} papers")

    else:
        _log_error("Unknown action: %s", action)
        sys.exit(1)
