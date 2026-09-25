"""Export CLI command handlers."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import scholaraio.interfaces.cli.paths as _dep_paths


def _ui(msg: str = "") -> None:
    from scholaraio.core import log

    log.ui(msg)


def _log_error(msg: str, *args) -> None:
    logging.getLogger(__name__).error(msg, *args)


def _workspace_root(cfg) -> Path:
    return _dep_paths._workspace_root(cfg)


def _default_docx_output_path(cfg) -> Path:
    return _dep_paths._default_docx_output_path(cfg)


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
        _log_error("Unknown export action: %s", action)
        sys.exit(1)


def _cmd_export_ris(args: argparse.Namespace, cfg) -> None:
    from scholaraio.services.export import export_ris

    paper_ids = args.paper_ids if args.paper_ids else None
    if not paper_ids and not args.all:
        _log_error("Specify paper IDs or --all")
        sys.exit(1)

    ris = export_ris(
        cfg.papers_dir,
        paper_ids=paper_ids,
        year=args.year,
        journal=args.journal,
    )

    if not ris:
        _ui("No matching papers found")
        return

    if args.output:
        out = Path(args.output)
        out.write_text(ris, encoding="utf-8")
        count = ris.count("TY  -")
        _ui(f"Exported to {out} ({count} papers)")
    else:
        print(ris)


def _cmd_export_markdown(args: argparse.Namespace, cfg) -> None:
    from scholaraio.services.export import export_markdown_refs

    paper_ids = args.paper_ids if args.paper_ids else None
    if not paper_ids and not args.all:
        _log_error("Specify paper IDs or --all")
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
        _log_error("%s", e)
        sys.exit(1)

    if not md:
        _ui("No matching papers found")
        return

    if args.output:
        out = Path(args.output)
        out.write_text(md, encoding="utf-8")
        count = md.count("\n")
        _ui(f"Exported to {out} ({count} citations, {style} style)")
    else:
        print(md)


def _cmd_export_docx(args: argparse.Namespace, cfg) -> None:
    from scholaraio.services.export import export_docx

    if args.input:
        input_path = Path(args.input)
        if not input_path.exists():
            _log_error("Input file does not exist: %s", args.input)
            sys.exit(1)
        content = input_path.read_text(encoding="utf-8")
    elif not sys.stdin.isatty():
        content = sys.stdin.read()
    else:
        _log_error("Specify a Markdown file with --input or pass content through stdin")
        sys.exit(1)

    output = Path(args.output) if args.output else _default_docx_output_path(cfg)

    try:
        export_docx(content, output, title=args.title or None)
        _ui(f"Exported to {output}")
    except ImportError as e:
        _log_error("%s", e)
        sys.exit(1)


def _cmd_export_bibtex(args: argparse.Namespace, cfg) -> None:
    from scholaraio.services.export import export_bibtex

    paper_ids = args.paper_ids if args.paper_ids else None
    if not paper_ids and not args.all:
        _log_error("Specify paper IDs or --all")
        sys.exit(1)

    bib = export_bibtex(
        cfg.papers_dir,
        paper_ids=paper_ids,
        year=args.year,
        journal=args.journal,
    )

    if not bib:
        _ui("No matching papers found")
        return

    if args.output:
        out = Path(args.output)
        out.write_text(bib, encoding="utf-8")
        _ui(f"Exported to {out} ({bib.count('@')} papers)")
    else:
        print(bib)
