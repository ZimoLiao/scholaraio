"""Diagram CLI command handler."""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

import scholaraio.interfaces.cli.paper as _dep_paper
import scholaraio.interfaces.cli.paths as _dep_paths


def _ui(msg: str = "") -> None:
    from scholaraio.core import log

    log.ui(msg)


def _log_error(msg: str, *args) -> None:
    logging.getLogger(__name__).error(msg, *args)


def _resolve_paper(paper_id: str, cfg):
    return _dep_paper._resolve_paper(paper_id, cfg)


def _workspace_root(cfg) -> Path:
    return _dep_paths._workspace_root(cfg)


def _workspace_figures_dir(cfg) -> Path:
    return _dep_paths._workspace_figures_dir(cfg)


def cmd_diagram(args: argparse.Namespace, cfg) -> None:
    """Paper/text -> editable scientific diagrams with multiple renderers."""
    from scholaraio.services.diagram import (
        generate_diagram,
        generate_diagram_from_text,
        generate_diagram_with_critic,
        render_ir,
    )

    out_dir = Path(args.output) if args.output else None
    from_text = getattr(args, "from_text", None)
    from_ir = getattr(args, "from_ir", None)

    sources = [bool(args.paper_id), bool(from_text), bool(from_ir)]
    if sum(sources) != 1:
        _log_error("Provide exactly one input source: paper_id, --from-text, or --from-ir")
        sys.exit(1)

    if from_ir:
        ir_path = Path(from_ir)
        if not ir_path.exists():
            _log_error("IR file does not exist: %s", ir_path)
            sys.exit(1)
        try:
            ir = json.loads(ir_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            _log_error("Failed to parse IR file: %s", e)
            sys.exit(1)
        try:
            out_path = render_ir(ir, args.format, out_path=_build_diagram_out_path(ir, args.format, out_dir, cfg))
        except (ValueError, RuntimeError) as e:
            _log_error("%s", e)
            sys.exit(1)
        _ui(f"Generated: {out_path}")
        _print_diagram_hint(args.format, Path(out_path))
        return

    if from_text:
        try:
            out_path = generate_diagram_from_text(
                description=from_text,
                diagram_type=args.type,
                fmt=args.format,
                cfg=cfg,
                out_dir=out_dir,
                dump_ir=args.dump_ir,
            )
            _ui(f"Generated: {out_path}")
            if not args.dump_ir:
                _print_diagram_hint(args.format, Path(out_path))
        except (ValueError, RuntimeError) as e:
            _log_error("%s", e)
            sys.exit(1)
        return

    paper_d = _resolve_paper(args.paper_id, cfg)
    try:
        if args.critic:
            result = generate_diagram_with_critic(
                paper_d=paper_d,
                diagram_type=args.type,
                fmt=args.format,
                cfg=cfg,
                out_dir=out_dir,
                dump_ir=args.dump_ir,
                max_rounds=args.critic_rounds,
            )
            out_path = result["out_path"]
            critique_log = result["critique_log"]
            _ui(f"Generated: {out_path}")
            if not args.dump_ir:
                _print_diagram_hint(args.format, Path(out_path))
            if args.critic_rounds > 0:
                _ui(f"Critic loop completed, total {len(critique_log)} rounds")
                for c in critique_log:
                    verdict = c.get("verdict", "unknown")
                    issue_count = len(c.get("issues", []))
                    _ui(f"  round {c.get('round', '?')}: verdict={verdict}, issues={issue_count}")
        else:
            out_path = generate_diagram(
                paper_d=paper_d,
                diagram_type=args.type,
                fmt=args.format,
                cfg=cfg,
                out_dir=out_dir,
                dump_ir=args.dump_ir,
            )
            _ui(f"Generated: {out_path}")
            if not args.dump_ir:
                _print_diagram_hint(args.format, Path(out_path))
    except (ValueError, RuntimeError) as e:
        _log_error("%s", e)
        sys.exit(1)


def _build_diagram_out_path(ir: dict, fmt: str, out_dir: Path | None, cfg=None) -> Path:
    if out_dir is None:
        out_dir = _workspace_figures_dir(cfg)
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_title = re.sub(r"[^\w\-]", "_", ir.get("title", "diagram"))[:40]
    return out_dir / f"diagram_{safe_title}.{fmt}"


def _print_diagram_hint(fmt: str, out_path: Path) -> None:
    if fmt == "svg":
        dot_path = out_path.with_suffix(".dot")
        _ui(f"DOT source: {dot_path}")
        _ui("Beamer insertion code:")
        _ui(r"  \begin{frame}")
        _ui(r"  \centering")
        try:
            display_path = out_path.resolve().relative_to(Path.cwd().resolve())
        except ValueError:
            display_path = out_path
        _ui(f"  \\includesvg[width=0.8\\columnwidth]{{{display_path}}}")
        _ui(r"  \end{frame}")
        _ui("Note: compile with -shell-escape and make sure Inkscape is installed")
    elif fmt == "drawio":
        _ui("Open https://app.diagrams.net in a browser and import the file to edit it")
