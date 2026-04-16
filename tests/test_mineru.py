from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from scholaraio.ingest.mineru import (
    ConvertOptions,
    ConvertResult,
    PDFValidationResult,
    _cloud_safe_pdf_name,
    _convert_chunk_cloud,
    _convert_long_pdf,
    _convert_long_pdf_cloud,
    _locate_cloud_markdown_output,
    _plan_cloud_chunking,
    _resolve_cloud_model_version,
    _split_pdf,
    cloud_safe_input_path,
    convert_pdf,
    convert_pdf_cloud,
    convert_pdfs_cloud_batch,
    validate_pdf_for_mineru,
)


def _allow_pdf_validation(monkeypatch):
    monkeypatch.setattr(
        "scholaraio.ingest.mineru.validate_pdf_for_mineru",
        lambda _path: PDFValidationResult(ok=True, page_count=1, deep_checked=True),
    )


def test_convert_long_pdf_cloud_preserves_cloud_model_version(tmp_path, monkeypatch):
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    chunk_pdf = tmp_path / "chunk-1.pdf"
    chunk_pdf.write_bytes(b"%PDF-1.4")

    captured: dict[str, str] = {}

    _allow_pdf_validation(monkeypatch)
    monkeypatch.setattr(
        "scholaraio.ingest.mineru._split_pdf",
        lambda _pdf_path, chunk_size, output_dir: [chunk_pdf],
    )

    def fake_convert_pdfs_cloud_batch(
        pdf_paths: list[Path],
        opts: ConvertOptions,
        *,
        api_key: str,
        cloud_url: str,
        batch_size: int = 20,
    ) -> list[ConvertResult]:
        captured["cloud_model_version"] = opts.cloud_model_version
        return [ConvertResult(pdf_path=pdf_paths[0], md_path=output_dir / "chunk-1.md", success=True)]

    output_dir = tmp_path / "out"
    output_dir.mkdir()

    def fake_merge_chunk_results(chunk_results, original_pdf_path, out_dir):
        assert chunk_results[0].success is True
        assert original_pdf_path == pdf_path
        return ConvertResult(pdf_path=original_pdf_path, md_path=out_dir / "paper.md", success=True)

    monkeypatch.setattr("scholaraio.ingest.mineru.convert_pdfs_cloud_batch", fake_convert_pdfs_cloud_batch)
    monkeypatch.setattr("scholaraio.ingest.mineru._merge_chunk_results", fake_merge_chunk_results)

    opts = ConvertOptions(
        output_dir=output_dir,
        backend="pipeline",
        cloud_model_version="MinerU-HTML",
        lang="en",
    )

    result = _convert_long_pdf_cloud(
        pdf_path,
        opts,
        api_key="test-key",
        cloud_url="https://mineru.example/api",
    )

    assert result.success is True
    assert captured["cloud_model_version"] == "MinerU-HTML"


def test_convert_long_pdf_uses_safe_chunk_workspace_for_long_filename(tmp_path, monkeypatch):
    long_stem = "a" * 250
    pdf_path = tmp_path / f"{long_stem}.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    chunk_pdf = tmp_path / "chunk-1.pdf"
    chunk_pdf.write_bytes(b"%PDF-1.4\n")
    output_dir = tmp_path / "out"

    _allow_pdf_validation(monkeypatch)

    def fake_split_pdf(_pdf_path, chunk_size, output_dir):
        assert len(output_dir.name.encode("utf-8")) <= 255
        assert long_stem not in output_dir.name
        return [chunk_pdf]

    monkeypatch.setattr("scholaraio.ingest.mineru._split_pdf", fake_split_pdf)
    monkeypatch.setattr(
        "scholaraio.ingest.mineru.convert_pdf",
        lambda path, opts: ConvertResult(pdf_path=path, md_path=opts.output_dir / "chunk-1.md", success=True),
    )
    monkeypatch.setattr(
        "scholaraio.ingest.mineru._merge_chunk_results",
        lambda chunk_results, original_pdf, out_dir: ConvertResult(
            pdf_path=original_pdf,
            md_path=out_dir / f"{original_pdf.stem}.md",
            success=True,
        ),
    )

    result = _convert_long_pdf(pdf_path, ConvertOptions(output_dir=output_dir), chunk_size=1)

    assert result.success is True


def test_convert_long_pdf_cloud_uses_safe_chunk_workspace_for_long_filename(tmp_path, monkeypatch):
    long_stem = "a" * 250
    pdf_path = tmp_path / f"{long_stem}.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    chunk_pdf = tmp_path / "chunk-1.pdf"
    chunk_pdf.write_bytes(b"%PDF-1.4\n")
    output_dir = tmp_path / "out"

    _allow_pdf_validation(monkeypatch)

    def fake_split_pdf(_pdf_path, chunk_size, output_dir):
        assert len(output_dir.name.encode("utf-8")) <= 255
        assert long_stem not in output_dir.name
        return [chunk_pdf]

    def fake_batch(pdf_paths, opts, *, api_key, cloud_url, batch_size=20):
        return [ConvertResult(pdf_path=pdf_paths[0], md_path=opts.output_dir / "chunk-1.md", success=True)]

    monkeypatch.setattr("scholaraio.ingest.mineru._split_pdf", fake_split_pdf)
    monkeypatch.setattr("scholaraio.ingest.mineru.convert_pdfs_cloud_batch", fake_batch)
    monkeypatch.setattr(
        "scholaraio.ingest.mineru._merge_chunk_results",
        lambda chunk_results, original_pdf, out_dir: ConvertResult(
            pdf_path=original_pdf,
            md_path=out_dir / f"{original_pdf.stem}.md",
            success=True,
        ),
    )

    result = _convert_long_pdf_cloud(
        pdf_path,
        ConvertOptions(output_dir=output_dir),
        api_key="token",
        cloud_url="https://mineru.example",
        chunk_size=1,
    )

    assert result.success is True


def test_split_pdf_uses_safe_chunk_names_for_long_filename(tmp_path, monkeypatch):
    long_stem = "a" * 250
    pdf_path = tmp_path / f"{long_stem}.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    saved_paths: list[Path] = []

    class FakeSourceDoc:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    class FakeChunkDoc:
        def insert_pdf(self, *_args, **_kwargs):
            return None

        def save(self, path):
            saved_paths.append(Path(path))

        def close(self):
            return None

    def fake_open(path=None):
        if path is None:
            return FakeChunkDoc()
        return FakeSourceDoc()

    monkeypatch.setattr("scholaraio.ingest.mineru._get_pdf_page_count", lambda _path: 2)
    monkeypatch.setitem(sys.modules, "pymupdf", SimpleNamespace(open=fake_open))

    chunks = _split_pdf(pdf_path, chunk_size=1, output_dir=tmp_path / "chunks")

    assert chunks == saved_paths
    assert len(chunks) == 2
    for chunk_path in chunks:
        assert len(chunk_path.name.encode("utf-8")) <= 255
        assert long_stem not in chunk_path.name


def test_resolve_cloud_model_version_falls_back_to_backend_when_unset():
    opts = ConvertOptions(backend="vlm-auto-engine", cloud_model_version="")
    assert _resolve_cloud_model_version(opts) == "vlm"


def test_resolve_cloud_model_version_uses_backend_mapping_by_default():
    opts = ConvertOptions(backend="vlm-auto-engine")
    assert _resolve_cloud_model_version(opts) == "vlm"


def test_validate_pdf_for_mineru_rejects_empty_file(tmp_path):
    pdf_path = tmp_path / "empty.pdf"
    pdf_path.write_bytes(b"")

    result = validate_pdf_for_mineru(pdf_path)

    assert result.ok is False
    assert "file is empty" in (result.error or "")


def test_validate_pdf_for_mineru_surfaces_deep_structure_error(tmp_path, monkeypatch):
    pdf_path = tmp_path / "corrupt.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\nbroken")

    monkeypatch.setattr(
        "scholaraio.ingest.mineru._validate_pdf_with_pymupdf",
        lambda _path: PDFValidationResult(
            ok=False,
            error="PDF validation failed: cannot open PDF structure: corrupt.pdf: broken xref",
            deep_checked=True,
        ),
    )

    result = validate_pdf_for_mineru(pdf_path)

    assert result.ok is False
    assert result.deep_checked is True
    assert "cannot open PDF structure" in (result.error or "")


def test_cloud_safe_pdf_name_truncates_long_filename_with_digest(tmp_path):
    pdf_path = tmp_path / f"{'paper' * 40}.pdf"

    safe_name = _cloud_safe_pdf_name(pdf_path)
    digest = hashlib.md5(pdf_path.name.encode("utf-8")).hexdigest()[:16]

    assert len(safe_name) <= 128
    assert safe_name.endswith(".pdf")
    assert digest in safe_name


def test_cloud_safe_input_path_limits_utf8_bytes_for_non_ascii_long_filename(tmp_path):
    pdf_path = tmp_path / f"{'测' * 70}{'a' * 31}.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    digest = hashlib.md5(pdf_path.name.encode("utf-8")).hexdigest()[:16]

    with cloud_safe_input_path(pdf_path) as alias:
        alias_parent = alias.path.parent
        assert alias.aliased is True
        assert alias.path.exists()
        assert alias.path != pdf_path
        assert len(alias.path.name) <= 128
        assert len(alias.path.name.encode("utf-8")) <= 128
        assert alias.path.name.endswith(".pdf")
        assert digest in alias.path.name

    assert not alias_parent.exists()


def test_cloud_safe_input_path_symlink_fallback_keeps_relative_source_readable(tmp_path, monkeypatch):
    pdf_path = tmp_path / f"{'relative-paper' * 12}.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "scholaraio.ingest.mineru.os.link",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("cross-device link")),
    )

    with cloud_safe_input_path(Path(pdf_path.name)) as alias:
        assert alias.aliased is True
        assert alias.path.exists()
        assert alias.path.read_bytes() == b"%PDF-1.4\n"


def test_convert_pdf_rejects_invalid_pdf_before_local_request(tmp_path, monkeypatch):
    pdf_path = tmp_path / "bad.pdf"
    pdf_path.write_bytes(b"not a pdf")

    called = {"post": False}

    def fake_post(*_args, **_kwargs):
        called["post"] = True
        raise AssertionError("invalid PDFs should not be submitted")

    monkeypatch.setattr("scholaraio.ingest.mineru.requests.post", fake_post)

    result = convert_pdf(pdf_path, ConvertOptions(output_dir=tmp_path / "out"))

    assert result.success is False
    assert called["post"] is False
    assert result.error_kind == "pdf_validation"
    assert "invalid PDF header" in (result.error or "")


def test_convert_pdf_saves_content_list_with_safe_name_for_long_filename(tmp_path, monkeypatch):
    long_stem = "a" * 250
    pdf_path = tmp_path / f"{long_stem}.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    safe_stem = Path(_cloud_safe_pdf_name(pdf_path)).stem

    _allow_pdf_validation(monkeypatch)

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {
                "results": {
                    pdf_path.stem: {
                        "md_content": "# ok\n",
                        "content_list": [{"type": "text", "text": "ok"}],
                    }
                }
            }

    monkeypatch.setattr("scholaraio.ingest.mineru.requests.post", lambda *_args, **_kwargs: FakeResponse())

    result = convert_pdf(pdf_path, ConvertOptions(output_dir=tmp_path, save_content_list=True))

    assert result.success is True
    assert (tmp_path / f"{safe_stem}_content_list.json").exists()
    assert f"{long_stem}_content_list.json" not in {path.name for path in tmp_path.iterdir()}


def test_convert_pdf_cloud_invokes_mineru_open_api_extract_with_token_and_flags(tmp_path, monkeypatch):
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    output_dir = tmp_path / "out"

    captured: dict[str, object] = {}

    _allow_pdf_validation(monkeypatch)
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/mineru-open-api" if name == "mineru-open-api" else None)

    def fake_run(cmd, *, capture_output, text, cwd, env, timeout, check):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["env_token"] = env.get("MINERU_TOKEN")
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "paper.md").write_text("# ok\n", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="saved")

    monkeypatch.setattr(subprocess, "run", fake_run)

    opts = ConvertOptions(
        output_dir=output_dir,
        cloud_model_version="vlm",
        lang="en",
        parse_method="ocr",
        formula_enable=False,
        table_enable=True,
        poll_timeout=321,
    )

    result = convert_pdf_cloud(
        pdf_path,
        opts,
        api_key="test-key",
        cloud_url="https://mineru.net/api/v4",
    )

    assert result.success is True
    assert result.md_path == output_dir / "paper.md"
    assert result.md_path.read_text(encoding="utf-8") == "# ok\n"
    assert captured["env_token"] == "test-key"
    assert captured["cwd"] == str(tmp_path)
    assert captured["cmd"] == [
        "/usr/bin/mineru-open-api",
        "extract",
        str(pdf_path),
        "-o",
        str(output_dir),
        "--language",
        "en",
        "--model",
        "vlm",
        "--ocr",
        "--formula=false",
        "--table=true",
        "--timeout",
        "321",
    ]


def test_convert_pdf_cloud_omits_pdf_only_flags_for_html_model_and_passes_custom_base_url(tmp_path, monkeypatch):
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    output_dir = tmp_path / "out"

    captured: dict[str, object] = {}

    _allow_pdf_validation(monkeypatch)
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/mineru-open-api" if name == "mineru-open-api" else None)

    def fake_run(cmd, *, capture_output, text, cwd, env, timeout, check):
        captured["cmd"] = cmd
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "paper.md").write_text("# html\n", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = convert_pdf_cloud(
        pdf_path,
        ConvertOptions(
            output_dir=output_dir,
            cloud_model_version="MinerU-HTML",
            lang="en",
            parse_method="ocr",
            formula_enable=False,
            table_enable=False,
        ),
        api_key="test-key",
        cloud_url="https://private-mineru.example/api",
    )

    assert result.success is True
    assert captured["cmd"] == [
        "/usr/bin/mineru-open-api",
        "extract",
        str(pdf_path),
        "-o",
        str(output_dir),
        "--language",
        "en",
        "--model",
        "html",
        "--timeout",
        "900",
        "--base-url",
        "https://private-mineru.example/api",
    ]


def test_convert_pdf_cloud_returns_actionable_error_when_cli_missing(tmp_path, monkeypatch):
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    _allow_pdf_validation(monkeypatch)
    monkeypatch.setattr(shutil, "which", lambda name: None)

    result = convert_pdf_cloud(
        pdf_path,
        ConvertOptions(output_dir=tmp_path / "out"),
        api_key="test-key",
        cloud_url="https://mineru.net/api/v4",
    )

    assert result.success is False
    assert "mineru-open-api" in (result.error or "")
    assert "pip install" in (result.error or "")


def test_convert_pdf_cloud_surfaces_cli_failure_details(tmp_path, monkeypatch):
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    _allow_pdf_validation(monkeypatch)
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/mineru-open-api" if name == "mineru-open-api" else None)

    def fake_run(cmd, *, capture_output, text, cwd, env, timeout, check):
        return subprocess.CompletedProcess(cmd, 6, stdout="", stderr="timed out")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = convert_pdf_cloud(
        pdf_path,
        ConvertOptions(output_dir=tmp_path / "out"),
        api_key="test-key",
        cloud_url="https://mineru.net/api/v4",
    )

    assert result.success is False
    assert "exit code 6" in (result.error or "")
    assert "timed out" in (result.error or "")


def test_convert_pdf_cloud_retries_timeout_with_exponential_backoff(tmp_path, monkeypatch):
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    output_dir = tmp_path / "out"

    attempts = {"count": 0}
    sleeps: list[float] = []

    _allow_pdf_validation(monkeypatch)
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/mineru-open-api" if name == "mineru-open-api" else None)

    def fake_run(cmd, *, capture_output, text, cwd, env, timeout, check):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "paper.md").write_text("# ok after retry\n", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr("scholaraio.ingest.mineru.time.sleep", lambda seconds: sleeps.append(seconds))

    result = convert_pdf_cloud(
        pdf_path,
        ConvertOptions(output_dir=output_dir, upload_retries=3),
        api_key="test-key",
        cloud_url="https://mineru.net/api/v4",
    )

    assert result.success is True
    assert attempts["count"] == 3
    assert sleeps == [1.0, 2.0]
    assert result.md_path == output_dir / "paper.md"


def test_convert_pdfs_cloud_batch_splits_into_chunks(tmp_path, monkeypatch):
    pdf_paths: list[Path] = []
    for idx in range(3):
        pdf_path = tmp_path / f"paper-{idx}.pdf"
        pdf_path.write_bytes(b"%PDF-1.4")
        pdf_paths.append(pdf_path)

    calls: list[list[str]] = []

    def fake_convert_chunk_cloud(
        chunk: list[tuple[int, Path]],
        opts: ConvertOptions,
        *,
        api_key: str,
        cloud_url: str,
    ) -> list[ConvertResult]:
        calls.append([f"{idx}:{path.name}" for idx, path in chunk])
        return [ConvertResult(pdf_path=path, md_path=tmp_path / f"{path.stem}.md", success=True) for idx, path in chunk]

    monkeypatch.setattr("scholaraio.ingest.mineru._convert_chunk_cloud", fake_convert_chunk_cloud)

    results = convert_pdfs_cloud_batch(
        pdf_paths,
        ConvertOptions(output_dir=tmp_path / "out"),
        api_key="test-key",
        cloud_url="https://mineru.example/api",
        batch_size=2,
    )

    assert calls == [["0:paper-0.pdf", "1:paper-1.pdf"], ["2:paper-2.pdf"]]
    assert len(results) == 3
    assert all(result.success for result in results)


def test_convert_pdfs_cloud_batch_preserves_global_unique_indexes_across_chunks(tmp_path, monkeypatch):
    pdf_paths: list[Path] = []
    for subdir in ("a", "b", "c", "d"):
        pdf_path = tmp_path / subdir / "paper.pdf"
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(b"%PDF-1.4")
        pdf_paths.append(pdf_path)

    seen_dirs: list[Path] = []

    def fake_convert_chunk_cloud(
        chunk: list[tuple[int, Path]],
        opts: ConvertOptions,
        *,
        api_key: str,
        cloud_url: str,
    ) -> list[ConvertResult]:
        results: list[ConvertResult] = []
        for global_idx, path in chunk:
            out_dir = opts.output_dir / f"{global_idx:04d}_{path.stem}"
            seen_dirs.append(out_dir)
            results.append(ConvertResult(pdf_path=path, md_path=out_dir / "index.md", success=True))
        return results

    monkeypatch.setattr("scholaraio.ingest.mineru._convert_chunk_cloud", fake_convert_chunk_cloud)

    convert_pdfs_cloud_batch(
        pdf_paths,
        ConvertOptions(output_dir=tmp_path / "out"),
        api_key="test-key",
        cloud_url="https://mineru.example/api",
        batch_size=2,
    )

    assert [path.name for path in seen_dirs] == [
        "0000_paper",
        "0001_paper",
        "0002_paper",
        "0003_paper",
    ]
    assert len(set(seen_dirs)) == 4


def test_convert_chunk_cloud_uses_bounded_parallel_workers(tmp_path, monkeypatch):
    import scholaraio.ingest.mineru as mineru

    pdf_paths = []
    for idx in range(3):
        path = tmp_path / f"paper-{idx}.pdf"
        path.write_bytes(b"%PDF-1.4\n")
        pdf_paths.append(path)

    submitted: list[Path] = []
    max_workers_seen: list[int] = []

    class FakeExecutor:
        def __init__(self, max_workers):
            max_workers_seen.append(max_workers)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def map(self, fn, items):
            result = []
            for item in items:
                submitted.append(item)
                result.append(fn(item))
            return result

    monkeypatch.setattr(mineru.concurrent.futures, "ThreadPoolExecutor", FakeExecutor)
    monkeypatch.setattr(
        "scholaraio.ingest.mineru.convert_pdf_cloud",
        lambda pdf_path, *_args, **_kwargs: ConvertResult(
            pdf_path=pdf_path,
            md_path=pdf_path.with_suffix(".md"),
            success=True,
        ),
    )

    results = _convert_chunk_cloud(
        list(enumerate(pdf_paths)),
        ConvertOptions(output_dir=tmp_path / "out", upload_workers=2),
        api_key="token",
        cloud_url="https://mineru.example/api",
    )

    assert max_workers_seen == [2]
    assert submitted == list(enumerate(pdf_paths))
    assert [res.pdf_path for res in results] == pdf_paths


def test_convert_chunk_cloud_isolates_duplicate_stems_into_unique_output_dirs(tmp_path, monkeypatch):
    pdf_a = tmp_path / "a" / "source.pdf"
    pdf_b = tmp_path / "b" / "source.pdf"
    pdf_a.parent.mkdir()
    pdf_b.parent.mkdir()
    pdf_a.write_bytes(b"%PDF-1.4\n")
    pdf_b.write_bytes(b"%PDF-1.4\n")

    seen_output_dirs: list[Path] = []

    monkeypatch.setattr(
        "scholaraio.ingest.mineru.convert_pdf_cloud",
        lambda pdf_path, opts, **_kwargs: (
            seen_output_dirs.append(opts.output_dir),
            ConvertResult(pdf_path=pdf_path, md_path=(opts.output_dir / "index.md"), success=True),
        )[1],
    )

    results = _convert_chunk_cloud(
        list(enumerate([pdf_a, pdf_b])),
        ConvertOptions(output_dir=tmp_path / "out", upload_workers=2),
        api_key="token",
        cloud_url="https://mineru.example/api",
    )

    assert len(results) == 2
    assert seen_output_dirs[0] != seen_output_dirs[1]


def test_plan_cloud_chunking_uses_200_page_limit_when_only_page_count_exceeds(tmp_path, monkeypatch):
    pdf_path = tmp_path / "long.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr("scholaraio.ingest.mineru._get_pdf_page_count", lambda _path: 201)

    should_chunk, chunk_size, reason = _plan_cloud_chunking(pdf_path)

    assert should_chunk is True
    assert chunk_size == 200
    assert "201 pages" in reason


def test_plan_cloud_chunking_uses_size_limit_when_file_is_too_large(tmp_path, monkeypatch):
    pdf_path = tmp_path / "big.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr("scholaraio.ingest.mineru._get_pdf_page_count", lambda _path: 400)
    monkeypatch.setattr("scholaraio.ingest.mineru._get_pdf_size_bytes", lambda _path: 250 * 1024 * 1024)

    should_chunk, chunk_size, reason = _plan_cloud_chunking(pdf_path)

    assert should_chunk is True
    assert chunk_size == 200
    assert "250.0 MB" in reason


def test_plan_cloud_chunking_uses_safe_fallback_chunk_size_when_page_count_unknown(tmp_path, monkeypatch):
    pdf_path = tmp_path / "unknown.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr("scholaraio.ingest.mineru._get_pdf_page_count", lambda _path: -1)
    monkeypatch.setattr("scholaraio.ingest.mineru._get_pdf_size_bytes", lambda _path: 250 * 1024 * 1024)

    should_chunk, chunk_size, reason = _plan_cloud_chunking(pdf_path)

    assert should_chunk is True
    assert chunk_size == 100
    assert "250.0 MB" in reason


def test_plan_cloud_chunking_clamps_unknown_page_fallback_to_cloud_max(tmp_path, monkeypatch):
    pdf_path = tmp_path / "unknown.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr("scholaraio.ingest.mineru._get_pdf_page_count", lambda _path: -1)
    monkeypatch.setattr("scholaraio.ingest.mineru._get_pdf_size_bytes", lambda _path: 250 * 1024 * 1024)

    should_chunk, chunk_size, _reason = _plan_cloud_chunking(pdf_path, default_chunk_size=800)

    assert should_chunk is True
    assert chunk_size == 200


def test_convert_pdf_cloud_skips_when_markdown_exists_in_nested_layout(tmp_path, monkeypatch):
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    out_dir = tmp_path / "out"
    nested_md = out_dir / pdf_path.stem / "index.md"
    nested_md.parent.mkdir(parents=True)
    nested_md.write_text("existing\n", encoding="utf-8")

    monkeypatch.setattr("scholaraio.ingest.mineru.shutil.which", lambda _name: "/usr/bin/mineru-open-api")
    monkeypatch.setattr(
        "scholaraio.ingest.mineru._locate_cloud_markdown_output",
        lambda _out_dir, _stem: nested_md,
    )
    monkeypatch.setattr(
        "scholaraio.ingest.mineru.subprocess.run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should skip existing output")),
    )

    result = convert_pdf_cloud(
        pdf_path,
        ConvertOptions(output_dir=out_dir),
        api_key="token",
    )

    assert result.success is True
    assert result.md_path == nested_md


def test_convert_pdf_cloud_rejects_invalid_pdf_before_cli(tmp_path, monkeypatch):
    pdf_path = tmp_path / "not-a-pdf.pdf"
    pdf_path.write_bytes(b"not a pdf")
    output_dir = tmp_path / "out"

    monkeypatch.setattr("scholaraio.ingest.mineru.shutil.which", lambda _name: "/usr/bin/mineru-open-api")

    called = {"subprocess": False}

    def fake_run(*_args, **_kwargs):
        called["subprocess"] = True
        return subprocess.CompletedProcess(["mineru-open-api"], 0, stdout="", stderr="")

    monkeypatch.setattr("scholaraio.ingest.mineru.subprocess.run", fake_run)

    result = convert_pdf_cloud(
        pdf_path,
        ConvertOptions(output_dir=output_dir),
        api_key="token",
    )

    assert result.success is False
    assert called["subprocess"] is False
    assert result.error_kind == "pdf_validation"
    assert "invalid PDF header" in (result.error or "")


def test_convert_long_pdf_cloud_rejects_invalid_pdf_before_split(tmp_path, monkeypatch):
    pdf_path = tmp_path / "bad.pdf"
    pdf_path.write_bytes(b"not a pdf")

    monkeypatch.setattr(
        "scholaraio.ingest.mineru._split_pdf",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("invalid PDF should not be split")),
    )

    result = _convert_long_pdf_cloud(
        pdf_path,
        ConvertOptions(output_dir=tmp_path / "out"),
        api_key="token",
        cloud_url="https://mineru.example",
    )

    assert result.success is False
    assert result.error_kind == "pdf_validation"
    assert "invalid PDF header" in (result.error or "")


def test_convert_pdf_cloud_uses_safe_upload_alias_for_long_filename(tmp_path, monkeypatch):
    long_stem = "a" * 150
    pdf_path = tmp_path / f"{long_stem}.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    output_dir = tmp_path / "out"

    captured: dict[str, object] = {}

    monkeypatch.setattr("scholaraio.ingest.mineru.shutil.which", lambda _name: "/usr/bin/mineru-open-api")
    monkeypatch.setattr(
        "scholaraio.ingest.mineru.validate_pdf_for_mineru",
        lambda _path: type("Validation", (), {"ok": True, "error": None})(),
    )

    def fake_run(cmd, *, capture_output, text, cwd, env, timeout, check):
        upload_path = Path(cmd[2])
        captured["cmd"] = cmd
        captured["upload_name"] = upload_path.name
        captured["upload_exists_during_run"] = upload_path.exists()
        captured["cwd"] = cwd
        safe_stem = upload_path.stem
        nested = output_dir / safe_stem / "index.md"
        nested.parent.mkdir(parents=True, exist_ok=True)
        nested.write_text("# ok\n", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("scholaraio.ingest.mineru.subprocess.run", fake_run)

    result = convert_pdf_cloud(
        pdf_path,
        ConvertOptions(output_dir=output_dir),
        api_key="token",
    )

    upload_name = str(captured["upload_name"])
    digest = hashlib.md5(pdf_path.name.encode("utf-8")).hexdigest()[:16]

    assert result.success is True
    assert result.pdf_path == pdf_path
    assert len(upload_name) <= 128
    assert digest in upload_name
    assert upload_name.endswith(".pdf")
    assert captured["upload_exists_during_run"] is True
    assert captured["cwd"] == str(Path(captured["cmd"][2]).parent)
    assert result.md_path == output_dir / Path(upload_name).stem / "index.md"


def test_convert_pdfs_cloud_batch_uses_safe_output_namespace_for_long_filename(tmp_path, monkeypatch):
    long_stem = "a" * 150
    pdf_path = tmp_path / f"{long_stem}.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    output_dir = tmp_path / "out"
    captured: dict[str, Path] = {}

    def fake_convert_pdf_cloud(path, opts, *, api_key, cloud_url):
        captured["output_dir"] = opts.output_dir
        return ConvertResult(pdf_path=path, success=True, md_path=opts.output_dir / "index.md")

    monkeypatch.setattr("scholaraio.ingest.mineru.convert_pdf_cloud", fake_convert_pdf_cloud)

    results = convert_pdfs_cloud_batch(
        [pdf_path],
        ConvertOptions(output_dir=output_dir),
        api_key="token",
        cloud_url="https://mineru.example",
        batch_size=1,
    )

    namespace = captured["output_dir"].name
    digest = hashlib.md5(pdf_path.name.encode("utf-8")).hexdigest()[:16]

    assert len(results) == 1
    assert namespace.startswith("0000_")
    assert len(namespace) <= 129
    assert digest in namespace
    assert long_stem not in namespace


def test_locate_cloud_markdown_output_does_not_reuse_unrelated_single_markdown(tmp_path):
    out_dir = tmp_path / "out"
    unrelated_md = out_dir / "other" / "index.md"
    unrelated_md.parent.mkdir(parents=True)
    unrelated_md.write_text("other\n", encoding="utf-8")

    assert _locate_cloud_markdown_output(out_dir, "paper") is None


def test_locate_cloud_markdown_output_matches_nested_index_for_requested_stem(tmp_path):
    out_dir = tmp_path / "out"
    nested_md = out_dir / "paper" / "index.md"
    nested_md.parent.mkdir(parents=True)
    nested_md.write_text("paper\n", encoding="utf-8")

    assert _locate_cloud_markdown_output(out_dir, "paper") == nested_md


def test_locate_cloud_markdown_output_ignores_generic_root_markdown_in_shared_output_dir(tmp_path):
    out_dir = tmp_path / "out"
    generic_md = out_dir / "full.md"
    generic_md.parent.mkdir(parents=True)
    generic_md.write_text("generic\n", encoding="utf-8")

    assert _locate_cloud_markdown_output(out_dir, "paper") is None
