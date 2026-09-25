"""Citation graph CLI command handlers."""

from __future__ import annotations

import argparse

import scholaraio.interfaces.cli.paper as _dep_paper
import scholaraio.interfaces.cli.paths as _dep_paths


def _ui(msg: str = "") -> None:
    from scholaraio.core import log

    log.ui(msg)


def _resolve_paper(paper_id: str, cfg):
    return _dep_paper._resolve_paper(paper_id, cfg)


def _resolve_ws_paper_ids(args: argparse.Namespace, cfg) -> set[str] | None:
    return _dep_paths._resolve_ws_paper_ids(args, cfg)


def cmd_refs(args: argparse.Namespace, cfg) -> None:
    from scholaraio.services.index import get_references
    from scholaraio.stores.papers import read_meta

    paper_d = _resolve_paper(args.paper_id, cfg)
    meta = read_meta(paper_d)
    paper_uuid = meta.get("id", "")

    pids = _resolve_ws_paper_ids(args, cfg)
    refs = get_references(paper_uuid, cfg.index_db, paper_ids=pids)
    if not refs:
        _ui("This paper has no reference data. Run `scholaraio refetch` first.")
        return

    in_lib = [r for r in refs if r.get("target_id")]
    out_lib = [r for r in refs if not r.get("target_id")]

    scope = f"workspace {args.ws}" if getattr(args, "ws", None) else "in-library"
    _ui(f"References: total {len(refs)} papers ({scope} {len(in_lib)} papers, outside-library {len(out_lib)} papers)\n")

    if in_lib:
        _ui("── in-library ──")
        for i, r in enumerate(in_lib, 1):
            display = r.get("dir_name") or r["target_id"]
            year = r.get("year") or "?"
            author = r.get("first_author") or "?"
            _ui(f"[{i}] {display}")
            _ui(f"     {author} | {year} | {r.get('title', '?')}")
            _ui(f"     DOI: {r['target_doi']}")
            _ui()

    if out_lib:
        _ui("── outside-library ──")
        for i, r in enumerate(out_lib, 1):
            _ui(f"[{i}] DOI: {r['target_doi']}")
        _ui()


def cmd_citing(args: argparse.Namespace, cfg) -> None:
    from scholaraio.services.index import get_citing_papers
    from scholaraio.stores.papers import read_meta

    paper_d = _resolve_paper(args.paper_id, cfg)
    meta = read_meta(paper_d)
    paper_uuid = meta.get("id", "")

    pids = _resolve_ws_paper_ids(args, cfg)
    results = get_citing_papers(paper_uuid, cfg.index_db, paper_ids=pids)
    if not results:
        scope = f"in workspace {args.ws}" if getattr(args, "ws", None) else "in the local library"
        _ui(f"No papers that cite this paper were found {scope}.")
        return

    scope = f"workspace {args.ws}" if getattr(args, "ws", None) else "local"
    _ui(f"Total {len(results)} {scope} papers cite this paper:\n")
    for i, r in enumerate(results, 1):
        display = r.get("dir_name") or r["source_id"]
        year = r.get("year") or "?"
        author = r.get("first_author") or "?"
        _ui(f"[{i}] {display}")
        _ui(f"     {author} | {year} | {r.get('title', '?')}")
        _ui()


def cmd_shared_refs(args: argparse.Namespace, cfg) -> None:
    from scholaraio.services.index import get_shared_references
    from scholaraio.stores.papers import read_meta

    paper_uuids = []
    for pid in args.paper_ids:
        paper_d = _resolve_paper(pid, cfg)
        meta = read_meta(paper_d)
        paper_uuids.append(meta.get("id", ""))

    min_shared = args.min if args.min is not None else 2
    pids = _resolve_ws_paper_ids(args, cfg)
    results = get_shared_references(paper_uuids, cfg.index_db, min_shared=min_shared, paper_ids=pids)
    if not results:
        _ui(f"No references are shared by at least {min_shared} papers.")
        return

    _ui(f"Shared references (cited by >={min_shared} papers): total {len(results)} papers\n")
    for i, r in enumerate(results, 1):
        count = r["shared_count"]
        if r.get("target_id"):
            display = r.get("dir_name") or r["target_id"]
            year = r.get("year") or "?"
            _ui(f"[{i}] [{count}x] {display}")
            _ui(f"     {r.get('title', '?')} | {year}")
            _ui(f"     DOI: {r['target_doi']}")
        else:
            _ui(f"[{i}] [{count}x] DOI: {r['target_doi']}")
        _ui()
