"""
cli.py — scholaraio 命令行入口
================================

命令：
    scholaraio index [--rebuild]
    scholaraio embed [--rebuild]
    scholaraio search <query> [--limit N] [--year Y] [--journal J] [--type T]
    scholaraio search-author <query> [--limit N] [--year Y] [--journal J] [--type T]
    scholaraio vsearch <query> [--limit N] [--year Y] [--journal J] [--type T]
    scholaraio usearch <query> [--limit N] [--year Y] [--journal J] [--type T]
    scholaraio show <paper-id> [--layer 1|2|3|4]
    scholaraio enrich-toc [<paper-id> | --all] [--force] [--inspect]
    scholaraio enrich-l3 [<paper-id> | --all] [--force] [--inspect] [--max-retries N]
    scholaraio diagram <paper-id> [--type TYPE] [--format FMT] [-o DIR] [--critic] [--critic-rounds N]
    scholaraio diagram --from-text "..." [--type TYPE] [--format FMT] [-o DIR]
    scholaraio diagram --from-ir <path> [--format FMT] [-o DIR]
    scholaraio top-cited [--limit N] [--year Y] [--journal J] [--type T]
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
    scholaraio explore fetch --issn <ISSN> [--name NAME] [--year-range Y]
    scholaraio explore embed --name <NAME> [--rebuild]
    scholaraio explore topics --name <NAME> [--build] [--rebuild] [--topic ID]
    scholaraio explore search --name <NAME> <query> [--limit N]
    scholaraio explore viz --name <NAME>
    scholaraio explore list
    scholaraio explore info [--name NAME]
    scholaraio export bibtex [<paper-id> ...] [--all] [--year Y] [--journal J] [-o FILE]
    scholaraio translate [<paper-id> | --all] [--lang LANG] [--force]
    scholaraio import-endnote <file.xml|file.ris> [--no-api] [--dry-run] [--no-convert]
    scholaraio import-zotero [--api-key KEY] [--library-id ID] [--local PATH] [--list-collections] ...
    scholaraio attach-pdf <paper-id> <path/to/paper.pdf>
    scholaraio websearch <query> [--count N]
    scholaraio webextract <url> [--pdf]
    scholaraio ingest-link <url> [<url> ...] [--dry-run] [--force] [--pdf] [--no-index] [--json]
    scholaraio citation-check [<file>] [--ws <workspace-name>]
    scholaraio proceedings apply-split <proceeding_dir> <split_plan.json>
    scholaraio proceedings build-clean-candidates <proceeding_dir>
    scholaraio proceedings apply-clean <proceeding_dir> <clean_plan.json>
    scholaraio ws init <name>
    scholaraio ws add <name> <paper-refs...> [--search Q] [--topic ID] [--all]
    scholaraio ws remove <name> <paper-refs...>
    scholaraio ws list
    scholaraio ws show <name>
    scholaraio ws search <name> <query> [--limit N] [--mode unified|keyword|semantic]
    scholaraio ws rename <old-name> <new-name>
    scholaraio ws export <name> [-o FILE]
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import logging
import re
import shlex
import shutil
import sys
import tempfile
import time
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from scholaraio.config import load_config
from scholaraio.log import redirect_console_ui, ui

_log = logging.getLogger(__name__)


# ============================================================================
#  Filter args helper
# ============================================================================


class _ResultLimitAction(argparse.Action):
    """Accept --limit as the canonical flag while keeping --top as a safe alias."""

    def __call__(self, parser, namespace, values, option_string=None):
        current = getattr(namespace, self.dest, None)
        if current is not None and current != values:
            parser.error("--limit 和 --top 不能同时指定不同的值")
        setattr(namespace, self.dest, values)


def _add_result_limit_arg(parser: argparse.ArgumentParser, help_text: str) -> None:
    parser.add_argument(
        "--limit",
        "--top",
        dest="result_limit",
        metavar="N",
        type=int,
        default=None,
        action=_ResultLimitAction,
        help=f"{help_text}（兼容旧写法 --top）",
    )


def _resolve_result_limit(args: argparse.Namespace, default: int) -> int:
    result_limit = getattr(args, "result_limit", None)
    if result_limit is not None:
        return result_limit
    legacy_top = getattr(args, "top", None)
    if legacy_top is not None:
        return legacy_top
    return default


def _resolve_top(args: argparse.Namespace, default: int) -> int:
    return _resolve_result_limit(args, default)


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
        _log.debug("metrics record failed: %s", _e)


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

    if not workspace.validate_workspace_name(ws_name):
        raise ValueError(f"非法工作区名称: {ws_name}")

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
    "docx": "pip install scholaraio[office]",
    "pptx": "pip install scholaraio[office]",
    "openpyxl": "pip install scholaraio[office]",
    "markitdown": "pip install scholaraio[office]",
    "fitz": "pip install scholaraio[pdf]",
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
        _log.error("论文目录不存在: %s", papers_dir)
        sys.exit(1)

    action = "重建索引" if args.rebuild else "构建索引"
    ui(f"{action}: {papers_dir} -> {db_path}")
    count = build_index(papers_dir, db_path, rebuild=args.rebuild)
    ui(f"完成：已索引 {count} 篇论文。")
    ui("下一步：运行 `scholaraio search <关键词>` 或 `scholaraio usearch <关键词>` 开始检索。")


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
        ui(f'未找到作者 "{query}" 的相关论文。')
        return

    ui(f'按作者检索到 {len(results)} 篇论文（"{query}"）:\n')
    for i, r in enumerate(results, start=1):
        _print_search_result(i, r)
    _print_search_next_steps()


def cmd_search(args: argparse.Namespace, cfg) -> None:
    import time

    from scholaraio.index import search
    from scholaraio.metrics import get_store

    query = " ".join(args.query)
    t0 = time.monotonic()
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

    elapsed = time.monotonic() - t0
    store = get_store()
    _record_search_metrics(store, "search", query, results, elapsed, args)

    if not results:
        ui(f'未找到与 "{query}" 相关的结果。')
        return

    ui(f'关键词检索到 {len(results)} 篇论文（"{query}"）:\n')
    for i, r in enumerate(results, start=1):
        _print_search_result(i, r)
    _print_search_next_steps()


def cmd_show(args: argparse.Namespace, cfg) -> None:
    from scholaraio.loader import append_notes, load_l1, load_l2, load_l3, load_l4, load_notes
    from scholaraio.metrics import get_store

    paper_d = _resolve_paper(args.paper_id, cfg)
    json_path = paper_d / "meta.json"
    md_path = paper_d / "paper.md"

    # Handle --append-notes (append, then continue to show content)
    if getattr(args, "append_notes", None):
        notes_text = str(args.append_notes).strip()
        if not notes_text:
            ui("警告：--append-notes 内容为空，已忽略。")
        else:
            try:
                append_notes(paper_d, notes_text)
            except (UnicodeDecodeError, OSError) as e:
                _log.error("追加笔记失败：%s", e)
                ui(f"追加笔记到 {paper_d.name}/notes.md 失败：{e}")
            else:
                ui(f"已追加笔记到 {paper_d.name}/notes.md")

    l1 = _enrich_show_header(load_l1(json_path), paper_d=paper_d, requested_id=args.paper_id, cfg=cfg)
    _print_header(l1)

    # Show existing agent notes (T2 layer) if available
    try:
        notes = load_notes(paper_d)
    except (UnicodeDecodeError, OSError) as e:
        _log.warning("读取 notes.md 失败：%s", e)
        notes = None
    if notes:
        ui("\n--- Agent 笔记 (notes.md) ---\n")
        ui(notes)
        ui("\n--- 笔记结束 ---\n")

    store = get_store()

    def _record_read() -> None:
        if store:
            try:
                store.record(
                    category="read",
                    name=paper_d.name,  # use dir_name so insights can find the paper
                    detail={
                        "layer": args.layer,
                        "title": l1.get("title", ""),
                        "doi": l1.get("doi", ""),
                    },
                )
            except Exception as _e:
                _log.debug("metrics record failed: %s", _e)

    if args.layer == 1:
        _record_read()
        return

    if args.layer == 2:
        abstract = load_l2(json_path)
        ui("\n--- 摘要 ---\n")
        ui(abstract)
        _record_read()
        return

    if args.layer == 3:
        conclusion = load_l3(json_path)
        if conclusion is None:
            _log.error("尚未提取结论。请先运行：scholaraio enrich-l3 %s", args.paper_id)
            sys.exit(1)
        ui("\n--- 结论 ---\n")
        ui(conclusion)
        _record_read()
        return

    if args.layer == 4:
        if not md_path.exists():
            _log.error("未找到 paper.md：%s", md_path)
            sys.exit(1)
        lang = getattr(args, "lang", None)
        if lang:
            from scholaraio.translate import validate_lang

            try:
                lang = validate_lang(lang)
            except ValueError:
                ui(f"错误: 无效的语言代码 '{lang}'")
                sys.exit(1)
            translated_path = md_path.parent / f"paper_{lang}.md"
            if translated_path.exists():
                ui(f"\n--- 全文（{lang}） ---\n")
            else:
                ui(f"\n--- 全文（原文，paper_{lang}.md 不存在） ---\n")
        else:
            ui("\n--- 全文 ---\n")
        ui(load_l4(md_path, lang=lang))
        _record_read()
        return


def cmd_embed(args: argparse.Namespace, cfg) -> None:
    try:
        from scholaraio.vectors import build_vectors
    except ImportError as e:
        _check_import_error(e)

    papers_dir = cfg.papers_dir
    if not papers_dir.exists():
        _log.error("论文目录不存在: %s", papers_dir)
        sys.exit(1)

    provider = (getattr(cfg.embed, "provider", "local") or "local").strip().lower()
    action = "重建向量索引" if args.rebuild else "更新向量索引"
    ui(f"{action}: {papers_dir} -> {cfg.index_db}")
    count = build_vectors(papers_dir, cfg.index_db, rebuild=args.rebuild, cfg=cfg)
    if provider == "none":
        ui("当前 embed.provider=none：已禁用向量生成，系统将使用关键词检索。")
        ui("如需语义检索，请将 embed.provider 改为 local 或 openai-compat 后重新运行 `scholaraio embed`。")
        return
    label = "总计" if args.rebuild else "新增"
    ui(f"完成：{label} {count} 条向量。")
    ui("下一步：运行 `scholaraio vsearch <问题>` 或 `scholaraio usearch <问题>` 试试检索效果。")


def cmd_vsearch(args: argparse.Namespace, cfg) -> None:
    import time

    try:
        from scholaraio.vectors import vsearch
    except ImportError as e:
        _check_import_error(e)

    from scholaraio.metrics import get_store

    query = " ".join(args.query)
    t0 = time.monotonic()
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

    elapsed = time.monotonic() - t0
    store = get_store()
    _record_search_metrics(store, "vsearch", query, results, elapsed, args)

    if not results:
        ui(f'未找到与 "{query}" 相关的结果。')
        return

    ui(f'语义检索结果（"{query}"，共 {len(results)} 条）\n')
    for i, r in enumerate(results, start=1):
        score = r.get("score", 0.0)
        _print_search_result(i, r, extra=f"分数: {score:.3f}")
    _print_search_next_steps()


def cmd_usearch(args: argparse.Namespace, cfg) -> None:
    import time

    from scholaraio.index import unified_search
    from scholaraio.metrics import get_store

    query = " ".join(args.query)
    t0 = time.monotonic()
    results, diagnostics = unified_search(
        query,
        cfg.index_db,
        top_k=_resolve_top(args, cfg.search.top_k),
        cfg=cfg,
        year=args.year,
        journal=args.journal,
        paper_type=args.paper_type,
        return_diagnostics=True,
    )
    elapsed = time.monotonic() - t0
    store = get_store()
    _record_search_metrics(store, "usearch", query, results, elapsed, args)

    if not results:
        ui(f'未找到与 "{query}" 相关的结果。')
        return

    if diagnostics.get("vector_degraded"):
        ui("提示：向量检索不可用，已降级为关键词检索。\n")
    ui(f'融合检索结果（"{query}"，共 {len(results)} 条）\n')
    for i, r in enumerate(results, start=1):
        score = r.get("score", 0.0)
        match = r.get("match", "?")
        _print_search_result(i, r, extra=f"{_format_match_tag(match)} {score:.3f}")
    _print_search_next_steps()


def cmd_audit(args: argparse.Namespace, cfg) -> None:
    from scholaraio.audit import audit_papers, format_report

    papers_dir = cfg.papers_dir
    if not papers_dir.exists():
        _log.error("论文目录不存在: %s", papers_dir)
        sys.exit(1)

    ui(f"正在审计论文库: {papers_dir}\n")
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
        metadata_to_dict,
        rename_files,
    )
    from scholaraio.papers import generate_uuid, write_meta

    def _coerce_str(value: object) -> str:
        if isinstance(value, str):
            return value
        if value is None:
            return ""
        return str(value)

    def _coerce_str_list(value: object) -> list[str]:
        if isinstance(value, str):
            return [value] if value.strip() else []
        if isinstance(value, (list, tuple, set)):
            items = [_coerce_str(item).strip() for item in value]
            return [item for item in items if item]
        return []

    def _coerce_citation_count(citation_count: object, *keys: str) -> int | None:
        if not isinstance(citation_count, dict):
            return None
        for key in keys:
            value = citation_count.get(key)
            if isinstance(value, (int, float)):
                return int(value)
            if isinstance(value, str):
                try:
                    return int(value)
                except ValueError:
                    continue
        return None

    def _meta_from_existing(
        existing_data: dict,
        *,
        existing_uuid: str,
        fallback_source_file: str,
    ) -> PaperMetadata:
        ids = existing_data.get("ids") or {}
        citation_count = existing_data.get("citation_count") or {}
        authors = _coerce_str_list(existing_data.get("authors"))
        first_author = _coerce_str(existing_data.get("first_author")) or (authors[0] if authors else "")
        first_author_lastname = _coerce_str(existing_data.get("first_author_lastname"))
        if not first_author_lastname and first_author:
            first_author_lastname = _extract_lastname(first_author)

        return PaperMetadata(
            id=existing_uuid,
            title=_coerce_str(existing_data.get("title")),
            authors=authors,
            first_author=first_author,
            first_author_lastname=first_author_lastname,
            year=existing_data.get("year"),
            doi=_coerce_str(existing_data.get("doi")),
            arxiv_id=_coerce_str(ids.get("arxiv")),
            publication_number=_coerce_str(ids.get("patent_publication_number")),
            journal=_coerce_str(existing_data.get("journal")),
            abstract=_coerce_str(existing_data.get("abstract")),
            paper_type=_coerce_str(existing_data.get("paper_type")),
            citation_count_s2=_coerce_citation_count(citation_count, "semantic_scholar", "s2"),
            citation_count_openalex=_coerce_citation_count(citation_count, "openalex"),
            citation_count_crossref=_coerce_citation_count(citation_count, "crossref"),
            s2_paper_id=_coerce_str(ids.get("semantic_scholar")),
            openalex_id=_coerce_str(ids.get("openalex")),
            crossref_doi=_coerce_str(ids.get("doi")) or _coerce_str(existing_data.get("doi")),
            api_sources=_coerce_str_list(existing_data.get("api_sources")),
            references=_coerce_str_list(existing_data.get("references")),
            volume=_coerce_str(existing_data.get("volume")),
            issue=_coerce_str(existing_data.get("issue")),
            pages=_coerce_str(existing_data.get("pages")),
            publisher=_coerce_str(existing_data.get("publisher")),
            issn=_coerce_str(existing_data.get("issn")),
            source_file=_coerce_str(existing_data.get("source_file")) or fallback_source_file,
            source_url=_coerce_str(existing_data.get("source_url")),
            source_type=_coerce_str(existing_data.get("source_type")),
            extracted_at=_coerce_str(existing_data.get("extracted_at")),
            extraction_method=_coerce_str(existing_data.get("extraction_method")),
        )

    papers_dir = cfg.papers_dir
    direct_dir = papers_dir / args.paper_id
    if direct_dir.is_dir():
        paper_d = direct_dir
    else:
        paper_d = _resolve_paper(args.paper_id, cfg)
    paper_id = paper_d.name
    md_path = paper_d / "paper.md"
    json_path = paper_d / "meta.json"

    if not md_path.exists():
        _log.error("文件不存在: %s", md_path)
        sys.exit(1)

    # Preserve existing UUID
    existing_data: dict = {}
    existing_uuid = ""
    if json_path.exists():
        try:
            existing_data = json.loads(json_path.read_text(encoding="utf-8"))
            existing_uuid = str(existing_data.get("id") or "")
        except (json.JSONDecodeError, OSError) as e:
            _log.debug("failed to read existing meta.json: %s", e)
    ids = existing_data.get("ids") or {}
    strong_registry_match = _lookup_registry_by_candidates(
        cfg,
        args.paper_id if args.paper_id != paper_d.name else "",
        existing_data.get("doi") or "",
        ids.get("doi") or "",
        ids.get("patent_publication_number") or "",
    )
    if strong_registry_match and strong_registry_match.get("id"):
        existing_uuid = str(strong_registry_match.get("id") or "")
    elif not existing_uuid:
        weak_registry_match = _lookup_registry_by_candidates(cfg, paper_d.name)
        if weak_registry_match and weak_registry_match.get("id"):
            existing_uuid = str(weak_registry_match.get("id") or "")
    if not existing_uuid:
        existing_uuid = generate_uuid()

    # Start from existing metadata and only override fields explicitly provided by the user.
    meta = _meta_from_existing(
        existing_data,
        existing_uuid=existing_uuid,
        fallback_source_file=md_path.name,
    )
    meta.id = existing_uuid
    meta.title = args.title
    if args.doi:
        meta.doi = args.doi
        meta.crossref_doi = args.doi
    if args.year is not None:
        meta.year = args.year
    meta.source_file = meta.source_file or md_path.name
    if args.author:
        meta.authors = [args.author]
        meta.first_author = args.author
        meta.first_author_lastname = _extract_lastname(args.author)

    ui(f"修复论文: {paper_id}")
    ui(f"  标题: {meta.title}")
    ui(f"  作者: {meta.first_author or '?'} | 年份: {meta.year or '?'} | DOI: {meta.doi or '无'}")

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

    ui(f"  结果: {meta.first_author_lastname} ({meta.year}) {meta.title[:60]}")
    if meta.doi:
        ui(f"  DOI: {meta.doi}")
    ui(f"  方法: {meta.extraction_method}")

    if args.dry_run:
        ui("  [dry-run] 未写入任何文件")
        return

    # Preserve existing enriched or custom top-level fields while updating metadata.
    new_data = dict(existing_data)
    new_data.update(metadata_to_dict(meta))
    write_meta(json_path.parent, new_data)
    ui(f"  已写入: {json_path.name}")

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
        _log.error("请指定 <paper-id> 或 --all")
        sys.exit(1)

    if args.all:
        ok, fail, skip = _run_batch_enrich(
            targets,
            cfg,
            worker_fn=lambda json_path, md_path: enrich_toc(
                json_path,
                md_path,
                cfg,
                force=args.force,
                inspect=args.inspect,
            ),
            success_message=_toc_success_message,
            failure_message="  TOC 提取失败",
            max_retries=2,
        )
    else:
        ok = fail = skip = 0
        for json_path in targets:
            md_path = json_path.parent / "paper.md"
            if not md_path.exists():
                _log.error("已跳过（缺少 paper.md）: %s", json_path.parent.name)
                skip += 1
                continue

            ui(f"\n{json_path.parent.name}")
            ui("  开始提取 TOC...")
            success = enrich_toc(
                json_path,
                md_path,
                cfg,
                force=args.force,
                inspect=args.inspect,
            )
            if success:
                ok += 1
                ui(_toc_success_message(json_path))
            else:
                fail += 1
                ui("  TOC 提取失败")

    if args.all or len(targets) > 1:
        ui(f"\n完成: {ok} 成功 | {fail} 失败 | {skip} 跳过")


def cmd_pipeline(args: argparse.Namespace, cfg) -> None:
    from scholaraio.ingest.pipeline import PRESETS, STEPS, run_pipeline

    if args.list_steps:
        ui("可用步骤：")
        for name, sdef in STEPS.items():
            ui(f"  {name:<10} [{sdef.scope:<7}]  {sdef.desc}")
        ui("\n可用预设：")
        for name, steps in PRESETS.items():
            ui(f"  {name:<10} = {', '.join(steps)}")
        return

    # Resolve step list
    if args.preset:
        if args.preset not in PRESETS:
            _log.error("未知预设 '%s'。可用预设: %s", args.preset, ", ".join(PRESETS))
            sys.exit(1)
        step_names = PRESETS[args.preset]
    elif args.steps:
        step_names = [s.strip() for s in args.steps.split(",") if s.strip()]
    else:
        _log.error("请指定一个预设名称或使用 --steps")
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
        _log.error("请指定 <paper-id> 或 --all")
        sys.exit(1)

    if args.all:
        ok, fail, skip = _run_batch_enrich(
            targets,
            cfg,
            worker_fn=lambda json_path, md_path: enrich_l3(
                json_path,
                md_path,
                cfg,
                force=args.force,
                max_retries=args.max_retries,
                inspect=args.inspect,
            ),
            success_message="  结论提取完成",
            failure_message="  结论提取失败",
            max_retries=args.max_retries,
        )
    else:
        ok = fail = skip = 0
        for json_path in targets:
            md_path = json_path.parent / "paper.md"
            if not md_path.exists():
                _log.error("已跳过（缺少 paper.md）: %s", json_path.parent.name)
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
                ui("  结论提取完成")
            else:
                fail += 1
                ui("  结论提取失败")

    if args.all or len(targets) > 1:
        ui(f"\n完成: {ok} 成功 | {fail} 失败 | {skip} 跳过")


def _toc_success_message(json_path: Path) -> str:
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        return f"  TOC 提取完成: {len(data.get('toc', []))} 节"
    except (OSError, json.JSONDecodeError):
        return "  TOC 提取完成"


def _run_batch_enrich(
    targets: list[Path],
    cfg,
    *,
    worker_fn,
    success_message: str | callable,
    failure_message: str,
    max_retries: int,
) -> tuple[int, int, int]:
    def _batch_message(json_path: Path, message: str) -> str:
        return f"{json_path.parent.name} | {message.strip()}"

    queued: list[tuple[Path, Path]] = []
    skip = 0
    for json_path in targets:
        md_path = json_path.parent / "paper.md"
        if not md_path.exists():
            _log.error("已跳过（缺少 paper.md）: %s", json_path.parent.name)
            skip += 1
            continue
        queued.append((json_path, md_path))

    if not queued:
        return 0, 0, skip

    workers = min(max(1, int(getattr(cfg.llm, "concurrency", 1))), len(queued))
    ui(f"并发处理（{workers} workers，共 {len(queued)} 篇）...")

    def _retry_one(json_path: Path, md_path: Path) -> tuple[Path, bool, int]:
        for attempt in range(1, max_retries + 2):
            try:
                success = worker_fn(json_path, md_path)
                if success:
                    return json_path, True, attempt
            except Exception as e:
                _log.warning("批量富化失败（%s，第 %d 次）: %s", json_path.parent.name, attempt, e)
            if attempt <= max_retries:
                time.sleep(float(2 ** (attempt - 1)))
        return json_path, False, max_retries + 1

    ok = fail = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = []
        for json_path, md_path in queued:
            ui(f"\n{_batch_message(json_path, '开始处理...')}")
            futures.append(pool.submit(_retry_one, json_path, md_path))
        for future in concurrent.futures.as_completed(futures):
            json_path, success, attempts = future.result()
            if success:
                ok += 1
                if attempts > 1:
                    ui(_batch_message(json_path, f"重试后成功（共 {attempts} 次）"))
                ui(
                    _batch_message(
                        json_path,
                        success_message(json_path) if callable(success_message) else success_message,
                    )
                )
            else:
                fail += 1
                if attempts > 1:
                    ui(_batch_message(json_path, f"已重试 {attempts - 1}/{max_retries} 次"))
                ui(_batch_message(json_path, failure_message))

    return ok, fail, skip


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
        ui("索引中没有引用数据。请先运行 scholaraio refetch --all。")
        return

    ui(f"按引用量排序的前 {len(results)} 篇论文：\n")
    for i, r in enumerate(results, start=1):
        _print_search_result(i, r)
    _print_search_next_steps()


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


def cmd_toolref(args: argparse.Namespace, cfg) -> None:
    from scholaraio.toolref import (
        TOOL_REGISTRY,
        toolref_fetch,
        toolref_list,
        toolref_search,
        toolref_show,
        toolref_use,
    )

    try:
        action = args.toolref_action

        if action == "fetch":
            count = toolref_fetch(args.tool, version=args.version, force=args.force, cfg=cfg)
            if count == 0:
                ui("未索引任何页面。请检查版本号或文档源。")

        elif action == "show":
            results = toolref_show(args.tool, *args.path, cfg=cfg)
            if not results:
                ui(f"未找到匹配：{args.tool} {' '.join(args.path)}")
                ui(f"尝试搜索：scholaraio toolref search {args.tool} {' '.join(args.path)}")
                return
            for r in results:
                ui(f"\n{'=' * 60}")
                ui(r["page_name"])
                if r.get("section"):
                    ui(f"   段落：{r['section']}  |  程序：{r.get('program', '')}")
                if r.get("synopsis"):
                    ui(f"   {r['synopsis']}")
                ui(f"{'─' * 60}")
                ui(r.get("content", "(无内容)"))

        elif action == "search":
            query = " ".join(args.query)
            results = toolref_search(
                args.tool,
                query,
                top_k=_resolve_result_limit(args, 20),
                program=args.program,
                section=args.section,
                cfg=cfg,
            )
            if not results:
                ui(f"无结果：{query}")
                return
            ui(f"找到 {len(results)} 条结果：\n")
            for i, r in enumerate(results, 1):
                synopsis = r.get("synopsis", "")[:80]
                ui(f"  {i:2d}. [{r['page_name']}] {synopsis}")

        elif action == "list":
            entries = toolref_list(args.tool, cfg=cfg)
            if not entries:
                tools = ", ".join(TOOL_REGISTRY.keys())
                ui(f"无已拉取文档。支持的工具：{tools}")
                ui("使用 `scholaraio toolref fetch <tool> --version <ver>` 拉取")
                return
            current_tool = ""
            for e in entries:
                if e["tool"] != current_tool:
                    current_tool = e["tool"]
                    ui(f"\n{e['display_name']}:")
                marker = " (current)" if e["is_current"] else ""
                completeness = ""
                unit = "页" if e.get("source_type") == "manifest" else "条"
                if e.get("source_type") == "manifest" and e.get("expected_pages"):
                    completeness = f" [{e['page_count']}/{e['expected_pages']} 已索引"
                    failed_pages = e.get("failed_pages")
                    if failed_pages:
                        completeness += f", {failed_pages} 失败"
                    completeness += "]"
                ui(f"  {e['version']}{marker} — {e['page_count']} {unit}{completeness}")

        elif action == "use":
            toolref_use(args.tool, args.version, cfg=cfg)
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        _log.error("%s", e)
        sys.exit(1)


def cmd_translate(args: argparse.Namespace, cfg) -> None:
    from scholaraio.translate import batch_translate, translate_paper

    papers_dir = cfg.papers_dir

    # Determine target language: CLI flag > config default; normalize input
    target_lang = (args.lang or cfg.translate.target_lang).lower().strip()

    try:
        from scholaraio.translate import validate_lang

        validate_lang(target_lang)
    except ValueError:
        ui(f"错误: 无效的语言代码 '{target_lang}'（应为 2-5 个小写字母，如 zh、en、ja）")
        sys.exit(1)

    if args.paper_id:
        paper_d = _resolve_paper(args.paper_id, cfg)
        tr = translate_paper(
            paper_d,
            cfg,
            target_lang=target_lang,
            force=args.force,
            portable=args.portable,
            progress_callback=ui,
        )
        if tr.ok:
            ui(f"翻译完成: {tr.path}")
            if tr.portable_path:
                ui(f"可移植导出: {tr.portable_path}")
        else:
            from scholaraio.translate import (
                SKIP_ALL_CHUNKS_FAILED,
                SKIP_ALREADY_EXISTS,
                SKIP_EMPTY,
                SKIP_NO_MD,
                SKIP_SAME_LANG,
            )

            _skip_messages = {
                SKIP_NO_MD: "跳过: 该论文目录下无 paper.md 文件",
                SKIP_EMPTY: "跳过: paper.md 内容为空",
                SKIP_SAME_LANG: f"跳过: 论文已是目标语言 ({target_lang})",
                SKIP_ALREADY_EXISTS: "跳过: 翻译已存在（使用 --force 强制重新翻译）",
            }
            if tr.partial and tr.path:
                ui(
                    f"翻译中断：已完成 {tr.completed_chunks}/{tr.total_chunks} 块，"
                    f"当前结果已写入 {tr.path}，可稍后继续续翻"
                )
                sys.exit(1)
            if tr.skip_reason == SKIP_ALL_CHUNKS_FAILED:
                ui("翻译失败: 所有分块都翻译失败，未写出目标文件")
                sys.exit(1)
            ui(_skip_messages.get(tr.skip_reason, "跳过"))
    elif args.all:
        ui(f"批量翻译 → {target_lang}")
        stats = batch_translate(papers_dir, cfg, target_lang=target_lang, force=args.force, portable=args.portable)
        ui(f"完成: {stats['translated']} 已翻译 | {stats['skipped']} 跳过 | {stats['failed']} 失败")
    else:
        ui("请指定 <paper-id> 或 --all")
        sys.exit(1)


def cmd_refetch(args: argparse.Namespace, cfg) -> None:
    import json
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from scholaraio.ingest.metadata import refetch_metadata
    from scholaraio.papers import iter_paper_dirs

    papers_dir = cfg.papers_dir

    if args.all:
        targets = sorted(d / "meta.json" for d in iter_paper_dirs(papers_dir))
    elif args.paper_id:
        targets = [_resolve_paper(args.paper_id, cfg) / "meta.json"]
    else:
        _log.error("请指定 <paper-id> 或 --all")
        sys.exit(1)

    references_only = bool(getattr(args, "references_only", False))

    # Filter: only papers missing citations or bibliographic details (unless --force)
    if args.all and references_only:
        filtered = []
        for jp in targets:
            data = json.loads(jp.read_text(encoding="utf-8"))
            if data.get("doi") and not (data.get("references") or []):
                filtered.append(jp)
        ui(f"共 {len(targets)} 篇，{len(filtered)} 篇需要补全 references")
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
    if not targets:
        if args.all:
            ui("无需更新")
            return
        sys.exit(1)

    ok = skip = 0
    total = len(targets)
    workers = min(getattr(args, "jobs", 5) or 5, total)
    ui(f"并发 refetch（{workers} workers，共 {total} 篇）...")

    def _do_refetch(jp: Path) -> tuple[Path, bool | None]:
        try:
            if references_only:
                return jp, refetch_metadata(jp, references_only=True)
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
        if args.rebuild and model_dir.exists():
            shutil.rmtree(model_dir, ignore_errors=True)
        ui(f"{'重建' if args.rebuild else '构建'}主题模型...")
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
            _log.error("%s", e)
            sys.exit(1)
    else:
        try:
            model = load_model(model_dir)
        except FileNotFoundError as e:
            _log.error("%s", e)
            sys.exit(1)

    # Quick reduce (no rebuild)
    if args.reduce is not None:
        ui(f"正在压缩到 {args.reduce} 个主题...")
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
            ui(f"正在合并 {len(groups)} 组主题: {groups}")
            model = merge_topics_by_ids(model, groups, save_path=model_dir, cfg=cfg)
        else:
            _log.error("--merge 格式错误，示例: --merge 1,6,14+3,5")

    # Show specific topic
    if args.topic is not None:
        tid = args.topic
        top_n = _resolve_result_limit(args, 0) or 0  # 0 = show all
        if tid == -1:
            papers = get_outliers(model)
            ui(f"离群论文: {len(papers)}\n")
        else:
            topic_words = model.get_topic(tid)
            if topic_words is False or topic_words is None:
                _log.error("主题 %d 不存在", tid)
                sys.exit(1)
            keywords = [w for w, _ in topic_words[:10]]
            papers = get_topic_papers(model, tid)
            ui(f"主题 {tid}: {', '.join(keywords)}")
            ui(f"{len(papers)} 篇论文\n")

        if top_n:
            papers = papers[:top_n]
        for i, p in enumerate(papers, 1):
            cc = p.get("citation_count", {})
            best = max((v for v in (cc or {}).values() if isinstance(v, (int, float))), default=0)
            cite_str = f"  [被引: {best}]" if best else ""
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
        ui("没有可用主题。可尝试减小 topics.min_topic_size 或增加论文数量。")
        return

    outliers = get_outliers(model)
    total = sum(t["count"] for t in overview) + len(outliers)
    ui(f"论文库概览：{total} 篇论文，{len(overview)} 个主题，{len(outliers)} 篇离群论文\n")

    for t in overview:
        kw = ", ".join(t["keywords"][:6])
        ui(f"主题 {t['topic_id']:2d}（{t['count']:3d} 篇）: {kw}")
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
        _log.error("论文目录不存在: %s", papers_dir)
        sys.exit(1)

    action = "预览补全" if args.dry_run else "补全摘要"
    doi_fetch = getattr(args, "doi_fetch", False)
    source = "DOI 官方来源" if doi_fetch else "本地 .md + LLM 回退"
    ui(f"{action}摘要（{source}）...\n")
    stats = backfill_abstracts(papers_dir, dry_run=args.dry_run, doi_fetch=doi_fetch, cfg=cfg)
    parts = [f"{stats['filled']} 已补全", f"{stats['skipped']} 跳过", f"{stats['failed']} 失败"]
    if stats.get("updated"):
        parts.insert(1, f"{stats['updated']} 已更新为官方摘要")
    ui(f"\n完成: {' | '.join(parts)}")
    if stats["filled"] and not args.dry_run:
        _log.debug("consider rebuilding vector index: scholaraio embed --rebuild")


def cmd_explore(args: argparse.Namespace, cfg) -> None:
    action = args.explore_action

    if action == "fetch":
        if args.limit is not None and args.limit <= 0:
            ui(f"--limit 必须为正整数，当前为: {args.limit}")
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
            limit=getattr(args, "limit", None),
            cfg=cfg,
        )
        ui(f"\n已抓取 {total} 篇论文")

    elif action == "embed":
        try:
            from scholaraio.explore import build_explore_vectors
        except ImportError as e:
            _check_import_error(e)
        n = build_explore_vectors(args.name, rebuild=args.rebuild, cfg=cfg)
        provider = (getattr(cfg.embed, "provider", "local") or "local").strip().lower()
        if provider == "none":
            ui("当前 embed.provider=none：探索库跳过向量生成，仅保留关键词检索。")
            return
        ui(f"完成: 新增 {n} 条向量嵌入")

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
            try:
                info = build_explore_topics(
                    args.name,
                    rebuild=args.rebuild,
                    min_topic_size=args.min_topic_size or 30,
                    nr_topics=nr_topics,
                    cfg=cfg,
                )
            except FileNotFoundError as e:
                _log.error("%s", e)
                sys.exit(1)
            ui(f"\n聚类完成: {info['n_topics']} 个主题，{info['n_outliers']} 篇离群论文，{info['n_papers']} 篇论文")

        try:
            model = load_model(model_dir)
        except FileNotFoundError:
            ui("尚未构建主题模型。请先运行 scholaraio explore topics --name <name> --build。")
            return

        if args.topic is not None:
            papers = get_topic_papers(model, args.topic)
            top_n = _resolve_top(args, 20)
            papers = papers[:top_n]
            ui(f"主题 {args.topic}: {len(papers)} 篇论文\n")
            for i, p in enumerate(papers, 1):
                cc = p.get("citation_count", {})
                best = max((v for v in (cc or {}).values() if isinstance(v, (int, float))), default=0)
                cite_str = f"  [被引: {best}]" if best else ""
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
            ui("没有可用主题。请先运行 scholaraio explore topics --name <name> --build。")
            return
        from scholaraio.topics import get_outliers

        outliers = get_outliers(model)
        total = sum(t["count"] for t in overview) + len(outliers)
        ui(f"\n{len(overview)} 个主题，{total} 篇论文，{len(outliers)} 篇离群论文\n")
        for t in overview:
            kw = ", ".join(t["keywords"][:6])
            ui(f"主题 {t['topic_id']:2d}（{t['count']:3d} 篇）: {kw}")
            for p in t["representative_papers"][:3]:
                title = p.get("title", "")
                if len(title) > 65:
                    title = title[:62] + "..."
                cc = p.get("citation_count", {})
                best = max((v for v in (cc or {}).values() if isinstance(v, (int, float))), default=0)
                cite_str = f"  [被引: {best}]" if best else ""
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
            try:
                results = explore_vsearch(args.name, query, top_k=top_k, cfg=cfg)
            except FileNotFoundError as e:
                _log.error("%s", e)
                sys.exit(1)
        if not results:
            ui("未找到结果。")
            return
        for i, r in enumerate(results, 1):
            authors = r.get("authors", [])
            first = authors[0] if authors else ""
            cited = r.get("cited_by_count", 0)
            cite_str = f"  [被引: {cited}]" if cited else ""
            ui(f"[{i}] [{r.get('year', '?')}] {r.get('title', '')}")
            ui(f"     {first} | {r.get('doi', '')}  (分数: {r['score']:.3f}){cite_str}")
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
            ui("尚未构建主题模型。请先运行 scholaraio explore topics --name <name> --build。")
            return
        _write_all_viz(model, model_dir / "viz")

    elif action == "list":
        import json as _json

        explore_root = cfg._root / "data" / "explore"
        if not explore_root.exists():
            ui("暂无 explore 库，请先运行 scholaraio explore fetch --issn <ISSN> 创建。")
            return
        for d in sorted(explore_root.iterdir()):
            if not d.is_dir():
                continue
            meta_file = d / "meta.json"
            if meta_file.exists():
                try:
                    meta = _json.loads(meta_file.read_text("utf-8"))
                except (OSError, _json.JSONDecodeError) as e:
                    ui(f"  {d.name}: meta.json 读取失败，已跳过（{e}）")
                    continue
                query = meta.get("query", {})
                if query:
                    qinfo = ", ".join(f"{k}={v}" for k, v in query.items())
                elif meta.get("issn"):
                    qinfo = f"ISSN {meta['issn']}"
                else:
                    qinfo = "?"
                ui(f"  {d.name}: {meta.get('count', '?')} 篇 ({qinfo}，抓取时间 {meta.get('fetched_at', '?')})")
        return

    elif action == "info":
        import json as _json

        if not args.name:
            # List all explore libraries
            explore_root = cfg._root / "data" / "explore"
            if not explore_root.exists():
                ui("暂无 explore 库，请先运行 scholaraio explore fetch --issn <ISSN> 创建。")
                return
            for d in sorted(explore_root.iterdir()):
                if not d.is_dir():
                    continue
                meta_file = d / "meta.json"
                if meta_file.exists():
                    try:
                        meta = _json.loads(meta_file.read_text("utf-8"))
                    except (OSError, _json.JSONDecodeError) as e:
                        ui(f"  {d.name}: meta.json 读取失败，已跳过（{e}）")
                        continue
                    # Show query info (backward compatible with old ISSN-only format)
                    query = meta.get("query", {})
                    if query:
                        qinfo = ", ".join(f"{k}={v}" for k, v in query.items())
                    elif meta.get("issn"):
                        qinfo = f"ISSN {meta['issn']}"
                    else:
                        qinfo = "?"
                    ui(f"  {d.name}: {meta.get('count', '?')} 篇 ({qinfo}，抓取时间 {meta.get('fetched_at', '?')})")
            return
        from scholaraio.explore import count_papers

        meta_file = cfg._root / "data" / "explore" / args.name / "meta.json"
        if meta_file.exists():
            try:
                meta = _json.loads(meta_file.read_text("utf-8"))
            except (OSError, _json.JSONDecodeError) as e:
                ui(f"读取 {meta_file} 失败：{e}")
                return
            ui(f"Explore 库: {args.name}")
            for k, v in meta.items():
                ui(f"  {k}: {v}")
        else:
            n = count_papers(args.name, cfg=cfg)
            ui(f"Explore 库 {args.name}: {n} 篇论文")

    else:
        _log.error("未知操作: %s", action)
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
        _log.error("请指定 <paper-id> 或 --all")
        sys.exit(1)

    renamed = skip = fail = 0
    for json_path in targets:
        if not json_path.exists():
            _log.error("未找到论文: %s", json_path.parent.name)
            fail += 1
            continue

        new_path = rename_paper(json_path, dry_run=args.dry_run)
        if new_path:
            action = "预览" if args.dry_run else "重命名"
            ui(f"{action}: {json_path.parent.name} -> {new_path.parent.name}")
            renamed += 1
        else:
            skip += 1

    ui(f"\n完成: {renamed} 已重命名 | {skip} 未变化 | {fail} 失败")
    if renamed and not args.dry_run:
        _log.debug("consider rebuilding index: scholaraio index --rebuild")


# ============================================================================
#  export
# ============================================================================


def cmd_export(args: argparse.Namespace, cfg) -> None:
    action = args.export_action
    if action == "bibtex":
        _cmd_export_bibtex(args, cfg)
    elif action == "ris":
        _cmd_export_ris(args, cfg)
    elif action == "markdown":
        _cmd_export_markdown(args, cfg)
    elif action == "docx":
        _cmd_export_docx(args, cfg)
    else:
        _log.error("未知导出操作: %s", action)
        sys.exit(1)


def _cmd_export_ris(args: argparse.Namespace, cfg) -> None:
    from scholaraio.export import export_ris

    paper_ids = args.paper_ids if args.paper_ids else None
    if not paper_ids and not args.all:
        _log.error("请指定论文 ID 或 --all")
        sys.exit(1)

    ris = export_ris(
        cfg.papers_dir,
        paper_ids=paper_ids,
        year=args.year,
        journal=args.journal,
    )

    if not ris:
        ui("未找到匹配的论文")
        return

    if args.output:
        out = Path(args.output)
        out.write_text(ris, encoding="utf-8")
        count = ris.count("TY  -")
        ui(f"已导出到 {out}（{count} 篇）")
    else:
        print(ris)


def _cmd_export_markdown(args: argparse.Namespace, cfg) -> None:
    from scholaraio.export import export_markdown_refs

    paper_ids = args.paper_ids if args.paper_ids else None
    if not paper_ids and not args.all:
        _log.error("请指定论文 ID 或 --all")
        sys.exit(1)

    style = getattr(args, "style", "apa") or "apa"

    try:
        md = export_markdown_refs(
            cfg.papers_dir,
            cfg=cfg,
            paper_ids=paper_ids,
            year=args.year,
            journal=args.journal,
            numbered=not args.bullet,
            style=style,
        )
    except (FileNotFoundError, ValueError, AttributeError, ImportError) as e:
        _log.error("%s", e)
        sys.exit(1)

    if not md:
        ui("未找到匹配的论文")
        return

    if args.output:
        out = Path(args.output)
        out.write_text(md, encoding="utf-8")
        count = md.count("\n")
        ui(f"已导出到 {out}（{count} 条引用，{style} 格式）")
    else:
        print(md)


def cmd_document(args: argparse.Namespace, cfg) -> None:
    action = getattr(args, "doc_action", None)
    if action == "inspect":
        _cmd_document_inspect(args, cfg)
    else:
        _log.error("请指定 document 子命令: inspect")
        sys.exit(1)


def _cmd_document_inspect(args: argparse.Namespace, cfg) -> None:
    from scholaraio.document import inspect

    file_path = Path(args.file)
    if not file_path.exists():
        _log.error("文件不存在: %s", file_path)
        sys.exit(1)
    fmt = getattr(args, "format", None)
    try:
        result = inspect(file_path, fmt=fmt)
    except (ValueError, ImportError) as e:
        _log.error("%s", e)
        sys.exit(1)
    print(result)


def cmd_diagram(args: argparse.Namespace, cfg) -> None:
    """论文/文字 → 可编辑科研图表（多后端渲染）。"""
    from scholaraio.diagram import (
        generate_diagram,
        generate_diagram_from_text,
        generate_diagram_with_critic,
        render_ir,
    )

    out_dir = Path(args.output) if args.output else None
    from_text = getattr(args, "from_text", None)
    from_ir = getattr(args, "from_ir", None)

    # Validate: need exactly one input source among paper_id / --from-text / --from-ir
    sources = [bool(args.paper_id), bool(from_text), bool(from_ir)]
    if sum(sources) != 1:
        _log.error("请提供且仅提供一个输入来源：paper_id、--from-text 或 --from-ir")
        sys.exit(1)

    # Mode 1: 从已有 IR 文件直接渲染（Critic 不参与，因为无原文对照）
    if from_ir:
        ir_path = Path(from_ir)
        if not ir_path.exists():
            _log.error("IR 文件不存在: %s", ir_path)
            sys.exit(1)
        try:
            ir = json.loads(ir_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            _log.error("IR 文件解析失败: %s", e)
            sys.exit(1)
        try:
            out_path = render_ir(ir, args.format, out_path=_build_diagram_out_path(ir, args.format, out_dir))
        except (ValueError, RuntimeError) as e:
            _log.error("%s", e)
            sys.exit(1)
        ui(f"已生成: {out_path}")
        _print_diagram_hint(args.format, out_path)
        return

    # Mode 2: 从文字描述生成（用于写作流程中的插图辅助）
    if from_text:
        try:
            out_path = generate_diagram_from_text(
                description=from_text,
                diagram_type=args.type,
                fmt=args.format,
                cfg=cfg,
                out_dir=out_dir,
                dump_ir=args.dump_ir,
            )
            ui(f"已生成: {out_path}")
            if not args.dump_ir:
                _print_diagram_hint(args.format, out_path)
        except (ValueError, RuntimeError) as e:
            _log.error("%s", e)
            sys.exit(1)
        return

    # Mode 3: 从论文提取（可选 Critic 闭环迭代）
    paper_d = _resolve_paper(args.paper_id, cfg)
    try:
        if args.critic:
            result = generate_diagram_with_critic(
                paper_d=paper_d,
                diagram_type=args.type,
                fmt=args.format,
                cfg=cfg,
                out_dir=out_dir,
                dump_ir=args.dump_ir,
                max_rounds=args.critic_rounds,
            )
            out_path = result["out_path"]
            critique_log = result["critique_log"]
            ui(f"已生成: {out_path}")
            if not args.dump_ir:
                _print_diagram_hint(args.format, out_path)
            if args.critic_rounds > 0:
                ui(f"Critic 闭环完成，共 {len(critique_log)} 轮")
                for c in critique_log:
                    verdict = c.get("verdict", "unknown")
                    issue_count = len(c.get("issues", []))
                    ui(f"  轮次 {c.get('round', '?')}: verdict={verdict}, issues={issue_count}")
        else:
            out_path = generate_diagram(
                paper_d=paper_d,
                diagram_type=args.type,
                fmt=args.format,
                cfg=cfg,
                out_dir=out_dir,
                dump_ir=args.dump_ir,
            )
            ui(f"已生成: {out_path}")
            if not args.dump_ir:
                _print_diagram_hint(args.format, out_path)
    except (ValueError, RuntimeError) as e:
        _log.error("%s", e)
        sys.exit(1)


def _build_diagram_out_path(ir: dict, fmt: str, out_dir: Path | None) -> Path:
    if out_dir is None:
        out_dir = Path("workspace/figures")
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_title = re.sub(r"[^\w\-]", "_", ir.get("title", "diagram"))[:40]
    return out_dir / f"diagram_{safe_title}.{fmt}"


def _print_diagram_hint(fmt: str, out_path: Path) -> None:
    if fmt == "svg":
        dot_path = out_path.with_suffix(".dot")
        ui(f"DOT 源码: {dot_path}")
        ui("Beamer 插入代码:")
        ui(r"  \begin{frame}")
        ui(r"  \centering")
        try:
            display_path = out_path.resolve().relative_to(Path.cwd().resolve())
        except ValueError:
            display_path = out_path
        ui(f"  \\includesvg[width=0.8\\columnwidth]{{{display_path}}}")
        ui(r"  \end{frame}")
        ui("注意: 编译时需带 -shell-escape 参数，且已安装 Inkscape")
    elif fmt == "drawio":
        ui("可用浏览器打开 https://app.diagrams.net 后导入编辑")


def cmd_style(args: argparse.Namespace, cfg) -> None:
    """Dispatcher for `scholaraio style` subcommands."""
    sub = getattr(args, "style_sub", None)
    if sub == "list":
        _cmd_style_list(args, cfg)
    elif sub == "show":
        _cmd_style_show(args, cfg)
    else:
        _log.error("请指定 style 子命令: list / show")
        sys.exit(1)


def _cmd_style_list(args: argparse.Namespace, cfg) -> None:
    from scholaraio.citation_styles import list_styles

    styles = list_styles(cfg)
    ui(f"可用引用格式（共 {len(styles)} 种）：")
    for s in styles:
        tag = f"[{s['source']}]"
        desc = f" — {s['description']}" if s.get("description") else ""
        print(f"  {s['name']:<28} {tag:<10}{desc}")
    print()
    ui("用法：scholaraio export markdown --all --style <name>")


def _cmd_style_show(args: argparse.Namespace, cfg) -> None:
    from scholaraio.citation_styles import show_style

    try:
        code = show_style(args.name, cfg)
        print(code)
    except (FileNotFoundError, ValueError) as e:
        _log.error("%s", e)
        sys.exit(1)


def _cmd_export_docx(args: argparse.Namespace, cfg) -> None:
    from scholaraio.export import export_docx

    # Determine input content
    if args.input:
        input_path = Path(args.input)
        if not input_path.exists():
            _log.error("输入文件不存在: %s", args.input)
            sys.exit(1)
        content = input_path.read_text(encoding="utf-8")
    elif not sys.stdin.isatty():
        content = sys.stdin.read()
    else:
        _log.error("请通过 --input 指定 Markdown 文件，或通过 stdin 传入内容")
        sys.exit(1)

    output = Path(args.output) if args.output else cfg._root / "workspace" / "output.docx"

    try:
        export_docx(content, output, title=args.title or None)
        ui(f"已导出到 {output}")
    except ImportError as e:
        _log.error("%s", e)
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

    # Validate workspace-name style arguments in CLI layer to prevent path traversal.
    names_to_check: list[str] = []
    if action in {"init", "add", "remove", "show", "search", "export"}:
        names_to_check.append(args.name)
    elif action == "rename":
        names_to_check.extend([args.old_name, args.new_name])

    for name in names_to_check:
        if not workspace.validate_workspace_name(name):
            ui(f"非法工作区名称: {name}")
            return

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
            ui(f"  {name}（{len(ids)} 篇论文）")

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
        mode = getattr(args, "mode", "unified")
        top_k = _resolve_top(args, cfg.search.top_k)

        if mode == "keyword":
            from scholaraio.index import search as kw_search

            results = kw_search(
                query,
                cfg.index_db,
                top_k=top_k,
                cfg=cfg,
                year=args.year,
                journal=args.journal,
                paper_type=args.paper_type,
                paper_ids=pids,
            )
        elif mode == "semantic":
            from scholaraio.vectors import vsearch

            results = vsearch(
                query,
                cfg.index_db,
                top_k=top_k,
                cfg=cfg,
                year=args.year,
                journal=args.journal,
                paper_type=args.paper_type,
                paper_ids=pids,
            )
        else:
            from scholaraio.index import unified_search

            results = unified_search(
                query,
                cfg.index_db,
                top_k=top_k,
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
            match = r.get("match")
            extra = _format_match_tag(match) if match else ""
            _print_search_result(i, r, extra=extra)
        _print_search_next_steps(include_ws_add=False)

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
            paper_type=args.paper_type,
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

    elif action == "rename":
        try:
            workspace.rename(ws_root, args.old_name, args.new_name)
        except (ValueError, FileNotFoundError, FileExistsError) as e:
            ui(str(e))
            return
        ui(f"工作区已重命名: {args.old_name} → {args.new_name}")


# ============================================================================
#  fsearch (federated search)
# ============================================================================


def _search_arxiv(query: str, top_k: int) -> list[dict]:
    """Call arXiv Atom API, return simplified paper dicts."""
    from scholaraio.sources.arxiv import search_arxiv

    return search_arxiv(query, top_k)


def _query_dois_for_set(cfg, doi_set: list[str]) -> set[str]:
    """Return the subset of doi_set that exists in the main library (case-insensitive).

    Only queries the specific DOIs requested, so this is O(len(doi_set)) regardless
    of library size. Returns an empty set if the index DB is missing or on any error.
    """
    import sqlite3

    if not doi_set or not Path(cfg.index_db).exists():
        return set()
    try:
        normalized = [d.lower() for d in doi_set]
        placeholders = ",".join("?" * len(normalized))
        with sqlite3.connect(str(cfg.index_db)) as conn:
            rows = conn.execute(
                f"SELECT doi FROM papers_registry WHERE LOWER(doi) IN ({placeholders})",
                normalized,
            ).fetchall()
        return {r[0].lower() for r in rows}
    except Exception:
        return set()


def _query_arxiv_ids_for_set(cfg, arxiv_id_set: list[str]) -> set[str]:
    """Return the subset of normalized arXiv IDs that exists in the main library."""
    from scholaraio.papers import iter_paper_dirs, read_meta
    from scholaraio.sources.arxiv import normalize_arxiv_ref

    if not arxiv_id_set or not Path(cfg.papers_dir).exists():
        return set()

    wanted: set[str] = set()
    for arxiv_id in arxiv_id_set:
        normalized = normalize_arxiv_ref(arxiv_id)
        if normalized:
            wanted.add(normalized)
    if not wanted:
        return set()

    found: set[str] = set()
    try:
        for paper_dir in iter_paper_dirs(Path(cfg.papers_dir)):
            try:
                meta = read_meta(paper_dir)
            except Exception:
                continue
            arxiv_id = meta.get("arxiv_id") or (meta.get("ids") or {}).get("arxiv", "")
            normalized = normalize_arxiv_ref(arxiv_id)
            if normalized and normalized in wanted:
                found.add(normalized)
    except Exception:
        return set()
    return found


def cmd_fsearch(args: argparse.Namespace, cfg) -> None:
    query = " ".join(args.query)
    top_k = _resolve_top(args, 10)
    scope_str = args.scope or "main"
    scopes = [s.strip() for s in scope_str.split(",") if s.strip()] or ["main"]

    ui(f'联邦搜索: "{query}"  scope={scope_str}\n')

    for scope in scopes:
        if scope == "main":
            ui("── [主库] ──")
            if not cfg.index_db.exists():
                ui("  主库索引不存在，请先运行 scholaraio index")
                results = []
            else:
                from scholaraio.index import unified_search

                try:
                    results, diagnostics = unified_search(
                        query,
                        cfg.index_db,
                        top_k=top_k,
                        cfg=cfg,
                        return_diagnostics=True,
                    )
                except Exception as e:
                    ui(f"  主库搜索失败：{e}")
                    results = []
                    diagnostics = {"vector_degraded": False}
            if not results:
                ui("  无结果")
            else:
                if diagnostics.get("vector_degraded"):
                    ui("  提示：向量检索不可用，已降级为关键词检索。")
                for i, r in enumerate(results, 1):
                    score = r.get("score", 0.0)
                    _print_search_result(i, r, extra=f"{_format_match_tag(r.get('match', '?'))} {score:.3f}")
            ui()

        elif scope.startswith("explore:"):
            explore_name = scope[len("explore:") :]
            from scholaraio.explore import validate_explore_name

            if explore_name != "*" and not validate_explore_name(explore_name):
                ui(f"  无效的 explore 库名 '{explore_name}'：不能为空，且不能包含路径分隔符或 '..'")
                ui()
                continue
            if explore_name == "*":
                from scholaraio.explore import list_explore_libs

                names = list_explore_libs(cfg)
                if not names:
                    ui("── [explore: *] ──")
                    ui("  暂无 explore 库，请先运行 scholaraio explore fetch --name <名称>")
                    ui()
            else:
                names = [explore_name]

            for name in names:
                ui(f"── [explore: {name}] ──")
                from scholaraio.explore import explore_db_path, explore_unified_search

                db = explore_db_path(name, cfg)
                if not db.exists():
                    ui(f"  explore 库 {name} 不存在或未建索引（explore.db 缺失）")
                    ui()
                    continue
                try:
                    results = explore_unified_search(name, query, top_k=top_k, cfg=cfg)
                except Exception as e:
                    ui(f"  搜索失败: {e}")
                    ui()
                    continue
                if not results:
                    ui("  无结果")
                else:
                    for i, r in enumerate(results, 1):
                        authors = r.get("authors", [])
                        first = authors[0] if authors else "?"
                        score = r.get("score", 0.0)
                        ui(f"  [{i}] [{r.get('year', '?')}] {r.get('title', '')}")
                        ui(f"       {first} | 分数: {score:.3f}")
                        ui()

        elif scope == "arxiv":
            ui("── [arXiv] ──")
            arxiv_results = _search_arxiv(query, top_k)
            if not arxiv_results:
                ui("  arXiv 不可用或无结果")
            else:
                # Only query the library for DOIs that actually appear in results
                arxiv_dois = [r["doi"].lower() for r in arxiv_results if r.get("doi")]
                arxiv_ids = [r.get("arxiv_id", "") for r in arxiv_results if r.get("arxiv_id")]
                in_lib_dois = _query_dois_for_set(cfg, arxiv_dois)
                in_lib_arxiv_ids = _query_arxiv_ids_for_set(cfg, arxiv_ids)
                for i, r in enumerate(arxiv_results, 1):
                    from scholaraio.sources.arxiv import normalize_arxiv_ref

                    authors = r.get("authors", [])
                    first = (authors[0] if authors else "?") + (" et al." if len(authors) > 1 else "")
                    doi = r.get("doi", "")
                    arxiv_id = r.get("arxiv_id", "")
                    normalized_arxiv_id = normalize_arxiv_ref(arxiv_id)
                    in_lib = bool(
                        (doi and doi.lower() in in_lib_dois)
                        or (normalized_arxiv_id and normalized_arxiv_id in in_lib_arxiv_ids)
                    )
                    status = "  [已入库]" if in_lib else ""
                    ui(f"  [{i}] [{r.get('year', '?')}] {r.get('title', '')}{status}")
                    ui(f"       {first} | arxiv:{arxiv_id}" + (f" | doi:{doi}" if doi else ""))
                    ui()

        elif scope == "proceedings":
            ui("── [论文集] ──")
            from scholaraio.index import search_proceedings
            from scholaraio.proceedings import proceedings_db_path

            db = proceedings_db_path(cfg._root)
            if not db.exists():
                ui("  proceedings 索引不存在，请先导入论文集")
                results = []
            else:
                try:
                    results = search_proceedings(query, db, top_k=top_k)
                except Exception as e:
                    ui(f"  proceedings 搜索失败：{e}")
                    results = []
            if not results:
                ui("  无结果")
            else:
                for i, r in enumerate(results, 1):
                    extra = f"proceedings:{r.get('proceeding_title', r.get('proceeding_dir', '?'))}"
                    _print_search_result(i, r, extra=extra)
            ui()

        else:
            ui(f"  未知 scope: {scope}，支持: main / proceedings / explore:NAME / explore:* / arxiv")


# ============================================================================
#  proceedings
# ============================================================================


def cmd_proceedings(args: argparse.Namespace, cfg) -> None:
    if args.proceedings_action == "build-clean-candidates":
        from scholaraio.ingest.proceedings import build_proceedings_clean_candidates

        proceeding_dir = Path(args.proceeding_dir).expanduser()
        if not proceeding_dir.exists():
            ui(f"proceedings 目录不存在: {proceeding_dir}")
            return

        candidates_path = build_proceedings_clean_candidates(proceeding_dir)
        ui(f"已生成 proceedings clean candidates: {candidates_path}")
        ui("等待 agent 审阅 clean_candidates.json 并生成 clean_plan.json，然后再执行后续清洗。")
        return

    if args.proceedings_action == "apply-split":
        from scholaraio.ingest.proceedings import apply_proceedings_split_plan

        proceeding_dir = Path(args.proceeding_dir).expanduser()
        split_plan = Path(args.split_plan).expanduser()

        if not proceeding_dir.exists():
            ui(f"proceedings 目录不存在: {proceeding_dir}")
            return
        if not split_plan.exists():
            ui(f"split plan 不存在: {split_plan}")
            return

        apply_proceedings_split_plan(proceeding_dir, split_plan)
        meta = json.loads((proceeding_dir / "meta.json").read_text(encoding="utf-8"))
        ui(f"已应用 proceedings split plan: {proceeding_dir.name} ({meta.get('child_paper_count', 0)} 篇)")
        return

    if args.proceedings_action == "apply-clean":
        from scholaraio.ingest.proceedings import apply_proceedings_clean_plan

        proceeding_dir = Path(args.proceeding_dir).expanduser()
        clean_plan = Path(args.clean_plan).expanduser()

        if not proceeding_dir.exists():
            ui(f"proceedings 目录不存在: {proceeding_dir}")
            return
        if not clean_plan.exists():
            ui(f"clean plan 不存在: {clean_plan}")
            return

        apply_proceedings_clean_plan(proceeding_dir, clean_plan)
        meta = json.loads((proceeding_dir / "meta.json").read_text(encoding="utf-8"))
        ui(f"已应用 proceedings clean plan: {proceeding_dir.name} ({meta.get('child_paper_count', 0)} 篇)")
        return

    ui(f"未知 proceedings 子命令: {args.proceedings_action}")


# ============================================================================
#  arXiv
# ============================================================================


def cmd_arxiv_search(args: argparse.Namespace, cfg) -> None:
    from scholaraio.sources.arxiv import search_arxiv

    query = " ".join(args.query).strip()
    top_k = _resolve_top(args, 10)
    category = (args.category or "").strip()
    sort = args.sort or "relevance"

    if not query and not category:
        ui("请至少提供检索词，或使用 --category 指定 arXiv 分类。")
        return

    ui(f'arXiv 搜索: query="{query or "*"}" category={category or "-"} sort={sort}\n')

    try:
        results = search_arxiv(query, top_k=top_k, category=category, sort=sort)
    except Exception as e:
        ui(f"arXiv 搜索失败: {e}")
        return
    if not results:
        ui("arXiv 不可用或无结果")
        return

    for i, r in enumerate(results, 1):
        authors = r.get("authors", [])
        first = (authors[0] if authors else "?") + (" et al." if len(authors) > 1 else "")
        ui(f"  [{i}] [{r.get('year', '?')}] {r.get('title', '')}")
        ui(f"       {first} | arxiv:{r.get('arxiv_id', '')}")
        if r.get("doi"):
            ui(f"       doi:{r['doi']}")
        if r.get("abstract"):
            ui(f"       {r['abstract'][:220]}{'...' if len(r['abstract']) > 220 else ''}")
        ui()


def cmd_arxiv_fetch(args: argparse.Namespace, cfg) -> None:
    from scholaraio.ingest.pipeline import PRESETS, run_pipeline
    from scholaraio.sources.arxiv import download_arxiv_pdf, normalize_arxiv_ref

    canonical_id = normalize_arxiv_ref(args.arxiv_ref)
    if not canonical_id:
        ui(f"无效的 arXiv 标识或 URL: {args.arxiv_ref}")
        return

    if args.dry_run:
        if args.ingest:
            ui(f"[dry-run] 将下载 arXiv PDF 并直接入库: {canonical_id}")
        else:
            ui(f"[dry-run] 将下载 arXiv PDF 到 inbox: {canonical_id}")
        return

    if args.ingest:
        ui(f"开始直接入库 arXiv 预印本: {canonical_id}")
        try:
            with tempfile.TemporaryDirectory(prefix="scholaraio_arxiv_") as tmpdir:
                tmp_inbox = Path(tmpdir)
                pdf_path = download_arxiv_pdf(canonical_id, tmp_inbox, overwrite=args.force)
                ui(f"已下载 PDF: {pdf_path.name}")
                run_pipeline(
                    PRESETS["ingest"],
                    cfg,
                    {"inbox_dir": tmp_inbox, "force": args.force, "include_aux_inboxes": False},
                )
        except Exception as e:
            ui(f"arXiv 下载或入库失败: {e}")
        return

    inbox_dir = cfg._root / "data" / "inbox"
    try:
        pdf_path = download_arxiv_pdf(canonical_id, inbox_dir, overwrite=args.force)
    except Exception as e:
        ui(f"arXiv 下载失败: {e}")
        return
    ui(f"已下载到 inbox: {pdf_path}")


def _slugify_ingest_link_title(title: str, fallback_url: str, index: int) -> str:
    raw = (title or "").strip() or _fallback_ingest_link_title(fallback_url, index)
    slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    slug = slug[:240].strip("-")
    return slug or f"link-{index:02d}"


def _fallback_ingest_link_title(source_url: str, index: int) -> str:
    parsed = urlparse(source_url)
    return Path(parsed.path).stem or parsed.netloc or f"link-{index:02d}"


def _render_ingest_link_markdown(title: str, source_url: str, body: str) -> str:
    parts = [
        f"# {title}",
        "",
        f"Source URL: {source_url}",
        "",
    ]
    body_text = (body or "").strip()
    if body_text:
        parts.append(body_text)
    return "\n".join(parts).rstrip() + "\n"


def _webextract_for_ingest_link(
    url: str,
    *,
    pdf: bool | None,
    extractor,
    max_attempts: int = 3,
    backoff_base: float = 1.0,
) -> dict:
    last_result: dict | None = None
    last_error = ""
    last_source_url = url

    for attempt in range(1, max_attempts + 1):
        try:
            result = extractor(url, pdf=pdf)
        except Exception as exc:
            last_result = None
            last_error = str(exc)
            last_source_url = url
        else:
            result = result or {}
            source_url = (result.get("url") or url).strip()
            error = (result.get("error") or "").strip()
            text = result.get("text") or ""
            last_result = result
            last_error = error
            last_source_url = source_url
            if not error or text.strip():
                if attempt > 1:
                    ui(f"链接提取重试后成功: {source_url} (第 {attempt} 次)")
                return result

        if attempt >= max_attempts:
            break
        wait = backoff_base * float(2 ** (attempt - 1))
        ui(f"链接提取失败，准备重试: {last_source_url} ({last_error})，{wait:.1f}s 后重试")
        time.sleep(wait)

    if last_result is not None:
        return last_result
    return {
        "url": last_source_url,
        "title": "",
        "text": "",
        "html": "",
        "error": last_error or "unknown extraction error",
    }


def cmd_websearch(args: argparse.Namespace, cfg) -> None:
    """实时网页搜索 (Bing via GUILessBingSearch)."""
    from scholaraio.sources import webtools

    query = " ".join(args.query)
    count = args.count

    try:
        results = webtools.search_and_display(query, count=count, cfg=cfg)
    except webtools.ServiceUnavailableError as e:
        ui(f"错误: {e}")
        ui("提示: 请确保 GUILessBingSearch 服务已启动")
        ui("  安装: https://github.com/wszqkzqk/GUILessBingSearch")
        ui("  启动: python guiless_bing_search.py")
        sys.exit(1)
    except webtools.WebSearchError as e:
        ui(f"搜索失败: {e}")
        sys.exit(1)

    if not results:
        return


def _terminal_preview(text: str, *, max_chars: int) -> tuple[str, bool]:
    body = (text or "").strip()
    if not body:
        return "", False
    if max_chars < 1 or len(body) <= max_chars:
        return body, False
    return body[:max_chars].rstrip(), True


def cmd_webextract(args: argparse.Namespace, cfg) -> None:
    """网页内容提取 (qt-web-extractor)."""
    from scholaraio.sources import webtools

    url = args.url
    pdf = args.pdf
    full = getattr(args, "full", False)
    max_chars = max(1, int(getattr(args, "max_chars", 4000) or 4000))

    try:
        result = webtools.extract_web(url, pdf=pdf, cfg=cfg)
    except webtools.WebExtractServiceUnavailableError as e:
        ui(f"错误: {e}")
        ui("提示: 请确保 qt-web-extractor 服务已启动")
        sys.exit(1)
    except webtools.WebExtractError as e:
        ui(f"提取失败: {e}")
        sys.exit(1)

    title = result.get("title", "")
    text = result.get("text") or ""
    text_body = text.strip()
    error = str(result.get("error") or "").strip()

    if error and not text_body:
        ui(f"提取失败: {error}")
        sys.exit(1)

    if error:
        ui(f"提取有警告: {error}")

    ui(f"提取成功: {title or url}")
    if not text_body:
        return

    output_text, truncated = (text_body, False) if full else _terminal_preview(text_body, max_chars=max_chars)
    if output_text:
        print(output_text)
    if truncated:
        ui(f"内容较长，已截断显示前 {len(output_text)} / {len(text_body)} 个字符；使用 --full 查看全文")


def cmd_ingest_link(args: argparse.Namespace, cfg) -> None:
    from scholaraio.ingest.pipeline import run_pipeline
    from scholaraio.sources import webtools

    urls = [u.strip() for u in args.urls if u.strip()]
    if not urls:
        ui("请至少提供一个 URL")
        return

    if args.dry_run:
        ui(f"[dry-run] 将抓取 {len(urls)} 个链接并直接入库")
        for url in urls:
            ui(f"  - {url}")
        return

    step_names = ["extract_doc", "ingest"]
    if not args.no_index:
        step_names.extend(["embed", "index"])

    summaries: list[dict[str, str]] = []
    output_mode = redirect_console_ui(sys.stderr) if args.json else nullcontext()

    def extract_for_ingest(url: str, *, pdf: bool | None = None) -> dict:
        return webtools.extract_web(url, pdf=pdf, cfg=cfg)

    try:
        with output_mode, tempfile.TemporaryDirectory(prefix="scholaraio_link_") as tmpdir:
            ui(f"开始直接入库链接: {len(urls)} 个")
            tmp_root = Path(tmpdir)
            inbox_dir = tmp_root / "inbox"
            inbox_dir.mkdir(parents=True, exist_ok=True)
            doc_inbox_dir = Path(tmpdir) / "inbox-doc"
            doc_inbox_dir.mkdir(parents=True, exist_ok=True)

            for idx, url in enumerate(urls, start=1):
                pdf_mode = True if args.pdf else None
                result = _webextract_for_ingest_link(url, pdf=pdf_mode, extractor=extract_for_ingest)
                source_url = (result.get("url") or url).strip()
                error = (result.get("error") or "").strip()
                text = result.get("text") or ""
                if error and not text.strip():
                    ui(f"链接提取失败，已跳过: {source_url} ({error})")
                    continue
                if error:
                    ui(f"链接提取有警告，继续入库: {source_url} ({error})")

                title = (result.get("title") or "").strip() or _fallback_ingest_link_title(source_url, idx)
                slug = _slugify_ingest_link_title(title, source_url, idx)
                md_name = f"{idx:02d}-{slug}.md"
                md_path = doc_inbox_dir / md_name
                sidecar_path = md_path.with_suffix(".json")

                md_text = _render_ingest_link_markdown(title, source_url, text)
                md_path.write_text(md_text, encoding="utf-8")

                sidecar = {
                    "title": title,
                    "source_file": md_name,
                    "source_url": source_url,
                    "source_type": "web",
                    "extracted_at": datetime.now(timezone.utc).isoformat(),
                    "extraction_method": "qt-web-extractor",
                }
                sidecar_path.write_text(json.dumps(sidecar, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

                summaries.append(
                    {
                        "url": source_url,
                        "title": title,
                        "markdown_file": md_name,
                    }
                )
                ui(f"已抓取: {title[:80]}")

            if not summaries:
                ui("没有可入库的链接内容")
                return

            run_pipeline(
                step_names,
                cfg,
                {
                    "inbox_dir": inbox_dir,
                    "doc_inbox_dir": doc_inbox_dir,
                    "force": args.force,
                    "include_aux_inboxes": False,
                },
            )
    except Exception as e:
        ui(f"链接抓取或入库失败: {e}")
        return

    if args.json:
        sys.stdout.write(json.dumps(summaries, ensure_ascii=False, indent=2) + "\n")


# ============================================================================
#  insights
# ============================================================================


def cmd_insights(args: argparse.Namespace, cfg) -> None:
    from datetime import datetime, timedelta, timezone

    from scholaraio import insights
    from scholaraio.metrics import get_store

    store = get_store()
    if not store:
        ui("暂无足够数据（metrics 未初始化）")
        return

    days = args.days
    if days <= 0:
        ui("--days 必须为正整数")
        return
    since_dt = datetime.now(timezone.utc) - timedelta(days=days)
    since_iso = since_dt.isoformat()

    # Fetch search events
    search_events = store.query(category="search", since=since_iso, limit=10000)
    # Fetch read events
    read_events = store.query(category="read", since=since_iso, limit=10000)

    if not search_events and not read_events:
        ui(f"暂无足够数据（过去 {days} 天内无搜索或阅读记录）")
        return

    ui(f"=== 科研行为分析（过去 {days} 天）===\n")

    ui("【搜索热词前 10】")
    hot_keywords = insights.extract_hot_keywords(search_events, top_k=10)
    if hot_keywords:
        for word, cnt in hot_keywords:
            bar = "█" * min(cnt, 20)
            ui(f"  {word:<20s} {bar} ({cnt})")
    else:
        ui("  暂无搜索记录")
    ui()

    ui("【最常阅读论文前 10】")
    most_read = insights.aggregate_most_read_titles(read_events, cfg.papers_dir, top_k=10)
    if most_read:
        for rank, (title_key, cnt) in enumerate(most_read, 1):
            label = title_key[:60]
            ui(f"  {rank:2d}. [{cnt}次] {label}")
    else:
        ui("  暂无阅读记录")
    ui()

    # 3. Weekly read-count trend (ASCII bar chart)
    ui("【阅读量趋势（按周）】")
    if read_events:
        week_counts = insights.build_weekly_read_trend(read_events)
        if week_counts:
            max_count = max(cnt for _, cnt in week_counts) or 1
            for week, cnt in week_counts:
                bar_len = round(cnt / max_count * 20)
                bar = "█" * bar_len
                ui(f"  {week}  {bar} {cnt}")
        else:
            ui("  暂无足够数据")
    else:
        ui("  暂无阅读记录")
    ui()

    # 4. Recommend semantically adjacent papers not yet read (based on last 7 days of reads)
    ui("【推荐：你可能还没读过的邻近论文】")
    recent_since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    recent_reads = store.query(category="read", since=recent_since, limit=500)
    recent_paper_ids = insights.recent_unique_read_names(recent_reads, limit=5)

    if not recent_paper_ids:
        ui("  过去7天无阅读记录，无法推荐")
    else:
        try:
            recommendations = insights.recommend_unread_neighbors(store, cfg, recent_days=7, recent_limit=5, top_k=5)
            if recommendations:
                for rank, (_pid, label, score) in enumerate(recommendations, 1):
                    label = label[:60]
                    ui(f"  {rank}. {label}  (分数: {score:.3f})")
            else:
                ui("  未找到合适的邻近论文（可能向量索引未建立）")
        except ImportError:
            ui("  语义搜索不可用（需安装 embed 依赖）")
    ui()

    # 5. Active workspaces — list workspaces with paper counts
    ui("【活跃工作区】")
    try:
        ws_root = cfg._root / "workspace"
        workspaces = insights.list_workspace_counts(ws_root)
        if workspaces:
            for ws_name, count in workspaces:
                ui(f"  {ws_name:<30s} {count} 篇论文")
        else:
            ui("  暂无工作区")
    except Exception:
        ui("  工作区信息不可用")
    ui()


# ============================================================================
#  metrics
# ============================================================================


def cmd_metrics(args: argparse.Namespace, cfg) -> None:
    from scholaraio.metrics import get_store

    store = get_store()
    if not store:
        _log.error("Metrics 数据库尚未初始化。")
        return

    if args.summary:
        s = store.summary()
        ui("LLM 调用统计（全部会话）：")
        ui(f"  调用次数:      {s['call_count']}")
        ui(f"  输入 tokens:   {s['total_tokens_in']:,}")
        ui(f"  输出 tokens:   {s['total_tokens_out']:,}")
        ui(f"  总 tokens:     {s['total_tokens_in'] + s['total_tokens_out']:,}")
        ui(f"  总耗时:        {s['total_duration_s']:.1f}s")
        return

    rows = store.query(
        category=args.category,
        since=args.since,
        limit=args.last,
    )
    if not rows:
        ui("没有记录。")
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


def cmd_backup(args: argparse.Namespace, cfg) -> None:
    from scholaraio.backup import BackupConfigError, build_rsync_command, run_backup

    action = getattr(args, "backup_action", None)
    if action == "list":
        ui(f"备份源目录: {cfg.backup_source_dir}")
        if not cfg.backup.targets:
            ui("未配置任何备份目标。")
            return
        ui()
        for name, target in sorted(cfg.backup.targets.items()):
            status = "启用" if target.enabled else "禁用"
            remote = f"{target.user}@{target.host}" if target.user else target.host
            ui(f"[{name}] {status}")
            ui(f"  远端: {remote}:{target.path}")
            ui(f"  模式: {target.mode}  |  压缩: {'on' if target.compress else 'off'}")
            if target.exclude:
                ui(f"  排除: {', '.join(target.exclude)}")
        return

    if action == "run":
        try:
            cmd = build_rsync_command(cfg, args.target, dry_run=args.dry_run)
            ui("即将执行备份命令：")
            ui("  " + shlex.join(cmd))
            result = run_backup(cfg, args.target, dry_run=args.dry_run)
        except BackupConfigError as exc:
            _log.error("%s", exc)
            sys.exit(1)

        if result.stdout.strip():
            ui()
            ui(result.stdout.rstrip())
        if result.stderr.strip():
            ui()
            ui(result.stderr.rstrip())
        if result.returncode != 0:
            _print_backup_failure_guidance(cfg, args.target, result.stderr)
            _log.error("备份失败，退出码: %s", result.returncode)
            sys.exit(result.returncode)
        if args.dry_run:
            ui()
            ui("预演完成：未实际传输文件。")
        else:
            ui()
            ui("备份完成。")
        return

    _log.error("未知 backup 子命令: %s", action)
    sys.exit(1)


def _print_backup_failure_guidance(cfg, target_name: str, stderr: str) -> None:
    stderr = (stderr or "").strip()
    if not stderr:
        return

    target = cfg.backup.targets.get(target_name)
    host = target.host if target and target.host else "<host>"
    user = target.user if target and target.user else "<user>"
    port = target.port if target and target.port else 22
    identity_file = target.identity_file if target and target.identity_file else "~/.ssh/id_ed25519"
    remote = f"{user}@{host}" if user != "<user>" else host
    lower = stderr.lower()

    auth_error = "permission denied" in lower or "publickey" in lower
    host_key_error = "host key verification failed" in lower or "host key is unknown" in lower
    if not auth_error and not host_key_error:
        return

    ui()
    ui("提示：`scholaraio backup run` 会强制使用非交互 SSH（`BatchMode=yes`），不会在 CLI 里等待密码或 host key 确认。")
    ui("建议按下面步骤完成一次性配置：")
    ui("  1. 在 `config.local.yaml` 中为该目标补齐 SSH 配置：")
    ui("     backup:")
    ui("       targets:")
    ui(f"         {target_name}:")
    ui(f"           host: {host}")
    ui(f"           user: {user}")
    ui(f"           port: {port}")
    ui(f"           identity_file: {identity_file}  # 推荐：密钥登录")
    ui("           password: <ssh-password>  # 备选：仅放在 config.local.yaml")
    if host_key_error:
        ui(f"  2. 先写入 `known_hosts`：`ssh-keyscan -p {port} {host} >> ~/.ssh/known_hosts`")
    else:
        ui("  2. `backup run` 不支持在 CLI 里临时输入 SSH 密码；请提前准备密钥或把密码写进 `config.local.yaml`。")
        ui(f"     首次连接若还没信任主机，请先执行：`ssh-keyscan -p {port} {host} >> ~/.ssh/known_hosts`")
    ui(f"  3. 若走密钥方案，先验证：`ssh -i {identity_file} -p {port} {remote} true`")
    ui("     若走密码方案，保存 `config.local.yaml` 后直接重试 backup dry-run 即可。")
    ui(f"  4. 验证通过后重试：`scholaraio backup run {target_name} --dry-run`")


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

    try:
        records, pdf_paths = parse_endnote_full(paths)
    except ImportError as e:
        _check_import_error(e)

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
    dry_run = getattr(args, "dry_run", False)

    if dry_run:
        ui(f"[dry-run] 论文目录: {paper_d}")
        ui(f"[dry-run] PDF 来源: {pdf_path}")
        ui(f"[dry-run] 目标 paper.md: {paper_d / 'paper.md'}")
        if existing_md.exists():
            ui("[dry-run] 警告：已有 paper.md，实际运行时将被覆盖")
        ui("[dry-run] 将执行: MinerU 转换 → 摘要补全 → 重新嵌入 → 重建索引")
        ui("[dry-run] 如确认无误，去掉 --dry-run 参数再运行")
        return

    if existing_md.exists():
        ui(f"警告：{paper_d.name} 已有 paper.md，将被覆盖")

    # Copy PDF to paper directory
    dest_pdf = paper_d / pdf_path.name
    shutil.copy2(str(pdf_path), str(dest_pdf))
    ui(f"已复制 PDF: {dest_pdf.name}")

    # Convert PDF → markdown via MinerU
    from scholaraio.ingest.mineru import (
        ConvertOptions,
        _convert_long_pdf,
        _convert_long_pdf_cloud,
        _get_pdf_page_count,
        _plan_cloud_chunking,
        check_server,
        convert_pdf,
        is_pdf_validation_error,
        validate_pdf_for_mineru,
    )
    from scholaraio.ingest.pdf_fallback import (
        convert_pdf_with_fallback,
        preferred_parser_order,
        prefers_fallback_parser,
    )

    mineru_opts = ConvertOptions(
        api_url=cfg.ingest.mineru_endpoint,
        output_dir=paper_d,
        backend=cfg.ingest.mineru_backend_local,
        cloud_model_version=cfg.ingest.mineru_model_version_cloud,
        lang=cfg.ingest.mineru_lang,
        parse_method=cfg.ingest.mineru_parse_method,
        formula_enable=cfg.ingest.mineru_enable_formula,
        table_enable=cfg.ingest.mineru_enable_table,
        poll_timeout=cfg.ingest.mineru_poll_timeout,
    )

    result = None
    preferred_done = False
    fallback_auto_detect = getattr(cfg.ingest, "pdf_fallback_auto_detect", True)
    fallback_order = preferred_parser_order(
        getattr(cfg.ingest, "pdf_preferred_parser", "mineru"),
        getattr(cfg.ingest, "pdf_fallback_order", None),
        auto_detect=fallback_auto_detect,
    )
    local_chunk_limit = getattr(cfg.ingest, "chunk_page_limit", 100)

    def _ensure_valid_for_mineru() -> None:
        validation = validate_pdf_for_mineru(dest_pdf)
        if not validation.ok:
            ui(f"PDF 校验失败: {validation.error or 'PDF validation failed'}")
            sys.exit(1)

    if prefers_fallback_parser(getattr(cfg.ingest, "pdf_preferred_parser", "mineru")):
        ok, parser_name, fallback_err = convert_pdf_with_fallback(
            dest_pdf,
            existing_md,
            parser_order=fallback_order,
            auto_detect=fallback_auto_detect,
        )
        if not ok:
            ui(f"首选解析器失败: {fallback_err}")
            sys.exit(1)
        ui(f"已按配置优先使用 {parser_name} 生成 paper.md")
        preferred_done = True
    elif check_server(cfg.ingest.mineru_endpoint):
        _ensure_valid_for_mineru()
        page_count = _get_pdf_page_count(dest_pdf)
        if page_count > local_chunk_limit:
            ui(f"检测到长 PDF（{page_count} 页，超过 {local_chunk_limit} 页限制），正在分片处理...")
            result = _convert_long_pdf(dest_pdf, mineru_opts, chunk_size=local_chunk_limit)
        else:
            result = convert_pdf(dest_pdf, mineru_opts)
    else:
        api_key = cfg.resolved_mineru_api_key()
        if not api_key:
            ui("MinerU 不可达且无 MinerU token，改用 fallback 解析器")
        else:
            from scholaraio.ingest.mineru import convert_pdf_cloud

            _ensure_valid_for_mineru()
            should_chunk, chunk_size, reason = _plan_cloud_chunking(
                dest_pdf,
                default_chunk_size=local_chunk_limit,
            )
            if should_chunk:
                ui(f"检测到云端需分片 PDF（{reason}），正在分片处理...")
                try:
                    result = _convert_long_pdf_cloud(
                        dest_pdf,
                        mineru_opts,
                        api_key=api_key,
                        cloud_url=cfg.ingest.mineru_cloud_url,
                        chunk_size=chunk_size,
                    )
                except ImportError as exc:
                    result = None
                    ui(f"云端分片依赖缺失，尝试 fallback：{exc}。可安装 scholaraio[pdf]")
                except Exception as exc:
                    result = None
                    ui(f"云端分片失败，尝试 fallback：{exc}")
            else:
                result = convert_pdf_cloud(
                    dest_pdf,
                    mineru_opts,
                    api_key=api_key,
                    cloud_url=cfg.ingest.mineru_cloud_url,
                )

    if not preferred_done and (result is None or not result.success):
        err = result.error if result is not None else "MinerU unavailable"
        if is_pdf_validation_error(result):
            ui(f"PDF 校验失败: {err}")
            sys.exit(1)
        ui(f"MinerU 转换失败，尝试 fallback: {err}")
        ok, parser_name, fallback_err = convert_pdf_with_fallback(
            dest_pdf,
            existing_md,
            parser_order=fallback_order,
            auto_detect=fallback_auto_detect,
        )
        if not ok:
            ui(f"fallback 解析失败: {fallback_err}")
            sys.exit(1)
        ui(f"已降级使用 {parser_name} 生成 paper.md")
    elif result is not None:
        # Move/rename output to paper.md
        if result.md_path and result.md_path != existing_md:
            md_src = result.md_path
            md_src_parent = md_src.parent
            if existing_md.exists():
                existing_md.unlink()
            shutil.move(str(md_src), str(existing_md))
            for images_src in [md_src.parent / "images", md_src.parent / f"{md_src.stem}_images"]:
                if images_src.is_dir():
                    target = paper_d / "images"
                    if images_src == target:
                        break
                    if target.exists():
                        shutil.rmtree(target)
                    shutil.move(str(images_src), str(target))
                    break
            if md_src_parent != paper_d and md_src_parent.is_dir() and not any(md_src_parent.iterdir()):
                md_src_parent.rmdir()

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
    cite_suffix = f"  [被引: {cite}]" if cite else ""
    extra_suffix = f"  ({extra})" if extra else ""
    # Prefer dir_name for display, fall back to paper_id (UUID)
    display_id = r.get("dir_name") or r["paper_id"]
    ui(f"[{idx}] {display_id}{extra_suffix}")
    ui(f"     {author_display} | {r.get('year', '?')} | {r.get('journal', '?')}{cite_suffix}")
    ui(f"     {r['title']}")
    ui()


def _print_search_next_steps(include_ws_add: bool = True) -> None:
    ui("下一步：可以运行 `scholaraio show <paper-id> --layer 2/3/4` 查看摘要、结论或全文。")
    if include_ws_add:
        ui("也可以运行 `scholaraio ws add <工作区名> <paper-id>` 把感兴趣的论文加入工作区。")


def _format_match_tag(match: str) -> str:
    mapping = {
        "both": "关键词+语义",
        "fts": "关键词",
        "vec": "语义",
    }
    return mapping.get(match, match)


def _format_citations(cc: dict) -> str:
    if not cc:
        return ""
    parts = []
    for src in ("semantic_scholar", "openalex", "crossref"):
        if src in cc:
            label = {"semantic_scholar": "S2", "openalex": "OA", "crossref": "CR"}[src]
            parts.append(f"{label}:{cc[src]}")
    return " | ".join(parts)


def _lookup_registry_by_candidates(cfg, *candidates: object) -> dict | None:
    """Try registry lookups in order and return the first match."""
    from scholaraio.index import lookup_paper

    seen: set[str] = set()
    for candidate in candidates:
        candidate_str = str(candidate or "").strip()
        if not candidate_str or candidate_str in seen:
            continue
        seen.add(candidate_str)
        reg = lookup_paper(cfg.index_db, candidate_str)
        if reg:
            return reg
    return None


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

    normalized_doi = paper_id.strip().lower()
    for pdir in iter_paper_dirs(papers_dir):
        try:
            data = _read_meta(pdir)
        except (ValueError, FileNotFoundError) as e:
            _log.debug("failed to read meta.json in %s: %s", pdir.name, e)
            continue
        doi = str(data.get("doi") or "").strip().lower()
        if data.get("id") == paper_id or (doi and doi == normalized_doi):
            return pdir
    _log.error("未找到论文: %s", paper_id)
    sys.exit(1)


def _print_header(l1: dict) -> None:
    authors = l1.get("authors") or []
    author_str = ", ".join(authors[:3])
    if len(authors) > 3:
        author_str += f" et al. ({len(authors)} total)"
    ui(f"论文ID   : {l1['paper_id']}")
    if l1.get("dir_name") and l1["dir_name"] != l1["paper_id"]:
        ui(f"目录名   : {l1['dir_name']}")
    ui(f"标题     : {l1['title']}")
    ui(f"作者     : {author_str}")
    ui(f"年份     : {l1.get('year') or '?'}  |  期刊: {l1.get('journal') or '?'}")
    if l1.get("doi"):
        ui(f"DOI      : {l1['doi']}")
    ids = l1.get("ids") or {}
    if ids.get("patent_publication_number"):
        ui(f"公开号   : {ids['patent_publication_number']}")
    if l1.get("paper_type"):
        ui(f"类型     : {l1['paper_type']}")
    cite_str = _format_citations(l1.get("citation_count") or {})
    if cite_str:
        ui(f"引用     : {cite_str}")
    if ids.get("semantic_scholar_url"):
        ui(f"S2       : {ids['semantic_scholar_url']}")
    if ids.get("openalex_url"):
        ui(f"OpenAlex : {ids['openalex_url']}")


def _enrich_show_header(l1: dict, *, paper_d: Path, requested_id: str, cfg) -> dict:
    enriched = dict(l1)
    enriched["dir_name"] = paper_d.name
    current_paper_id = str(enriched.get("paper_id") or "").strip()
    reg = _lookup_registry_by_candidates(
        cfg,
        requested_id if requested_id != paper_d.name else "",
        enriched.get("doi") or "",
        paper_d.name if not current_paper_id or current_paper_id == paper_d.name else "",
    )
    if reg and reg.get("id"):
        enriched["paper_id"] = str(reg["id"])
    return enriched


def cmd_citation_check(args: argparse.Namespace, cfg) -> None:
    from scholaraio.citation_check import check_citations, extract_citations

    # Read input text
    if args.file:
        p = Path(args.file)
        if not p.exists():
            _log.error("文件不存在：%s", p)
            sys.exit(1)
        text = p.read_text(encoding="utf-8")
    else:
        text = sys.stdin.read()

    if not text.strip():
        ui("输入文本为空。")
        return

    citations = extract_citations(text)
    if not citations:
        ui("未在文本中发现引用。")
        return

    ui(f"提取到 {len(citations)} 条引用，正在验证…\n")

    try:
        paper_ids = _resolve_ws_paper_ids(args, cfg)
    except ValueError as e:
        ui(str(e))
        return

    results = check_citations(
        citations,
        cfg.index_db,
        paper_ids=paper_ids,
    )

    # Count by status (internal codes)
    counts = {"VERIFIED": 0, "NOT_IN_LIBRARY": 0, "AMBIGUOUS": 0}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1

    status_labels = {
        "VERIFIED": "已验证",
        "NOT_IN_LIBRARY": "库中未找到",
        "AMBIGUOUS": "候选不唯一",
    }

    for r in results:
        status_icon = {"VERIFIED": "✓", "NOT_IN_LIBRARY": "✗", "AMBIGUOUS": "?"}.get(r["status"], " ")
        status_text = status_labels.get(r["status"], r["status"])
        ui(f"  [{status_icon}] {status_text:8s}  {r['raw']}  ({r['author']}, {r['year']})")
        if r["matches"]:
            for m in r["matches"][:3]:
                display_id = m.get("dir_name") or m.get("paper_id", "?")
                ui(f"       → {display_id}")
                ui(f"         {m.get('title', '?')}")

    ui()
    ui(
        f"验证结果：已验证 {counts['VERIFIED']} / "
        f"候选不唯一 {counts['AMBIGUOUS']} / "
        f"库中未找到 {counts['NOT_IN_LIBRARY']}"
    )


# ============================================================================
#  Entry point
# ============================================================================


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scholaraio",
        description="面向 AI coding agent 的研究终端",
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
    _add_result_limit_arg(p_search, "最多返回 N 条（默认读 config search.top_k）")
    _add_filter_args(p_search)

    # --- search-author ---
    p_sa = sub.add_parser("search-author", help="按作者名搜索")
    p_sa.set_defaults(func=cmd_search_author)
    p_sa.add_argument("query", nargs="+", help="作者名（模糊匹配）")
    _add_result_limit_arg(p_sa, "最多返回 N 条（默认读 config search.top_k）")
    _add_filter_args(p_sa)

    # --- show ---
    p_show = sub.add_parser("show", help="查看论文内容")
    p_show.set_defaults(func=cmd_show)
    p_show.add_argument("paper_id", help="论文 ID（目录名 / UUID / DOI）")
    p_show.add_argument(
        "--layer",
        type=int,
        default=2,
        choices=[1, 2, 3, 4],
        help="加载层级：1=元数据, 2=摘要, 3=结论, 4=全文（默认 2）",
    )
    p_show.add_argument("--lang", type=str, default=None, help="加载翻译版本（如 zh），仅 L4 生效")
    p_show.add_argument(
        "--append-notes",
        type=str,
        default=None,
        metavar="TEXT",
        help="向论文笔记 notes.md 追加内容（T2 层，跨会话复用）",
    )

    # --- embed ---
    p_embed = sub.add_parser("embed", help="生成语义向量写入 index.db")
    p_embed.set_defaults(func=cmd_embed)
    p_embed.add_argument("--rebuild", action="store_true", help="清空后重建")

    # --- vsearch ---
    p_vsearch = sub.add_parser("vsearch", help="语义向量检索")
    p_vsearch.set_defaults(func=cmd_vsearch)
    p_vsearch.add_argument("query", nargs="+", help="检索词")
    _add_result_limit_arg(p_vsearch, "最多返回 N 条（默认读 config embed.top_k）")
    _add_filter_args(p_vsearch)

    # --- usearch (unified) ---
    p_usearch = sub.add_parser("usearch", help="融合检索（关键词 + 语义向量）")
    p_usearch.set_defaults(func=cmd_usearch)
    p_usearch.add_argument("query", nargs="+", help="检索词")
    _add_result_limit_arg(p_usearch, "最多返回 N 条（默认读 config search.top_k）")
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
    p_refetch = sub.add_parser("refetch", help="重新查询 API 补全引用量、references 等字段")
    p_refetch.set_defaults(func=cmd_refetch)
    p_refetch.add_argument("paper_id", nargs="?", help="论文 ID（目录名 / UUID / DOI；省略则需 --all）")
    p_refetch.add_argument("--all", action="store_true", help="补查所有缺失引用量的论文")
    p_refetch.add_argument("--force", action="store_true", help="强制重新查询（包括已有引用量的论文）")
    p_refetch.add_argument(
        "--references-only",
        "--refs-only",
        action="store_true",
        help="仅补 references 为空的 DOI 论文；单篇模式下只更新 references",
    )
    p_refetch.add_argument("--jobs", "-j", type=int, default=5, help="并发数（默认 5）")

    # --- top-cited ---
    p_tc = sub.add_parser("top-cited", help="按引用量排序查看论文")
    p_tc.set_defaults(func=cmd_top_cited)
    _add_result_limit_arg(p_tc, "最多返回 N 条（默认读 config search.top_k）")
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
    p_topics.add_argument("--build", action="store_true", help="构建主题模型")
    p_topics.add_argument("--rebuild", action="store_true", help="清空旧模型目录后重建主题模型")
    p_topics.add_argument("--reduce", type=int, default=None, metavar="N", help="快速合并主题到 N 个（不重新聚类）")
    p_topics.add_argument(
        "--merge", type=str, default=None, metavar="IDS", help="手动合并主题，格式: 1,6,14+3,5（用+分隔组）"
    )
    p_topics.add_argument("--topic", type=int, default=None, metavar="ID", help="查看指定主题的论文（-1 查看 outlier）")
    _add_result_limit_arg(p_topics, "返回条数")
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
    p_repair.add_argument("paper_id", help="论文 ID（目录名 / UUID / DOI）")
    p_repair.add_argument("--title", required=True, help="正确的论文标题")
    p_repair.add_argument("--doi", default="", help="已知 DOI（加速 API 查询）")
    p_repair.add_argument("--author", default="", help="一作全名")
    p_repair.add_argument("--year", type=int, default=None, help="发表年份")
    p_repair.add_argument("--no-api", action="store_true", help="跳过 API 查询，仅用提供的信息")
    p_repair.add_argument("--dry-run", action="store_true", help="预览，不实际修改")

    # --- explore ---
    p_explore = sub.add_parser("explore", help="多维文献探索（OpenAlex 拉取 + 嵌入 + 聚类）")
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
    p_ef.add_argument("--limit", type=int, default=None, help="最多拉取的论文数量上限（不设则无限）")

    p_ee = p_explore_sub.add_parser("embed", help="为探索库生成语义向量")
    p_ee.add_argument("--name", required=True, help="探索库名称")
    p_ee.add_argument("--rebuild", action="store_true", help="清空后重建")

    p_et = p_explore_sub.add_parser("topics", help="探索库主题建模")
    p_et.add_argument("--name", required=True, help="探索库名称")
    p_et.add_argument("--build", action="store_true", help="构建主题模型")
    p_et.add_argument("--rebuild", action="store_true", help="重建主题模型")
    p_et.add_argument("--topic", type=int, default=None, help="查看指定主题的论文")
    _add_result_limit_arg(p_et, "返回条数")
    p_et.add_argument("--min-topic-size", type=int, default=None, help="最小聚类大小（默认 30）")
    p_et.add_argument("--nr-topics", type=int, default=None, help="目标主题数（默认自然聚类）")

    p_es = p_explore_sub.add_parser("search", help="探索库搜索（语义/关键词/融合）")
    p_es.add_argument("--name", required=True, help="探索库名称")
    p_es.add_argument("query", nargs="+", help="查询文本")
    _add_result_limit_arg(p_es, "返回条数")
    p_es.add_argument(
        "--mode", choices=["semantic", "keyword", "unified"], default="semantic", help="搜索模式（默认 semantic）"
    )

    p_ev = p_explore_sub.add_parser("viz", help="生成全部可视化（HTML）")
    p_ev.add_argument("--name", required=True, help="探索库名称")

    p_el = p_explore_sub.add_parser("list", help="列出所有探索库")

    p_ei = p_explore_sub.add_parser("info", help="查看探索库信息")
    p_ei.add_argument("--name", default=None, help="探索库名称（省略列出全部）")

    # --- export ---
    p_export = sub.add_parser("export", help="导出论文或文档（BibTeX / RIS / Markdown / DOCX）")
    p_export.set_defaults(func=cmd_export)
    p_export_sub = p_export.add_subparsers(dest="export_action", required=True)

    p_eb = p_export_sub.add_parser("bibtex", help="导出 BibTeX 格式（LaTeX 引用）")
    p_eb.add_argument("paper_ids", nargs="*", help="论文目录名（可多个）")
    p_eb.add_argument("--all", action="store_true", help="导出全部论文")
    p_eb.add_argument("--year", type=str, default=None, help="年份过滤：2023 / 2020-2024")
    p_eb.add_argument("--journal", type=str, default=None, help="期刊名过滤（模糊匹配）")
    p_eb.add_argument("-o", "--output", type=str, default=None, help="输出文件路径（省略则输出到屏幕）")

    p_er = p_export_sub.add_parser("ris", help="导出 RIS 格式（Zotero / Endnote / Mendeley 导入）")
    p_er.add_argument("paper_ids", nargs="*", help="论文目录名（可多个）")
    p_er.add_argument("--all", action="store_true", help="导出全部论文")
    p_er.add_argument("--year", type=str, default=None, help="年份过滤：2023 / 2020-2024")
    p_er.add_argument("--journal", type=str, default=None, help="期刊名过滤（模糊匹配）")
    p_er.add_argument("-o", "--output", type=str, default=None, help="输出文件路径（省略则输出到屏幕）")

    p_em = p_export_sub.add_parser("markdown", help="导出 Markdown 文献列表（可直接粘贴到文档）")
    p_em.add_argument("paper_ids", nargs="*", help="论文目录名（可多个）")
    p_em.add_argument("--all", action="store_true", help="导出全部论文")
    p_em.add_argument("--year", type=str, default=None, help="年份过滤：2023 / 2020-2024")
    p_em.add_argument("--journal", type=str, default=None, help="期刊名过滤（模糊匹配）")
    p_em.add_argument("--bullet", action="store_true", help="使用无序列表（默认有序）")
    p_em.add_argument(
        "--style",
        type=str,
        default="apa",
        help="引用格式：apa（默认）/ vancouver / chicago-author-date / mla / <自定义>",
    )
    p_em.add_argument("-o", "--output", type=str, default=None, help="输出文件路径（省略则输出到屏幕）")

    p_ed = p_export_sub.add_parser("docx", help="将 Markdown 文本导出为 Word DOCX 文件")
    p_ed.add_argument("--input", "-i", type=str, default=None, help="输入 Markdown 文件路径（省略则从 stdin 读取）")
    p_ed.add_argument(
        "--output", "-o", type=str, default=None, help="输出 .docx 文件路径（默认 workspace/output.docx）"
    )
    p_ed.add_argument("--title", type=str, default=None, help="文档标题（可选，插入为一级标题）")

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
    _add_result_limit_arg(p_ws_add, "限制 --search 返回条数")
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
    _add_result_limit_arg(p_ws_search, "返回条数")
    p_ws_search.add_argument(
        "--mode", choices=["unified", "keyword", "semantic"], default="unified", help="搜索模式（默认 unified）"
    )
    _add_filter_args(p_ws_search)

    p_ws_rename = p_ws_sub.add_parser("rename", help="重命名工作区")
    p_ws_rename.add_argument("old_name", help="当前工作区名称")
    p_ws_rename.add_argument("new_name", help="新工作区名称")

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
    p_ap.add_argument("--dry-run", action="store_true", help="预览将要执行的操作，不实际运行")

    # --- citation-check ---
    p_cc = sub.add_parser("citation-check", help="验证文本中的引用是否在本地知识库中")
    p_cc.set_defaults(func=cmd_citation_check)
    p_cc.add_argument("file", nargs="?", default=None, help="待检查的文件路径（省略则从 stdin 读取）")
    p_cc.add_argument("--ws", type=str, default=None, help="在指定工作区范围内验证")

    # --- setup ---
    p_setup = sub.add_parser(
        "setup",
        help="环境检测与安装向导",
        description="默认进入交互式安装向导；使用 `check` 子命令仅做环境诊断。",
    )
    p_setup.set_defaults(func=cmd_setup)
    p_setup_sub = p_setup.add_subparsers(dest="setup_action")
    p_setup_check = p_setup_sub.add_parser("check", help="检查环境状态")
    p_setup_check.add_argument("--lang", choices=["en", "zh"], default="zh", help="输出语言（zh 或 en，默认 zh）")

    # --- backup ---
    p_backup = sub.add_parser("backup", help="rsync 增量备份", description="rsync 增量备份")
    p_backup.set_defaults(func=cmd_backup)
    p_backup_sub = p_backup.add_subparsers(dest="backup_action", required=True)

    p_backup_list = p_backup_sub.add_parser("list", help="列出已配置的备份目标")
    del p_backup_list  # no extra args needed

    p_backup_run = p_backup_sub.add_parser("run", help="执行指定备份目标")
    p_backup_run.add_argument("target", help="备份目标名称（来自 config backup.targets）")
    p_backup_run.add_argument("--dry-run", action="store_true", help="预演模式，只展示 rsync 计划而不实际传输")

    # --- fsearch ---
    p_fsearch = sub.add_parser("fsearch", help="联邦搜索：同时搜索主库、proceedings、explore 库和 arXiv")
    p_fsearch.set_defaults(func=cmd_fsearch)
    p_fsearch.add_argument("query", nargs="+", help="检索词")
    p_fsearch.add_argument(
        "--scope",
        type=str,
        default="main",
        help="搜索范围（逗号分隔）：main / proceedings / explore:NAME / explore:* / arxiv（默认 main）",
    )
    _add_result_limit_arg(p_fsearch, "每个来源最多返回 N 条（默认 10）")

    # --- proceedings ---
    p_proc = sub.add_parser("proceedings", help="论文集辅助命令（apply-split 等）")
    p_proc.set_defaults(func=cmd_proceedings)
    p_proc_sub = p_proc.add_subparsers(dest="proceedings_action", required=True)

    p_proc_apply = p_proc_sub.add_parser("apply-split", help="对已准备好的 proceedings 应用 split_plan.json")
    p_proc_apply.add_argument("proceeding_dir", help="proceedings 目录路径")
    p_proc_apply.add_argument("split_plan", help="split_plan.json 路径")

    p_proc_clean_candidates = p_proc_sub.add_parser(
        "build-clean-candidates", help="为已拆分的 proceedings 生成 clean_candidates.json"
    )
    p_proc_clean_candidates.add_argument("proceeding_dir", help="proceedings 目录路径")

    p_proc_apply_clean = p_proc_sub.add_parser("apply-clean", help="对已拆分的 proceedings 应用 clean_plan.json")
    p_proc_apply_clean.add_argument("proceeding_dir", help="proceedings 目录路径")
    p_proc_apply_clean.add_argument("clean_plan", help="clean_plan.json 路径")

    # --- arxiv ---
    p_arxiv = sub.add_parser("arxiv", help="arXiv 检索与拉取工具")
    p_arxiv_sub = p_arxiv.add_subparsers(dest="arxiv_action", required=True)

    p_arxiv_search = p_arxiv_sub.add_parser("search", help="搜索 arXiv 预印本")
    p_arxiv_search.set_defaults(func=cmd_arxiv_search)
    p_arxiv_search.add_argument("query", nargs="*", help="检索词（可省略，配合 --category 使用）")
    _add_result_limit_arg(p_arxiv_search, "最多返回 N 条（默认 10）")
    p_arxiv_search.add_argument("--category", type=str, default="", help="arXiv 分类，如 physics.flu-dyn")
    p_arxiv_search.add_argument(
        "--sort", choices=["relevance", "recent"], default="relevance", help="排序方式（默认 relevance）"
    )

    p_arxiv_fetch = p_arxiv_sub.add_parser("fetch", help="下载 arXiv PDF，可选直接入库")
    p_arxiv_fetch.set_defaults(func=cmd_arxiv_fetch)
    p_arxiv_fetch.add_argument("arxiv_ref", help="arXiv ID、arXiv:ID、abs URL 或 pdf URL")
    p_arxiv_fetch.add_argument("--ingest", action="store_true", help="下载后直接走 ingest pipeline 入库")
    p_arxiv_fetch.add_argument("--force", action="store_true", help="覆盖已有同名 PDF 或强制 pipeline 处理")
    p_arxiv_fetch.add_argument("--dry-run", action="store_true", help="预览将要执行的操作")

    # --- websearch ---
    p_web = sub.add_parser("websearch", help="实时网页搜索 (Bing via GUILessBingSearch)")
    p_web.set_defaults(func=cmd_websearch)
    p_web.add_argument("query", nargs="+", help="搜索查询词")
    p_web.add_argument("--count", type=int, default=10, help="返回结果数量（默认 10）")

    # --- webextract ---
    p_wext = sub.add_parser("webextract", help="网页内容提取 (qt-web-extractor)")
    p_wext.set_defaults(func=cmd_webextract)
    p_wext.add_argument("url", help="要提取的网页 URL")
    p_wext.add_argument("--pdf", action="store_true", help="目标为 PDF 文件")
    p_wext.add_argument("--full", action="store_true", help="输出完整提取结果，不截断")
    p_wext.add_argument("--max-chars", type=int, default=4000, help="预览模式最大输出字符数（默认 4000）")

    # --- ingest-link ---
    p_ingest_link = sub.add_parser("ingest-link", help="抓取渲染后的网页/在线 PDF，并按文档流程直接入库")
    p_ingest_link.set_defaults(func=cmd_ingest_link)
    p_ingest_link.add_argument("urls", nargs="+", help="一个或多个网页/在线 PDF URL")
    p_ingest_link.add_argument("--dry-run", action="store_true", help="预览将要执行的操作")
    p_ingest_link.add_argument("--force", action="store_true", help="强制重新处理生成的文档")
    p_ingest_link.add_argument("--pdf", action="store_true", help="仅在自动识别不稳时，提示 webextract 按 PDF 模式抓取")
    p_ingest_link.add_argument("--no-index", action="store_true", help="仅入库，不执行 embed/index")
    p_ingest_link.add_argument("--json", action="store_true", help="输出抓取结果摘要 JSON")

    # --- insights ---
    p_insights = sub.add_parser("insights", help="研究行为分析：搜索热词、最常阅读论文等")
    p_insights.set_defaults(func=cmd_insights)
    p_insights.add_argument("--days", type=int, default=30, help="分析最近 N 天的数据（默认 30）")

    # --- metrics ---
    p_metrics = sub.add_parser("metrics", help="查看 LLM token 用量和调用统计")
    p_metrics.set_defaults(func=cmd_metrics)
    p_metrics.add_argument("--last", type=int, default=20, help="最近 N 条记录")
    p_metrics.add_argument("--category", default="llm", help="事件类别（llm/api/step，默认 llm）")
    p_metrics.add_argument("--since", default=None, help="起始时间（ISO 格式，如 2026-03-01）")
    p_metrics.add_argument("--summary", action="store_true", help="仅显示汇总统计")

    # --- style ---
    p_style = sub.add_parser("style", help="引用格式管理（列出 / 查看自定义格式）")
    p_style.set_defaults(func=cmd_style)
    p_style_sub = p_style.add_subparsers(dest="style_sub", required=True)

    p_style_list = p_style_sub.add_parser("list", help="列出所有可用引用格式")
    del p_style_list  # no extra args needed

    p_style_show = p_style_sub.add_parser("show", help="查看引用格式的格式化函数代码")
    p_style_show.add_argument("name", help="格式名称，如 jcp / apa / vancouver")

    # --- document ---
    p_doc = sub.add_parser("document", help="Office 文档工具（inspect 等）")
    p_doc.set_defaults(func=cmd_document)
    p_doc_sub = p_doc.add_subparsers(dest="doc_action", required=True)

    p_doc_inspect = p_doc_sub.add_parser("inspect", help="检查 Office 文档结构（DOCX / PPTX / XLSX）")
    p_doc_inspect.add_argument("file", help="文件路径")
    p_doc_inspect.add_argument(
        "--format",
        choices=["docx", "pptx", "xlsx"],
        default=None,
        help="文件格式（默认从扩展名推断）",
    )

    # --- diagram ---
    p_diagram = sub.add_parser("diagram", help="论文 → 可编辑科研图表（DOT/SVG / drawio XML / Mermaid）")
    p_diagram.set_defaults(func=cmd_diagram)
    p_diagram.add_argument("paper_id", nargs="?", help="论文 ID（目录名 / UUID / DOI）；与 --from-ir 二选一")
    p_diagram.add_argument(
        "--type",
        choices=["model_arch", "tech_route", "exp_setup"],
        default="model_arch",
        help="图表类型（默认 model_arch）",
    )
    p_diagram.add_argument(
        "--format",
        choices=["svg", "drawio", "dot", "mermaid"],
        default="svg",
        help="输出格式（默认 svg）",
    )
    p_diagram.add_argument(
        "--dump-ir",
        action="store_true",
        help="仅提取并保存 IR（JSON），不渲染",
    )
    p_diagram.add_argument(
        "--from-ir",
        type=str,
        default=None,
        help="从已有的 IR JSON 文件直接渲染（与 paper_id / --from-text 三选一）",
    )
    p_diagram.add_argument(
        "--from-text",
        type=str,
        default=None,
        help="从文字描述直接生成图表（与 paper_id / --from-ir 三选一）",
    )
    p_diagram.add_argument(
        "-o",
        "--output",
        type=str,
        default=None,
        help="输出目录（默认 workspace/figures/）",
    )
    p_diagram.add_argument(
        "--critic",
        action="store_true",
        help="启用 Critic-Agent 闭环迭代自审（参考 PaperVizAgent 的 Critic-Visualizer loop）",
    )
    p_diagram.add_argument(
        "--critic-rounds",
        type=int,
        default=3,
        help="Critic 最大迭代轮次（默认 3，仅 --critic 时生效）",
    )

    # --- enrich-l3 ---
    p_l3 = sub.add_parser("enrich-l3", help="LLM 提取结论段写入 JSON")
    p_l3.set_defaults(func=cmd_enrich_l3)
    p_l3.add_argument("paper_id", nargs="?", help="论文 ID（省略则需 --all）")
    p_l3.add_argument("--all", action="store_true", help="处理 papers_dir 中所有论文")
    p_l3.add_argument("--force", action="store_true", help="强制重新提取（覆盖已有结果）")
    p_l3.add_argument("--inspect", action="store_true", help="展示提取过程详情")
    p_l3.add_argument("--max-retries", type=int, default=2, help="最大重试次数（默认 2）")

    # --- toolref ---
    p_tr = sub.add_parser("toolref", help="科学计算工具文档查阅（fetch/show/search/list/use）")
    p_tr.set_defaults(func=cmd_toolref)
    p_tr_sub = p_tr.add_subparsers(dest="toolref_action", required=True)

    p_trf = p_tr_sub.add_parser("fetch", help="拉取工具文档（git clone → 提取 → 索引）")
    p_trf.add_argument("tool", help="工具名（qe/lammps/gromacs/openfoam/bioinformatics）")
    p_trf.add_argument("--version", default=None, help="版本号（如 7.5, 22Jul2025_update3）")
    p_trf.add_argument("--force", action="store_true", help="强制重新拉取并覆盖本地缓存")

    p_trs = p_tr_sub.add_parser("show", help="查看指定命令/参数的文档")
    p_trs.add_argument("tool", help="工具名")
    p_trs.add_argument("path", nargs="+", help="查找路径（如 pw ecutwfc）")

    p_trq = p_tr_sub.add_parser("search", help="全文搜索工具文档")
    p_trq.add_argument("tool", help="工具名")
    p_trq.add_argument("query", nargs="+", help="搜索关键词")
    _add_result_limit_arg(p_trq, "返回条数（默认 20）")
    p_trq.add_argument("--program", default=None, help="按程序过滤（如 pw.x）")
    p_trq.add_argument("--section", default=None, help="按 namelist/section 过滤（如 SYSTEM）")

    p_trl = p_tr_sub.add_parser("list", help="列出已有工具文档及版本")
    p_trl.add_argument("tool", nargs="?", default=None, help="工具名（省略列出全部）")

    p_tru = p_tr_sub.add_parser("use", help="切换工具文档的当前活跃版本")
    p_tru.add_argument("tool", help="工具名")
    p_tru.add_argument("version", help="目标版本号")

    # --- translate ---
    p_trans = sub.add_parser("translate", help="翻译论文 Markdown 到目标语言")
    p_trans.set_defaults(func=cmd_translate)
    p_trans.add_argument("paper_id", nargs="?", help="论文 ID（省略则需 --all）")
    p_trans.add_argument("--all", action="store_true", help="批量翻译所有论文")
    p_trans.add_argument("--lang", type=str, default=None, help="目标语言（默认读 config translate.target_lang）")
    p_trans.add_argument("--force", action="store_true", help="强制重新翻译（覆盖已有翻译）")
    p_trans.add_argument(
        "--portable",
        action="store_true",
        help="额外导出到 workspace/translation-ws/ 的可移植翻译包（复制 images/）",
    )

    return parser


def main() -> None:
    parser = _build_parser()

    args = parser.parse_args()
    cfg = load_config()
    cfg.ensure_dirs()

    from scholaraio import log as _log
    from scholaraio import metrics as _metrics
    from scholaraio.ingest.metadata._models import configure_s2_session, configure_session

    session_id = _log.setup(cfg)
    is_setup_cmd = args.command == "setup"
    try:
        _metrics.init(cfg.metrics_db_path, session_id)
    except Exception as exc:
        if not is_setup_cmd:
            raise
        ui(f"警告：metrics 初始化失败，已跳过，不影响 setup: {exc}")
    configure_session(cfg.ingest.contact_email)
    configure_s2_session(cfg.resolved_s2_api_key())

    args.func(args, cfg)


if __name__ == "__main__":
    main()
