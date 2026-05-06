from __future__ import annotations

import base64
from pathlib import Path

from scholaraio.core.config import Config
from scholaraio.providers.mineru import ConvertResult, PDFValidationResult
from scholaraio.services.ingest.pipeline import InboxCtx, StepResult, _process_inbox, batch_convert_pdfs, step_mineru
from scholaraio.services.ingest_metadata._models import PaperMetadata


def _allow_pdf_validation(monkeypatch):
    import scholaraio.providers.mineru as mineru

    monkeypatch.setattr(
        mineru,
        "validate_pdf_for_mineru",
        lambda _path: PDFValidationResult(ok=True, page_count=1, deep_checked=True),
    )


def test_cloud_batch_uses_safe_asset_directory_for_long_pdf_name(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    papers = tmp_path / "papers"
    pending = tmp_path / "pending"
    long_stem = "a" * 250
    pdf = inbox / f"{long_stem}.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    cfg = Config()
    cfg._root = tmp_path
    cfg.paths.papers_dir = "papers"
    monkeypatch.setattr(cfg, "resolved_mineru_api_key", lambda: "token")

    import scholaraio.providers.mineru as mineru
    import scholaraio.services.ingest.pipeline as pipeline

    monkeypatch.setattr(mineru, "check_server", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(mineru, "_plan_cloud_chunking", lambda *_args, **_kwargs: (False, 600, ""))

    def fake_cloud_batch(pdf_paths, opts, *, api_key, cloud_url, batch_size):
        safe_stem = Path(mineru._cloud_safe_pdf_name(pdf_paths[0])).stem
        md_dir = opts.output_dir / f"0000_{safe_stem}" / safe_stem
        images_dir = md_dir / "images"
        images_dir.mkdir(parents=True)
        (images_dir / "figure.png").write_bytes(b"img")
        md_path = md_dir / "index.md"
        md_path.write_text("# ok\n", encoding="utf-8")
        return [ConvertResult(pdf_path=pdf_paths[0], md_path=md_path, success=True)]

    def fake_extract(ctx):
        images_dir, _, _ = pipeline._find_assets(ctx.inbox_dir, ctx.pdf_path.stem, ctx.md_path.stem)
        assert images_dir is not None
        assert len(images_dir.name.encode("utf-8")) <= 255
        assert long_stem not in images_dir.name
        return StepResult.OK

    monkeypatch.setattr(mineru, "convert_pdfs_cloud_batch", fake_cloud_batch)
    monkeypatch.setitem(pipeline.STEPS, "extract", pipeline.StepDef(fn=fake_extract, scope="inbox", desc="test"))

    _process_inbox(
        inbox,
        papers,
        pending,
        {},
        ["mineru", "extract"],
        cfg,
        {},
        False,
        [],
    )


def test_move_assets_normalizes_safe_stem_json_artifacts(tmp_path):
    import scholaraio.providers.mineru as mineru
    import scholaraio.services.ingest.pipeline as pipeline

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    dest = tmp_path / "paper"
    dest.mkdir()
    long_stem = "a" * 250
    safe_stem = Path(mineru._cloud_safe_pdf_name(Path(f"{long_stem}.pdf"))).stem
    (inbox / f"{safe_stem}_layout.json").write_text("{}", encoding="utf-8")
    (inbox / f"{safe_stem}_content_list.json").write_text("[]", encoding="utf-8")
    (inbox / f"{safe_stem}_paper_origin.pdf").write_bytes(b"%PDF-1.4\n")

    pipeline._move_assets(inbox, dest, long_stem, long_stem)

    assert (dest / "layout.json").exists()
    assert (dest / "content_list.json").exists()
    assert (dest / "paper_origin.pdf").exists()
    assert not any(path.name.startswith(safe_stem) for path in dest.iterdir())


def test_move_assets_moves_generic_image_dir_and_rewrites_markdown_refs(tmp_path):
    import scholaraio.services.ingest.pipeline as pipeline

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    dest = tmp_path / "paper"
    dest.mkdir()
    images = inbox / "paper_images"
    images.mkdir()
    (images / "fig.png").write_bytes(b"png")
    paper_md = dest / "paper.md"
    paper_md.write_text("![fig](paper_images/fig.png)\n", encoding="utf-8")

    pipeline._move_assets(inbox, dest, "paper", "paper")

    assert (dest / "images" / "fig.png").read_bytes() == b"png"
    assert paper_md.read_text(encoding="utf-8") == "![fig](images/fig.png)\n"


def test_process_inbox_local_mineru_images_reach_paper_directory(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    papers = tmp_path / "papers"
    pending = tmp_path / "pending"
    pdf = inbox / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    image_bytes = b"fake-png"

    cfg = Config()
    cfg._root = tmp_path

    import scholaraio.providers.mineru as mineru
    import scholaraio.services.ingest.pipeline as pipeline

    _allow_pdf_validation(monkeypatch)
    monkeypatch.setattr(mineru, "check_server", lambda *_args, **_kwargs: True)

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {
                "results": {
                    pdf.stem: {
                        "md_content": "![fig](images/fig.png)\n",
                        "images": {"fig.png": "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")},
                    }
                }
            }

    monkeypatch.setattr(mineru.requests, "post", lambda *_args, **_kwargs: FakeResponse())

    def fake_extract(ctx):
        ctx.meta = PaperMetadata(
            title="Local MinerU Images",
            first_author_lastname="Zhang",
            year=2026,
            doi="10.1000/local-images",
        )
        return StepResult.OK

    monkeypatch.setattr(pipeline.STEPS["extract"], "fn", fake_extract)

    _process_inbox(
        inbox,
        papers,
        pending,
        {},
        ["mineru", "extract", "ingest"],
        cfg,
        {"no_api": True},
        False,
        [],
    )

    paper_dirs = list(papers.iterdir())
    assert len(paper_dirs) == 1
    paper_dir = paper_dirs[0]
    assert (paper_dir / "paper.md").read_text(encoding="utf-8") == "![fig](images/fig.png)\n"
    assert (paper_dir / "images" / "fig.png").read_bytes() == image_bytes


def test_step_mineru_falls_back_without_cloud_key(tmp_path, monkeypatch):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    cfg = Config()
    monkeypatch.setattr(cfg, "resolved_mineru_api_key", lambda: "")

    ctx = InboxCtx(
        pdf_path=pdf,
        inbox_dir=tmp_path,
        papers_dir=tmp_path / "papers",
        existing_dois={},
        cfg=cfg,
        opts={},
    )

    import scholaraio.providers.mineru as mineru
    import scholaraio.providers.pdf_fallback as pdf_fallback

    _allow_pdf_validation(monkeypatch)
    monkeypatch.setattr(mineru, "check_server", lambda *_: False)
    monkeypatch.setattr(mineru, "_get_pdf_page_count", lambda *_: 1)
    monkeypatch.setattr(
        mineru,
        "convert_pdf",
        lambda *_: ConvertResult(pdf_path=pdf, success=False, error="should not be called"),
    )

    calls: list[tuple[Path, Path]] = []

    def _fallback(pdf_path: Path, md_path: Path, parser_order=None, auto_detect=True):
        calls.append((pdf_path, md_path))
        md_path.write_text("fallback ok\n", encoding="utf-8")
        return True, "pymupdf", None

    monkeypatch.setattr(pdf_fallback, "convert_pdf_with_fallback", _fallback)

    result = step_mineru(ctx)

    assert result == StepResult.OK
    assert calls == [(pdf, tmp_path / "paper.md")]
    assert ctx.md_path == tmp_path / "paper.md"
    assert ctx.md_path.read_text(encoding="utf-8") == "fallback ok\n"


def test_step_mineru_skips_page_count_when_mineru_unreachable_and_no_cloud_key(tmp_path, monkeypatch):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    cfg = Config()
    monkeypatch.setattr(cfg, "resolved_mineru_api_key", lambda: "")

    ctx = InboxCtx(
        pdf_path=pdf,
        inbox_dir=tmp_path,
        papers_dir=tmp_path / "papers",
        existing_dois={},
        cfg=cfg,
        opts={},
    )

    import scholaraio.providers.mineru as mineru
    import scholaraio.providers.pdf_fallback as pdf_fallback

    _allow_pdf_validation(monkeypatch)

    def _page_count(*_args, **_kwargs):
        raise AssertionError("page count should not be queried when MinerU is unreachable without cloud key")

    monkeypatch.setattr(mineru, "check_server", lambda *_: False)
    monkeypatch.setattr(mineru, "_get_pdf_page_count", _page_count)
    monkeypatch.setattr(
        pdf_fallback,
        "convert_pdf_with_fallback",
        lambda _pdf, md_path, **_kwargs: (
            md_path.write_text("fallback ok\n", encoding="utf-8"),
            True,
            "pymupdf",
            None,
        )[1:],
    )

    result = step_mineru(ctx)

    assert result == StepResult.OK
    assert ctx.md_path == tmp_path / "paper.md"


def test_batch_convert_pdfs_falls_back_without_cloud_key(tmp_path, monkeypatch):
    paper_dir = tmp_path / "papers" / "Smith-2023-Test"
    paper_dir.mkdir(parents=True)
    (paper_dir / "meta.json").write_text("{}", encoding="utf-8")
    pdf = paper_dir / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    cfg = Config()
    cfg._root = tmp_path
    cfg.paths.papers_dir = "papers"
    monkeypatch.setattr(cfg, "resolved_mineru_api_key", lambda: "")

    import scholaraio.providers.mineru as mineru
    import scholaraio.providers.pdf_fallback as pdf_fallback
    import scholaraio.services.ingest.pipeline as pipeline

    monkeypatch.setattr(mineru, "check_server", lambda *_: False)
    monkeypatch.setattr(pipeline, "_batch_postprocess", lambda *_args, **_kwargs: None)

    calls: list[tuple[Path, Path]] = []

    def _fallback(pdf_path: Path, md_path: Path, parser_order=None, auto_detect=True):
        calls.append((pdf_path, md_path))
        md_path.write_text("fallback batch ok\n", encoding="utf-8")
        return True, "docling", None

    monkeypatch.setattr(pdf_fallback, "convert_pdf_with_fallback", _fallback)

    stats = batch_convert_pdfs(cfg, enrich=False)

    assert stats == {"converted": 1, "failed": 0, "skipped": 0}
    assert calls == [(pdf, paper_dir / "paper.md")]
    assert (paper_dir / "paper.md").read_text(encoding="utf-8") == "fallback batch ok\n"


def test_batch_convert_pdfs_fallback_cleans_noncanonical_source_pdf(tmp_path, monkeypatch):
    paper_dir = tmp_path / "papers" / "Smith-2023-Test"
    paper_dir.mkdir(parents=True)
    (paper_dir / "meta.json").write_text("{}", encoding="utf-8")
    pdf = paper_dir / "source.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    cfg = Config()
    cfg._root = tmp_path
    cfg.paths.papers_dir = "papers"
    monkeypatch.setattr(cfg, "resolved_mineru_api_key", lambda: "")

    import scholaraio.providers.mineru as mineru
    import scholaraio.providers.pdf_fallback as pdf_fallback
    import scholaraio.services.ingest.pipeline as pipeline

    monkeypatch.setattr(mineru, "check_server", lambda *_: False)
    monkeypatch.setattr(pipeline, "_batch_postprocess", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        pdf_fallback,
        "convert_pdf_with_fallback",
        lambda _pdf, md_path, **_kwargs: (
            md_path.write_text("fallback batch ok\n", encoding="utf-8"),
            True,
            "docling",
            None,
        )[1:],
    )

    stats = batch_convert_pdfs(cfg, enrich=False)

    assert stats == {"converted": 1, "failed": 0, "skipped": 0}
    assert (paper_dir / "paper.md").read_text(encoding="utf-8") == "fallback batch ok\n"
    assert not pdf.exists()


def test_batch_convert_pdfs_cloud_splits_items_that_exceed_new_limits(tmp_path, monkeypatch):
    paper_dir = tmp_path / "papers" / "Smith-2023-Test"
    paper_dir.mkdir(parents=True)
    (paper_dir / "meta.json").write_text("{}", encoding="utf-8")
    pdf = paper_dir / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    cfg = Config()
    cfg._root = tmp_path
    cfg.paths.papers_dir = "papers"
    monkeypatch.setattr(cfg, "resolved_mineru_api_key", lambda: "token")

    import scholaraio.providers.mineru as mineru
    import scholaraio.services.ingest.pipeline as pipeline

    monkeypatch.setattr(mineru, "check_server", lambda *_: False)
    monkeypatch.setattr(pipeline, "_batch_postprocess", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mineru, "_plan_cloud_chunking", lambda *_args, **_kwargs: (True, 320, "too large"))
    monkeypatch.setattr(
        mineru,
        "convert_pdfs_cloud_batch",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should use split path")),
    )
    captured: dict[str, object] = {}

    def fake_convert_long(pdf_path, opts, *, api_key, cloud_url, chunk_size):
        captured["chunk_size"] = chunk_size
        (paper_dir / "paper.md").write_text("split batch ok\n", encoding="utf-8")
        return ConvertResult(pdf_path=pdf_path, md_path=paper_dir / "paper.md", success=True)

    monkeypatch.setattr(mineru, "_convert_long_pdf_cloud", fake_convert_long)

    stats = batch_convert_pdfs(cfg, enrich=False)

    assert stats == {"converted": 1, "failed": 0, "skipped": 0}
    assert captured["chunk_size"] == 320
    assert (paper_dir / "paper.md").read_text(encoding="utf-8") == "split batch ok\n"


def test_batch_convert_pdfs_cloud_split_importerror_falls_back(tmp_path, monkeypatch):
    paper_dir = tmp_path / "papers" / "Smith-2023-Test"
    paper_dir.mkdir(parents=True)
    (paper_dir / "meta.json").write_text("{}", encoding="utf-8")
    pdf = paper_dir / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    cfg = Config()
    cfg._root = tmp_path
    cfg.paths.papers_dir = "papers"
    monkeypatch.setattr(cfg, "resolved_mineru_api_key", lambda: "token")

    import scholaraio.providers.mineru as mineru
    import scholaraio.providers.pdf_fallback as pdf_fallback
    import scholaraio.services.ingest.pipeline as pipeline

    monkeypatch.setattr(mineru, "check_server", lambda *_: False)
    monkeypatch.setattr(pipeline, "_batch_postprocess", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mineru, "_plan_cloud_chunking", lambda *_args, **_kwargs: (True, 320, "too large"))
    monkeypatch.setattr(
        mineru,
        "_convert_long_pdf_cloud",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ImportError("install pymupdf")),
    )
    monkeypatch.setattr(
        pdf_fallback,
        "convert_pdf_with_fallback",
        lambda _pdf, md_path, **_kwargs: (
            md_path.write_text("fallback batch split ok\n", encoding="utf-8"),
            True,
            "docling",
            None,
        )[1:],
    )

    stats = batch_convert_pdfs(cfg, enrich=False)

    assert stats == {"converted": 1, "failed": 0, "skipped": 0}
    assert (paper_dir / "paper.md").read_text(encoding="utf-8") == "fallback batch split ok\n"


def test_batch_convert_pdfs_cloud_batch_success_counts_each_result(tmp_path, monkeypatch):
    paper_dir = tmp_path / "papers" / "Smith-2023-Test"
    paper_dir.mkdir(parents=True)
    (paper_dir / "meta.json").write_text("{}", encoding="utf-8")
    pdf = paper_dir / "source.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    tmp_md = tmp_path / "batch-out" / "source.md"
    tmp_md.parent.mkdir(parents=True)
    tmp_md.write_text("batch ok\n", encoding="utf-8")

    cfg = Config()
    cfg._root = tmp_path
    cfg.paths.papers_dir = "papers"
    monkeypatch.setattr(cfg, "resolved_mineru_api_key", lambda: "token")

    import scholaraio.providers.mineru as mineru
    import scholaraio.services.ingest.pipeline as pipeline

    monkeypatch.setattr(mineru, "check_server", lambda *_: False)
    monkeypatch.setattr(pipeline, "_batch_postprocess", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mineru, "_plan_cloud_chunking", lambda *_args, **_kwargs: (False, 600, ""))
    monkeypatch.setattr(
        mineru,
        "convert_pdfs_cloud_batch",
        lambda *_args, **_kwargs: [ConvertResult(pdf_path=pdf, md_path=tmp_md, success=True)],
    )

    stats = batch_convert_pdfs(cfg, enrich=False)

    assert stats == {"converted": 1, "failed": 0, "skipped": 0}
    assert (paper_dir / "paper.md").read_text(encoding="utf-8") == "batch ok\n"
    assert not pdf.exists()


def test_batch_convert_pdfs_cloud_batch_missing_md_falls_back(tmp_path, monkeypatch):
    paper_dir = tmp_path / "papers" / "Smith-2023-Test"
    paper_dir.mkdir(parents=True)
    (paper_dir / "meta.json").write_text("{}", encoding="utf-8")
    pdf = paper_dir / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    cfg = Config()
    cfg._root = tmp_path
    cfg.paths.papers_dir = "papers"
    monkeypatch.setattr(cfg, "resolved_mineru_api_key", lambda: "token")

    import scholaraio.providers.mineru as mineru
    import scholaraio.providers.pdf_fallback as pdf_fallback
    import scholaraio.services.ingest.pipeline as pipeline

    monkeypatch.setattr(mineru, "check_server", lambda *_: False)
    monkeypatch.setattr(pipeline, "_batch_postprocess", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mineru, "_plan_cloud_chunking", lambda *_args, **_kwargs: (False, 600, ""))
    monkeypatch.setattr(
        mineru,
        "convert_pdfs_cloud_batch",
        lambda *_args, **_kwargs: [ConvertResult(pdf_path=pdf, md_path=None, success=True)],
    )
    monkeypatch.setattr(
        pdf_fallback,
        "convert_pdf_with_fallback",
        lambda _pdf, md_path, **_kwargs: (
            md_path.write_text("fallback batch ok\n", encoding="utf-8"),
            True,
            "docling",
            None,
        )[1:],
    )

    stats = batch_convert_pdfs(cfg, enrich=False)

    assert stats == {"converted": 1, "failed": 0, "skipped": 0}
    assert (paper_dir / "paper.md").read_text(encoding="utf-8") == "fallback batch ok\n"


def test_batch_convert_pdfs_cloud_batch_moves_markdown_relative_images(tmp_path, monkeypatch):
    paper_dir = tmp_path / "papers" / "Smith-2023-Test"
    paper_dir.mkdir(parents=True)
    (paper_dir / "meta.json").write_text("{}", encoding="utf-8")
    pdf = paper_dir / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    md_dir = tmp_path / "batch-out" / "source"
    md_dir.mkdir(parents=True)
    tmp_md = md_dir / "index.md"
    tmp_md.write_text("![img](images/fig.png)\n", encoding="utf-8")
    (md_dir / "images").mkdir()
    (md_dir / "images" / "fig.png").write_bytes(b"png")

    cfg = Config()
    cfg._root = tmp_path
    cfg.paths.papers_dir = "papers"
    monkeypatch.setattr(cfg, "resolved_mineru_api_key", lambda: "token")

    import scholaraio.providers.mineru as mineru
    import scholaraio.services.ingest.pipeline as pipeline

    monkeypatch.setattr(mineru, "check_server", lambda *_: False)
    monkeypatch.setattr(pipeline, "_batch_postprocess", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mineru, "_plan_cloud_chunking", lambda *_args, **_kwargs: (False, 600, ""))
    monkeypatch.setattr(
        mineru,
        "convert_pdfs_cloud_batch",
        lambda *_args, **_kwargs: [ConvertResult(pdf_path=pdf, md_path=tmp_md, success=True)],
    )

    stats = batch_convert_pdfs(cfg, enrich=False)

    assert stats == {"converted": 1, "failed": 0, "skipped": 0}
    assert (paper_dir / "paper.md").read_text(encoding="utf-8") == "![img](images/fig.png)\n"
    assert (paper_dir / "images" / "fig.png").exists()


def test_batch_convert_pdfs_cloud_batch_does_not_skip_duplicate_source_stems(tmp_path, monkeypatch):
    paper_a = tmp_path / "papers" / "Alpha-2023-Test"
    paper_b = tmp_path / "papers" / "Beta-2023-Test"
    paper_a.mkdir(parents=True)
    paper_b.mkdir(parents=True)
    (paper_a / "meta.json").write_text("{}", encoding="utf-8")
    (paper_b / "meta.json").write_text("{}", encoding="utf-8")
    pdf_a = paper_a / "source.pdf"
    pdf_b = paper_b / "source.pdf"
    pdf_a.write_bytes(b"%PDF-1.4\n")
    pdf_b.write_bytes(b"%PDF-1.4\n")
    md_a = tmp_path / "batch-out-a" / "source.md"
    md_b = tmp_path / "batch-out-b" / "source.md"
    md_a.parent.mkdir(parents=True)
    md_b.parent.mkdir(parents=True)
    md_a.write_text("alpha\n", encoding="utf-8")
    md_b.write_text("beta\n", encoding="utf-8")

    cfg = Config()
    cfg._root = tmp_path
    cfg.paths.papers_dir = "papers"
    monkeypatch.setattr(cfg, "resolved_mineru_api_key", lambda: "token")

    import scholaraio.providers.mineru as mineru
    import scholaraio.services.ingest.pipeline as pipeline

    monkeypatch.setattr(mineru, "check_server", lambda *_: False)
    monkeypatch.setattr(pipeline, "_batch_postprocess", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mineru, "_plan_cloud_chunking", lambda *_args, **_kwargs: (False, 600, ""))
    monkeypatch.setattr(
        mineru,
        "convert_pdfs_cloud_batch",
        lambda *_args, **_kwargs: [
            ConvertResult(pdf_path=pdf_a, md_path=md_a, success=True),
            ConvertResult(pdf_path=pdf_b, md_path=md_b, success=True),
        ],
    )

    stats = batch_convert_pdfs(cfg, enrich=False)

    assert stats == {"converted": 2, "failed": 0, "skipped": 0}
    assert (paper_a / "paper.md").read_text(encoding="utf-8") == "alpha\n"
    assert (paper_b / "paper.md").read_text(encoding="utf-8") == "beta\n"


def test_process_inbox_cloud_batch_preserves_nested_markdown_result(tmp_path, monkeypatch):
    inbox_dir = tmp_path / "inbox"
    inbox_dir.mkdir()
    pdf = inbox_dir / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    nested_md = inbox_dir / "paper" / "index.md"
    nested_md.parent.mkdir(parents=True)
    nested_md.write_text("nested batch ok\n", encoding="utf-8")

    cfg = Config()
    cfg._root = tmp_path
    monkeypatch.setattr(cfg, "resolved_mineru_api_key", lambda: "token")

    import scholaraio.providers.mineru as mineru
    import scholaraio.services.ingest.pipeline as pipeline

    monkeypatch.setattr(mineru, "check_server", lambda *_: False)
    monkeypatch.setattr(mineru, "_plan_cloud_chunking", lambda *_args, **_kwargs: (False, 600, ""))
    monkeypatch.setattr(
        mineru,
        "convert_pdfs_cloud_batch",
        lambda *_args, **_kwargs: [ConvertResult(pdf_path=pdf, md_path=nested_md, success=True)],
    )

    observed: dict[str, Path | None] = {}
    original_extract = pipeline.STEPS["extract"].fn

    def fake_extract(ctx):
        observed["md_path"] = ctx.md_path
        ctx.status = "skipped"
        return StepResult.OK

    monkeypatch.setattr(pipeline.STEPS["extract"], "fn", fake_extract)

    try:
        _process_inbox(
            inbox_dir,
            tmp_path / "papers",
            tmp_path / "pending",
            {},
            ["mineru", "extract"],
            cfg,
            {},
            False,
            [],
        )
    finally:
        monkeypatch.setattr(pipeline.STEPS["extract"], "fn", original_extract)

    assert observed["md_path"] == nested_md


def test_process_inbox_cloud_batch_normalizes_nested_images_for_ingest_assets(tmp_path, monkeypatch):
    inbox_dir = tmp_path / "inbox"
    inbox_dir.mkdir()
    pdf = inbox_dir / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    nested_md = inbox_dir / "paper" / "index.md"
    nested_md.parent.mkdir(parents=True)
    nested_md.write_text("![img](images/fig.png)\n", encoding="utf-8")
    nested_images = nested_md.parent / "images"
    nested_images.mkdir()
    (nested_images / "fig.png").write_bytes(b"png")

    cfg = Config()
    cfg._root = tmp_path
    monkeypatch.setattr(cfg, "resolved_mineru_api_key", lambda: "token")

    import scholaraio.providers.mineru as mineru
    import scholaraio.services.ingest.pipeline as pipeline

    monkeypatch.setattr(mineru, "check_server", lambda *_: False)
    monkeypatch.setattr(mineru, "_plan_cloud_chunking", lambda *_args, **_kwargs: (False, 600, ""))
    monkeypatch.setattr(
        mineru,
        "convert_pdfs_cloud_batch",
        lambda *_args, **_kwargs: [ConvertResult(pdf_path=pdf, md_path=nested_md, success=True)],
    )

    observed: dict[str, object] = {}
    original_extract = pipeline.STEPS["extract"].fn

    def fake_extract(ctx):
        observed["md_path"] = ctx.md_path
        observed["images_dir"] = inbox_dir / "paper_mineru_images"
        assert observed["images_dir"].is_dir() is True
        assert (observed["images_dir"] / "fig.png").exists()
        ctx.status = "skipped"
        return StepResult.OK

    monkeypatch.setattr(pipeline.STEPS["extract"], "fn", fake_extract)

    try:
        _process_inbox(
            inbox_dir,
            tmp_path / "papers",
            tmp_path / "pending",
            {},
            ["mineru", "extract"],
            cfg,
            {},
            False,
            [],
        )
    finally:
        monkeypatch.setattr(pipeline.STEPS["extract"], "fn", original_extract)

    assert observed["md_path"] == nested_md


def test_process_inbox_cloud_batch_keeps_images_for_mineru_only(tmp_path, monkeypatch):
    inbox_dir = tmp_path / "inbox"
    inbox_dir.mkdir()
    pdf = inbox_dir / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    md_path = inbox_dir / "paper.md"
    images_dir = inbox_dir / "images"
    isolated_dir = inbox_dir / "0000_paper"

    cfg = Config()
    cfg._root = tmp_path
    monkeypatch.setattr(cfg, "resolved_mineru_api_key", lambda: "token")

    import scholaraio.providers.mineru as mineru

    monkeypatch.setattr(mineru, "check_server", lambda *_: False)
    monkeypatch.setattr(mineru, "_plan_cloud_chunking", lambda *_args, **_kwargs: (False, 600, ""))

    def fake_convert(*_args, **_kwargs):
        isolated_dir.mkdir()
        nested_md = isolated_dir / "index.md"
        nested_md.write_text("![img](images/fig.png)\n", encoding="utf-8")
        (isolated_dir / "images").mkdir()
        (isolated_dir / "images" / "fig.png").write_bytes(b"png")
        return [ConvertResult(pdf_path=pdf, md_path=nested_md, success=True)]

    monkeypatch.setattr(
        mineru,
        "convert_pdfs_cloud_batch",
        fake_convert,
    )

    _process_inbox(
        inbox_dir,
        tmp_path / "papers",
        tmp_path / "pending",
        {},
        ["mineru"],
        cfg,
        {},
        False,
        [],
    )

    assert md_path.exists() is True
    assert images_dir.is_dir() is True
    assert (images_dir / "fig.png").exists()
    assert not isolated_dir.exists()


def test_process_inbox_cloud_batch_failure_retries_mineru_per_file(tmp_path, monkeypatch):
    inbox_dir = tmp_path / "inbox"
    inbox_dir.mkdir()
    pdf = inbox_dir / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    cfg = Config()
    cfg._root = tmp_path
    monkeypatch.setattr(cfg, "resolved_mineru_api_key", lambda: "token")

    import scholaraio.providers.mineru as mineru
    import scholaraio.services.ingest.pipeline as pipeline

    mineru_calls: list[Path] = []
    extract_seen: dict[str, Path | None] = {}
    original_mineru = pipeline.STEPS["mineru"].fn
    original_extract = pipeline.STEPS["extract"].fn

    monkeypatch.setattr(mineru, "check_server", lambda *_: False)
    monkeypatch.setattr(mineru, "_plan_cloud_chunking", lambda *_args, **_kwargs: (False, 600, ""))
    monkeypatch.setattr(
        mineru,
        "convert_pdfs_cloud_batch",
        lambda *_args, **_kwargs: [ConvertResult(pdf_path=pdf, success=False, error="timeout")],
    )

    def fake_step_mineru(ctx):
        mineru_calls.append(ctx.pdf_path)
        ctx.md_path = inbox_dir / "paper.md"
        ctx.md_path.write_text("retried mineru ok\n", encoding="utf-8")
        return StepResult.OK

    def fake_extract(ctx):
        extract_seen["md_path"] = ctx.md_path
        ctx.status = "skipped"
        return StepResult.OK

    monkeypatch.setattr(pipeline.STEPS["mineru"], "fn", fake_step_mineru)
    monkeypatch.setattr(pipeline.STEPS["extract"], "fn", fake_extract)

    try:
        _process_inbox(
            inbox_dir,
            tmp_path / "papers",
            tmp_path / "pending",
            {},
            ["mineru", "extract"],
            cfg,
            {},
            False,
            [],
        )
    finally:
        monkeypatch.setattr(pipeline.STEPS["mineru"], "fn", original_mineru)
        monkeypatch.setattr(pipeline.STEPS["extract"], "fn", original_extract)

    assert mineru_calls == [pdf]
    assert extract_seen["md_path"] == inbox_dir / "paper.md"


def test_process_inbox_skips_cloud_batch_when_fallback_parser_is_preferred(tmp_path, monkeypatch):
    inbox_dir = tmp_path / "inbox"
    inbox_dir.mkdir()
    pdf = inbox_dir / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    cfg = Config()
    cfg._root = tmp_path
    cfg.ingest.pdf_preferred_parser = "docling"
    monkeypatch.setattr(cfg, "resolved_mineru_api_key", lambda: "token")

    import scholaraio.providers.mineru as mineru
    import scholaraio.services.ingest.pipeline as pipeline

    extract_seen: dict[str, Path | None] = {}
    original_mineru = pipeline.STEPS["mineru"].fn
    original_extract = pipeline.STEPS["extract"].fn

    monkeypatch.setattr(mineru, "check_server", lambda *_: False)
    monkeypatch.setattr(
        mineru,
        "convert_pdfs_cloud_batch",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("should not use cloud batch when docling is preferred")
        ),
    )

    def fake_step_mineru(ctx):
        ctx.md_path = inbox_dir / "paper.md"
        ctx.md_path.write_text("preferred parser path\n", encoding="utf-8")
        return StepResult.OK

    def fake_extract(ctx):
        extract_seen["md_path"] = ctx.md_path
        ctx.status = "skipped"
        return StepResult.OK

    monkeypatch.setattr(pipeline.STEPS["mineru"], "fn", fake_step_mineru)
    monkeypatch.setattr(pipeline.STEPS["extract"], "fn", fake_extract)

    try:
        _process_inbox(
            inbox_dir,
            tmp_path / "papers",
            tmp_path / "pending",
            {},
            ["mineru", "extract"],
            cfg,
            {},
            False,
            [],
        )
    finally:
        monkeypatch.setattr(pipeline.STEPS["mineru"], "fn", original_mineru)
        monkeypatch.setattr(pipeline.STEPS["extract"], "fn", original_extract)

    assert extract_seen["md_path"] == inbox_dir / "paper.md"


def test_step_mineru_prefers_docling_when_configured(tmp_path, monkeypatch):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    cfg = Config()
    cfg.ingest.pdf_preferred_parser = "docling"

    ctx = InboxCtx(
        pdf_path=pdf,
        inbox_dir=tmp_path,
        papers_dir=tmp_path / "papers",
        existing_dois={},
        cfg=cfg,
        opts={},
    )

    import scholaraio.providers.mineru as mineru
    import scholaraio.providers.pdf_fallback as pdf_fallback

    _allow_pdf_validation(monkeypatch)
    mineru_calls: list[Path] = []
    fallback_calls: list[tuple[Path, Path, list[str] | None]] = []

    monkeypatch.setattr(mineru, "check_server", lambda *_: True)
    monkeypatch.setattr(mineru, "_get_pdf_page_count", lambda *_: 1)
    monkeypatch.setattr(
        mineru,
        "convert_pdf",
        lambda pdf_path, *_args, **_kwargs: (
            mineru_calls.append(pdf_path),
            ConvertResult(pdf_path=pdf_path, success=False, error="should not be called"),
        )[1],
    )

    def _fallback(pdf_path: Path, md_path: Path, parser_order=None, auto_detect=True):
        fallback_calls.append((pdf_path, md_path, list(parser_order) if parser_order is not None else None))
        md_path.write_text("docling preferred\n", encoding="utf-8")
        return True, "docling", None

    monkeypatch.setattr(pdf_fallback, "convert_pdf_with_fallback", _fallback)

    result = step_mineru(ctx)

    assert result == StepResult.OK
    assert mineru_calls == []
    assert len(fallback_calls) == 1
    assert fallback_calls[0][:2] == (pdf, tmp_path / "paper.md")
    assert fallback_calls[0][2] is not None
    assert fallback_calls[0][2][0] == "docling"
    assert ctx.md_path == tmp_path / "paper.md"


def test_step_mineru_skips_page_count_when_preferred_parser_bypasses_mineru(tmp_path, monkeypatch):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    cfg = Config()
    cfg.ingest.pdf_preferred_parser = "docling"

    ctx = InboxCtx(
        pdf_path=pdf,
        inbox_dir=tmp_path,
        papers_dir=tmp_path / "papers",
        existing_dois={},
        cfg=cfg,
        opts={},
    )

    import scholaraio.providers.mineru as mineru
    import scholaraio.providers.pdf_fallback as pdf_fallback

    _allow_pdf_validation(monkeypatch)

    def _page_count(*_args, **_kwargs):
        raise AssertionError("page count should not be queried for fallback-only parsers")

    monkeypatch.setattr(mineru, "_get_pdf_page_count", _page_count)
    monkeypatch.setattr(mineru, "check_server", lambda *_: True)
    monkeypatch.setattr(
        pdf_fallback,
        "convert_pdf_with_fallback",
        lambda _pdf, md_path, **_kwargs: (
            md_path.write_text("docling preferred\n", encoding="utf-8"),
            True,
            "docling",
            None,
        )[1:],
    )

    result = step_mineru(ctx)

    assert result == StepResult.OK
    assert ctx.md_path == tmp_path / "paper.md"


def test_step_mineru_preferred_fallback_does_not_run_mineru_validation(tmp_path, monkeypatch):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"not a pdf")

    cfg = Config()
    cfg.ingest.pdf_preferred_parser = "docling"

    ctx = InboxCtx(
        pdf_path=pdf,
        inbox_dir=tmp_path,
        papers_dir=tmp_path / "papers",
        existing_dois={},
        cfg=cfg,
        opts={},
    )

    import scholaraio.providers.mineru as mineru
    import scholaraio.providers.pdf_fallback as pdf_fallback

    monkeypatch.setattr(
        mineru,
        "validate_pdf_for_mineru",
        lambda _path: PDFValidationResult(ok=False, error="PDF validation failed: should not run"),
    )
    monkeypatch.setattr(
        mineru,
        "check_server",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("fallback-only path should not check MinerU")),
    )
    monkeypatch.setattr(
        pdf_fallback,
        "convert_pdf_with_fallback",
        lambda _pdf, md_path, **_kwargs: (
            md_path.write_text("docling preferred\n", encoding="utf-8"),
            True,
            "docling",
            None,
        )[1:],
    )

    result = step_mineru(ctx)

    assert result == StepResult.OK
    assert ctx.md_path == tmp_path / "paper.md"
    assert ctx.md_path.read_text(encoding="utf-8") == "docling preferred\n"


def test_step_mineru_rejects_invalid_pdf_without_fallback(tmp_path, monkeypatch):
    pdf = tmp_path / "bad.pdf"
    pdf.write_bytes(b"not a pdf")

    cfg = Config()

    ctx = InboxCtx(
        pdf_path=pdf,
        inbox_dir=tmp_path,
        papers_dir=tmp_path / "papers",
        existing_dois={},
        cfg=cfg,
        opts={},
    )

    import scholaraio.providers.mineru as mineru
    import scholaraio.providers.pdf_fallback as pdf_fallback

    monkeypatch.setattr(mineru, "check_server", lambda *_: True)
    monkeypatch.setattr(
        pdf_fallback,
        "convert_pdf_with_fallback",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("invalid PDFs should not fallback")),
    )

    result = step_mineru(ctx)

    assert result == StepResult.FAIL
    assert ctx.status == "failed"
    assert ctx.md_path is None


def test_step_mineru_cloud_does_not_split_pdf_below_new_cloud_limits(tmp_path, monkeypatch):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    cfg = Config()
    monkeypatch.setattr(cfg, "resolved_mineru_api_key", lambda: "token")

    ctx = InboxCtx(
        pdf_path=pdf,
        inbox_dir=tmp_path,
        papers_dir=tmp_path / "papers",
        existing_dois={},
        cfg=cfg,
        opts={},
    )

    import scholaraio.providers.mineru as mineru

    _allow_pdf_validation(monkeypatch)
    monkeypatch.setattr(mineru, "check_server", lambda *_: False)
    monkeypatch.setattr(mineru, "_plan_cloud_chunking", lambda *_args, **_kwargs: (False, 600, ""))
    monkeypatch.setattr(
        mineru,
        "convert_pdf_cloud",
        lambda pdf_path, *_args, **_kwargs: ConvertResult(
            pdf_path=pdf_path, md_path=tmp_path / "paper.md", success=True
        ),
    )
    monkeypatch.setattr(
        mineru,
        "_convert_long_pdf_cloud",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not split")),
    )

    result = step_mineru(ctx)

    assert result == StepResult.OK
    assert ctx.md_path == tmp_path / "paper.md"


def test_step_mineru_cloud_splits_when_new_cloud_limits_require_it(tmp_path, monkeypatch):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    cfg = Config()
    monkeypatch.setattr(cfg, "resolved_mineru_api_key", lambda: "token")

    ctx = InboxCtx(
        pdf_path=pdf,
        inbox_dir=tmp_path,
        papers_dir=tmp_path / "papers",
        existing_dois={},
        cfg=cfg,
        opts={},
    )

    import scholaraio.providers.mineru as mineru

    _allow_pdf_validation(monkeypatch)
    monkeypatch.setattr(mineru, "check_server", lambda *_: False)
    monkeypatch.setattr(mineru, "_plan_cloud_chunking", lambda *_args, **_kwargs: (True, 320, "too large"))
    monkeypatch.setattr(
        mineru,
        "convert_pdf_cloud",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should use split path")),
    )

    captured: dict[str, object] = {}

    def fake_convert_long(pdf_path, opts, *, api_key, cloud_url, chunk_size):
        captured["chunk_size"] = chunk_size
        return ConvertResult(pdf_path=pdf_path, md_path=tmp_path / "paper.md", success=True)

    monkeypatch.setattr(mineru, "_convert_long_pdf_cloud", fake_convert_long)

    result = step_mineru(ctx)

    assert result == StepResult.OK
    assert captured["chunk_size"] == 320
    assert ctx.md_path == tmp_path / "paper.md"


def test_step_mineru_cloud_split_importerror_falls_back(tmp_path, monkeypatch):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    cfg = Config()
    monkeypatch.setattr(cfg, "resolved_mineru_api_key", lambda: "token")

    ctx = InboxCtx(
        pdf_path=pdf,
        inbox_dir=tmp_path,
        papers_dir=tmp_path / "papers",
        existing_dois={},
        cfg=cfg,
        opts={},
    )

    import scholaraio.providers.mineru as mineru
    import scholaraio.providers.pdf_fallback as pdf_fallback

    _allow_pdf_validation(monkeypatch)
    monkeypatch.setattr(mineru, "check_server", lambda *_: False)
    monkeypatch.setattr(mineru, "_plan_cloud_chunking", lambda *_args, **_kwargs: (True, 320, "too large"))
    monkeypatch.setattr(
        mineru,
        "_convert_long_pdf_cloud",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ImportError("install pymupdf")),
    )
    monkeypatch.setattr(
        pdf_fallback,
        "convert_pdf_with_fallback",
        lambda _pdf, md_path, **_kwargs: (
            md_path.write_text("fallback ok\n", encoding="utf-8"),
            True,
            "pymupdf",
            None,
        )[1:],
    )

    result = step_mineru(ctx)

    assert result == StepResult.OK
    assert ctx.md_path == tmp_path / "paper.md"
    assert ctx.md_path.read_text(encoding="utf-8") == "fallback ok\n"
