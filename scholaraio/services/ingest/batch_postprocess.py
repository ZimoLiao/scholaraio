"""Post-processing helpers for batch PDF conversion."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from scholaraio.core.config import Config
from scholaraio.core.log import ui as _base_ui
from scholaraio.services.ingest import steps as ingest_steps
from scholaraio.services.ingest.types import StepResult

_log = logging.getLogger(__name__)
ui = _base_ui


def _pipeline_attr(name: str, fallback):
    from scholaraio.services.ingest import pipeline as pipeline_mod

    return getattr(pipeline_mod, name, fallback)


def _ui(message: str = "") -> None:
    legacy_ui = _pipeline_attr("ui", _base_ui)
    if legacy_ui is not _base_ui:
        legacy_ui(message)
        return
    ui(message)


def postprocess_convert(pdir: Path, pdf_path: Path, result) -> None:
    """Post-process a single MinerU conversion result in paper_dir."""
    paper_md = pdir / "paper.md"

    # Move output to paper.md
    if result.md_path and result.md_path != paper_md:
        if paper_md.exists():
            paper_md.unlink()
        shutil.move(str(result.md_path), str(paper_md))

    # Clean up MinerU artifacts
    for pattern in ["*_layout.json", "*_content_list.json", "*_origin.pdf"]:
        for f in pdir.glob(pattern):
            f.unlink(missing_ok=True)
    for img_dir in pdir.glob("*_images"):
        if img_dir.name != "images" and img_dir.is_dir():
            target = pdir / "images"
            if target.exists():
                shutil.rmtree(target)
            img_dir.rename(target)

    # Preserve the source PDF under the paper-directory basename.
    if pdf_path.exists():
        from scholaraio.stores.papers import normalize_pdf_name

        normalize_pdf_name(pdir, pdf_path)


def batch_postprocess(
    converted_dirs: list[Path],
    cfg: Config,
    *,
    enrich: bool = False,
) -> None:
    """Abstract backfill + optional toc/l3 enrich + embed/index for converted papers."""
    from scholaraio.stores.papers import read_meta, update_meta

    # Abstract backfill
    backfilled = 0
    for pdir in converted_dirs:
        paper_md = pdir / "paper.md"
        if not paper_md.exists():
            continue
        try:
            data = read_meta(pdir)
            if not data.get("abstract"):
                from scholaraio.services.ingest_metadata import extract_abstract_from_md

                abstract = extract_abstract_from_md(paper_md, cfg)
                if abstract:
                    data["abstract"] = abstract
                    update_meta(pdir, abstract=abstract)
                    backfilled += 1
        except (ValueError, FileNotFoundError) as e:
            _log.debug("failed to backfill abstract for %s: %s", pdir.name, e)
    if backfilled:
        _ui(f"Abstracts backfilled: {backfilled} papers")

    # Enrich: toc + l3
    if enrich:
        enriched = 0
        failed = 0
        opts: dict[str, Any] = {"dry_run": False, "force": False, "max_retries": 2}
        step_toc = _pipeline_attr("step_toc", ingest_steps.step_toc)
        step_l3 = _pipeline_attr("step_l3", ingest_steps.step_l3)
        for pdir in converted_dirs:
            json_path = pdir / "meta.json"
            if not json_path.exists():
                continue
            _ui(f"  enrich: {pdir.name}")
            toc_res = step_toc(json_path, cfg, opts)
            l3_res = step_l3(json_path, cfg, opts)
            if toc_res == StepResult.FAIL or l3_res == StepResult.FAIL:
                failed += 1
            else:
                enriched += 1
        _ui(f"Enrichment completed: {enriched} ok | {failed} failed")

    # Re-embed + re-index once
    step_embed = _pipeline_attr("step_embed", ingest_steps.step_embed)
    step_index = _pipeline_attr("step_index", ingest_steps.step_index)
    step_embed(cfg.papers_dir, cfg, {"dry_run": False, "rebuild": False})
    step_index(cfg.papers_dir, cfg, {"dry_run": False, "rebuild": False})
