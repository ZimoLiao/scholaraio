"""Document CLI command handler."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path


def _log_error(msg: str, *args) -> None:
    logging.getLogger(__name__).error(msg, *args)


def cmd_document(args: argparse.Namespace, cfg) -> None:
    action = getattr(args, "doc_action", None)
    if action == "inspect":
        _cmd_document_inspect(args, cfg)
    else:
        _log_error("Specify the document subcommand: inspect")
        sys.exit(1)


def _cmd_document_inspect(args: argparse.Namespace, cfg) -> None:
    from scholaraio.services.document import inspect

    file_path = Path(args.file)
    if not file_path.exists():
        _log_error("File does not exist: %s", file_path)
        sys.exit(1)
    fmt = getattr(args, "format", None)
    try:
        result = inspect(file_path, fmt=fmt)
    except (ValueError, ImportError) as e:
        _log_error("%s", e)
        sys.exit(1)
    print(result)
