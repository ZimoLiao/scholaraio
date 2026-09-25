"""Proceedings CLI command handler."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _ui(msg: str = "") -> None:
    from scholaraio.core import log

    log.ui(msg)


def cmd_proceedings(args: argparse.Namespace, cfg) -> None:
    del cfg  # proceedings subcommands currently operate on explicit paths.

    if args.proceedings_action == "build-clean-candidates":
        from scholaraio.services.ingest.proceedings_volume import build_proceedings_clean_candidates

        proceeding_dir = Path(args.proceeding_dir).expanduser()
        if not proceeding_dir.exists():
            _ui(f"Proceedings directory does not exist: {proceeding_dir}")
            return

        candidates_path = build_proceedings_clean_candidates(proceeding_dir)
        _ui(f"Generated proceedings clean candidates: {candidates_path}")
        _ui("Waiting for an agent to review clean_candidates.json and create clean_plan.json before cleanup.")
        return

    if args.proceedings_action == "apply-split":
        from scholaraio.services.ingest.proceedings_volume import apply_proceedings_split_plan

        proceeding_dir = Path(args.proceeding_dir).expanduser()
        split_plan = Path(args.split_plan).expanduser()

        if not proceeding_dir.exists():
            _ui(f"Proceedings directory does not exist: {proceeding_dir}")
            return
        if not split_plan.exists():
            _ui(f"Split plan does not exist: {split_plan}")
            return

        apply_proceedings_split_plan(proceeding_dir, split_plan)
        meta = json.loads((proceeding_dir / "meta.json").read_text(encoding="utf-8"))
        _ui(f"Applied proceedings split plan: {proceeding_dir.name} ({meta.get('child_paper_count', 0)} papers)")
        return

    if args.proceedings_action == "apply-clean":
        from scholaraio.services.ingest.proceedings_volume import apply_proceedings_clean_plan

        proceeding_dir = Path(args.proceeding_dir).expanduser()
        clean_plan = Path(args.clean_plan).expanduser()

        if not proceeding_dir.exists():
            _ui(f"Proceedings directory does not exist: {proceeding_dir}")
            return
        if not clean_plan.exists():
            _ui(f"Clean plan does not exist: {clean_plan}")
            return

        apply_proceedings_clean_plan(proceeding_dir, clean_plan)
        meta = json.loads((proceeding_dir / "meta.json").read_text(encoding="utf-8"))
        _ui(f"Applied proceedings clean plan: {proceeding_dir.name} ({meta.get('child_paper_count', 0)} papers)")
        return

    _ui(f"Unknown proceedings subcommand: {args.proceedings_action}")
