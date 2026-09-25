"""Patent fetch and search CLI command handlers."""

from __future__ import annotations

import argparse
import sys


def _ui(msg: str = "") -> None:
    from scholaraio.core import log

    log.ui(msg)


def cmd_patent_fetch(args: argparse.Namespace, cfg) -> None:
    """Download patent PDFs to inbox-patent."""
    from scholaraio.services import patent_fetch

    id_or_url = args.id_or_url
    path = patent_fetch.download_patent_pdf(id_or_url, cfg=cfg)
    if path is None:
        sys.exit(1)
    _ui(f"Saved to: {path}")


def cmd_patent_search(args: argparse.Namespace, cfg) -> None:
    """USPTO patent search."""
    from scholaraio.providers import uspto_odp, uspto_ppubs
    from scholaraio.services import patent_fetch

    query = " ".join(args.query) if args.query else None
    app_number = args.application
    count = args.count
    offset = args.offset
    source = getattr(args, "source", "ppubs")
    fetch = getattr(args, "fetch", False)

    # Application number lookup mode
    if app_number:
        if source == "ppubs":
            _ui("Use --source odp for exact application-number lookup; USPTO ODP API key is required.")
            sys.exit(1)
        try:
            result = uspto_odp.get_patent_by_application_number(app_number, cfg=cfg)
        except uspto_odp.USPTOAPIError as e:
            _ui(f"Query failed: {e}")
            sys.exit(1)

        if not result:
            _ui(f"No patent found for application number: {app_number}")
            sys.exit(1)

        _ui(f"Application: {result.application_number}")
        _ui(f"  Title: {result.title}")
        if result.inventors:
            _ui(f"  Inventors: {', '.join(result.inventors[:5])}")
        if result.publication_number:
            _ui(f"  Publication: {result.publication_number}")
        if result.patent_number:
            _ui(f"  Patent Number: US{result.patent_number}")
        if result.filing_date:
            _ui(f"  Filing Date: {result.filing_date}")
        if result.grant_date:
            _ui(f"  Grant Date: {result.grant_date}")
        if result.application_status:
            _ui(f"  Status: {result.application_status}")
        if result.application_type:
            _ui(f"  Type: {result.application_type}")

        if fetch and result.publication_number:
            patent_fetch.download_patent_pdf(result.publication_number, cfg=cfg)
        return

    # Search mode
    if not query:
        _ui("Provide search terms or use --application <application number>")
        sys.exit(1)

    if source == "odp":
        try:
            results = uspto_odp.search_patents(query, limit=count, offset=offset, cfg=cfg)
        except uspto_odp.USPTOAPIError as e:
            _ui(f"Search failed: {e}")
            sys.exit(1)

        if not results:
            _ui(f"No patent results found for '{query}'.")
            return

        _ui(f"\nFound {len(results)} USPTO patent records")
        odp_to_fetch: list[str] = []
        for i, p in enumerate(results, 1):
            _ui(f"\n[{i}] {p.title}")
            _ui(f"    Application: {p.application_number}")
            if p.publication_number:
                _ui(f"    Publication: {p.publication_number}")
            if p.inventors:
                _ui(f"    Inventors: {', '.join(p.inventors[:3])}")
            if p.filing_date:
                _ui(f"    Filing: {p.filing_date}")
            if p.application_status:
                _ui(f"    Status: {p.application_status}")
            if p.publication_number:
                _ui(f"    download: scholaraio patent-fetch {p.publication_number}")
                if fetch:
                    odp_to_fetch.append(p.publication_number)

        if fetch and odp_to_fetch:
            _ui(f"\nStart downloading {len(odp_to_fetch)} patent PDFs...")
            for pub_num in odp_to_fetch:
                patent_fetch.download_patent_pdf(pub_num, cfg=cfg)
        return

    # Default: PPUBS (no auth)
    try:
        client = uspto_ppubs.PpubsClient()
        total, ppubs_results = client.search(query, start=offset, limit=count)
    except uspto_ppubs.PpubsError as e:
        _ui(f"Search failed: {e}")
        sys.exit(1)

    if not ppubs_results:
        _ui(f"No patent results found for '{query}'.")
        return

    _ui(f"\nFound {len(ppubs_results)} of {total} USPTO patent records")
    to_fetch: list[str] = []
    for i, ppub in enumerate(ppubs_results, 1):
        _ui(f"\n[{i}] {ppub.title}")
        if ppub.publication_number:
            _ui(f"    Publication: {ppub.publication_number}")
        if ppub.inventors:
            _ui(f"    Inventors: {', '.join(ppub.inventors[:3])}")
        if ppub.assignees:
            _ui(f"    Assignees: {', '.join(ppub.assignees[:2])}")
        if ppub.filing_date:
            _ui(f"    Filing: {ppub.filing_date}")
        if ppub.publication_date:
            _ui(f"    Published: {ppub.publication_date}")
        if ppub.patent_type:
            _ui(f"    Type: {ppub.patent_type}")
        if ppub.publication_number:
            _ui(f"    download: scholaraio patent-fetch {ppub.publication_number}")
            if fetch:
                to_fetch.append(ppub.publication_number)

    if fetch and to_fetch:
        _ui(f"\nStart downloading {len(to_fetch)} patent PDFs...")
        for pub_num in to_fetch:
            patent_fetch.download_patent_pdf(pub_num, cfg=cfg)
