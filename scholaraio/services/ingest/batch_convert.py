"""Batch PDF conversion orchestration for already-ingested papers."""

from __future__ import annotations

import logging
import shutil
from collections.abc import Iterable
from pathlib import Path

from scholaraio.core.config import Config
from scholaraio.core.log import ui as _base_ui
from scholaraio.services.ingest import batch_assets, batch_postprocess

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


def _log_error(message: str, *args) -> None:
    legacy_log = _pipeline_attr("_log", _log)
    legacy_log.error(message, *args)


def batch_convert_pdfs(
    cfg: Config,
    *,
    enrich: bool = False,
    paper_dirs: Iterable[Path] | None = None,
) -> dict[str, int]:
    """批量转换已入库论文的 PDF 为 paper.md，可选 enrich。

    扫描 configured papers library 中有 PDF 无 paper.md 的论文，
    云端模式使用 ``convert_pdfs_cloud_batch()`` 真正批量转换，
    本地模式逐篇调用。转换后可选运行 toc + l3 + abstract backfill，
    最后一次性 embed + index。

    Args:
        cfg: 全局配置。
        enrich: 转换后是否运行 toc + l3 + abstract backfill。
        paper_dirs: Optional subset of paper directories to scan.  The default
            scans the whole configured library.

    Returns:
        统计字典 ``{"converted": N, "failed": N, "skipped": N}``。
    """
    from scholaraio.stores.papers import iter_paper_dirs

    # Collect papers with PDF but no paper.md
    to_convert: list[tuple[Path, Path]] = []  # (paper_dir, pdf_path)
    candidates = iter_paper_dirs(cfg.papers_dir) if paper_dirs is None else sorted(set(paper_dirs))
    for pdir in candidates:
        if not (pdir / "meta.json").exists():
            continue
        if (pdir / "paper.md").exists():
            continue
        pdfs = list(pdir.glob("*.pdf"))
        if pdfs:
            to_convert.append((pdir, pdfs[0]))

    stats: dict[str, int] = {"converted": 0, "failed": 0, "skipped": 0}
    if not to_convert:
        _ui("No PDFs need conversion")
        return stats

    from scholaraio.providers.mineru import ConvertOptions, check_server, is_pdf_validation_error
    from scholaraio.providers.pdf_fallback import (
        convert_pdf_with_fallback,
        preferred_parser_order,
        prefers_fallback_parser,
    )

    use_local = check_server(cfg.ingest.mineru_endpoint)
    api_key = None
    fallback_auto_detect = getattr(cfg.ingest, "pdf_fallback_auto_detect", True)
    fallback_order = preferred_parser_order(
        getattr(cfg.ingest, "pdf_preferred_parser", "mineru"),
        getattr(cfg.ingest, "pdf_fallback_order", None),
        auto_detect=fallback_auto_detect,
    )
    prefer_fallback = prefers_fallback_parser(getattr(cfg.ingest, "pdf_preferred_parser", "mineru"))
    if not use_local:
        api_key = cfg.resolved_mineru_api_key()
        if not api_key:
            _ui(
                "MinerU is unreachable and no MinerU token is configured; continuing batch conversion with fallback parser"
            )

    _ui(f"\nStarting batch conversion for {len(to_convert)} PDFs...")

    converted_dirs: list[Path] = []

    def _run_fallback(pdir: Path, pdf_path: Path) -> bool:
        ok, parser_name, err = convert_pdf_with_fallback(
            pdf_path,
            pdir / "paper.md",
            parser_order=fallback_order,
            auto_detect=fallback_auto_detect,
        )
        if not ok:
            _ui(f"  {pdir.name}: fallback failed: {err}")
            stats["failed"] += 1
            return False
        if pdf_path.exists():
            from scholaraio.stores.papers import normalize_pdf_name

            normalize_pdf_name(pdir, pdf_path)
        _ui(f"  {pdir.name}: fell back to {parser_name}")
        converted_dirs.append(pdir)
        stats["converted"] += 1
        return True

    if prefer_fallback:
        for idx, (pdir, pdf_path) in enumerate(to_convert):
            _ui(f"[{idx + 1}/{len(to_convert)}] {pdir.name}")
            _run_fallback(pdir, pdf_path)
    elif use_local:
        # Local MinerU: sequential single-file conversion
        from scholaraio.providers.mineru import convert_pdf

        for idx, (pdir, pdf_path) in enumerate(to_convert):
            _ui(f"[{idx + 1}/{len(to_convert)}] {pdir.name}")
            mineru_opts = ConvertOptions(
                api_url=cfg.ingest.mineru_endpoint,
                output_dir=pdir,
                backend=cfg.ingest.mineru_backend_local,
                cloud_model_version=cfg.ingest.mineru_model_version_cloud,
                lang=cfg.ingest.mineru_lang,
                parse_method=cfg.ingest.mineru_parse_method,
                formula_enable=cfg.ingest.mineru_enable_formula,
                table_enable=cfg.ingest.mineru_enable_table,
            )
            result = convert_pdf(pdf_path, mineru_opts)
            if not result.success:
                _ui(f"  MinerU failed: {result.error}")
                if is_pdf_validation_error(result):
                    stats["failed"] += 1
                    continue
                _run_fallback(pdir, pdf_path)
                continue

            postprocess_convert = _pipeline_attr("_postprocess_convert", batch_postprocess.postprocess_convert)
            postprocess_convert(pdir, pdf_path, result)
            converted_dirs.append(pdir)
            stats["converted"] += 1
    elif not api_key:
        for idx, (pdir, pdf_path) in enumerate(to_convert):
            _ui(f"[{idx + 1}/{len(to_convert)}] {pdir.name}")
            _run_fallback(pdir, pdf_path)
    else:
        # Cloud MinerU: true batch conversion via convert_pdfs_cloud_batch
        import tempfile

        from scholaraio.providers.mineru import (
            ConvertOptions,
            _convert_long_pdf_cloud,
            _plan_cloud_chunking,
            convert_pdfs_cloud_batch,
        )

        # Collect PDF paths for cloud batch conversion.
        pdf_paths: list[Path] = []
        dir_map: dict[Path, Path] = {}
        chunked_items: list[tuple[Path, Path, int, str]] = []
        default_chunk_size = getattr(cfg.ingest, "chunk_page_limit", 100)
        for pdir, pdf in to_convert:
            should_chunk, chunk_size, reason = _plan_cloud_chunking(
                pdf,
                default_chunk_size=default_chunk_size,
            )
            if should_chunk:
                chunked_items.append((pdir, pdf, chunk_size, reason))
                continue
            dir_map[pdf] = pdir
            pdf_paths.append(pdf)

        if pdf_paths:
            with tempfile.TemporaryDirectory(prefix="scholaraio_batch_") as tmp:
                tmp_dir = Path(tmp)
                batch_opts = ConvertOptions(
                    output_dir=tmp_dir,
                    backend=cfg.ingest.mineru_backend_local,
                    cloud_model_version=cfg.ingest.mineru_model_version_cloud,
                    lang=cfg.ingest.mineru_lang,
                    parse_method=cfg.ingest.mineru_parse_method,
                    formula_enable=cfg.ingest.mineru_enable_formula,
                    table_enable=cfg.ingest.mineru_enable_table,
                    upload_workers=cfg.ingest.mineru_upload_workers,
                    upload_retries=cfg.ingest.mineru_upload_retries,
                    download_retries=cfg.ingest.mineru_download_retries,
                    poll_timeout=cfg.ingest.mineru_poll_timeout,
                )

                batch_results = convert_pdfs_cloud_batch(
                    pdf_paths,
                    batch_opts,
                    api_key=api_key,
                    cloud_url=cfg.ingest.mineru_cloud_url,
                    batch_size=cfg.ingest.mineru_batch_size,
                )

                for br in batch_results:
                    pdir = dir_map.get(br.pdf_path)
                    if pdir is None:
                        _log_error("batch result pdf %s not in dir_map", br.pdf_path)
                        stats["failed"] += 1
                        continue

                    if not br.success:
                        _ui(f"  {pdir.name}: MinerU failed: {br.error}")
                        if is_pdf_validation_error(br):
                            stats["failed"] += 1
                            continue
                        _run_fallback(pdir, br.pdf_path)
                        continue

                    md_src = br.md_path if br.md_path and br.md_path.exists() else None
                    if md_src is None:
                        _ui(f"  {pdir.name}: MinerU did not produce valid markdown; falling back locally")
                        _run_fallback(pdir, br.pdf_path)
                        continue

                    # Move .md to paper_dir/paper.md
                    paper_md = pdir / "paper.md"
                    shutil.move(str(md_src), str(paper_md))
                    move_batch_images = _pipeline_attr("_move_batch_images", batch_assets.move_batch_images)
                    move_batch_images(paper_md, pdir, br.pdf_path.stem, md_src, tmp_dir)

                    # Preserve source PDF under the paper-directory basename.
                    pdf_path = br.pdf_path
                    if pdf_path.exists() and pdf_path.parent == pdir:
                        from scholaraio.stores.papers import normalize_pdf_name

                        normalize_pdf_name(pdir, pdf_path)

                    _ui(f"  {pdir.name}: OK")
                    converted_dirs.append(pdir)
                    stats["converted"] += 1

        for idx, (pdir, pdf_path, chunk_size, reason) in enumerate(chunked_items, start=len(pdf_paths) + 1):
            _ui(f"[{idx}/{len(pdf_paths) + len(chunked_items)}] {pdir.name}")
            _ui(f"  {pdir.name}: cloud chunking ({reason}, chunk_size={chunk_size})")
            mineru_opts = ConvertOptions(
                output_dir=pdir,
                backend=cfg.ingest.mineru_backend_local,
                cloud_model_version=cfg.ingest.mineru_model_version_cloud,
                lang=cfg.ingest.mineru_lang,
                parse_method=cfg.ingest.mineru_parse_method,
                formula_enable=cfg.ingest.mineru_enable_formula,
                table_enable=cfg.ingest.mineru_enable_table,
                upload_workers=cfg.ingest.mineru_upload_workers,
                upload_retries=cfg.ingest.mineru_upload_retries,
                download_retries=cfg.ingest.mineru_download_retries,
                poll_timeout=cfg.ingest.mineru_poll_timeout,
            )
            try:
                result = _convert_long_pdf_cloud(
                    pdf_path,
                    mineru_opts,
                    api_key=api_key,
                    cloud_url=cfg.ingest.mineru_cloud_url,
                    chunk_size=chunk_size,
                )
            except ImportError as exc:
                _ui(f"  {pdir.name}: cloud chunking dependency missing; falling back locally: {exc}")
                _run_fallback(pdir, pdf_path)
                continue
            except Exception as exc:
                _ui(f"  {pdir.name}: cloud chunking failed; falling back locally: {exc}")
                _run_fallback(pdir, pdf_path)
                continue
            if not result.success:
                _ui(f"  {pdir.name}: MinerU failed: {result.error}")
                if is_pdf_validation_error(result):
                    stats["failed"] += 1
                    continue
                _run_fallback(pdir, pdf_path)
                continue
            postprocess_convert = _pipeline_attr("_postprocess_convert", batch_postprocess.postprocess_convert)
            postprocess_convert(pdir, pdf_path, result)
            converted_dirs.append(pdir)
            stats["converted"] += 1

    _ui(
        f"Batch conversion completed: {stats['converted']} succeeded / {stats['failed']} failed / {stats['skipped']} skipped"
    )

    # Post-processing: abstract backfill + optional enrich (toc + l3)
    if converted_dirs:
        run_batch_postprocess = _pipeline_attr("_batch_postprocess", batch_postprocess.batch_postprocess)
        run_batch_postprocess(converted_dirs, cfg, enrich=enrich)

    return stats
