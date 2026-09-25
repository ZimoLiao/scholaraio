"""Paper/global ingest pipeline steps."""

from __future__ import annotations

import json as _json
import logging
from pathlib import Path

from scholaraio.core.config import Config
from scholaraio.core.log import ui as _base_ui
from scholaraio.services.ingest.types import StepResult

_log = logging.getLogger(__name__)
ui = _base_ui


def _ui(message: str = "") -> None:
    """Emit UI output while honoring canonical pipeline-level monkeypatches."""
    from scholaraio.services.ingest import pipeline as pipeline_mod

    pipeline_ui = getattr(pipeline_mod, "ui", _base_ui)
    if pipeline_ui is not _base_ui:
        pipeline_ui(message)
        return
    ui(message)


def step_toc(json_path: Path, cfg: Config, opts: dict) -> StepResult:
    """LLM 提取 TOC 写入 JSON（papers 作用域封装）。

    Args:
        json_path: 论文 JSON 路径（meta.json）。
        cfg: 全局配置。
        opts: 运行选项。

    Returns:
        ``StepResult.OK`` 成功, ``StepResult.FAIL`` 失败, ``StepResult.SKIP`` 跳过。
    """
    from scholaraio.services.loader import enrich_toc

    md_path = json_path.parent / "paper.md"
    if not md_path.exists():
        _log.debug("skipping (no paper.md): %s", json_path.parent.name)
        return StepResult.SKIP

    if opts.get("dry_run"):
        _log.debug("would run toc: %s", json_path.stem)
        return StepResult.OK

    ok = enrich_toc(
        json_path,
        md_path,
        cfg,
        force=opts.get("force", False),
        inspect=opts.get("inspect", False),
    )
    return StepResult.OK if ok else StepResult.FAIL


def step_l3(json_path: Path, cfg: Config, opts: dict) -> StepResult:
    """LLM 提取结论段写入 JSON（papers 作用域封装）。

    Args:
        json_path: 论文 JSON 路径（meta.json）。
        cfg: 全局配置。
        opts: 运行选项。

    Returns:
        ``StepResult.OK`` 成功, ``StepResult.FAIL`` 失败, ``StepResult.SKIP`` 跳过。
    """
    from scholaraio.services.loader import enrich_l3

    md_path = json_path.parent / "paper.md"
    if not md_path.exists():
        _log.debug("skipping (no paper.md): %s", json_path.parent.name)
        return StepResult.SKIP

    if opts.get("dry_run"):
        _log.debug("would run l3: %s", json_path.stem)
        return StepResult.OK

    ok = enrich_l3(
        json_path,
        md_path,
        cfg,
        force=opts.get("force", False),
        max_retries=opts.get("max_retries", 2),
        inspect=opts.get("inspect", False),
    )
    return StepResult.OK if ok else StepResult.FAIL


def step_translate(json_path: Path, cfg: Config, opts: dict) -> StepResult:
    """翻译论文 Markdown 到目标语言（papers 作用域）。

    Args:
        json_path: 论文 JSON 路径（meta.json）。
        cfg: 全局配置。
        opts: 运行选项。

    Returns:
        ``StepResult.OK`` 成功, ``StepResult.FAIL`` 失败, ``StepResult.SKIP`` 跳过。
    """
    from scholaraio.services.translate import SKIP_ALL_CHUNKS_FAILED, translate_paper

    paper_d = json_path.parent
    md_path = paper_d / "paper.md"
    if not md_path.exists():
        _log.debug("skipping translate (no paper.md): %s", paper_d.name)
        return StepResult.SKIP

    if opts.get("dry_run"):
        _log.debug("would translate: %s", paper_d.name)
        return StepResult.OK

    target_lang = opts.get("translate_lang") or cfg.translate.target_lang
    try:
        from scholaraio.services.translate import validate_lang

        target_lang = validate_lang(target_lang)
    except ValueError as exc:
        _ui(f"  Skipping translation (invalid language: {exc})")
        return StepResult.SKIP
    force = opts.get("force", False)
    tr = translate_paper(paper_d, cfg, target_lang=target_lang, force=force)
    if tr.partial:
        _ui(
            f"  Translation interrupted: completed {tr.completed_chunks}/{tr.total_chunks} chunks; rerun later to resume"
        )
        return StepResult.FAIL
    if tr.skip_reason == SKIP_ALL_CHUNKS_FAILED:
        _ui("  Translation failed: all chunks failed")
        return StepResult.FAIL
    if not tr.ok:
        return StepResult.SKIP
    _ui(f"  Translated: {tr.path.name}")  # type: ignore[union-attr]
    return StepResult.OK


def step_embed(papers_dir: Path, cfg: Config, opts: dict) -> StepResult:
    """生成语义向量写入 index.db（global 作用域）。

    Args:
        papers_dir: 论文目录。
        cfg: 全局配置。
        opts: 运行选项。

    Returns:
        ``StepResult.OK``；缺少 embed 依赖时跳过并返回 ``StepResult.SKIP``。
    """
    try:
        from scholaraio.services.vectors import build_vectors
    except ImportError:
        _ui("Skipping embed step: missing dependencies; install with: pip install scholaraio[embed]")
        return StepResult.SKIP

    db_path = cfg.index_db
    rebuild = opts.get("rebuild", False)

    if opts.get("dry_run"):
        _log.debug("would %s vectors: %s -> %s", "rebuild" if rebuild else "update", papers_dir, db_path)
        return StepResult.OK

    count = build_vectors(papers_dir, db_path, rebuild=rebuild, cfg=cfg)
    _ui(f"Vector index done, {count} new.")
    return StepResult.OK


def step_index(papers_dir: Path, cfg: Config, opts: dict) -> StepResult:
    """更新 SQLite FTS5 索引（global 作用域）。

    Args:
        papers_dir: 论文目录。
        cfg: 全局配置。
        opts: 运行选项。

    Returns:
        ``StepResult.OK``。
    """
    from scholaraio.services.index import build_index

    db_path = cfg.index_db
    rebuild = opts.get("rebuild", False)

    if opts.get("dry_run"):
        _log.debug("would %s index: %s -> %s", "rebuild" if rebuild else "update", papers_dir, db_path)
        return StepResult.OK

    _ui(f"{'Rebuild' if rebuild else 'Update'} index: {papers_dir} -> {db_path}")
    count = build_index(papers_dir, db_path, rebuild=rebuild)
    _ui(f"Index done, {count} papers.")
    return StepResult.OK


def step_refetch(json_path: Path, cfg: Config, opts: dict) -> StepResult:
    """重新查询 API 补全引用量等缺失字段（papers 作用域封装）。

    Args:
        json_path: 论文 JSON 路径。
        cfg: 全局配置。
        opts: 运行选项。

    Returns:
        ``StepResult.OK`` 有更新, ``StepResult.SKIP`` 跳过。
    """
    data = _json.loads(json_path.read_text(encoding="utf-8"))
    doi = data.get("doi", "")
    cc = data.get("citation_count") or {}
    has_citations = bool(cc)

    if not doi:
        _log.debug("skipping (no DOI): %s", json_path.stem)
        return StepResult.SKIP

    if has_citations and not opts.get("force", False):
        return StepResult.SKIP

    if opts.get("dry_run"):
        _log.debug("would refetch: %s (doi=%s)", json_path.stem, doi)
        return StepResult.OK

    if opts.get("no_api"):
        _log.debug("skipping (--no-api): %s", json_path.stem)
        return StepResult.SKIP

    from scholaraio.services.ingest_metadata import refetch_metadata

    changed = refetch_metadata(json_path, db_path=cfg.index_db)
    if changed:
        _log.debug("updated: %s", json_path.stem)
    else:
        _log.debug("no change: %s", json_path.stem)
    return StepResult.OK if changed else StepResult.SKIP
