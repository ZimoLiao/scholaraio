"""TOC and L3 enrichment CLI command handlers."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import logging
import sys
import time
from collections.abc import Callable
from pathlib import Path


def _ui(msg: str = "") -> None:
    from scholaraio.core import log

    log.ui(msg)


def _log_error(msg: str, *args) -> None:
    logging.getLogger(__name__).error(msg, *args)


def _log_warning(msg: str, *args) -> None:
    logging.getLogger(__name__).warning(msg, *args)


def _concurrent_futures():
    return concurrent.futures


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def cmd_enrich_toc(args: argparse.Namespace, cfg) -> None:
    from scholaraio.services.loader import enrich_toc
    from scholaraio.stores.papers import iter_paper_dirs

    papers_dir = cfg.papers_dir

    if args.all:
        targets = sorted(d / "meta.json" for d in iter_paper_dirs(papers_dir))
    elif args.paper_id:
        targets = [papers_dir / args.paper_id / "meta.json"]
    else:
        _log_error("Specify <paper-id> or --all")
        sys.exit(1)

    if args.all:
        ok, fail, skip = _run_batch_enrich(
            targets,
            cfg,
            worker_fn=lambda json_path, md_path: enrich_toc(
                json_path,
                md_path,
                cfg,
                force=args.force,
                inspect=args.inspect,
            ),
            success_message=_toc_success_message,
            failure_message="  TOC extraction failed",
            max_retries=2,
        )
    else:
        ok = fail = skip = 0
        for json_path in targets:
            md_path = json_path.parent / "paper.md"
            if not md_path.exists():
                _log_error("Skipped (missing paper.md): %s", json_path.parent.name)
                skip += 1
                continue

            _ui(f"\n{json_path.parent.name}")
            _ui("  Extracting TOC...")
            success = enrich_toc(
                json_path,
                md_path,
                cfg,
                force=args.force,
                inspect=args.inspect,
            )
            if success:
                ok += 1
                _ui(_toc_success_message(json_path))
            else:
                fail += 1
                _ui("  TOC extraction failed")

    if args.all or len(targets) > 1:
        _ui(f"\nDone: {ok} succeeded | {fail} failed | {skip} skipped")


def cmd_enrich_l3(args: argparse.Namespace, cfg) -> None:
    from scholaraio.services.loader import enrich_l3
    from scholaraio.stores.papers import iter_paper_dirs

    papers_dir = cfg.papers_dir

    if args.all:
        targets = sorted(d / "meta.json" for d in iter_paper_dirs(papers_dir))
    elif args.paper_id:
        targets = [papers_dir / args.paper_id / "meta.json"]
    else:
        _log_error("Specify <paper-id> or --all")
        sys.exit(1)

    if args.all:
        ok, fail, skip = _run_batch_enrich(
            targets,
            cfg,
            worker_fn=lambda json_path, md_path: enrich_l3(
                json_path,
                md_path,
                cfg,
                force=args.force,
                max_retries=args.max_retries,
                inspect=args.inspect,
            ),
            success_message="  Conclusion extraction completed",
            failure_message="  Conclusion extraction failed",
            max_retries=args.max_retries,
        )
    else:
        ok = fail = skip = 0
        for json_path in targets:
            md_path = json_path.parent / "paper.md"
            if not md_path.exists():
                _log_error("Skipped (missing paper.md): %s", json_path.parent.name)
                skip += 1
                continue

            _ui(f"\n{json_path.parent.name}")
            success = enrich_l3(
                json_path,
                md_path,
                cfg,
                force=args.force,
                max_retries=args.max_retries,
                inspect=args.inspect,
            )
            if success:
                ok += 1
                _ui("  Conclusion extraction completed")
            else:
                fail += 1
                _ui("  Conclusion extraction failed")

    if args.all or len(targets) > 1:
        _ui(f"\nDone: {ok} succeeded | {fail} failed | {skip} skipped")


def _toc_success_message(json_path: Path) -> str:
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        return f"  TOC extraction completed: {len(data.get('toc', []))} sections"
    except (OSError, json.JSONDecodeError):
        return "  TOC extraction completed"


def _run_batch_enrich(
    targets: list[Path],
    cfg,
    *,
    worker_fn,
    success_message: str | Callable[[Path], str],
    failure_message: str,
    max_retries: int,
) -> tuple[int, int, int]:
    def _batch_message(json_path: Path, message: str) -> str:
        return f"{json_path.parent.name} | {message.strip()}"

    queued: list[tuple[Path, Path]] = []
    skip = 0
    for json_path in targets:
        md_path = json_path.parent / "paper.md"
        if not md_path.exists():
            _log_error("Skipped (missing paper.md): %s", json_path.parent.name)
            skip += 1
            continue
        queued.append((json_path, md_path))

    if not queued:
        return 0, 0, skip

    workers = min(max(1, int(getattr(cfg.llm, "concurrency", 1))), len(queued))
    _ui(f"Concurrent processing ({workers} workers, total {len(queued)} papers)...")

    def _retry_one(json_path: Path, md_path: Path) -> tuple[Path, bool, int]:
        for attempt in range(1, max_retries + 2):
            try:
                success = worker_fn(json_path, md_path)
                if success:
                    return json_path, True, attempt
            except Exception as e:
                _log_warning("Batch enrichment failed (%s, attempt %d): %s", json_path.parent.name, attempt, e)
            if attempt <= max_retries:
                _sleep(float(2 ** (attempt - 1)))
        return json_path, False, max_retries + 1

    ok = fail = 0
    futures_mod = _concurrent_futures()
    with futures_mod.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = []
        for json_path, md_path in queued:
            _ui(f"\n{_batch_message(json_path, 'Start processing...')}")
            futures.append(pool.submit(_retry_one, json_path, md_path))
        for future in futures_mod.as_completed(futures):
            json_path, success, attempts = future.result()
            if success:
                ok += 1
                if attempts > 1:
                    _ui(_batch_message(json_path, f"Succeeded after retry (total {attempts} times)"))
                _ui(
                    _batch_message(
                        json_path,
                        success_message(json_path) if callable(success_message) else success_message,
                    )
                )
            else:
                fail += 1
                if attempts > 1:
                    _ui(_batch_message(json_path, f"Retried {attempts - 1}/{max_retries} times"))
                _ui(_batch_message(json_path, failure_message))

    return ok, fail, skip
