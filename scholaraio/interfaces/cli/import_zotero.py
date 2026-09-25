"""Zotero import CLI command handler."""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import scholaraio.interfaces.cli.attach_pdf as _dep_attach_pdf
import scholaraio.interfaces.cli.dependencies as _dep_dependencies
import scholaraio.interfaces.cli.paths as _dep_paths


def _ui(msg: str = "") -> None:
    from scholaraio.core import log

    log.ui(msg)


def _check_import_error(exc: ImportError) -> None:
    _dep_dependencies._check_import_error(exc)


def _batch_convert_pdfs(cfg, *, enrich: bool = False) -> None:
    _dep_attach_pdf._batch_convert_pdfs(cfg, enrich=enrich)


def _workspace_root(cfg) -> Path:
    return _dep_paths._workspace_root(cfg)


def cmd_import_zotero(args: argparse.Namespace, cfg) -> None:
    api_key = args.api_key or cfg.resolved_zotero_api_key()
    library_id = args.library_id or cfg.resolved_zotero_library_id()
    library_type = args.library_type or cfg.zotero.library_type

    if args.local:
        db_path = Path(args.local)
        if not db_path.exists():
            _ui(f"Error: Zotero database does not exist: {db_path}")
            sys.exit(1)

        from scholaraio.providers.zotero import list_collections_local, parse_zotero_local

        if args.list_collections:
            collections = list_collections_local(db_path)
            if not collections:
                _ui("No collections found")
                return
            _ui(f"{'Key':<12} {'Items':>5}  Name")
            _ui("-" * 50)
            for c in collections:
                _ui(f"{c['key']:<12} {c['numItems']:>5}  {c['name']}")
            return

        records, pdf_paths = parse_zotero_local(
            db_path,
            collection_key=args.collection,
            item_types=args.item_type,
        )
    else:
        if not api_key:
            _ui("Error: Zotero API key is required (--api-key, config.local.yaml zotero.api_key, or ZOTERO_API_KEY)")
            sys.exit(1)
        if not library_id:
            _ui(
                "Error: Zotero library ID is required (--library-id, config.local.yaml zotero.library_id, or ZOTERO_LIBRARY_ID)"
            )
            sys.exit(1)

        try:
            from scholaraio.providers.zotero import fetch_zotero_api, list_collections_api
        except ImportError as e:
            _check_import_error(e)

        if args.list_collections:
            collections = list_collections_api(library_id, api_key, library_type=library_type)
            if not collections:
                _ui("No collections found")
                return
            _ui(f"{'Key':<12} {'Items':>5}  Name")
            _ui("-" * 50)
            for c in collections:
                _ui(f"{c['key']:<12} {c['numItems']:>5}  {c['name']}")
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
        _ui("No records fetched")
        return

    n_pdfs = sum(1 for p in pdf_paths if p is not None)
    if n_pdfs:
        _ui(f"Fetched {len(records)} records, {n_pdfs} PDFs")
    else:
        _ui(f"Fetched {len(records)} records")

    from scholaraio.services.ingest.pipeline import import_external

    stats = import_external(
        records,
        cfg,
        pdf_paths=pdf_paths,
        no_api=args.no_api,
        dry_run=args.dry_run,
    )

    if not args.dry_run and not args.no_convert and stats["ingested"] > 0:
        _batch_convert_pdfs(cfg, enrich=True)

    if args.import_collections and not args.dry_run:
        _import_zotero_collections_as_workspaces(args, cfg, api_key, library_id, library_type)


def _import_zotero_collections_as_workspaces(args, cfg, api_key, library_id, library_type):
    """Create workspaces from Zotero collections after import."""

    from scholaraio.projects import workspace
    from scholaraio.stores.papers import iter_paper_dirs

    if args.local:
        from scholaraio.providers.zotero import list_collections_local, parse_zotero_local

        collections = list_collections_local(Path(args.local))
    else:
        from scholaraio.providers.zotero import list_collections_api

        collections = list_collections_api(library_id, api_key, library_type=library_type)

    from scholaraio.stores.papers import read_meta

    doi_to_uuid: dict[str, str] = {}
    for pdir in iter_paper_dirs(cfg.papers_dir):
        try:
            meta = read_meta(pdir)
        except (ValueError, FileNotFoundError):
            continue
        if meta.get("doi") and meta.get("id"):
            doi_to_uuid[meta["doi"].lower()] = meta["id"]

    ws_root = _workspace_root(cfg)
    for coll in collections:
        name = coll["name"].replace("/", "-").replace(" ", "_")
        ws_dir = ws_root / name

        if args.local:
            coll_records, _ = parse_zotero_local(
                Path(args.local),
                collection_key=coll["key"],
            )
        else:
            from scholaraio.providers.zotero import fetch_zotero_api

            coll_records, _ = fetch_zotero_api(
                library_id,
                api_key,
                library_type=library_type,
                collection_key=coll["key"],
                download_pdfs=False,
            )

        uuids = []
        for r in coll_records:
            if r.doi and r.doi.lower() in doi_to_uuid:
                uuids.append(doi_to_uuid[r.doi.lower()])

        if not uuids:
            continue

        workspace.create(ws_dir)
        workspace.add(ws_dir, uuids, cfg.index_db)
        _ui(f"workspace {name}: {len(uuids)} papers")
