"""Audit CLI command handler."""

from __future__ import annotations

import argparse
import logging
import sys


def _ui(msg: str = "") -> None:
    from scholaraio.core import log

    log.ui(msg)


def _log_error(msg: str, *args) -> None:
    logging.getLogger(__name__).error(msg, *args)


def cmd_audit(args: argparse.Namespace, cfg) -> None:
    from scholaraio.services.audit import audit_papers, format_report

    papers_dir = cfg.papers_dir
    if not papers_dir.exists():
        _log_error("Papers directory does not exist: %s", papers_dir)
        sys.exit(1)

    _ui(f"Auditing paper library: {papers_dir}\n")
    issues = audit_papers(papers_dir)

    if args.severity:
        issues = [i for i in issues if i.severity == args.severity]

    _ui(format_report(issues))
