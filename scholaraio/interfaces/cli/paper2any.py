"""Paper2Any CLI handoff command."""

from __future__ import annotations

import argparse
import logging
import subprocess
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

    if args.paper2any_action == "setup":
        from scholaraio.services.paper2any_runtime import setup_paper2any_runtime

        try:
            setup_result = setup_paper2any_runtime(
                cfg,
                root=args.root,
                repo_url=args.repo_url,
                install=not args.skip_install,
                update=args.update,
                save_config=not args.no_save_config,
            )
        except (FileExistsError, OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as e:
            _log.error("%s", e)
            sys.exit(1)
        _ui(f"Paper2Any root   : {setup_result.root}")
        _ui(f"Repository       : {setup_result.repo_url}")
        _ui(f"Runtime status   : {setup_result.status.detail}")
        if setup_result.status.venv_python:
            _ui(f"Python runtime   : {setup_result.status.venv_python}")
        if setup_result.status.ready:
            _ui("Paper2Any runtime is ready.")
        else:
            _ui("Paper2Any runtime is not ready; rerun without --skip-install.")
        return

    if args.paper2any_action == "status":
        from scholaraio.services.paper2any_runtime import check_paper2any_status

        status = check_paper2any_status(cfg, args.root)
        _ui(f"Paper2Any root   : {status.root}")
        _ui(f"Python runtime   : {status.venv_python}")
        _ui(f"Runtime status   : {status.detail}")
        if not status.ready:
            _ui("Run              : scholaraio paper2any setup")
            sys.exit(1)
        return

    if args.paper2any_action == "capabilities":
        from scholaraio.services.paper2any_runtime import paper2any_capabilities

        _ui("Paper2Any capabilities:")
        for capability in paper2any_capabilities():
            _ui(f"- {capability['name']} [{capability['mode']}]: {capability['description']}")
        _ui("")
        _ui("Modes:")
        _ui("- prepare: use `scholaraio paper2any prepare ...` to create a runnable handoff bundle")
        _ui("- api: run `scholaraio paper2any serve` and call the upstream /api/v1 routes")
        return

    if args.paper2any_action == "serve":
        from scholaraio.services.paper2any_runtime import start_paper2any_api

        _ui(f"Starting Paper2Any FastAPI backend on http://{args.host}:{args.port}")
        try:
            start_paper2any_api(
                cfg,
                root=args.root,
                host=args.host,
                port=args.port,
                reload=args.reload,
            )
        except (FileNotFoundError, OSError, subprocess.CalledProcessError) as e:
            _log.error("%s", e)
            sys.exit(1)
        return

    if args.paper2any_action != "prepare":
        _log.error("Unknown paper2any action: %s", args.paper2any_action)
        sys.exit(1)

    from scholaraio.services.paper2any import prepare_paper2any_bundle

    paper_d = _resolve_paper(args.paper_id, cfg)
    try:
        bundle_result = prepare_paper2any_bundle(
            paper_d,
            cfg,
            task=args.task,
            graph_type=args.graph_type,
            input_preference=args.input_preference,
            source_file=args.source_file,
            out_dir=args.out_dir,
            paper2any_root=args.paper2any_root,
            page_count=args.page_count,
            language=args.language,
            style=args.style,
        )
    except (FileNotFoundError, OSError, ValueError) as e:
        _log.error("%s", e)
        sys.exit(1)

    _ui(f"Paper2Any bundle: {bundle_result.bundle_dir}")
    _ui(f"Manifest       : {bundle_result.manifest_path}")
    _ui(f"Run script     : {bundle_result.script_path}")
    _ui(f"Input          : {bundle_result.input_kind} -> {bundle_result.input_path}")
    _ui(f"Output dir     : {bundle_result.output_dir}")
    _ui(f"Run            : {bundle_result.script_path} --api-key <key>")
