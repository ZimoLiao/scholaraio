"""Tool reference CLI command handler."""

from __future__ import annotations

import argparse
import logging
import sys

import scholaraio.interfaces.cli.arguments as _dep_arguments


def _ui(msg: str = "") -> None:
    from scholaraio.core import log

    log.ui(msg)


def _log_error(msg: str, *args) -> None:
    logging.getLogger(__name__).error(msg, *args)


def _resolve_result_limit(args: argparse.Namespace, default: int) -> int:
    return _dep_arguments._resolve_result_limit(args, default)


def cmd_toolref(args: argparse.Namespace, cfg) -> None:
    from scholaraio.stores.toolref import (
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
                _ui("No pages indexed. Check the version or documentation source.")

        elif action == "show":
            results = toolref_show(args.tool, *args.path, cfg=cfg)
            if not results:
                _ui(f"No match found: {args.tool} {' '.join(args.path)}")
                _ui(f"Try searching: scholaraio toolref search {args.tool} {' '.join(args.path)}")
                return
            for r in results:
                _ui(f"\n{'=' * 60}")
                _ui(r["page_name"])
                if r.get("section"):
                    _ui(f"   section: {r['section']}  |  program: {r.get('program', '')}")
                if r.get("synopsis"):
                    _ui(f"   {r['synopsis']}")
                _ui(f"{'─' * 60}")
                _ui(r.get("content", "(no content)"))

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
                _ui(f"no results: {query}")
                return
            _ui(f"Found {len(results)} records:\n")
            for i, r in enumerate(results, 1):
                synopsis = r.get("synopsis", "")[:80]
                _ui(f"  {i:2d}. [{r['page_name']}] {synopsis}")

        elif action == "list":
            entries = toolref_list(args.tool, cfg=cfg)
            if not entries:
                tools = ", ".join(TOOL_REGISTRY.keys())
                _ui(f"No fetched documentation. Supported tools: {tools}")
                _ui("Use `scholaraio toolref fetch <tool> --version <ver>` to fetch documentation")
                return
            current_tool = ""
            for e in entries:
                if e["tool"] != current_tool:
                    current_tool = e["tool"]
                    _ui(f"\n{e['display_name']}:")
                marker = " (current)" if e["is_current"] else ""
                completeness = ""
                unit = "pages" if e.get("source_type") == "manifest" else "records"
                if e.get("source_type") == "manifest" and e.get("expected_pages"):
                    completeness = f" [{e['page_count']}/{e['expected_pages']} indexed"
                    failed_pages = e.get("failed_pages")
                    if failed_pages:
                        completeness += f", {failed_pages} failed"
                    completeness += "]"
                _ui(f"  {e['version']}{marker} — {e['page_count']} {unit}{completeness}")

        elif action == "use":
            toolref_use(args.tool, args.version, cfg=cfg)
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        _log_error("%s", e)
        sys.exit(1)
