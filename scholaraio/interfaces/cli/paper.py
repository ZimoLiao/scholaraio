"""Shared CLI paper resolution and display helpers."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from scholaraio.interfaces.cli.output import _format_citations as _default_format_citations

_log = logging.getLogger(__name__)


def _ui(message: str = "") -> None:
    from scholaraio.core import log

    log.ui(message)


def _lookup_registry_by_candidates(cfg, *candidates: object) -> dict | None:
    """Try registry lookups in order and return the first match."""
    from scholaraio.services.index import lookup_paper

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
    """Resolve a paper identifier (dir_name, UUID, or DOI) to its directory."""
    from scholaraio.stores.papers import iter_paper_dirs

    papers_dir = cfg.papers_dir
    # 1. Direct dir_name match on filesystem.
    paper_d = papers_dir / paper_id
    if (paper_d / "meta.json").exists():
        return paper_d
    # 2. Registry lookup (fast, but may be stale).
    from scholaraio.services.index import lookup_paper

    reg = lookup_paper(cfg.index_db, paper_id)
    if reg:
        paper_d = papers_dir / reg["dir_name"]
        if (paper_d / "meta.json").exists():
            return paper_d
    # 3. Filesystem scan fallback (handles stale registry / pre-index state).
    from scholaraio.stores.papers import read_meta as _read_meta

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
    _log.error("Paper not found: %s", paper_id)
    sys.exit(1)


def _print_header(l1: dict) -> None:
    authors = l1.get("authors") or []
    author_str = ", ".join(authors[:3])
    if len(authors) > 3:
        author_str += f" et al. ({len(authors)} total)"
    _ui(f"Paper ID   : {l1['paper_id']}")
    if l1.get("dir_name") and l1["dir_name"] != l1["paper_id"]:
        _ui(f"Directory   : {l1['dir_name']}")
    _ui(f"Title     : {l1['title']}")
    _ui(f"Author     : {author_str}")
    _ui(f"Year     : {l1.get('year') or '?'}  |  Journal: {l1.get('journal') or '?'}")
    if l1.get("doi"):
        _ui(f"DOI      : {l1['doi']}")
    ids = l1.get("ids") or {}
    if ids.get("patent_publication_number"):
        _ui(f"Publication number   : {ids['patent_publication_number']}")
    if l1.get("paper_type"):
        _ui(f"Type     : {l1['paper_type']}")
    format_citations = _default_format_citations
    cite_str = format_citations(l1.get("citation_count") or {})
    if cite_str:
        _ui(f"Citations     : {cite_str}")
    if ids.get("semantic_scholar_url"):
        _ui(f"S2       : {ids['semantic_scholar_url']}")
    if ids.get("openalex_url"):
        _ui(f"OpenAlex : {ids['openalex_url']}")


def _enrich_show_header(l1: dict, *, paper_d: Path, requested_id: str, cfg) -> dict:
    enriched = dict(l1)
    enriched["dir_name"] = paper_d.name
    current_paper_id = str(enriched.get("paper_id") or "").strip()
    lookup_registry = _lookup_registry_by_candidates
    reg = lookup_registry(
        cfg,
        requested_id if requested_id != paper_d.name else "",
        enriched.get("doi") or "",
        paper_d.name if not current_paper_id or current_paper_id == paper_d.name else "",
    )
    if reg and reg.get("id"):
        enriched["paper_id"] = str(reg["id"])
    return enriched
