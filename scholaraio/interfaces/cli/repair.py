"""Metadata repair CLI command handler."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path


def _ui(msg: str = "") -> None:
    try:
        from scholaraio.interfaces.cli import compat as cli_mod
    except ImportError:
        from scholaraio.core.log import ui as log_ui

        log_ui(msg)
        return
    cli_mod.ui(msg)


def _log_debug(msg: str, *args) -> None:
    try:
        from scholaraio.interfaces.cli import compat as cli_mod
    except ImportError:
        logging.getLogger(__name__).debug(msg, *args)
        return
    cli_mod._log.debug(msg, *args)


def _log_error(msg: str, *args) -> None:
    try:
        from scholaraio.interfaces.cli import compat as cli_mod
    except ImportError:
        logging.getLogger(__name__).error(msg, *args)
        return
    cli_mod._log.error(msg, *args)


def _lookup_registry_by_candidates(cfg, *candidates: object) -> dict | None:
    from scholaraio.interfaces.cli import compat as cli_mod

    return cli_mod._lookup_registry_by_candidates(cfg, *candidates)


def _resolve_paper(paper_id: str, cfg) -> Path:
    from scholaraio.interfaces.cli import compat as cli_mod

    return cli_mod._resolve_paper(paper_id, cfg)


def cmd_repair(args: argparse.Namespace, cfg) -> None:
    from scholaraio.services.ingest_metadata import (
        PaperMetadata,
        _extract_lastname,
        enrich_metadata,
        generate_new_stem,
        metadata_to_dict,
        rename_files,
    )
    from scholaraio.stores.papers import generate_uuid, write_meta

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
        _log_error("File does not exist: %s", md_path)
        sys.exit(1)

    # Preserve existing UUID
    existing_data: dict = {}
    existing_uuid = ""
    if json_path.exists():
        try:
            existing_data = json.loads(json_path.read_text(encoding="utf-8"))
            existing_uuid = str(existing_data.get("id") or "")
        except (json.JSONDecodeError, OSError) as e:
            _log_debug("failed to read existing meta.json: %s", e)
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

    _ui(f"Repair paper: {paper_id}")
    _ui(f"  Title: {meta.title}")
    _ui(f"  Author: {meta.first_author or '?'} | Year: {meta.year or '?'} | DOI: {meta.doi or 'none'}")

    # API enrichment
    if not args.no_api:
        _log_debug("querying APIs")
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
        _log_debug("skipping API query (--no-api)")

    _ui(f"  Result: {meta.first_author_lastname} ({meta.year}) {meta.title[:60]}")
    if meta.doi:
        _ui(f"  DOI: {meta.doi}")
    _ui(f"  Method: {meta.extraction_method}")

    if args.dry_run:
        _ui("  [dry-run] No files were written")
        return

    # Preserve existing enriched or custom top-level fields while updating metadata.
    new_data = dict(existing_data)
    new_data.update(metadata_to_dict(meta))
    write_meta(json_path.parent, new_data)
    _ui(f"  Wrote: {json_path.name}")

    new_stem = generate_new_stem(meta)
    rename_files(md_path, json_path, new_stem, dry_run=False, db_path=cfg.index_db)

    _log_debug("done. consider running pipeline reindex")
