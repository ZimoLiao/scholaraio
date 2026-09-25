"""Synthetic catalog benchmark: run from the repository root.

python scripts/benchmarks/library_catalog.py --sizes 2000 10000 50000 --samples 20
Cold means a fresh process-local projection, not a flushed OS disk cache.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scholaraio.core.config import _build_config
from scholaraio.services.library_catalog import LibraryCatalog
from scholaraio.services.library_view import get_main_paper_detail


def run(size: int, samples: int) -> dict:
    with tempfile.TemporaryDirectory(prefix="scholaraio-catalog-benchmark-") as directory:
        cfg = _build_config({}, Path(directory))
        cfg.ensure_dirs()
        for i in range(size):
            paper = cfg.papers_dir / f"paper-{i:06}"
            paper.mkdir()
            (paper / "meta.json").write_text(
                json.dumps(
                    {
                        "id": str(i),
                        "title": f"Paper {i:06} turbulence",
                        "authors": [f"Author {i % 100}"],
                        "year": 2000 + i % 26,
                        "abstract": "Evidence. " * 30,
                    }
                ),
                encoding="utf-8",
            )
        # Audit is independently scheduled and measured elsewhere, not part of
        # the metadata query projection. Never launch it against real libraries.
        with patch("scholaraio.services.library_view._background_issue_map", return_value={}):
            catalog = LibraryCatalog(cfg, "main")
            started = time.perf_counter()
            page = catalog.page({"limit": "100"})
            cold = time.perf_counter() - started
            warm, filtered = [], []
            for _ in range(samples):
                started = time.perf_counter()
                catalog.page({"limit": "100"})
                warm.append(time.perf_counter() - started)
                started = time.perf_counter()
                catalog.page({"limit": "100", "author": "Author 42", "sort": "title"})
                filtered.append(time.perf_counter() - started)
            started = time.perf_counter()
            get_main_paper_detail(cfg, "0", background_audit=True)
            detail = time.perf_counter() - started
            started = time.perf_counter()
            catalog.page({"limit": "100", "refresh": "1"})
            scan = time.perf_counter() - started
            sqlite_bytes = (
                catalog.db.execute("PRAGMA page_count").fetchone()[0]
                * catalog.db.execute("PRAGMA page_size").fetchone()[0]
            )
            catalog.close()

        def timings(values: list[float]) -> dict:
            return {
                "p50_ms": round(statistics.median(values) * 1000, 2),
                "p95_ms": round(sorted(values)[min(len(values) - 1, int(len(values) * 0.95))] * 1000, 2),
            }

        return {
            "records": size,
            "cold_ms": round(cold * 1000, 2),
            "warm_page": timings(warm),
            "filtered_page": timings(filtered),
            "detail_ms": round(detail * 1000, 2),
            "forced_scan_ms": round(scan * 1000, 2),
            "page_bytes": len(json.dumps(page).encode()),
            "rows_returned": len(page["papers"]),
            "sqlite_projection_bytes": sqlite_bytes,
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", nargs="+", type=int, default=[2000, 10000, 50000])
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--check", action="store_true", help="Fail if the documented synthetic budget is exceeded")
    args = parser.parse_args()
    if args.samples < 1 or any(size < 1 for size in args.sizes):
        parser.error("sizes and samples must be positive")
    print(json.dumps({"python": platform.python_version(), "platform": platform.platform()}), flush=True)
    passed = True
    for size in args.sizes:
        result = run(size, args.samples)
        result["budget_passed"] = (
            result["warm_page"]["p95_ms"] < 250
            and result["filtered_page"]["p95_ms"] < 250
            and result["cold_ms"] < 30000
            and result["page_bytes"] < 256 * 1024
            and result["rows_returned"] <= 100
        )
        passed = passed and result["budget_passed"]
        print(json.dumps(result), flush=True)
    if args.check and not passed:
        raise SystemExit(1)
