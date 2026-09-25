"""Citation style CLI command handler."""

from __future__ import annotations

import argparse
import logging
import sys


def _ui(msg: str = "") -> None:
    from scholaraio.core import log

    log.ui(msg)


def _log_error(msg: str, *args) -> None:
    logging.getLogger(__name__).error(msg, *args)


def cmd_style(args: argparse.Namespace, cfg) -> None:
    """Dispatcher for `scholaraio style` subcommands."""
    sub = getattr(args, "style_sub", None)
    if sub == "list":
        _cmd_style_list(args, cfg)
    elif sub == "show":
        _cmd_style_show(args, cfg)
    else:
        _log_error("Specify a style subcommand: list / show")
        sys.exit(1)


def _cmd_style_list(args: argparse.Namespace, cfg) -> None:
    from scholaraio.stores.citation_styles import list_styles

    ui = _ui
    styles = list_styles(cfg)
    ui(f"Available citation styles (total {len(styles)} styles): ")
    for s in styles:
        tag = f"[{s['source']}]"
        desc = f" — {s['description']}" if s.get("description") else ""
        print(f"  {s['name']:<28} {tag:<10}{desc}")
    print()
    ui("Usage: scholaraio export markdown --all --style <name>")


def _cmd_style_show(args: argparse.Namespace, cfg) -> None:
    from scholaraio.stores.citation_styles import show_style

    try:
        code = show_style(args.name, cfg)
        print(code)
    except (FileNotFoundError, ValueError) as e:
        _log_error("%s", e)
        sys.exit(1)
