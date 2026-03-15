"""
cli.py — scholaraio 命令行入口
================================

命令：
    scholaraio index [--rebuild]
    scholaraio embed [--rebuild]
    scholaraio search <query> [--top N] [--year Y] [--journal J] [--type T]
    scholaraio search-author <query> [--top N] [--year Y] [--journal J] [--type T]
    scholaraio vsearch <query> [--top N] [--year Y] [--journal J] [--type T]
    scholaraio usearch <query> [--top N] [--year Y] [--journal J] [--type T]
    scholaraio show <paper-id> [--layer 1|2|3|4]
    scholaraio enrich-toc [<paper-id> | --all] [--force] [--inspect]
    scholaraio enrich-l3 [<paper-id> | --all] [--force] [--inspect] [--max-retries N]
    scholaraio top-cited [--top N] [--year Y] [--journal J] [--type T]
    scholaraio refs <paper-id>
    scholaraio citing <paper-id>
    scholaraio shared-refs <id1> <id2> ... [--min N]
    scholaraio refetch [<paper-id> | --all] [--force]
    scholaraio rename [<paper-id> | --all] [--dry-run]
    scholaraio audit [--severity error|warning|info]
    scholaraio repair <paper-id> --title "..." [--doi DOI] [--author NAME] [--year Y] [--no-api] [--dry-run]
    scholaraio backfill-abstract [--dry-run]
    scholaraio topics [--build] [--rebuild] [--viz] [--topic ID]
    scholaraio pipeline <preset> | --steps <s1,s2,...> [--list] [--dry-run] ...
    scholaraio metrics [--summary] [--last N] [--category CAT] [--since DATE]
    scholaraio setup [check] [--lang en|zh]
    scholaraio migrate-dirs [--execute]
    scholaraio explore fetch --issn <ISSN> [--name NAME] [--year-range Y]
    scholaraio explore embed --name <NAME> [--rebuild]
    scholaraio explore topics --name <NAME> [--build] [--rebuild] [--topic ID]
    scholaraio explore search --name <NAME> <query> [--top N]
    scholaraio explore viz --name <NAME>
    scholaraio explore info [--name NAME]
    scholaraio export bibtex [<paper-id> ...] [--all] [--year Y] [--journal J] [-o FILE]
    scholaraio import-endnote <file.xml|file.ris> [--no-api] [--dry-run] [--no-convert]
    scholaraio import-zotero [--api-key KEY] [--library-id ID] [--local PATH] [--list-collections] ...
    scholaraio attach-pdf <paper-id> <path/to/paper.pdf>
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

from scholaraio.config import load_config
from scholaraio.log import ui

_log = logging.getLogger(__name__)


# ============================================================================
#  Filter args helper
# ============================================================================


def _resolve_top(args: argparse.Namespace, default: int) -> int:
    return args.top if args.top is not None else default


def _add_filter_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--year", type=str, default=None, help="年份过滤：2023 / 2020-2024 / 2020-")
    parser.add_argument("--journal", type=str, default=None, help="期刊名过滤（模糊匹配）")
    parser.add_argument(
        "--type",
        type=str,
        default=None,
        dest="paper_type",
        help="论文类型过滤：review / journal-article 等（模糊匹配）",
    )


def _resolve_ws_paper_ids(args: argparse.Namespace, cfg) -> set[str] | None:
    ws_name = getattr(args, "ws", None)
    if not ws_name:
        return None
    from scholaraio import workspace

    ws_dir = cfg._root / "workspace" / ws_name
    pids = workspace.read_paper_ids(ws_dir)
    if not pids:
        ui(f"工作区 {ws_name} 为空或不存在")
    return pids


# ============================================================================
#  Dependency check helpers
# ============================================================================

_INSTALL_HINTS: dict[str, str] = {
    "sentence_transformers": "pip install scholaraio[embed]",
    "faiss": "pip install scholaraio[embed]",
    "numpy": "pip install scholaraio[embed]",
    "bertopic": "pip install scholaraio[topics]",
    "pandas": "pip install scholaraio[topics]",
    "endnote_utils": "pip install scholaraio[import]",
    "pyzotero": "pip install scholaraio[import]",
}


def _check_import_error(e: ImportError) -> None:
    """Log a user-friendly message for missing optional dependencies, then exit."""
    mod = getattr(e, "name", "") or ""
    # Match the top-level package name
    top = mod.split(".")[0] if mod else ""
    hint = _INSTALL_HINTS.get(top, "")
    if hint:
        _log.error("缺少依赖: %s\n  安装: %s", mod, hint)
    else:
        _log.error("缺少依赖: %s\n  请安装所需的 Python 包", e)
    sys.exit(1)


# ============================================================================
#  Commands
# ============================================================================


def cmd_index(args: argparse.Namespace, cfg) -> None:
    from scholaraio.index import build_index

    papers_dir = cfg.papers_dir
    db_path = cfg.index_db

    if not papers_dir.exists():
        _log.error("papers_dir does not exist: %s", papers_dir)
        sys.exit(1)

    action = "Rebuilding" if args.rebuild else "Building"
    ui(f"{action} index: {papers_dir} -> {db_path}")
    count = build_index(papers_dir, db_path, rebuild=args.rebuild)
    ui(f"Done, indexed {count} papers.")


def cmd_search_author(args: argparse.Namespace, cfg) -> None:
    from scholaraio.index import search_author

    query = " ".join(args.query)
    try:
        results = search_author(
            query,
            cfg.index_db,
            top_k=_resolve_top(args, cfg.search.top_k),
            year=args.year,
            journal=args.journal,
            paper_type=args.paper_type,
        )
    except FileNotFoundError as e:
        _log.error("%s", e)
        sys.exit(1)

    if not results:
        ui(f'No papers found for author "{query}".')
        return

    ui(f'Found {len(results)} papers (author: "{query}"):\n')
    for i, r in enumerate(results, start=1):
        _print_search_result(i, r)


def cmd_search(args: argparse.Namespace, cfg) -> None:
    from scholaraio.index import search

    query = " ".join(args.query)
    try:
        results = search(
            query,
            cfg.index_db,
            top_k=_resolve_top(args, cfg.search.top_k),
            year=args.year,
            journal=args.journal,
            paper_type=args.paper_type,
        )
    except FileNotFoundError as e:
        _log.error("%s", e)
        sys.exit(1)

    if not results:
        ui(f'No results for "{query}".')
        return

    ui(f'Found {len(results)} papers (query: "{query}"):\n')
    for i, r in enumerate(results, start=1):
        _print_search_result(i, r)

    _log.debug("Use: scholaraio show <paper-id> --layer 2/3/4")


def cmd_show(args: argparse.Namespace, cfg) -> None:
    from scholaraio.loader import load_l1, load_l2, load_l3, load_l4

    paper_d = _resolve_paper(args.paper_id, cfg)
    json_path = paper_d / "meta.json"
    md_path = paper_d / "paper.md"

    l1 = load_l1(json_path)
    _print_header(l1)

    if args.layer == 1:
        return

    if args.layer == 2:
        abstract = load_l2(json_path)
        ui("\n--- Abstract ---\n")
        ui(abstract)
        return

    if args.layer == 3:
        conclusion = load_l3(json_path)
        if conclusion is None:
            _log.error("L3 not extracted yet. Run: scholaraio enrich-l3 %s", args.paper_id)
            sys.exit(1)
        ui("\n--- Conclusion ---\n")
        ui(conclusion)
        return

    if args.layer == 4:
        if not md_path.exists():
            _log.error("paper.md not found: %s", md_path)
            sys.exit(1)
        ui("\n--- Full Text ---\n")
        ui(load_l4(md_path))
        return


def cmd_embed(args: argparse.Namespace, cfg) -> None:
    try:
        from scholaraio.vectors import build_vectors
    except ImportError as e:
        _check_import_error(e)

    papers_dir = cfg.papers_dir
    if not papers_dir.exists():
        _log.error("papers_dir does not exist: %s", papers_dir)
        sys.exit(1)

    action = "Rebuilding" if args.rebuild else "Updating"
    ui(f"{action} vector index: {papers_dir} -> {cfg.index_db}")
    count = build_vectors(papers_dir, cfg.index_db, rebuild=args.rebuild, cfg=cfg)
    label = "total" if args.rebuild else "new"
    ui(f"Done, {count} {label} vectors.")


def cmd_vsearch(args: argparse.Namespace, cfg) -> None:
    try:
        from scholaraio.vectors import vsearch
    except ImportError as e:
        _check_import_error(e)

    query = " ".join(args.query)
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
        _log.error("%s", e)
        sys.exit(1)

    if not results:
        ui(f'No results for "{query}".')
        return

    ui(f'Semantic search: "{query}"  top {len(results)}\n')
    for i, r in enumerate(results, start=1):
        score = r.get("score", 0.0)
        _print_search_result(i, r, extra=f"score: {score:.3f}")


def cmd_usearch(args: argparse.Namespace, cfg) -> None:
    from scholaraio.index import unified_search

    query = " ".join(args.query)
    results = unified_search(
        query,
        cfg.index_db,
        top_k=_resolve_top(args, cfg.search.top_k),
        cfg=cfg,
        year=args.year,
        journal=args.journal,
        paper_type=args.paper_type,
    )

    if not results:
        ui(f'No results for "{query}".')
        return

    ui(f'Unified search: "{query}"  {len(results)} results\n')
    for i, r in enumerate(results, start=1):
        score = r.get("score", 0.0)
        match = r.get("match", "?")
        _print_search_result(i, r, extra=f"{match} {score:.3f}")


def cmd_audit(args: argparse.Namespace, cfg) -> None:
    from scholaraio.audit import audit_papers, format_report

    papers_dir = cfg.papers_dir
    if not papers_dir.exists():
        _log.error("papers_dir does not exist: %s", papers_dir)
        sys.exit(1)

    ui(f"Auditing papers: {papers_dir}\n")
    issues = audit_papers(papers_dir)

    if args.severity:
        issues = [i for i in issues if i.severity == args.severity]

    ui(format_report(issues))


def cmd_repair(args: argparse.Namespace, cfg) -> None:
    import json

    from scholaraio.ingest.metadata import (
        PaperMetadata,
        _extract_lastname,
        enrich_metadata,
        generate_new_stem,
        rename_files,
        write_metadata_json,
    )

    papers_dir = cfg.papers_dir
    paper_id = args.paper_id

    paper_d = papers_dir / paper_id
    md_path = paper_d / "paper.md"
    json_path = paper_d / "meta.json"

    if not md_path.exists():
        _log.error("File not found: %s", md_path)
        sys.exit(1)

    # Preserve existing UUID
    existing_uuid = ""
    if json_path.exists():
        try:
            existing_data = json.loads(json_path.read_text(encoding="utf-8"))
            existing_uuid = existing_data.get("id", "")
        except (json.JSONDecodeError, OSError) as e:
            _log.debug("failed to read existing meta.json: %s", e)

    # Build PaperMetadata from CLI args (skip md parsing)
    meta = PaperMetadata()
    meta.id = existing_uuid
    meta.title = args.title
    meta.doi = args.doi or ""
    meta.year = args.year
    meta.source_file = md_path.name
    if args.author:
        meta.authors = [args.author]
        meta.first_author = args.author
        meta.first_author_lastname = _extract_lastname(args.author)

    ui(f"Repair: {paper_id}")
    ui(f"  Title:  {meta.title}")
    ui(f"  Author: {meta.first_author or '?'} | Year: {meta.year or '?'} | DOI: {meta.doi or 'none'}")

    # API enrichment
    if not args.no_api:
        _log.debug("querying APIs")
        cli_author = meta.first_author
        cli_lastname = meta.first_author_lastname
        cli_year = meta.year

        meta = enrich_metadata(meta)

        if cli_author and not meta.authors:
            meta.authors = [cli_author]
            meta.first_author = cli_author
            meta.first_author_lastname = cli_lastname
        if cli_year and not meta.year:
            meta.year = cli_year
    else:
        meta.extraction_method = "manual_fix"
        _log.debug("skipping API query (--no-api)")

    ui(f"  Result: {meta.first_author_lastname} ({meta.year}) {meta.title[:60]}")
    if meta.doi:
        ui(f"  DOI: {meta.doi}")
    ui(f"  Method: {meta.extraction_method}")

    if args.dry_run:
        ui("  [dry-run] no files written")
        return

    # Write new JSON
    write_metadata_json(meta, json_path)
    ui(f"  Written: {json_path.name}")

    new_stem = generate_new_stem(meta)
    rename_files(md_path, json_path, new_stem, dry_run=False)

    _log.debug("done. consider running pipeline reindex")


def cmd_enrich_toc(args: argparse.Namespace, cfg) -> None:
    from scholaraio.loader import enrich_toc
    from scholaraio.papers import iter_paper_dirs

    papers_dir = cfg.papers_dir

    if args.all:
        targets = sorted(d / "meta.json" for d in iter_paper_dirs(papers_dir))
    elif args.paper_id:
        targets = [papers_dir / args.paper_id / "meta.json"]
    else:
        _log.error("Please specify <paper-id> or --all")
        sys.exit(1)

    ok = fail = skip = 0
    for json_path in targets:
        md_path = json_path.parent / "paper.md"
        if not md_path.exists():
            _log.error("Skipped (no paper.md): %s", json_path.parent.name)
            skip += 1
            continue

        ui(f"\n{json_path.parent.name}")
        success = enrich_toc(
            json_path,
            md_path,
            cfg,
            force=args.force,
            inspect=args.inspect,
        )
        if success:
            ok += 1
        else:
            fail += 1

    if args.all or len(targets) > 1:
        ui(f"\nDone: {ok} ok | {fail} failed | {skip} skipped")


def cmd_pipeline(args: argparse.Namespace, cfg) -> None:
    from scholaraio.ingest.pipeline import PRESETS, STEPS, run_pipeline

    if args.list_steps:
        ui("Available steps:")
        for name, sdef in STEPS.items():
            ui(f"  {name:<10} [{sdef.scope:<7}]  {sdef.desc}")
        ui("\nAvailable presets:")
        for name, steps in PRESETS.items():
            ui(f"  {name:<10} = {', '.join(steps)}")
        return

    # Resolve step list
    if args.preset:
        if args.preset not in PRESETS:
            _log.error("Unknown preset '%s'. Available: %s", args.preset, ", ".join(PRESETS))
            sys.exit(1)
        step_names = PRESETS[args.preset]
    elif args.steps:
        step_names = [s.strip() for s in args.steps.split(",") if s.strip()]
    else:
        _log.error("Please specify a preset name or --steps")
        sys.exit(1)

    opts = {
        "dry_run": args.dry_run,
        "no_api": args.no_api,
        "force": args.force,
        "inspect": args.inspect,
        "max_retries": args.max_retries,
        "rebuild": args.rebuild,
    }
    if args.inbox:
        opts["inbox_dir"] = Path(args.inbox).resolve()
    if args.papers:
        opts["papers_dir"] = Path(args.papers).resolve()

    run_pipeline(step_names, cfg, opts)


def cmd_enrich_l3(args: argparse.Namespace, cfg) -> None:
    from scholaraio.loader import enrich_l3
    from scholaraio.papers import iter_paper_dirs

    papers_dir = cfg.papers_dir

    if args.all:
        targets = sorted(d / "meta.json" for d in iter_paper_dirs(papers_dir))
    elif args.paper_id:
        targets = [papers_dir / args.paper_id / "meta.json"]
    else:
        _log.error("Please specify <paper-id> or --all")
        sys.exit(1)

    ok = fail = skip = 0
    for json_path in targets:
        md_path = json_path.parent / "paper.md"
        if not md_path.exists():
            _log.error("Skipped (no paper.md): %s", json_path.parent.name)
            skip += 1
            continue

        ui(f"\n{json_path.parent.name}")
        success = enrich_l3(
            json_path,
            md_path,
            cfg,
            force=args.force,
            max_retries=args.max_retries,
            inspect=args.inspect,
        )
        if success:
            ok += 1
        else:
            fail += 1

    if args.all or len(targets) > 1:
        ui(f"\nDone: {ok} ok | {fail} failed | {skip} skipped")


def cmd_top_cited(args: argparse.Namespace, cfg) -> None:
    from scholaraio.index import top_cited

    try:
        results = top_cited(
            cfg.index_db,
            top_k=_resolve_top(args, cfg.search.top_k),
            year=args.year,
            journal=args.journal,
            paper_type=args.paper_type,
        )
    except FileNotFoundError as e:
        _log.error("%s", e)
        sys.exit(1)

    if not results:
        ui("No citation data in index. Run scholaraio refetch --all first.")
        return

    ui(f"Top {len(results)} papers by citations:\n")
    for i, r in enumerate(results, start=1):
        _print_search_result(i, r)


def cmd_refs(args: argparse.Namespace, cfg) -> None:
    from scholaraio.index import get_references
    from scholaraio.papers import read_meta

    paper_d = _resolve_paper(args.paper_id, cfg)
    meta = read_meta(paper_d)
    paper_uuid = meta.get("id", "")

    pids = _resolve_ws_paper_ids(args, cfg)
    refs = get_references(paper_uuid, cfg.index_db, paper_ids=pids)
    if not refs:
        ui("该论文没有参考文献数据。请先运行 refetch 拉取 references。")
        return

    in_lib = [r for r in refs if r.get("target_id")]
    out_lib = [r for r in refs if not r.get("target_id")]

    scope = f"工作区 {args.ws}" if getattr(args, "ws", None) else "库内"
    ui(f"参考文献共 {len(refs)} 篇（{scope} {len(in_lib)} 篇，库外 {len(out_lib)} 篇）\n")

    if in_lib:
        ui("── 库内 ──")
        for i, r in enumerate(in_lib, 1):
            display = r.get("dir_name") or r["target_id"]
            year = r.get("year") or "?"
            author = r.get("first_author") or "?"
            ui(f"[{i}] {display}")
            ui(f"     {author} | {year} | {r.get('title', '?')}")
            ui(f"     DOI: {r['target_doi']}")
            ui()

    if out_lib:
        ui("── 库外 ──")
        for i, r in enumerate(out_lib, 1):
            ui(f"[{i}] DOI: {r['target_doi']}")
        ui()


def cmd_citing(args: argparse.Namespace, cfg) -> None:
    from scholaraio.index import get_citing_papers
    from scholaraio.papers import read_meta

    paper_d = _resolve_paper(args.paper_id, cfg)
    meta = read_meta(paper_d)
    paper_uuid = meta.get("id", "")

    pids = _resolve_ws_paper_ids(args, cfg)
    results = get_citing_papers(paper_uuid, cfg.index_db, paper_ids=pids)
    if not results:
        scope = f"工作区 {args.ws} 中" if getattr(args, "ws", None) else "本地"
        ui(f"没有找到引用该论文的{scope}论文。")
        return

    scope = f"工作区 {args.ws}" if getattr(args, "ws", None) else "本地"
    ui(f"共 {len(results)} 篇{scope}论文引用了此论文：\n")
    for i, r in enumerate(results, 1):
        display = r.get("dir_name") or r["source_id"]
        year = r.get("year") or "?"
        author = r.get("first_author") or "?"
        ui(f"[{i}] {display}")
        ui(f"     {author} | {year} | {r.get('title', '?')}")
        ui()


def cmd_shared_refs(args: argparse.Namespace, cfg) -> None:
    from scholaraio.index import get_shared_references
    from scholaraio.papers import read_meta

    paper_uuids = []
    for pid in args.paper_ids:
        paper_d = _resolve_paper(pid, cfg)
        meta = read_meta(paper_d)
        paper_uuids.append(meta.get("id", ""))

    min_shared = args.min if args.min is not None else 2
    pids = _resolve_ws_paper_ids(args, cfg)
    results = get_shared_references(paper_uuids, cfg.index_db, min_shared=min_shared, paper_ids=pids)
    if not results:
        ui(f"没有找到被 ≥{min_shared} 篇论文共同引用的参考文献。")
        return

    ui(f"共同参考文献（被 ≥{min_shared} 篇共引）：共 {len(results)} 篇\n")
    for i, r in enumerate(results, 1):
        count = r["shared_count"]
        if r.get("target_id"):
            display = r.get("dir_name") or r["target_id"]
            year = r.get("year") or "?"
            ui(f"[{i}] [{count}x] {display}")
            ui(f"     {r.get('title', '?')} | {year}")
            ui(f"     DOI: {r['target_doi']}")
        else:
            ui(f"[{i}] [{count}x] DOI: {r['target_doi']}")
        ui()


def cmd_refetch(args: argparse.Namespace, cfg) -> None:
    import json
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from scholaraio.ingest.metadata import refetch_metadata
    from scholaraio.papers import iter_paper_dirs

    papers_dir = cfg.papers_dir

    if args.all:
        targets = sorted(d / "meta.json" for d in iter_paper_dirs(papers_dir))
    elif args.paper_id:
        targets = [papers_dir / args.paper_id / "meta.json"]
    else:
        _log.error("Please specify <paper-id> or --all")
        sys.exit(1)

    # Filter: only papers missing citations or bibliographic details (unless --force)
    if args.all and not args.force:
        filtered = []
        for jp in targets:
            data = json.loads(jp.read_text(encoding="utf-8"))
            if not data.get("doi"):
                continue
            missing_cite = not data.get("citation_count")
            missing_bib = not all(data.get(k) for k in ("volume", "publisher"))
            if missing_cite or missing_bib:
                filtered.append(jp)
        ui(f"共 {len(targets)} 篇，{len(filtered)} 篇需要补全")
        targets = filtered

    if not targets:
        ui("无需更新")
        return

    # Filter out non-existent paths
    valid = []
    fail = 0
    for jp in targets:
        if jp.exists():
            valid.append(jp)
        else:
            _log.error("未找到论文: %s", jp.parent.name)
            fail += 1
    targets = valid

    ok = skip = 0
    total = len(targets)
    workers = min(getattr(args, "jobs", 5) or 5, total)
    ui(f"并发 refetch（{workers} workers，共 {total} 篇）...")

    def _do_refetch(jp: Path) -> tuple[Path, bool | None]:
        try:
            return jp, refetch_metadata(jp)
        except Exception as e:
            _log.error("refetch 失败 %s: %s", jp.parent.name, e)
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
                ui(f"[{done}/{total}] ✗ {name}")
            elif changed:
                ok += 1
                ui(f"[{done}/{total}] ✓ {name}")
            else:
                skip += 1
                ui(f"[{done}/{total}] - {name}")

    ui(f"\n完成: {ok} 更新 | {skip} 无变化 | {fail} 失败")


def _write_all_viz(model, viz_dir: Path) -> None:
    """Write 6 BERTopic HTML visualizations to *viz_dir*."""
    from scholaraio.topics import (
        visualize_barchart,
        visualize_heatmap,
        visualize_term_rank,
        visualize_topic_hierarchy,
        visualize_topics_2d,
        visualize_topics_over_time,
    )

    viz_dir.mkdir(parents=True, exist_ok=True)
    _log.debug("generating visualizations")

    charts = [
        ("topics_2d", "2D scatter", visualize_topics_2d),
        ("barchart", "Keywords  ", visualize_barchart),
        ("hierarchy", "Hierarchy ", visualize_topic_hierarchy),
        ("heatmap", "Heatmap   ", visualize_heatmap),
        ("term_rank", "Term rank ", visualize_term_rank),
    ]
    for fname, label, func in charts:
        html = func(model)
        (viz_dir / f"{fname}.html").write_text(html, encoding="utf-8")
        ui(f"  {label} -> {viz_dir / f'{fname}.html'}")

    try:
        html = visualize_topics_over_time(model)
        (viz_dir / "topics_over_time.html").write_text(html, encoding="utf-8")
        ui(f"  Over time  -> {viz_dir / 'topics_over_time.html'}")
    except Exception as e:
        _log.error("Topics-over-time failed: %s", e)


def cmd_topics(args: argparse.Namespace, cfg) -> None:
    try:
        from scholaraio.topics import (
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
        ui(f"{'Rebuilding' if args.rebuild else 'Building'} topic model...")
        model = build_topics(
            cfg.index_db,
            cfg.papers_dir,
            min_topic_size=min_ts,
            nr_topics=_resolve_nr_topics(),
            save_path=model_dir,
            cfg=cfg,
        )
    else:
        try:
            model = load_model(model_dir)
        except FileNotFoundError as e:
            _log.error("%s", e)
            sys.exit(1)

    # Quick reduce (no rebuild)
    if args.reduce is not None:
        ui(f"Reducing to {args.reduce} topics...")
        model = reduce_topics_to(model, args.reduce, save_path=model_dir, cfg=cfg)

    # Manual merge
    if args.merge:
        from scholaraio.topics import merge_topics_by_ids

        # Parse "1,6,14+3,5" → [[1,6,14],[3,5]]
        groups = []
        for group_str in args.merge.split("+"):
            ids = [int(x.strip()) for x in group_str.split(",") if x.strip()]
            if len(ids) >= 2:
                groups.append(ids)
        if groups:
            ui(f"Merging {len(groups)} groups: {groups}")
            model = merge_topics_by_ids(model, groups, save_path=model_dir, cfg=cfg)
        else:
            _log.error("--merge 格式错误，示例: --merge 1,6,14+3,5")

    # Show specific topic
    if args.topic is not None:
        tid = args.topic
        top_n = args.top or 0  # 0 = show all
        if tid == -1:
            papers = get_outliers(model)
            ui(f"Outlier papers: {len(papers)}\n")
        else:
            topic_words = model.get_topic(tid)
            if topic_words is False or topic_words is None:
                _log.error("Topic %d does not exist", tid)
                sys.exit(1)
            keywords = [w for w, _ in topic_words[:10]]
            papers = get_topic_papers(model, tid)
            ui(f"Topic {tid}: {', '.join(keywords)}")
            ui(f"{len(papers)} papers\n")

        if top_n:
            papers = papers[:top_n]
        for i, p in enumerate(papers, 1):
            cc = p.get("citation_count", {})
            best = max((v for v in (cc or {}).values() if isinstance(v, (int, float))), default=0)
            cite_str = f"  [cited: {best}]" if best else ""
            authors = p.get("authors", "")
            first_author = authors.split(",")[0].strip() if authors else ""
            ui(f"  {i:2d}. [{p.get('year', '?')}] {p.get('title', p['paper_id'])}")
            ui(f"      {first_author} | {p.get('journal', '')}{cite_str}")
        return

    # Generate visualizations (6 charts, same as explore)
    if args.viz:
        _write_all_viz(model, model_dir / "viz")
        return

    # Default: show overview
    overview = get_topic_overview(model)
    if not overview:
        ui("No valid topics found. Try reducing topics.min_topic_size or adding more papers.")
        return

    outliers = get_outliers(model)
    total = sum(t["count"] for t in overview) + len(outliers)
    ui(f"Library: {total} papers, {len(overview)} topics, {len(outliers)} outliers\n")

    for t in overview:
        kw = ", ".join(t["keywords"][:6])
        ui(f"Topic {t['topic_id']:2d} ({t['count']:3d} papers): {kw}")
        for p in t["representative_papers"][:3]:
            year = p.get("year", "?")
            title = p.get("title", "")
            if len(title) > 70:
                title = title[:67] + "..."
            ui(f"    [{year}] {title}")
        ui()


def cmd_backfill_abstract(args: argparse.Namespace, cfg) -> None:
    from scholaraio.ingest.metadata import backfill_abstracts

    papers_dir = cfg.papers_dir
    if not papers_dir.exists():
        _log.error("papers_dir does not exist: %s", papers_dir)
        sys.exit(1)

    action = "Preview" if args.dry_run else "Backfill"
    doi_fetch = getattr(args, "doi_fetch", False)
    source = "DOI official source" if doi_fetch else "local .md + LLM fallback"
    ui(f"{action} abstract ({source})...\n")
    stats = backfill_abstracts(papers_dir, dry_run=args.dry_run, doi_fetch=doi_fetch, cfg=cfg)
    parts = [f"{stats['filled']} filled", f"{stats['skipped']} skipped", f"{stats['failed']} failed"]
    if stats.get("updated"):
        parts.insert(1, f"{stats['updated']} updated from official")
    ui(f"\nDone: {' | '.join(parts)}")
    if stats["filled"] and not args.dry_run:
        _log.debug("consider rebuilding vector index: scholaraio embed --rebuild")


def cmd_explore(args: argparse.Namespace, cfg) -> None:
    action = args.explore_action

    if action == "fetch":
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
                ui("请提供 --name 或至少一个过滤条件")
                return
        from scholaraio.explore import fetch_explore

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
            cfg=cfg,
        )
        ui(f"\nFetched {total} papers")

    elif action == "embed":
        try:
            from scholaraio.explore import build_explore_vectors
        except ImportError as e:
            _check_import_error(e)
        n = build_explore_vectors(args.name, rebuild=args.rebuild, cfg=cfg)
        ui(f"Done: {n} new embeddings")

    elif action == "topics":
        try:
            from scholaraio.explore import _explore_dir, build_explore_topics
        except ImportError as e:
            _check_import_error(e)
        try:
            from scholaraio.topics import get_topic_overview, get_topic_papers, load_model
        except ImportError as e:
            _check_import_error(e)

        model_dir = _explore_dir(args.name, cfg) / "topic_model"

        if args.build or args.rebuild:
            nr_topics = args.nr_topics
            info = build_explore_topics(
                args.name,
                rebuild=args.rebuild,
                min_topic_size=args.min_topic_size or 30,
                nr_topics=nr_topics,
                cfg=cfg,
            )
            ui(
                f"\nClustering done: {info['n_topics']} topics, "
                f"{info['n_outliers']} outliers, "
                f"{info['n_papers']} papers"
            )

        try:
            model = load_model(model_dir)
        except FileNotFoundError:
            ui("No topic model. Run scholaraio explore topics --name <name> --build first.")
            return

        if args.topic is not None:
            papers = get_topic_papers(model, args.topic)
            top_n = _resolve_top(args, 20)
            papers = papers[:top_n]
            ui(f"Topic {args.topic}: {len(papers)} papers\n")
            for i, p in enumerate(papers, 1):
                cc = p.get("citation_count", {})
                best = max((v for v in (cc or {}).values() if isinstance(v, (int, float))), default=0)
                cite_str = f"  [cited: {best}]" if best else ""
                authors = p.get("authors", "")
                first_author = authors.split(",")[0].strip() if authors else ""
                title = p.get("title", "")
                if len(title) > 70:
                    title = title[:67] + "..."
                ui(f"  {i:3d}. [{p.get('year', '?')}] {title}")
                ui(f"       {first_author} | {p.get('paper_id', '')}{cite_str}")
            return

        overview = get_topic_overview(model)
        if not overview:
            ui("No valid topics. Run scholaraio explore topics --name <name> --build first.")
            return
        from scholaraio.topics import get_outliers

        outliers = get_outliers(model)
        total = sum(t["count"] for t in overview) + len(outliers)
        ui(f"\n{len(overview)} topics, {total} papers, {len(outliers)} outliers\n")
        for t in overview:
            kw = ", ".join(t["keywords"][:6])
            ui(f"Topic {t['topic_id']:2d} ({t['count']:3d} papers): {kw}")
            for p in t["representative_papers"][:3]:
                title = p.get("title", "")
                if len(title) > 65:
                    title = title[:62] + "..."
                cc = p.get("citation_count", {})
                best = max((v for v in (cc or {}).values() if isinstance(v, (int, float))), default=0)
                cite_str = f"  [cited: {best}]" if best else ""
                ui(f"    [{p.get('year', '?')}] {title}{cite_str}")
            ui()

    elif action == "search":
        query = " ".join(args.query)
        mode = getattr(args, "mode", "semantic") or "semantic"
        top_k = _resolve_top(args, 10)
        if mode == "keyword":
            from scholaraio.explore import explore_search

            results = explore_search(args.name, query, top_k=top_k, cfg=cfg)
        elif mode == "unified":
            try:
                from scholaraio.explore import explore_unified_search
            except ImportError as e:
                _check_import_error(e)
            results = explore_unified_search(args.name, query, top_k=top_k, cfg=cfg)
        else:
            try:
                from scholaraio.explore import explore_vsearch
            except ImportError as e:
                _check_import_error(e)
            results = explore_vsearch(args.name, query, top_k=top_k, cfg=cfg)
        if not results:
            ui("No results found.")
            return
        for i, r in enumerate(results, 1):
            authors = r.get("authors", [])
            first = authors[0] if authors else ""
            cited = r.get("cited_by_count", 0)
            cite_str = f"  [cited: {cited}]" if cited else ""
            ui(f"[{i}] [{r.get('year', '?')}] {r.get('title', '')}")
            ui(f"     {first} | {r.get('doi', '')}  (score: {r['score']:.3f}){cite_str}")
            ui()

    elif action == "viz":
        try:
            from scholaraio.explore import _explore_dir
            from scholaraio.topics import load_model
        except ImportError as e:
            _check_import_error(e)
        model_dir = _explore_dir(args.name, cfg) / "topic_model"
        try:
            model = load_model(model_dir)
        except FileNotFoundError:
            ui("No topic model. Run scholaraio explore topics --name <name> --build first.")
            return
        _write_all_viz(model, model_dir / "viz")

    elif action == "info":
        import json as _json

        if not args.name:
            # List all explore libraries
            explore_root = cfg._root / "data" / "explore"
            if not explore_root.exists():
                ui("No explore libraries. Use scholaraio explore fetch --issn <ISSN> to create one.")
                return
            for d in sorted(explore_root.iterdir()):
                meta_file = d / "meta.json"
                if meta_file.exists():
                    meta = _json.loads(meta_file.read_text("utf-8"))
                    # Show query info (backward compatible with old ISSN-only format)
                    query = meta.get("query", {})
                    if query:
                        qinfo = ", ".join(f"{k}={v}" for k, v in query.items())
                    elif meta.get("issn"):
                        qinfo = f"ISSN {meta['issn']}"
                    else:
                        qinfo = "?"
                    ui(f"  {d.name}: {meta.get('count', '?')} papers ({qinfo}, fetched {meta.get('fetched_at', '?')})")
            return
        from scholaraio.explore import count_papers

        meta_file = cfg._root / "data" / "explore" / args.name / "meta.json"
        if meta_file.exists():
            meta = _json.loads(meta_file.read_text("utf-8"))
            ui(f"Explore library: {args.name}")
            for k, v in meta.items():
                ui(f"  {k}: {v}")
        else:
            n = count_papers(args.name, cfg=cfg)
            ui(f"Explore library {args.name}: {n} papers")

    else:
        _log.error("Unknown action: %s", action)
        sys.exit(1)


def cmd_rename(args: argparse.Namespace, cfg) -> None:
    from scholaraio.ingest.metadata import rename_paper
    from scholaraio.papers import iter_paper_dirs

    papers_dir = cfg.papers_dir

    if args.all:
        targets = sorted(d / "meta.json" for d in iter_paper_dirs(papers_dir))
    elif args.paper_id:
        targets = [papers_dir / args.paper_id / "meta.json"]
    else:
        _log.error("Please specify <paper-id> or --all")
        sys.exit(1)

    renamed = skip = fail = 0
    for json_path in targets:
        if not json_path.exists():
            _log.error("Paper not found: %s", json_path.parent.name)
            fail += 1
            continue

        new_path = rename_paper(json_path, dry_run=args.dry_run)
        if new_path:
            action = "Preview" if args.dry_run else "Rename"
            ui(f"{action}: {json_path.parent.name} -> {new_path.parent.name}")
            renamed += 1
        else:
            skip += 1

    ui(f"\nDone: {renamed} renamed | {skip} unchanged | {fail} failed")
    if renamed and not args.dry_run:
        _log.debug("consider rebuilding index: scholaraio index --rebuild")


# ============================================================================
#  export
# ============================================================================


def cmd_export(args: argparse.Namespace, cfg) -> None:
    action = args.export_action
    if action == "bibtex":
        _cmd_export_bibtex(args, cfg)
    else:
        _log.error("Unknown export action: %s", action)
        sys.exit(1)


def _cmd_export_bibtex(args: argparse.Namespace, cfg) -> None:
    from scholaraio.export import export_bibtex

    paper_ids = args.paper_ids if args.paper_ids else None
    if not paper_ids and not args.all:
        _log.error("请指定论文 ID 或 --all")
        sys.exit(1)

    bib = export_bibtex(
        cfg.papers_dir,
        paper_ids=paper_ids,
        year=args.year,
        journal=args.journal,
    )

    if not bib:
        ui("未找到匹配的论文")
        return

    if args.output:
        out = Path(args.output)
        out.write_text(bib, encoding="utf-8")
        ui(f"已导出到 {out}（{bib.count('@')} 篇）")
    else:
        print(bib)


# ============================================================================
#  workspace
# ============================================================================


def cmd_ws(args: argparse.Namespace, cfg) -> None:
    from scholaraio import workspace

    ws_root = cfg._root / "workspace"
    action = args.ws_action

    if action == "init":
        ws_dir = ws_root / args.name
        workspace.create(ws_dir)
        ui(f"工作区已创建: {ws_dir}")

    elif action == "add":
        ws_dir = ws_root / args.name
        if not (ws_dir / "papers.json").exists():
            workspace.create(ws_dir)

        # Resolve paper_refs from batch flags or positional args
        paper_refs = args.paper_refs or []
        if args.add_all:
            import sqlite3

            index_db_path = Path(cfg.index_db)
            if not index_db_path.exists():
                ui("索引数据库不存在，可能尚未初始化。")
                ui("请先运行: scholaraio index")
                return

            try:
                with sqlite3.connect(cfg.index_db) as conn:
                    conn.row_factory = sqlite3.Row
                    rows = conn.execute("SELECT id, dir_name FROM papers_registry").fetchall()
            except sqlite3.OperationalError as e:
                _log.debug("索引数据库查询失败: %s", e)
                ui("索引数据库结构不完整或尚未初始化。")
                ui("请先运行: scholaraio index")
                return

            resolved = [{"id": r["id"], "dir_name": r["dir_name"]} for r in rows]
            if not resolved:
                ui("主库中没有论文")
                return
            added = workspace.add(ws_dir, [], cfg.index_db, resolved=resolved)
            ui(f"已添加 {len(added)} 篇论文到 {args.name}")
            for e in added:
                ui(f"  + {e['dir_name']}")
            return
        elif args.add_topic is not None:
            from scholaraio.topics import get_topic_papers, load_model

            try:
                model = load_model(cfg.topics_model_dir)
            except (FileNotFoundError, ImportError) as e:
                ui(f"无法加载主题模型: {e}")
                ui("请先运行: scholaraio topics --build")
                return
            papers = get_topic_papers(model, args.add_topic)
            if not papers:
                ui(f"主题 {args.add_topic} 中没有论文")
                return
            paper_refs = [p["paper_id"] for p in papers]
            ui(f"主题 {args.add_topic}: 找到 {len(paper_refs)} 篇论文")
        elif args.add_search is not None:
            from scholaraio.index import unified_search

            results = unified_search(
                args.add_search,
                cfg.index_db,
                top_k=_resolve_top(args, cfg.search.top_k),
                cfg=cfg,
                year=getattr(args, "year", None),
                journal=getattr(args, "journal", None),
                paper_type=getattr(args, "paper_type", None),
            )
            if not results:
                ui(f'未找到 "{args.add_search}" 的结果')
                return
            paper_refs = [r["paper_id"] for r in results]
            ui(f'搜索 "{args.add_search}": 找到 {len(paper_refs)} 篇论文')

        if not paper_refs:
            ui("未指定论文引用")
            return

        added = workspace.add(ws_dir, paper_refs, cfg.index_db)
        ui(f"已添加 {len(added)} 篇论文到 {args.name}")
        for e in added:
            ui(f"  + {e['dir_name']}")

    elif action == "remove":
        ws_dir = ws_root / args.name
        removed = workspace.remove(ws_dir, args.paper_refs, cfg.index_db)
        ui(f"已移除 {len(removed)} 篇论文")
        for e in removed:
            ui(f"  - {e['dir_name']}")

    elif action == "list":
        names = workspace.list_workspaces(ws_root)
        if not names:
            ui("没有工作区")
            return
        for name in names:
            ws_dir = ws_root / name
            ids = workspace.read_paper_ids(ws_dir)
            ui(f"  {name} ({len(ids)} papers)")

    elif action == "show":
        ws_dir = ws_root / args.name
        papers = workspace.show(ws_dir, cfg.index_db)
        ui(f"工作区 {args.name}: {len(papers)} 篇论文")
        for i, p in enumerate(papers, 1):
            ui(f"  {i:3d}. {p['dir_name']}")

    elif action == "search":
        ws_dir = ws_root / args.name
        pids = workspace.read_paper_ids(ws_dir)
        if not pids:
            ui("工作区为空")
            return
        query = " ".join(args.query)
        from scholaraio.index import unified_search

        results = unified_search(
            query,
            cfg.index_db,
            top_k=_resolve_top(args, cfg.search.top_k),
            cfg=cfg,
            year=args.year,
            journal=args.journal,
            paper_type=args.paper_type,
            paper_ids=pids,
        )
        if not results:
            ui(f'工作区 {args.name} 中未找到 "{query}" 的结果')
            return
        ui(f"工作区 {args.name} 中找到 {len(results)} 篇:\n")
        for i, r in enumerate(results, 1):
            _print_search_result(i, r, extra=f" [{r.get('match', '')}]")

    elif action == "export":
        ws_dir = ws_root / args.name
        dir_names = workspace.read_dir_names(ws_dir, cfg.index_db)
        if not dir_names:
            ui("工作区为空")
            return
        from scholaraio.export import export_bibtex

        bib = export_bibtex(
            cfg.papers_dir,
            paper_ids=list(dir_names),
            year=args.year,
            journal=args.journal,
        )
        if not bib:
            ui("未找到匹配的论文")
            return
        if args.output:
            out = Path(args.output)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(bib, encoding="utf-8")
            ui(f"已导出到 {out}（{bib.count('@')} 篇）")
        else:
            print(bib)


# ============================================================================
#  metrics
# ============================================================================


def cmd_metrics(args: argparse.Namespace, cfg) -> None:
    from scholaraio.metrics import get_store

    store = get_store()
    if not store:
        _log.error("Metrics database not initialized.")
        return

    if args.summary:
        s = store.summary()
        ui("LLM call statistics (all sessions):")
        ui(f"  calls:        {s['call_count']}")
        ui(f"  prompt tokens:  {s['total_tokens_in']:,}")
        ui(f"  completion:     {s['total_tokens_out']:,}")
        ui(f"  total tokens:   {s['total_tokens_in'] + s['total_tokens_out']:,}")
        ui(f"  total time:     {s['total_duration_s']:.1f}s")
        return

    rows = store.query(
        category=args.category,
        since=args.since,
        limit=args.last,
    )
    if not rows:
        ui("No records.")
        return

    # Header
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


def cmd_setup(args: argparse.Namespace, cfg) -> None:
    from scholaraio.setup import format_check_results, run_check, run_wizard

    action = getattr(args, "setup_action", None)
    if action == "check":
        lang = getattr(args, "lang", "zh")
        results = run_check(cfg, lang)
        ui(format_check_results(results))
    else:
        run_wizard(cfg)


_NOTIFY_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def _validate_notify_name(name: str) -> None:
    if not _NOTIFY_NAME_RE.match(name):
        raise SystemExit(f"错误: 通知任务名称只允许字母、数字、连字符、下划线和点（不含空格）: {name!r}")


def cmd_notify(args: argparse.Namespace, cfg) -> None:
    from scholaraio import notify

    ws_root = cfg._root / "workspace"
    action = args.notify_action

    if action == "init":
        _validate_notify_name(args.name)
        channels = args.channel or []
        ws_dir = ws_root / args.name
        # Apply global NotifyConfig defaults when arg was not explicitly provided
        nc = cfg.notify
        config = notify.init_notify(
            ws_dir,
            query=args.query,
            schedule=args.schedule if args.schedule is not None else nc.default_schedule,
            channels=channels,
            sources=args.sources or list(nc.default_sources),
            relevance_threshold=args.threshold if args.threshold is not None else nc.default_threshold,
            max_papers=args.max_papers if args.max_papers is not None else nc.default_max_papers,
        )
        ui(f"通知任务已创建: {ws_dir}")
        ui(f"  兴趣查询: {config['interest_query']}")
        ui(f"  调度计划: {config['schedule']}")
        ui(f"  频道数量: {len(config['channels'])}")
        if not config["channels"]:
            ui("  提示: 使用 --channel 'tgram://TOKEN/CHAT_ID' 添加推送频道")
        ui(f"\n预览摘要效果: scholaraio notify run {args.name} --dry-run")

    elif action == "run":
        _validate_notify_name(args.name)
        ws_dir = ws_root / args.name
        if not (ws_dir / "notify.json").exists():
            ui(f"错误: 通知任务不存在: {args.name}")
            ui("请先运行: scholaraio notify init <名称> --query <查询词>")
            return

        dry_run = args.dry_run
        mode = " (dry-run)" if dry_run else ""
        ui(f"运行通知任务{mode}: {args.name}")

        result = notify.run_notify(ws_dir, cfg, dry_run=dry_run)

        ui(f"\n  拉取: {result['n_fetched']} 篇")
        ui(f"  新增: {result['n_new']} 篇 (阈值过滤后)")
        ui(f"  摘要: {result['digest_path']}")
        if dry_run:
            ui("  dry-run 模式: 未推送，未更新 last_run")
        elif result["n_new"] == 0:
            ui("  本期无新论文")
        elif result["failed_channels"]:
            ui(f"  推送失败频道: {result['failed_channels']}")
        elif result["n_channels"] == 0:
            ui("  仅保存到文件（未配置推送频道）")
        else:
            ui(f"  已推送: {result['n_sent']} 篇")

    elif action == "list":
        tasks = notify.list_notify_tasks(ws_root)
        if not tasks:
            ui("没有通知任务")
            ui("创建方法: scholaraio notify init <名称> --query <查询词>")
            return
        ui(f"共 {len(tasks)} 个通知任务:\n")
        for t in tasks:
            last = t["last_run"] or "从未运行"
            ch_str = f"{len(t['channels'])} 个频道" if t["channels"] else "未配置频道"
            ui(f"  {t['name']}")
            ui(f"    查询: {t['query']}")
            ui(f"    计划: {t['schedule']}  |  {ch_str}  |  上次运行: {last}")

    elif action == "install":
        _validate_notify_name(args.name)
        ws_dir = ws_root / args.name
        if not (ws_dir / "notify.json").exists():
            ui(f"错误: 通知任务不存在: {args.name}")
            return

        # Prefer SCHOLARAIO_CONFIG env override so the installed unit matches
        # the current session's config; fall back to the discovered config file.
        import os

        env_cfg = os.environ.get("SCHOLARAIO_CONFIG")
        if env_cfg:
            config_file = Path(env_cfg)
        else:
            config_file = cfg._root / "config.yaml"
            if not config_file.exists():
                config_file = Path.home() / ".scholaraio" / "config.yaml"

        service_path, timer_path = notify.install_systemd(ws_dir, config_file)
        ui("systemd 文件已写入:")
        ui(f"  {service_path}")
        ui(f"  {timer_path}")
        ws_name = args.name
        ui(f"\n定时器已启动: scholaraio-notify-{ws_name}.timer")
        ui(f"手动触发: systemctl --user start scholaraio-notify-{ws_name}.service")
        ui(f"查看日志: journalctl --user -u scholaraio-notify-{ws_name}.service")

    elif action == "history":
        _validate_notify_name(args.name)
        records = notify.get_digest_history(cfg.index_db, args.name, limit=args.last)
        if not records:
            ui(f"暂无推送历史: {args.name}")
            return
        ui(f"推送历史 ({args.name}，最近 {len(records)} 条):\n")
        for r in records:
            sent = r["sent_at"][:10] if r["sent_at"] else "未推送"
            ui(f"  {r['generated_at'][:10]}  {r['n_papers']:3d} 篇  [{sent}]  {r['digest_path']}")

    else:
        _log.error("未知 notify 子命令: %s", action)
        import sys

        sys.exit(1)


def cmd_migrate_dirs(args: argparse.Namespace, cfg) -> None:
    from scholaraio.migrate import migrate_to_dirs

    dry_run = not args.execute
    stats = migrate_to_dirs(cfg.papers_dir, dry_run=dry_run)
    mode = "dry-run" if dry_run else "executed"
    ui(f"\n迁移完成 ({mode}): {stats['migrated']} 迁移 | {stats['skipped']} 跳过 | {stats['failed']} 失败")
    if dry_run and stats["migrated"]:
        ui("添加 --execute 以实际执行迁移")
    if not dry_run and stats["migrated"]:
        ui("请运行 `scholaraio pipeline reindex` 重建索引")


def cmd_import_endnote(args: argparse.Namespace, cfg) -> None:
    try:
        from scholaraio.sources.endnote import parse_endnote_full
    except ImportError as e:
        _check_import_error(e)

    from scholaraio.ingest.pipeline import import_external

    paths = [Path(f) for f in args.files]
    for p in paths:
        if not p.exists():
            ui(f"错误：文件不存在: {p}")
            sys.exit(1)

    records, pdf_paths = parse_endnote_full(paths)
    if not records:
        ui("未解析到任何记录")
        return

    n_pdfs = sum(1 for p in pdf_paths if p is not None)
    if n_pdfs:
        ui(f"解析到 {len(records)} 条记录，{n_pdfs} 个可匹配 PDF")
    else:
        ui(f"解析到 {len(records)} 条记录")

    stats = import_external(
        records,
        cfg,
        pdf_paths=pdf_paths,
        no_api=args.no_api,
        dry_run=args.dry_run,
    )

    # Batch convert PDFs → paper.md via MinerU + enrich (toc/l3/abstract)
    if not args.dry_run and not args.no_convert and stats["ingested"] > 0:
        _batch_convert_pdfs(cfg, enrich=True)


def _batch_convert_pdfs(cfg, *, enrich: bool = False) -> None:
    """Convert all unprocessed PDFs in papers_dir to paper.md via MinerU."""
    from scholaraio.ingest.pipeline import batch_convert_pdfs

    batch_convert_pdfs(cfg, enrich=enrich)


def cmd_import_zotero(args: argparse.Namespace, cfg) -> None:
    import tempfile

    # Resolve credentials
    api_key = args.api_key or cfg.resolved_zotero_api_key()
    library_id = args.library_id or cfg.resolved_zotero_library_id()
    library_type = args.library_type or cfg.zotero.library_type

    # Local SQLite mode
    if args.local:
        db_path = Path(args.local)
        if not db_path.exists():
            ui(f"错误：Zotero 数据库不存在: {db_path}")
            sys.exit(1)

        from scholaraio.sources.zotero import list_collections_local, parse_zotero_local

        if args.list_collections:
            collections = list_collections_local(db_path)
            if not collections:
                ui("没有找到 collections")
                return
            ui(f"{'Key':<12} {'Items':>5}  Name")
            ui("-" * 50)
            for c in collections:
                ui(f"{c['key']:<12} {c['numItems']:>5}  {c['name']}")
            return

        records, pdf_paths = parse_zotero_local(
            db_path,
            collection_key=args.collection,
            item_types=args.item_type,
        )
    else:
        # Web API mode
        if not api_key:
            ui("错误：需要 Zotero API key（--api-key 或 config.local.yaml zotero.api_key 或 ZOTERO_API_KEY 环境变量）")
            sys.exit(1)
        if not library_id:
            ui(
                "错误：需要 Zotero library ID（--library-id 或 config.local.yaml zotero.library_id 或 ZOTERO_LIBRARY_ID 环境变量）"
            )
            sys.exit(1)

        try:
            from scholaraio.sources.zotero import fetch_zotero_api, list_collections_api
        except ImportError as e:
            _check_import_error(e)

        if args.list_collections:
            collections = list_collections_api(library_id, api_key, library_type=library_type)
            if not collections:
                ui("没有找到 collections")
                return
            ui(f"{'Key':<12} {'Items':>5}  Name")
            ui("-" * 50)
            for c in collections:
                ui(f"{c['key']:<12} {c['numItems']:>5}  {c['name']}")
            return

        download_pdfs = not args.no_pdf
        pdf_dir = Path(tempfile.mkdtemp(prefix="scholaraio_zotero_")) if download_pdfs else None

        records, pdf_paths = fetch_zotero_api(
            library_id,
            api_key,
            library_type=library_type,
            collection_key=args.collection,
            item_types=args.item_type,
            download_pdfs=download_pdfs,
            pdf_dir=pdf_dir,
        )

    if not records:
        ui("未获取到任何记录")
        return

    n_pdfs = sum(1 for p in pdf_paths if p is not None)
    if n_pdfs:
        ui(f"获取到 {len(records)} 条记录，{n_pdfs} 个 PDF")
    else:
        ui(f"获取到 {len(records)} 条记录")

    from scholaraio.ingest.pipeline import import_external

    stats = import_external(
        records,
        cfg,
        pdf_paths=pdf_paths,
        no_api=args.no_api,
        dry_run=args.dry_run,
    )

    # Batch convert PDFs → paper.md via MinerU + enrich (toc/l3/abstract)
    if not args.dry_run and not args.no_convert and stats["ingested"] > 0:
        _batch_convert_pdfs(cfg, enrich=True)

    # Import collections as workspaces
    if args.import_collections and not args.dry_run:
        _import_zotero_collections_as_workspaces(args, cfg, api_key, library_id, library_type)


def _import_zotero_collections_as_workspaces(args, cfg, api_key, library_id, library_type):
    """Create workspaces from Zotero collections after import."""

    from scholaraio import workspace
    from scholaraio.papers import iter_paper_dirs

    if args.local:
        from scholaraio.sources.zotero import list_collections_local, parse_zotero_local

        collections = list_collections_local(Path(args.local))
    else:
        from scholaraio.sources.zotero import list_collections_api

        collections = list_collections_api(library_id, api_key, library_type=library_type)

    # Build DOI → UUID map from existing papers
    from scholaraio.papers import read_meta

    doi_to_uuid: dict[str, str] = {}
    for pdir in iter_paper_dirs(cfg.papers_dir):
        try:
            meta = read_meta(pdir)
        except (ValueError, FileNotFoundError):
            continue
        if meta.get("doi") and meta.get("id"):
            doi_to_uuid[meta["doi"].lower()] = meta["id"]

    ws_root = cfg._root / "workspace"
    for coll in collections:
        name = coll["name"].replace("/", "-").replace(" ", "_")
        ws_dir = ws_root / name

        # Get papers in this collection
        if args.local:
            coll_records, _ = parse_zotero_local(
                Path(args.local),
                collection_key=coll["key"],
            )
        else:
            from scholaraio.sources.zotero import fetch_zotero_api

            coll_records, _ = fetch_zotero_api(
                library_id,
                api_key,
                library_type=library_type,
                collection_key=coll["key"],
                download_pdfs=False,
            )

        # Match to ingested papers by DOI
        uuids = []
        for r in coll_records:
            if r.doi and r.doi.lower() in doi_to_uuid:
                uuids.append(doi_to_uuid[r.doi.lower()])

        if not uuids:
            continue

        workspace.create(ws_dir)
        workspace.add(ws_dir, uuids, cfg.index_db)
        ui(f"工作区 {name}: {len(uuids)} 篇论文")


def cmd_attach_pdf(args: argparse.Namespace, cfg) -> None:
    import shutil

    paper_d = _resolve_paper(args.paper_id, cfg)
    pdf_path = Path(args.pdf_path)

    if not pdf_path.exists():
        ui(f"错误：PDF 文件不存在: {pdf_path}")
        sys.exit(1)

    existing_md = paper_d / "paper.md"
    if existing_md.exists():
        ui(f"警告：{paper_d.name} 已有 paper.md，将被覆盖")

    # Copy PDF to paper directory
    dest_pdf = paper_d / pdf_path.name
    shutil.copy2(str(pdf_path), str(dest_pdf))
    ui(f"已复制 PDF: {dest_pdf.name}")

    # Convert PDF → markdown via MinerU
    from scholaraio.ingest.mineru import ConvertOptions, check_server, convert_pdf

    mineru_opts = ConvertOptions(
        api_url=cfg.ingest.mineru_endpoint,
        output_dir=paper_d,
    )

    if check_server(cfg.ingest.mineru_endpoint):
        result = convert_pdf(dest_pdf, mineru_opts)
    else:
        api_key = cfg.resolved_mineru_api_key()
        if not api_key:
            ui("错误：MinerU 不可达且无云 API key")
            sys.exit(1)
        from scholaraio.ingest.mineru import convert_pdf_cloud

        result = convert_pdf_cloud(
            dest_pdf,
            mineru_opts,
            api_key=api_key,
            cloud_url=cfg.ingest.mineru_cloud_url,
        )

    if not result.success:
        ui(f"MinerU 转换失败: {result.error}")
        sys.exit(1)

    # Move/rename output to paper.md
    if result.md_path and result.md_path != existing_md:
        if existing_md.exists():
            existing_md.unlink()
        shutil.move(str(result.md_path), str(existing_md))

    # Clean up MinerU artifacts (keep images/)
    for pattern in ["*_layout.json", "*_content_list.json", "*_origin.pdf"]:
        for f in paper_d.glob(pattern):
            f.unlink(missing_ok=True)
    # Rename MinerU images dir if needed
    for img_dir in paper_d.glob("*_images"):
        if img_dir.name != "images" and img_dir.is_dir():
            target = paper_d / "images"
            if target.exists():
                shutil.rmtree(target)
            img_dir.rename(target)

    # Clean up the copied PDF (we only need the markdown)
    if dest_pdf.exists() and dest_pdf.name != "paper.pdf":
        dest_pdf.unlink()

    ui(f"paper.md 已生成: {paper_d.name}/")

    # Backfill abstract if missing
    from scholaraio.papers import read_meta, write_meta

    data = read_meta(paper_d)
    if not data.get("abstract"):
        from scholaraio.ingest.metadata import extract_abstract_from_md

        abstract = extract_abstract_from_md(existing_md, cfg)
        if abstract:
            data["abstract"] = abstract
            write_meta(paper_d, data)
            ui(f"abstract 已补全 ({len(abstract)} chars)")

    # Incremental re-embed + re-index
    from scholaraio.ingest.pipeline import step_embed, step_index

    step_embed(cfg.papers_dir, cfg, {"dry_run": False, "rebuild": False})
    step_index(cfg.papers_dir, cfg, {"dry_run": False, "rebuild": False})


# ============================================================================
#  Output helpers
# ============================================================================


def _print_search_result(idx: int, r: dict, extra: str = "") -> None:
    authors = r.get("authors") or ""
    author_display = authors.split(",")[0].strip() + (" et al." if "," in authors else "")
    cite = r.get("citation_count") or ""
    cite_suffix = f"  [cited: {cite}]" if cite else ""
    extra_suffix = f"  ({extra})" if extra else ""
    # Prefer dir_name for display, fall back to paper_id (UUID)
    display_id = r.get("dir_name") or r["paper_id"]
    ui(f"[{idx}] {display_id}{extra_suffix}")
    ui(f"     {author_display} | {r.get('year', '?')} | {r.get('journal', '?')}{cite_suffix}")
    ui(f"     {r['title']}")
    ui()


def _format_citations(cc: dict) -> str:
    if not cc:
        return ""
    parts = []
    for src in ("semantic_scholar", "openalex", "crossref"):
        if src in cc:
            label = {"semantic_scholar": "S2", "openalex": "OA", "crossref": "CR"}[src]
            parts.append(f"{label}:{cc[src]}")
    return " | ".join(parts)


def _resolve_paper(paper_id: str, cfg) -> Path:
    """Resolve a paper identifier (dir_name, UUID, or DOI) to its directory.

    Resolution order:
    1. Direct dir_name match on filesystem
    2. Registry lookup (UUID / DOI) → dir_name
    3. Filesystem scan — read each meta.json["id"] to find UUID match

    Returns the paper directory Path, or exits with error.
    """
    from scholaraio.papers import iter_paper_dirs

    papers_dir = cfg.papers_dir
    # 1. Direct dir_name
    paper_d = papers_dir / paper_id
    if (paper_d / "meta.json").exists():
        return paper_d
    # 2. Registry lookup (fast, but may be stale)
    from scholaraio.index import lookup_paper

    reg = lookup_paper(cfg.index_db, paper_id)
    if reg:
        paper_d = papers_dir / reg["dir_name"]
        if (paper_d / "meta.json").exists():
            return paper_d
    # 3. Filesystem scan fallback (handles stale registry / pre-index state)
    from scholaraio.papers import read_meta as _read_meta

    for pdir in iter_paper_dirs(papers_dir):
        try:
            data = _read_meta(pdir)
        except (ValueError, FileNotFoundError) as e:
            _log.debug("failed to read meta.json in %s: %s", pdir.name, e)
            continue
        if data.get("id") == paper_id or data.get("doi") == paper_id:
            return pdir
    _log.error("Paper not found: %s", paper_id)
    sys.exit(1)


def _print_header(l1: dict) -> None:
    authors = l1.get("authors") or []
    author_str = ", ".join(authors[:3])
    if len(authors) > 3:
        author_str += f" et al. ({len(authors)} total)"
    ui(f"paper_id : {l1['paper_id']}")
    ui(f"title    : {l1['title']}")
    ui(f"authors  : {author_str}")
    ui(f"year     : {l1.get('year') or '?'}  |  journal: {l1.get('journal') or '?'}")
    if l1.get("doi"):
        ui(f"doi      : {l1['doi']}")
    if l1.get("paper_type"):
        ui(f"type     : {l1['paper_type']}")
    cite_str = _format_citations(l1.get("citation_count") or {})
    if cite_str:
        ui(f"cited    : {cite_str}")
    ids = l1.get("ids") or {}
    if ids.get("semantic_scholar_url"):
        ui(f"S2       : {ids['semantic_scholar_url']}")
    if ids.get("openalex_url"):
        ui(f"OpenAlex : {ids['openalex_url']}")


# ============================================================================
#  Entry point
# ============================================================================


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="scholaraio",
        description="本地学术文献检索工具",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- index ---
    p_index = sub.add_parser("index", help="构建 FTS5 检索索引")
    p_index.set_defaults(func=cmd_index)
    p_index.add_argument("--rebuild", action="store_true", help="清空后重建")

    # --- search ---
    p_search = sub.add_parser("search", help="关键词检索")
    p_search.set_defaults(func=cmd_search)
    p_search.add_argument("query", nargs="+", help="检索词")
    p_search.add_argument("--top", type=int, default=None, help="最多返回 N 条（默认读 config search.top_k）")
    _add_filter_args(p_search)

    # --- search-author ---
    p_sa = sub.add_parser("search-author", help="按作者名搜索")
    p_sa.set_defaults(func=cmd_search_author)
    p_sa.add_argument("query", nargs="+", help="作者名（模糊匹配）")
    p_sa.add_argument("--top", type=int, default=None, help="最多返回 N 条（默认读 config search.top_k）")
    _add_filter_args(p_sa)

    # --- show ---
    p_show = sub.add_parser("show", help="查看论文内容")
    p_show.set_defaults(func=cmd_show)
    p_show.add_argument("paper_id", help="论文目录名（search 结果中显示）")
    p_show.add_argument(
        "--layer",
        type=int,
        default=2,
        choices=[1, 2, 3, 4],
        help="加载层级：1=元数据, 2=摘要, 3=结论, 4=全文（默认 2）",
    )

    # --- embed ---
    p_embed = sub.add_parser("embed", help="生成语义向量写入 index.db")
    p_embed.set_defaults(func=cmd_embed)
    p_embed.add_argument("--rebuild", action="store_true", help="清空后重建")

    # --- vsearch ---
    p_vsearch = sub.add_parser("vsearch", help="语义向量检索")
    p_vsearch.set_defaults(func=cmd_vsearch)
    p_vsearch.add_argument("query", nargs="+", help="检索词")
    p_vsearch.add_argument("--top", type=int, default=None, help="最多返回 N 条（默认读 config embed.top_k）")
    _add_filter_args(p_vsearch)

    # --- usearch (unified) ---
    p_usearch = sub.add_parser("usearch", help="融合检索（关键词 + 语义向量）")
    p_usearch.set_defaults(func=cmd_usearch)
    p_usearch.add_argument("query", nargs="+", help="检索词")
    p_usearch.add_argument("--top", type=int, default=None, help="最多返回 N 条（默认读 config search.top_k）")
    _add_filter_args(p_usearch)

    # --- enrich-toc ---
    p_toc = sub.add_parser("enrich-toc", help="LLM 过滤标题噪声，提取论文 TOC 写入 JSON")
    p_toc.set_defaults(func=cmd_enrich_toc)
    p_toc.add_argument("paper_id", nargs="?", help="论文 ID（省略则需 --all）")
    p_toc.add_argument("--all", action="store_true", help="处理 papers_dir 中所有论文")
    p_toc.add_argument("--force", action="store_true", help="强制重新提取")
    p_toc.add_argument("--inspect", action="store_true", help="展示过滤过程")

    # --- pipeline ---
    p_pipe = sub.add_parser("pipeline", help="组合步骤流水线（可任意组装）")
    p_pipe.set_defaults(func=cmd_pipeline)
    p_pipe.add_argument(
        "preset",
        nargs="?",
        help="预设名称：full | ingest | enrich | reindex",
    )
    p_pipe.add_argument("--steps", help="自定义步骤序列（逗号分隔），如 toc,l3,index")
    p_pipe.add_argument("--list", dest="list_steps", action="store_true", help="列出所有步骤和预设")
    p_pipe.add_argument("--dry-run", action="store_true", help="预览，不写文件")
    p_pipe.add_argument("--no-api", action="store_true", help="离线模式，跳过外部 API")
    p_pipe.add_argument("--force", action="store_true", help="强制重新处理（toc/l3）")
    p_pipe.add_argument("--inspect", action="store_true", help="展示处理详情")
    p_pipe.add_argument("--max-retries", type=int, default=2, help="l3 最大重试次数（默认 2）")
    p_pipe.add_argument("--rebuild", action="store_true", help="重建索引（index 步骤）")
    p_pipe.add_argument("--inbox", help="inbox 目录（默认 data/inbox）")
    p_pipe.add_argument("--papers", help="papers 目录（默认配置值）")

    # --- refetch ---
    p_refetch = sub.add_parser("refetch", help="重新查询 API 补全引用量等字段")
    p_refetch.set_defaults(func=cmd_refetch)
    p_refetch.add_argument("paper_id", nargs="?", help="论文 ID（省略则需 --all）")
    p_refetch.add_argument("--all", action="store_true", help="补查所有缺失引用量的论文")
    p_refetch.add_argument("--force", action="store_true", help="强制重新查询（包括已有引用量的论文）")
    p_refetch.add_argument("--jobs", "-j", type=int, default=5, help="并发数（默认 5）")

    # --- top-cited ---
    p_tc = sub.add_parser("top-cited", help="按引用量排序查看论文")
    p_tc.set_defaults(func=cmd_top_cited)
    p_tc.add_argument("--top", type=int, default=None, help="最多返回 N 条（默认读 config search.top_k）")
    _add_filter_args(p_tc)

    # --- refs ---
    p_refs = sub.add_parser("refs", help="查看论文的参考文献列表")
    p_refs.set_defaults(func=cmd_refs)
    p_refs.add_argument("paper_id", help="论文 ID（目录名 / UUID / DOI）")
    p_refs.add_argument("--ws", type=str, default=None, help="限定工作区范围")

    # --- citing ---
    p_citing = sub.add_parser("citing", help="查看哪些本地论文引用了此论文")
    p_citing.set_defaults(func=cmd_citing)
    p_citing.add_argument("paper_id", help="论文 ID（目录名 / UUID / DOI）")
    p_citing.add_argument("--ws", type=str, default=None, help="限定工作区范围")

    # --- shared-refs ---
    p_sr = sub.add_parser("shared-refs", help="共同参考文献分析")
    p_sr.set_defaults(func=cmd_shared_refs)
    p_sr.add_argument("paper_ids", nargs="+", help="论文 ID（至少 2 个）")
    p_sr.add_argument("--min", type=int, default=None, help="最少共引次数（默认 2）")
    p_sr.add_argument("--ws", type=str, default=None, help="限定工作区范围")

    # --- topics ---
    p_topics = sub.add_parser("topics", help="BERTopic 主题建模与探索")
    p_topics.set_defaults(func=cmd_topics)
    p_topics.add_argument("--build", action="store_true", help="构建主题模型（增量）")
    p_topics.add_argument("--rebuild", action="store_true", help="清空后重建主题模型")
    p_topics.add_argument("--reduce", type=int, default=None, metavar="N", help="快速合并主题到 N 个（不重新聚类）")
    p_topics.add_argument(
        "--merge", type=str, default=None, metavar="IDS", help="手动合并主题，格式: 1,6,14+3,5（用+分隔组）"
    )
    p_topics.add_argument("--topic", type=int, default=None, metavar="ID", help="查看指定主题的论文（-1 查看 outlier）")
    p_topics.add_argument("--top", type=int, default=None, help="返回条数")
    p_topics.add_argument("--min-topic-size", type=int, default=None, help="最小聚类大小（覆盖 config）")
    p_topics.add_argument("--nr-topics", type=int, default=None, help="目标主题数（覆盖 config，0=auto, -1=不合并）")
    p_topics.add_argument("--viz", action="store_true", help="生成 HTML 可视化图表（6 张）")

    # --- backfill-abstract ---
    p_bf = sub.add_parser("backfill-abstract", help="补全缺失的 abstract（支持 DOI 官方抓取）")
    p_bf.set_defaults(func=cmd_backfill_abstract)
    p_bf.add_argument("--dry-run", action="store_true", help="预览，不写文件")
    p_bf.add_argument("--doi-fetch", action="store_true", help="从出版商网页抓取官方 abstract（覆盖现有）")

    # --- rename ---
    p_rename = sub.add_parser("rename", help="根据 JSON 元数据重命名论文文件")
    p_rename.set_defaults(func=cmd_rename)
    p_rename.add_argument("paper_id", nargs="?", help="论文 ID（省略则需 --all）")
    p_rename.add_argument("--all", action="store_true", help="重命名所有文件名不正确的论文")
    p_rename.add_argument("--dry-run", action="store_true", help="预览，不实际重命名")

    # --- audit ---
    p_audit = sub.add_parser("audit", help="审计已入库论文的数据质量")
    p_audit.set_defaults(func=cmd_audit)
    p_audit.add_argument("--severity", choices=["error", "warning", "info"], help="只显示指定严重级别的问题")

    # --- repair ---
    p_repair = sub.add_parser("repair", help="修复论文元数据（手动指定 title/DOI，跳过 MD 解析）")
    p_repair.set_defaults(func=cmd_repair)
    p_repair.add_argument("paper_id", help="论文 ID（文件名 stem）")
    p_repair.add_argument("--title", required=True, help="正确的论文标题")
    p_repair.add_argument("--doi", default="", help="已知 DOI（加速 API 查询）")
    p_repair.add_argument("--author", default="", help="一作全名")
    p_repair.add_argument("--year", type=int, default=None, help="发表年份")
    p_repair.add_argument("--no-api", action="store_true", help="跳过 API 查询，仅用提供的信息")
    p_repair.add_argument("--dry-run", action="store_true", help="预览，不实际修改")

    # --- explore ---
    p_explore = sub.add_parser("explore", help="期刊全量探索（OpenAlex 拉取 + 嵌入 + 聚类）")
    p_explore.set_defaults(func=cmd_explore)
    p_explore_sub = p_explore.add_subparsers(dest="explore_action", required=True)

    p_ef = p_explore_sub.add_parser("fetch", help="从 OpenAlex 拉取论文（多维度 filter）")
    p_ef.add_argument("--issn", default=None, help="期刊 ISSN（如 0022-1120）")
    p_ef.add_argument("--concept", default=None, help="OpenAlex concept ID（如 C62520636）")
    p_ef.add_argument("--topic-id", default=None, help="OpenAlex topic ID")
    p_ef.add_argument("--author", default=None, help="OpenAlex author ID")
    p_ef.add_argument("--institution", default=None, help="OpenAlex institution ID")
    p_ef.add_argument("--keyword", default=None, help="标题/摘要关键词搜索")
    p_ef.add_argument("--source-type", default=None, help="来源类型（journal/conference/repository）")
    p_ef.add_argument("--oa-type", default=None, help="论文类型（article/review 等）")
    p_ef.add_argument("--min-citations", type=int, default=None, help="最小引用量")
    p_ef.add_argument("--name", help="探索库名称（默认从 filter 推导）")
    p_ef.add_argument("--year-range", help="年份过滤（如 2020-2025）")
    p_ef.add_argument("--incremental", action="store_true", help="增量更新（追加新论文）")

    p_ee = p_explore_sub.add_parser("embed", help="为探索库生成语义向量")
    p_ee.add_argument("--name", required=True, help="探索库名称")
    p_ee.add_argument("--rebuild", action="store_true", help="清空后重建")

    p_et = p_explore_sub.add_parser("topics", help="探索库主题建模")
    p_et.add_argument("--name", required=True, help="探索库名称")
    p_et.add_argument("--build", action="store_true", help="构建主题模型")
    p_et.add_argument("--rebuild", action="store_true", help="重建主题模型")
    p_et.add_argument("--topic", type=int, default=None, help="查看指定主题的论文")
    p_et.add_argument("--top", type=int, default=None, help="返回条数")
    p_et.add_argument("--min-topic-size", type=int, default=None, help="最小聚类大小（默认 30）")
    p_et.add_argument("--nr-topics", type=int, default=None, help="目标主题数（默认自然聚类）")

    p_es = p_explore_sub.add_parser("search", help="探索库搜索（语义/关键词/融合）")
    p_es.add_argument("--name", required=True, help="探索库名称")
    p_es.add_argument("query", nargs="+", help="查询文本")
    p_es.add_argument("--top", type=int, default=None, help="返回条数")
    p_es.add_argument(
        "--mode", choices=["semantic", "keyword", "unified"], default="semantic", help="搜索模式（默认 semantic）"
    )

    p_ev = p_explore_sub.add_parser("viz", help="生成全部可视化（HTML）")
    p_ev.add_argument("--name", required=True, help="探索库名称")

    p_ei = p_explore_sub.add_parser("info", help="查看探索库信息")
    p_ei.add_argument("--name", default=None, help="探索库名称（省略列出全部）")

    # --- export ---
    p_export = sub.add_parser("export", help="导出论文（BibTeX 等格式）")
    p_export.set_defaults(func=cmd_export)
    p_export_sub = p_export.add_subparsers(dest="export_action", required=True)

    p_eb = p_export_sub.add_parser("bibtex", help="导出 BibTeX 格式")
    p_eb.add_argument("paper_ids", nargs="*", help="论文目录名（可多个）")
    p_eb.add_argument("--all", action="store_true", help="导出全部论文")
    p_eb.add_argument("--year", type=str, default=None, help="年份过滤：2023 / 2020-2024")
    p_eb.add_argument("--journal", type=str, default=None, help="期刊名过滤（模糊匹配）")
    p_eb.add_argument("-o", "--output", type=str, default=None, help="输出文件路径（省略则输出到屏幕）")

    # --- ws (workspace) ---
    p_ws = sub.add_parser("ws", help="工作区论文子集管理")
    p_ws.set_defaults(func=cmd_ws)
    p_ws_sub = p_ws.add_subparsers(dest="ws_action", required=True)

    p_ws_init = p_ws_sub.add_parser("init", help="初始化工作区")
    p_ws_init.add_argument("name", help="工作区名称（workspace/ 下的子目录名）")

    p_ws_add = p_ws_sub.add_parser("add", help="添加论文到工作区")
    p_ws_add.add_argument("name", help="工作区名称")
    p_ws_add.add_argument("paper_refs", nargs="*", help="论文引用（UUID / 目录名 / DOI）")
    p_ws_add_batch = p_ws_add.add_mutually_exclusive_group()
    p_ws_add_batch.add_argument("--search", dest="add_search", type=str, default=None, help="按搜索结果批量添加")
    p_ws_add_batch.add_argument("--topic", dest="add_topic", type=int, default=None, help="按主题 ID 批量添加")
    p_ws_add_batch.add_argument("--all", dest="add_all", action="store_true", default=False, help="添加全库论文")
    p_ws_add.add_argument("--top", type=int, default=None, help="限制 --search 返回条数")
    _add_filter_args(p_ws_add)

    p_ws_rm = p_ws_sub.add_parser("remove", help="从工作区移除论文")
    p_ws_rm.add_argument("name", help="工作区名称")
    p_ws_rm.add_argument("paper_refs", nargs="+", help="论文引用（UUID / 目录名 / DOI）")

    p_ws_list = p_ws_sub.add_parser("list", help="列出所有工作区")

    p_ws_show = p_ws_sub.add_parser("show", help="查看工作区中的论文")
    p_ws_show.add_argument("name", help="工作区名称")

    p_ws_search = p_ws_sub.add_parser("search", help="在工作区内搜索")
    p_ws_search.add_argument("name", help="工作区名称")
    p_ws_search.add_argument("query", nargs="+", help="查询文本")
    p_ws_search.add_argument("--top", type=int, default=None, help="返回条数")
    _add_filter_args(p_ws_search)

    p_ws_export = p_ws_sub.add_parser("export", help="导出工作区论文 BibTeX")
    p_ws_export.add_argument("name", help="工作区名称")
    p_ws_export.add_argument("-o", "--output", type=str, default=None, help="输出文件路径")
    _add_filter_args(p_ws_export)

    # --- import-endnote ---
    p_ie = sub.add_parser("import-endnote", help="从 Endnote XML/RIS 导入论文元数据")
    p_ie.set_defaults(func=cmd_import_endnote)
    p_ie.add_argument("files", nargs="+", help="Endnote 导出文件（.xml 或 .ris）")
    p_ie.add_argument("--no-api", action="store_true", help="跳过 API 查询，仅用文件中的元数据")
    p_ie.add_argument("--dry-run", action="store_true", help="预览，不实际导入")
    p_ie.add_argument("--no-convert", action="store_true", help="跳过 PDF → paper.md 转换（默认自动转换）")

    # --- import-zotero ---
    p_iz = sub.add_parser("import-zotero", help="从 Zotero 导入论文元数据和 PDF")
    p_iz.set_defaults(func=cmd_import_zotero)
    p_iz.add_argument("--local", metavar="SQLITE_PATH", help="使用本地 zotero.sqlite")
    p_iz.add_argument("--api-key", help="Zotero API key")
    p_iz.add_argument("--library-id", help="Zotero library ID")
    p_iz.add_argument("--library-type", choices=["user", "group"], help="Library 类型（默认 user）")
    p_iz.add_argument("--collection", metavar="KEY", help="仅导入指定 collection")
    p_iz.add_argument("--item-type", nargs="+", help="限定 item 类型（如 journalArticle conferencePaper）")
    p_iz.add_argument("--list-collections", action="store_true", help="列出所有 collections 后退出")
    p_iz.add_argument("--no-pdf", action="store_true", help="跳过 PDF 下载/复制")
    p_iz.add_argument("--no-api", action="store_true", help="跳过学术 API 查询")
    p_iz.add_argument("--dry-run", action="store_true", help="预览，不实际导入")
    p_iz.add_argument("--no-convert", action="store_true", help="跳过 PDF → paper.md 转换")
    p_iz.add_argument("--import-collections", action="store_true", help="将 Zotero collections 创建为工作区")

    # --- attach-pdf ---
    p_ap = sub.add_parser("attach-pdf", help="为已入库论文补充 PDF 并生成 paper.md")
    p_ap.set_defaults(func=cmd_attach_pdf)
    p_ap.add_argument("paper_id", help="论文 ID（目录名 / UUID / DOI）")
    p_ap.add_argument("pdf_path", help="PDF 文件路径")

    # --- setup ---
    p_setup = sub.add_parser("setup", help="环境检测与安装向导 / Setup wizard")
    p_setup.set_defaults(func=cmd_setup)
    p_setup_sub = p_setup.add_subparsers(dest="setup_action")
    p_setup_check = p_setup_sub.add_parser("check", help="检查环境状态 / Check environment status")
    p_setup_check.add_argument(
        "--lang", choices=["en", "zh"], default="zh", help="输出语言 / Output language (default: zh)"
    )

    # --- notify ---
    p_notify = sub.add_parser("notify", help="论文推送摘要（定期推送新论文到 Telegram/邮件等）")
    p_notify.set_defaults(func=cmd_notify)
    p_notify_sub = p_notify.add_subparsers(dest="notify_action", required=True)

    p_ni = p_notify_sub.add_parser("init", help="创建或更新通知任务配置")
    p_ni.add_argument("name", help="工作区名称（同时作为通知任务名）")
    p_ni.add_argument("--query", required=True, help="感兴趣的研究方向（用于相关性评分）")
    p_ni.add_argument("--schedule", default=None, help="Cron 调度计划（默认: 每周一 08:00）")
    p_ni.add_argument(
        "--channel",
        action="append",
        default=None,
        metavar="URL",
        help="Apprise 推送频道 URL（可多次指定），如 tgram://TOKEN/CHAT_ID",
    )
    p_ni.add_argument(
        "--sources", nargs="+", default=None, choices=["openalex", "library"], help="论文来源（默认: openalex）"
    )
    p_ni.add_argument("--threshold", type=float, default=None, help="相关性阈值 0-1（默认 0.65）")
    p_ni.add_argument("--max-papers", type=int, default=None, help="每期最多收录论文数（默认 10）")

    p_nr = p_notify_sub.add_parser("run", help="立即运行一次推送摘要")
    p_nr.add_argument("name", help="通知任务名称（工作区名）")
    p_nr.add_argument("--dry-run", action="store_true", help="只生成 draft.md，不推送也不更新 last_run")

    p_notify_sub.add_parser("list", help="列出所有通知任务")

    p_ninstall = p_notify_sub.add_parser("install", help="安装 systemd user timer")
    p_ninstall.add_argument("name", help="通知任务名称")

    p_nhist = p_notify_sub.add_parser("history", help="查看推送历史")
    p_nhist.add_argument("name", help="通知任务名称")
    p_nhist.add_argument("--last", type=int, default=10, help="显示最近 N 条（默认 10）")

    # --- migrate-dirs ---
    p_migrate = sub.add_parser("migrate-dirs", help="迁移 data/papers/ 从平铺结构到每篇一目录")
    p_migrate.set_defaults(func=cmd_migrate_dirs)
    p_migrate.add_argument("--execute", action="store_true", help="实际执行迁移（默认 dry-run）")

    # --- metrics ---
    p_metrics = sub.add_parser("metrics", help="查看 LLM token 用量和调用统计")
    p_metrics.set_defaults(func=cmd_metrics)
    p_metrics.add_argument("--last", type=int, default=20, help="最近 N 条记录")
    p_metrics.add_argument("--category", default="llm", help="事件类别（llm/api/step，默认 llm）")
    p_metrics.add_argument("--since", default=None, help="起始时间（ISO 格式，如 2026-03-01）")
    p_metrics.add_argument("--summary", action="store_true", help="仅显示汇总统计")

    # --- enrich-l3 ---
    p_l3 = sub.add_parser("enrich-l3", help="LLM 提取结论段写入 JSON")
    p_l3.set_defaults(func=cmd_enrich_l3)
    p_l3.add_argument("paper_id", nargs="?", help="论文 ID（省略则需 --all）")
    p_l3.add_argument("--all", action="store_true", help="处理 papers_dir 中所有论文")
    p_l3.add_argument("--force", action="store_true", help="强制重新提取（覆盖已有结果）")
    p_l3.add_argument("--inspect", action="store_true", help="展示提取过程详情")
    p_l3.add_argument("--max-retries", type=int, default=2, help="最大重试次数（默认 2）")

    args = parser.parse_args()
    cfg = load_config()
    cfg.ensure_dirs()

    from scholaraio import log as _log
    from scholaraio import metrics as _metrics
    from scholaraio.ingest.metadata._models import configure_session

    session_id = _log.setup(cfg)
    _metrics.init(cfg.metrics_db_path, session_id)
    configure_session(cfg.ingest.contact_email)

    args.func(args, cfg)


if __name__ == "__main__":
    main()
