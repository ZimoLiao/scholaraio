"""Paper2Any CLI handoff command."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_log = logging.getLogger(__name__)


def _ui(msg: str = "") -> None:
    try:
        from scholaraio.interfaces.cli import compat as cli_mod
    except ImportError:
        from scholaraio.core.log import ui as log_ui

        log_ui(msg)
        return
    cli_mod.ui(msg)


def _resolve_paper(paper_id: str, cfg) -> Path:
    from scholaraio.interfaces.cli import compat as cli_mod

    return cli_mod._resolve_paper(paper_id, cfg)


def cmd_paper2any(args: argparse.Namespace, cfg) -> None:
    """Prepare ScholarAIO paper content for an external Paper2Any checkout."""

    if args.paper2any_action != "prepare":
        _log.error("Unknown paper2any action: %s", args.paper2any_action)
        sys.exit(1)

    from scholaraio.services.paper2any import prepare_paper2any_bundle

    paper_d = _resolve_paper(args.paper_id, cfg)
    try:
        result = prepare_paper2any_bundle(
            paper_d,
            cfg,
            task=args.task,
            graph_type=args.graph_type,
            input_preference=args.input_preference,
            out_dir=args.out_dir,
            paper2any_root=args.paper2any_root,
            page_count=args.page_count,
            language=args.language,
            style=args.style,
        )
    except (FileNotFoundError, OSError, ValueError) as e:
        _log.error("%s", e)
        sys.exit(1)

    _ui(f"Paper2Any bundle: {result.bundle_dir}")
    _ui(f"Manifest       : {result.manifest_path}")
    _ui(f"Run script     : {result.script_path}")
    _ui(f"Input          : {result.input_kind} -> {result.input_path}")
    _ui(f"Output dir     : {result.output_dir}")
    if args.paper2any_root:
        _ui(f"Run            : {result.script_path} --api-key <key>")
    else:
        _ui(f"Run            : PAPER2ANY_ROOT=/path/to/Paper2Any {result.script_path} --api-key <key>")
