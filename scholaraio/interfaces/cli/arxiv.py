"""arXiv CLI command handlers."""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

import scholaraio.interfaces.cli.arguments as _dep_arguments
import scholaraio.interfaces.cli.paths as _dep_paths


def _ui(msg: str = "") -> None:
    from scholaraio.core import log

    log.ui(msg)


def _resolve_top(args: argparse.Namespace, default: int) -> int:
    return _dep_arguments._resolve_top(args, default)


def _default_inbox_dir(cfg) -> Path:
    return _dep_paths._default_inbox_dir(cfg)


def cmd_arxiv_search(args: argparse.Namespace, cfg) -> None:
    from scholaraio.providers.arxiv import search_arxiv

    query = " ".join(args.query).strip()
    top_k = _resolve_top(args, 10)
    category = (args.category or "").strip()
    sort = args.sort or "relevance"

    if not query and not category:
        _ui("Provide search terms, or specify an arXiv category with --category.")
        return

    _ui(f'arXiv search: query="{query or "*"}" category={category or "-"} sort={sort}\n')

    try:
        results = search_arxiv(query, top_k=top_k, category=category, sort=sort)
    except Exception as e:
        _ui(f"arXiv search failed: {e}")
        return
    if not results:
        _ui("arXiv is unavailable or returned no results")
        return

    for i, r in enumerate(results, 1):
        authors = r.get("authors", [])
        first = (authors[0] if authors else "?") + (" et al." if len(authors) > 1 else "")
        _ui(f"  [{i}] [{r.get('year', '?')}] {r.get('title', '')}")
        _ui(f"       {first} | arxiv:{r.get('arxiv_id', '')}")
        if r.get("doi"):
            _ui(f"       doi:{r['doi']}")
        if r.get("abstract"):
            _ui(f"       {r['abstract'][:220]}{'...' if len(r['abstract']) > 220 else ''}")
        _ui()


def cmd_arxiv_fetch(args: argparse.Namespace, cfg) -> None:
    from scholaraio.providers.arxiv import download_arxiv_pdf, normalize_arxiv_ref
    from scholaraio.services.ingest.pipeline import PRESETS, run_pipeline

    canonical_id = normalize_arxiv_ref(args.arxiv_ref)
    if not canonical_id:
        _ui(f"Invalid arXiv identifier or URL: {args.arxiv_ref}")
        return

    if args.dry_run:
        if args.ingest:
            _ui(f"[dry-run] Will download arXiv PDF and ingest it: {canonical_id}")
        else:
            _ui(f"[dry-run] Will download arXiv PDF to inbox: {canonical_id}")
        return

    if args.ingest:
        _ui(f"Start ingesting arXiv preprint: {canonical_id}")
        try:
            with tempfile.TemporaryDirectory(prefix="scholaraio_arxiv_") as tmpdir:
                tmp_inbox = Path(tmpdir)
                pdf_path = download_arxiv_pdf(canonical_id, tmp_inbox, overwrite=args.force)
                _ui(f"Downloaded PDF: {pdf_path.name}")
                run_pipeline(
                    PRESETS["ingest"],
                    cfg,
                    {"inbox_dir": tmp_inbox, "force": args.force, "include_aux_inboxes": False},
                )
        except Exception as e:
            _ui(f"arXiv download or ingest failed: {e}")
        return

    inbox_dir = _default_inbox_dir(cfg)
    try:
        pdf_path = download_arxiv_pdf(canonical_id, inbox_dir, overwrite=args.force)
    except Exception as e:
        _ui(f"arXiv download failed: {e}")
        return
    _ui(f"Downloaded to inbox: {pdf_path}")
