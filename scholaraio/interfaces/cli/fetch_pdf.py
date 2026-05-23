"""PDF fetch CLI command handler."""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path


def _ui(msg: str = "") -> None:
    try:
        from scholaraio.interfaces.cli import compat as cli_mod
    except ImportError:
        from scholaraio.core.log import ui as log_ui

        log_ui(msg)
        return
    cli_mod.ui(msg)


def _default_inbox_dir(cfg) -> Path:
    from scholaraio.interfaces.cli import compat as cli_mod

    return cli_mod._default_inbox_dir(cfg)


def _resolve_paper(paper_id: str, cfg) -> Path:
    from scholaraio.interfaces.cli import compat as cli_mod

    return cli_mod._resolve_paper(paper_id, cfg)


def _print_result(result) -> None:
    status = result.status
    if status == "downloaded":
        path = result.path or "-"
        _ui(f"Downloaded PDF: {path}")
        if result.pdf_url:
            _ui(f"Source URL: {result.pdf_url}")
        if result.bytes_downloaded:
            _ui(f"Bytes: {result.bytes_downloaded}")
    elif status == "skipped":
        _ui(f"Skipped: {result.message or result.locator}")
    else:
        _ui(f"Failed: {result.locator} ({result.message})")


def _print_staged_ingest_result(result) -> None:
    name = result.path.name if result.path is not None else result.locator
    _ui(f"Staged PDF for ingest: {name} (temporary; use --out-dir to keep a copy)")
    if result.pdf_url:
        _ui(f"Source URL: {result.pdf_url}")
    if result.bytes_downloaded:
        _ui(f"Bytes: {result.bytes_downloaded}")


def _validate_mode(args: argparse.Namespace) -> str:
    has_locator = bool((getattr(args, "locator", None) or "").strip())
    has_paper = bool(_paper_ids(args))
    has_all = bool(getattr(args, "all", False))
    modes = [has_locator, has_paper, has_all]
    if sum(1 for enabled in modes if enabled) != 1:
        _ui("Choose exactly one mode: fetch-pdf <locator>, fetch-pdf --paper <id> [<id> ...], or fetch-pdf --all")
        sys.exit(1)
    if getattr(args, "ingest", False) and not has_locator:
        _ui("--ingest is only supported when downloading a new locator")
        sys.exit(1)
    if getattr(args, "out_dir", None) and not has_locator:
        _ui("--out-dir is only supported when downloading a new locator")
        sys.exit(1)
    if has_locator:
        return "locator"
    if has_paper:
        return "paper"
    return "all"


def _paper_ids(args: argparse.Namespace) -> list[str]:
    value = getattr(args, "paper", None)
    if value is None:
        return []
    if isinstance(value, str):
        values = [value]
    else:
        values = list(value)
    return [str(item).strip() for item in values if str(item).strip()]


def _run_ingest_for_pdf(pdf_path: Path, cfg, *, force: bool) -> None:
    from scholaraio.services.ingest.pipeline import PRESETS, run_pipeline

    with tempfile.TemporaryDirectory(prefix="scholaraio_pdf_ingest_") as tmpdir:
        tmp_inbox = Path(tmpdir)
        shutil.copy2(pdf_path, tmp_inbox / pdf_path.name)
        run_pipeline(
            PRESETS["ingest"],
            cfg,
            {"inbox_dir": tmp_inbox, "force": force, "include_aux_inboxes": False},
        )


def _download_new_locator(args: argparse.Namespace, cfg) -> None:
    from scholaraio.services.pdf_fetch import fetch_pdf

    locator = str(args.locator).strip()
    out_dir_arg = getattr(args, "out_dir", None)
    ingest = bool(getattr(args, "ingest", False))
    force = bool(getattr(args, "force", False))
    direct = bool(getattr(args, "direct", False))
    timeout = float(getattr(args, "timeout", 60.0))

    with ExitStack() as stack:
        staged_for_ingest = ingest and not out_dir_arg
        if ingest and not out_dir_arg:
            out_dir = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="scholaraio_pdf_fetch_")))
        elif out_dir_arg:
            out_dir = Path(out_dir_arg).expanduser().resolve()
        else:
            out_dir = _default_inbox_dir(cfg)

        try:
            result = fetch_pdf(locator, out_dir, direct=direct, force=force, timeout=timeout)
        except Exception as exc:
            _ui(f"PDF fetch failed: {exc}")
            sys.exit(1)

        if staged_for_ingest:
            _print_staged_ingest_result(result)
        else:
            _print_result(result)
        if ingest:
            if result.path is None:
                _ui("PDF ingest failed: no PDF path was produced")
                sys.exit(1)
            try:
                _run_ingest_for_pdf(result.path, cfg, force=force)
            except Exception as exc:
                _ui(f"PDF ingest failed: {exc}")
                sys.exit(1)


def _print_batch_summary(results) -> None:
    downloaded = sum(1 for result in results if result.status == "downloaded")
    skipped = sum(1 for result in results if result.status == "skipped")
    failed = sum(1 for result in results if result.status == "failed")
    _ui(f"PDF refetch summary: downloaded={downloaded} skipped={skipped} failed={failed}")
    if failed:
        sys.exit(1)


def _refetch_selected(args: argparse.Namespace, cfg) -> None:
    from scholaraio.services.pdf_fetch import batch_refetch_pdfs, refetch_paper_pdf

    paper_dirs = [_resolve_paper(paper_id, cfg) for paper_id in _paper_ids(args)]
    try:
        if len(paper_dirs) == 1:
            result = refetch_paper_pdf(
                paper_dirs[0],
                cfg,
                direct=bool(getattr(args, "direct", False)),
                force=bool(getattr(args, "force", False)),
                timeout=float(getattr(args, "timeout", 60.0)),
            )
            _print_result(result)
            return
        results = batch_refetch_pdfs(
            cfg,
            paper_dirs=paper_dirs,
            direct=bool(getattr(args, "direct", False)),
            force=bool(getattr(args, "force", False)),
            timeout=float(getattr(args, "timeout", 60.0)),
        )
    except Exception as exc:
        _ui(f"PDF refetch failed: {exc}")
        sys.exit(1)
    for result in results:
        _print_result(result)
    _print_batch_summary(results)


def _refetch_all(args: argparse.Namespace, cfg) -> None:
    from scholaraio.services.pdf_fetch import batch_refetch_pdfs

    results = batch_refetch_pdfs(
        cfg,
        direct=bool(getattr(args, "direct", False)),
        force=bool(getattr(args, "force", False)),
        timeout=float(getattr(args, "timeout", 60.0)),
    )
    for result in results:
        _print_result(result)
    _print_batch_summary(results)


def cmd_fetch_pdf(args: argparse.Namespace, cfg) -> None:
    """Download a PDF through the user's current legal access context."""
    mode = _validate_mode(args)
    if mode == "locator":
        _download_new_locator(args, cfg)
    elif mode == "paper":
        _refetch_selected(args, cfg)
    else:
        _refetch_all(args, cfg)
