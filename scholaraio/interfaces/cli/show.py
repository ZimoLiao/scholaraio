"""Show CLI command handler."""

from __future__ import annotations

import argparse
import logging
import sys

import scholaraio.interfaces.cli.paper as _dep_paper


def _ui(msg: str = "") -> None:
    from scholaraio.core import log

    log.ui(msg)


def _log_error(msg: str, *args) -> None:
    logging.getLogger(__name__).error(msg, *args)


def _log_warning(msg: str, *args) -> None:
    logging.getLogger(__name__).warning(msg, *args)


def _log_debug(msg: str, *args) -> None:
    logging.getLogger(__name__).debug(msg, *args)


def _resolve_paper(paper_id: str, cfg):
    return _dep_paper._resolve_paper(paper_id, cfg)


def _enrich_show_header(l1: dict, *, paper_d, requested_id: str, cfg) -> dict:
    return _dep_paper._enrich_show_header(l1, paper_d=paper_d, requested_id=requested_id, cfg=cfg)


def _print_header(l1: dict) -> None:
    _dep_paper._print_header(l1)


def cmd_show(args: argparse.Namespace, cfg) -> None:
    from scholaraio.services.loader import append_notes, load_l1, load_l2, load_l3, load_l4, load_notes
    from scholaraio.services.metrics import get_store

    paper_d = _resolve_paper(args.paper_id, cfg)
    json_path = paper_d / "meta.json"
    md_path = paper_d / "paper.md"

    if getattr(args, "append_notes", None):
        notes_text = str(args.append_notes).strip()
        if not notes_text:
            _ui("Warning: --append-notes is empty; ignored.")
        else:
            try:
                append_notes(paper_d, notes_text)
            except (UnicodeDecodeError, OSError) as e:
                _log_error("Append notes failed: %s", e)
                _ui(f"Append notes to {paper_d.name}/notes.md failed: {e}")
            else:
                _ui(f"Appended notes to {paper_d.name}/notes.md")

    l1 = _enrich_show_header(load_l1(json_path), paper_d=paper_d, requested_id=args.paper_id, cfg=cfg)
    _print_header(l1)

    try:
        notes = load_notes(paper_d)
    except (UnicodeDecodeError, OSError) as e:
        _log_warning("Read notes.md failed: %s", e)
        notes = None
    if notes:
        _ui("\n--- Agent notes (notes.md) ---\n")
        _ui(notes)
        _ui("\n--- End notes ---\n")

    store = get_store()

    def _record_read() -> None:
        if store:
            try:
                store.record(
                    category="read",
                    name=paper_d.name,
                    detail={
                        "layer": args.layer,
                        "title": l1.get("title", ""),
                        "doi": l1.get("doi", ""),
                    },
                )
            except Exception as e:
                _log_debug("metrics record failed: %s", e)

    if args.layer == 1:
        _record_read()
        return

    if args.layer == 2:
        abstract = load_l2(json_path)
        _ui("\n--- abstracts ---\n")
        _ui(abstract)
        _record_read()
        return

    if args.layer == 3:
        conclusion = load_l3(json_path)
        if conclusion is None:
            _log_error("Conclusion has not been extracted. Run first: scholaraio enrich-l3 %s", args.paper_id)
            sys.exit(1)
        _ui("\n--- conclusion ---\n")
        _ui(conclusion)
        _record_read()
        return

    if args.layer == 4:
        if not md_path.exists():
            _log_error("No paper.md: %s", md_path)
            sys.exit(1)
        lang = getattr(args, "lang", None)
        if lang:
            from scholaraio.services.translate import validate_lang

            try:
                lang = validate_lang(lang)
            except ValueError:
                _ui(f"Error: Invalid language code '{lang}'")
                sys.exit(1)
            translated_path = md_path.parent / f"paper_{lang}.md"
            if translated_path.exists():
                _ui(f"\n--- Full text ({lang}) ---\n")
            else:
                _ui(f"\n--- Full text (source, paper_{lang}.md does not exist) ---\n")
        else:
            _ui("\n--- Full text ---\n")
        _ui(load_l4(md_path, lang=lang))
        _record_read()
        return
