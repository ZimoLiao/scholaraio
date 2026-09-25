"""Pipeline CLI command handler."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path


def _ui(msg: str = "") -> None:
    from scholaraio.core import log

    log.ui(msg)


def _log_error(msg: str, *args) -> None:
    logging.getLogger(__name__).error(msg, *args)


def cmd_pipeline(args: argparse.Namespace, cfg) -> None:
    from scholaraio.services.ingest.pipeline import PRESETS, STEPS, run_pipeline

    if args.list_steps:
        _ui("Available steps: ")
        for name, sdef in STEPS.items():
            _ui(f"  {name:<10} [{sdef.scope:<7}]  {sdef.desc}")
        _ui("\nAvailable presets: ")
        for name, steps in PRESETS.items():
            _ui(f"  {name:<10} = {', '.join(steps)}")
        return

    # Resolve step list
    if args.preset:
        if args.preset not in PRESETS:
            _log_error("Unknown preset '%s'. Available presets: %s", args.preset, ", ".join(PRESETS))
            sys.exit(1)
        step_names = PRESETS[args.preset]
    elif args.steps:
        step_names = [s.strip() for s in args.steps.split(",") if s.strip()]
    else:
        _log_error("Specify a preset name or use --steps")
        sys.exit(1)

    opts = {
        "dry_run": args.dry_run,
        "no_api": args.no_api,
        "force": args.force,
        "inspect": args.inspect,
        "max_retries": args.max_retries,
        "rebuild": args.rebuild,
    }
    if args.inbox:
        opts["inbox_dir"] = Path(args.inbox).resolve()
    if args.papers:
        opts["papers_dir"] = Path(args.papers).resolve()

    run_pipeline(step_names, cfg, opts)
