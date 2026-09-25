"""Translate CLI command handler."""

from __future__ import annotations

import argparse
import sys

import scholaraio.interfaces.cli.paper as _dep_paper


def _ui(msg: str = "") -> None:
    from scholaraio.core import log

    log.ui(msg)


def _resolve_paper(paper_id: str, cfg):
    return _dep_paper._resolve_paper(paper_id, cfg)


def cmd_translate(args: argparse.Namespace, cfg) -> None:
    from scholaraio.services.translate import batch_translate, translate_paper

    ui = _ui
    papers_dir = cfg.papers_dir
    target_lang = (args.lang or cfg.translate.target_lang).lower().strip()

    try:
        from scholaraio.services.translate import validate_lang

        validate_lang(target_lang)
    except ValueError:
        ui(f"Error: Invalid language code '{target_lang}' (expected 2-5 lowercase letters, such as zh, en, ja)")
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
            ui(f"Translation completed: {tr.path}")
            if tr.portable_path:
                ui(f"Portable export: {tr.portable_path}")
        else:
            from scholaraio.services.translate import (
                SKIP_ALL_CHUNKS_FAILED,
                SKIP_ALREADY_EXISTS,
                SKIP_EMPTY,
                SKIP_NO_MD,
                SKIP_SAME_LANG,
            )

            _skip_messages = {
                SKIP_NO_MD: "skipped: this paper directory has no paper.md",
                SKIP_EMPTY: "Skipped: paper.md is empty",
                SKIP_SAME_LANG: f"Skipped: paper is already in the target language ({target_lang})",
                SKIP_ALREADY_EXISTS: "Skipped: translation already exists (use --force to retranslate)",
            }
            if tr.partial and tr.path:
                ui(
                    f"Translation interrupted: completed {tr.completed_chunks}/{tr.total_chunks} chunks, "
                    f"Current output was written to {tr.path}, you can resume later"
                )
                sys.exit(1)
            if tr.skip_reason == SKIP_ALL_CHUNKS_FAILED:
                ui("Translation failed: all chunks failed; no target file was written")
                sys.exit(1)
            ui(_skip_messages.get(tr.skip_reason, "skipped"))
    elif args.all:
        ui(f"Batch translation -> {target_lang}")
        stats = batch_translate(papers_dir, cfg, target_lang=target_lang, force=args.force, portable=args.portable)
        ui(f"Done: {stats['translated']} translated | {stats['skipped']} skipped | {stats['failed']} failed")
    else:
        ui("Specify <paper-id> or --all")
        sys.exit(1)
