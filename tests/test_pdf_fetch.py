"""Integration tests for the lightweight PDF fetcher."""

from __future__ import annotations

import argparse
import json
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

import pytest

from scholaraio.core.config import _build_config

PDF_BYTES = b"%PDF-1.4\n% scholar aio test pdf\n1 0 obj\n<<>>\nendobj\n%%EOF\n"
Route = tuple[int, str, bytes] | tuple[int, str, bytes, dict[str, str]]


class _RouteHandler(BaseHTTPRequestHandler):
    routes: ClassVar[dict[str, Route]] = {}
    request_counts: ClassVar[dict[str, int]] = {}

    def do_GET(self) -> None:
        self.request_counts[self.path] = self.request_counts.get(self.path, 0) + 1
        route = self.routes.get(
            self.path,
            (404, "text/plain", b"missing"),
        )
        status, content_type, body = route[:3]
        headers = route[3] if len(route) > 3 else {}
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


@contextmanager
def _http_server(routes: dict[str, Route], request_counts: dict[str, int] | None = None) -> Iterator[str]:
    class Handler(_RouteHandler):
        pass

    Handler.routes = routes
    Handler.request_counts = request_counts if request_counts is not None else {}
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


@contextmanager
def _temporary_proxy_env(proxy_url: str) -> Iterator[None]:
    names = [
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "http_proxy",
        "https_proxy",
        "ALL_PROXY",
        "all_proxy",
        "NO_PROXY",
        "no_proxy",
    ]
    old = {name: os.environ.get(name) for name in names}
    try:
        for name in names:
            os.environ.pop(name, None)
        for name in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"]:
            os.environ[name] = proxy_url
        yield
    finally:
        for name, value in old.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def test_fetch_pdf_discovers_citation_pdf_url_and_downloads_over_real_http(tmp_path: Path) -> None:
    from scholaraio.services.pdf_fetch import fetch_pdf

    routes: dict[str, tuple[int, str, bytes]] = {}
    with _http_server(routes) as base_url:
        routes["/article"] = (
            200,
            "text/html; charset=utf-8",
            (
                "<html><head>"
                f'<meta name="citation_pdf_url" content="{base_url}/paper.pdf">'
                '<meta name="citation_title" content="Real HTTP Paper">'
                "</head><body>Article landing</body></html>"
            ).encode(),
        )
        routes["/paper.pdf"] = (200, "application/pdf", PDF_BYTES)

        result = fetch_pdf(f"{base_url}/article", tmp_path, direct=True)

    assert result.path is not None
    assert result.path.read_bytes() == PDF_BYTES
    assert result.pdf_url.endswith("/paper.pdf")
    assert result.source == "landing:citation_pdf_url"
    assert result.bytes_downloaded == len(PDF_BYTES)


def test_fetch_pdf_reports_actual_meta_pdf_source(tmp_path: Path) -> None:
    from scholaraio.services.pdf_fetch import fetch_pdf

    routes: dict[str, tuple[int, str, bytes]] = {}
    with _http_server(routes) as base_url:
        routes["/article"] = (
            200,
            "text/html; charset=utf-8",
            (
                "<html><head>"
                f'<meta name="dc.identifier" content="{base_url}/paper.pdf">'
                "</head><body>Article landing</body></html>"
            ).encode(),
        )
        routes["/paper.pdf"] = (200, "application/pdf", PDF_BYTES)

        result = fetch_pdf(f"{base_url}/article", tmp_path, direct=True)

    assert result.path is not None
    assert result.source == "landing:meta:dc.identifier"


def test_locator_to_url_normalizes_case_insensitive_doi_org_url() -> None:
    from scholaraio.services.pdf_fetch import _locator_to_url

    assert _locator_to_url("https://DOI.ORG/10.1000/CaseSensitive") == ("https://doi.org/10.1000/CaseSensitive")


def test_direct_fetch_ignores_proxy_environment_with_real_http(tmp_path: Path) -> None:
    from scholaraio.services.pdf_fetch import fetch_pdf

    with (
        _http_server({"/paper.pdf": (200, "application/pdf", PDF_BYTES)}) as base_url,
        _temporary_proxy_env("http://127.0.0.1:9"),
    ):
        result = fetch_pdf(f"{base_url}/paper.pdf", tmp_path, direct=True)

    assert result.path is not None
    assert result.path.read_bytes().startswith(b"%PDF")


def test_fetch_pdf_saves_initial_pdf_response_without_second_get(tmp_path: Path) -> None:
    from scholaraio.services.pdf_fetch import fetch_pdf

    request_counts: dict[str, int] = {}
    with _http_server(
        {"/signed-download": (200, "application/pdf", PDF_BYTES)},
        request_counts=request_counts,
    ) as base_url:
        result = fetch_pdf(f"{base_url}/signed-download", tmp_path, direct=True)

    assert result.path is not None
    assert result.path.read_bytes() == PDF_BYTES
    assert request_counts["/signed-download"] == 1


def test_download_pdf_url_checks_existing_file_after_redirect(tmp_path: Path) -> None:
    from scholaraio.services import pdf_fetch

    (tmp_path / "download.pdf").write_bytes(b"%PDF-1.4\nold\n%%EOF\n")
    request_counts: dict[str, int] = {}
    routes: dict[str, Route] = {}
    with _http_server(routes, request_counts=request_counts) as base_url:
        routes["/download"] = (
            302,
            "text/plain",
            b"",
            {"Location": f"{base_url}/final.pdf"},
        )
        routes["/final.pdf"] = (200, "application/pdf", PDF_BYTES)
        with pdf_fetch._session(direct=True, timeout=5.0) as session:
            result = pdf_fetch._download_pdf_url(f"{base_url}/download", tmp_path, session=session)

    assert result.status == "downloaded"
    assert result.path == tmp_path / "final.pdf"
    assert result.path.read_bytes() == PDF_BYTES
    assert (tmp_path / "download.pdf").read_bytes() == b"%PDF-1.4\nold\n%%EOF\n"
    assert request_counts["/download"] == 1
    assert request_counts["/final.pdf"] == 1


def test_fetch_pdf_closes_owned_session_after_download(tmp_path: Path, monkeypatch) -> None:
    from scholaraio.services import pdf_fetch

    sessions: list[dict[str, bool]] = []
    original_session = pdf_fetch._session

    def tracking_session(*, direct: bool, timeout: float):
        session = original_session(direct=direct, timeout=timeout)
        state = {"closed": False}
        original_close = session.close

        def close() -> None:
            state["closed"] = True
            original_close()

        session.close = close
        sessions.append(state)
        return session

    monkeypatch.setattr(pdf_fetch, "_session", tracking_session)

    with _http_server({"/paper.pdf": (200, "application/pdf", PDF_BYTES)}) as base_url:
        result = pdf_fetch.fetch_pdf(f"{base_url}/paper.pdf", tmp_path, direct=True)

    assert result.status == "downloaded"
    assert sessions == [{"closed": True}]


def test_fetch_pdf_preserves_pdf_suffix_after_long_title_truncation(tmp_path: Path) -> None:
    from scholaraio.services.pdf_fetch import fetch_pdf

    long_title = "Long Publisher Title " + ("with many words " * 20)
    routes: dict[str, tuple[int, str, bytes]] = {}
    with _http_server(routes) as base_url:
        routes["/article"] = (
            200,
            "text/html; charset=utf-8",
            (
                "<html><head>"
                f'<meta name="citation_title" content="{long_title}">'
                f'<meta name="citation_pdf_url" content="{base_url}/paper.pdf">'
                "</head></html>"
            ).encode(),
        )
        routes["/paper.pdf"] = (200, "application/pdf", PDF_BYTES)

        result = fetch_pdf(f"{base_url}/article", tmp_path, direct=True)

    assert result.path is not None
    assert result.path.name.endswith(".pdf")
    assert len(result.path.name.encode("utf-8")) <= 255


def test_fetch_pdf_limits_multibyte_filename_to_filesystem_bytes(tmp_path: Path) -> None:
    from scholaraio.services.pdf_fetch import fetch_pdf

    long_title = "超长中文标题" * 80
    routes: dict[str, tuple[int, str, bytes]] = {}
    with _http_server(routes) as base_url:
        routes["/article"] = (
            200,
            "text/html; charset=utf-8",
            (
                "<html><head>"
                f'<meta name="citation_title" content="{long_title}">'
                f'<meta name="citation_pdf_url" content="{base_url}/paper.pdf">'
                "</head></html>"
            ).encode(),
        )
        routes["/paper.pdf"] = (200, "application/pdf", PDF_BYTES)

        result = fetch_pdf(f"{base_url}/article", tmp_path, direct=True)

    assert result.path is not None
    assert result.path.name.endswith(".pdf")
    assert len(result.path.name.encode("utf-8")) <= 255


def test_fetch_pdf_normalizes_pdf_header_to_byte_zero(tmp_path: Path) -> None:
    from scholaraio.services.pdf_fetch import fetch_pdf

    prefixed_pdf = b"\x00publisher-banner\n" + PDF_BYTES
    with _http_server({"/paper.pdf": (200, "application/pdf", prefixed_pdf)}) as base_url:
        result = fetch_pdf(f"{base_url}/paper.pdf", tmp_path, direct=True)

    assert result.path is not None
    assert result.path.read_bytes() == PDF_BYTES


def test_valid_pdf_payload_reads_only_header(tmp_path: Path, monkeypatch) -> None:
    from scholaraio.services import pdf_fetch

    path = tmp_path / "large.pdf"
    path.write_bytes(PDF_BYTES + (b"x" * 1024 * 1024))

    def fail_read_bytes(_self: Path) -> bytes:
        raise AssertionError("validation should not read the whole PDF")

    monkeypatch.setattr(Path, "read_bytes", fail_read_bytes)

    assert pdf_fetch._valid_pdf_payload(path) is True


def test_normalize_pdf_header_streams_without_full_file_read(tmp_path: Path, monkeypatch) -> None:
    from scholaraio.services import pdf_fetch

    path = tmp_path / "prefixed-large.pdf"
    with path.open("wb") as fh:
        fh.write(b"\x00publisher-banner\n")
        fh.write(PDF_BYTES)
        fh.write(b"x" * 1024 * 1024)

    def fail_read_bytes(_self: Path) -> bytes:
        raise AssertionError("normalization should not read the whole PDF")

    def fail_write_bytes(_self: Path, _data: bytes) -> int:
        raise AssertionError("normalization should not rewrite from an in-memory bytes object")

    monkeypatch.setattr(Path, "read_bytes", fail_read_bytes)
    monkeypatch.setattr(Path, "write_bytes", fail_write_bytes)

    pdf_fetch._normalize_pdf_header(path)

    with path.open("rb") as fh:
        assert fh.read(5) == b"%PDF-"


def test_refetch_existing_paper_uses_source_url_and_replaces_canonical_pdf(tmp_path: Path) -> None:
    from scholaraio.services.pdf_fetch import refetch_paper_pdf

    routes: dict[str, tuple[int, str, bytes]] = {}
    with _http_server(routes) as base_url:
        paper_dir = tmp_path / "papers" / "Doe-2026-Real-HTTP-Paper"
        paper_dir.mkdir(parents=True)
        (paper_dir / "meta.json").write_text(
            json.dumps(
                {
                    "id": "paper-1",
                    "title": "Real HTTP Paper",
                    "doi": "10.9999/real-http-paper",
                    "source_url": f"{base_url}/article",
                }
            ),
            encoding="utf-8",
        )
        canonical_pdf = paper_dir / "Doe-2026-Real-HTTP-Paper.pdf"
        canonical_pdf.write_bytes(b"%PDF-1.4\nold\n%%EOF\n")

        routes["/article"] = (
            200,
            "text/html; charset=utf-8",
            f'<meta name="citation_pdf_url" content="{base_url}/new.pdf">'.encode(),
        )
        routes["/new.pdf"] = (200, "application/pdf", PDF_BYTES)

        cfg = _build_config({"paths": {"papers_dir": str(tmp_path / "papers")}}, tmp_path)
        result = refetch_paper_pdf(paper_dir, cfg, direct=True, force=True)

    assert result.path == canonical_pdf
    assert canonical_pdf.read_bytes() == PDF_BYTES


def test_batch_refetch_skips_papers_without_locator(tmp_path: Path) -> None:
    from scholaraio.services.pdf_fetch import batch_refetch_pdfs

    papers_dir = tmp_path / "papers"
    (papers_dir / "No-DOI").mkdir(parents=True)
    (papers_dir / "No-DOI" / "meta.json").write_text(
        json.dumps({"id": "no-doi", "title": "No DOI"}),
        encoding="utf-8",
    )
    cfg = _build_config({"paths": {"papers_dir": str(papers_dir)}}, tmp_path)

    results = batch_refetch_pdfs(cfg, direct=True, force=True)

    assert len(results) == 1
    assert results[0].status == "skipped"
    assert "no DOI or source_url" in results[0].message


def test_batch_refetch_records_bad_metadata_and_continues(tmp_path: Path) -> None:
    from scholaraio.services.pdf_fetch import batch_refetch_pdfs

    routes: dict[str, tuple[int, str, bytes]] = {}
    with _http_server(routes) as base_url:
        papers_dir = tmp_path / "papers"
        bad_dir = papers_dir / "Broken-Metadata"
        bad_dir.mkdir(parents=True)
        (bad_dir / "meta.json").write_text("{not-json", encoding="utf-8")

        good_dir = papers_dir / "Doe-2026-Good-Paper"
        good_dir.mkdir(parents=True)
        (good_dir / "meta.json").write_text(
            json.dumps({"id": "good-paper", "source_url": f"{base_url}/paper.pdf"}),
            encoding="utf-8",
        )
        routes["/paper.pdf"] = (200, "application/pdf", PDF_BYTES)

        cfg = _build_config({"paths": {"papers_dir": str(papers_dir)}}, tmp_path)
        results = batch_refetch_pdfs(
            cfg,
            paper_dirs=[bad_dir, good_dir],
            direct=True,
            force=True,
            timeout=5.0,
        )

    assert [result.status for result in results] == ["failed", "downloaded"]
    assert results[0].locator == bad_dir.name
    assert "Malformed JSON" in results[0].message
    assert results[1].path == good_dir / f"{good_dir.name}.pdf"
    assert results[1].path.read_bytes() == PDF_BYTES


def test_batch_refetch_reuses_and_closes_one_session(tmp_path: Path, monkeypatch) -> None:
    from scholaraio.services import pdf_fetch

    sessions: list[dict[str, bool]] = []
    original_session = pdf_fetch._session

    def tracking_session(*, direct: bool, timeout: float):
        session = original_session(direct=direct, timeout=timeout)
        state = {"closed": False}
        original_close = session.close

        def close() -> None:
            state["closed"] = True
            original_close()

        session.close = close
        sessions.append(state)
        return session

    monkeypatch.setattr(pdf_fetch, "_session", tracking_session)

    routes: dict[str, tuple[int, str, bytes]] = {}
    with _http_server(routes) as base_url:
        papers_dir = tmp_path / "papers"
        paper_dirs: list[Path] = []
        for idx in range(2):
            paper_dir = papers_dir / f"Doe-2026-Reuse-Session-{idx}"
            paper_dirs.append(paper_dir)
            paper_dir.mkdir(parents=True)
            (paper_dir / "meta.json").write_text(
                json.dumps({"id": f"paper-{idx}", "source_url": f"{base_url}/article-{idx}"}),
                encoding="utf-8",
            )
            (paper_dir / f"{paper_dir.name}.pdf").write_bytes(b"%PDF-1.4\nold\n%%EOF\n")
            routes[f"/article-{idx}"] = (
                200,
                "text/html; charset=utf-8",
                f'<meta name="citation_pdf_url" content="{base_url}/paper-{idx}.pdf">'.encode(),
            )
            routes[f"/paper-{idx}.pdf"] = (200, "application/pdf", PDF_BYTES)

        cfg = _build_config({"paths": {"papers_dir": str(papers_dir)}}, tmp_path)
        results = pdf_fetch.batch_refetch_pdfs(cfg, paper_dirs=paper_dirs, direct=True, force=True)

    assert [result.status for result in results] == ["downloaded", "downloaded"]
    assert sessions == [{"closed": True}]


def test_fetch_pdf_cli_downloads_new_locator_to_configured_inbox(tmp_path: Path) -> None:
    from scholaraio.interfaces.cli.fetch_pdf import cmd_fetch_pdf

    routes: dict[str, tuple[int, str, bytes]] = {}
    with _http_server(routes) as base_url:
        routes["/article"] = (
            200,
            "text/html; charset=utf-8",
            (
                "<html><head>"
                f'<meta name="citation_pdf_url" content="{base_url}/paper.pdf">'
                '<meta name="citation_title" content="CLI Real HTTP Paper">'
                "</head></html>"
            ).encode(),
        )
        routes["/paper.pdf"] = (200, "application/pdf", PDF_BYTES)

        cfg = _build_config(
            {"paths": {"inbox_dir": "queues/inbox", "papers_dir": "papers"}},
            tmp_path,
        )
        args = argparse.Namespace(
            locator=f"{base_url}/article",
            paper=None,
            all=False,
            out_dir=None,
            direct=True,
            force=False,
            ingest=False,
            timeout=5.0,
        )

        cmd_fetch_pdf(args, cfg)

    pdfs = sorted(cfg.inbox_dir.glob("*.pdf"))
    assert len(pdfs) == 1
    assert pdfs[0].read_bytes() == PDF_BYTES


def test_fetch_pdf_cli_ingest_uses_single_file_inbox_with_out_dir(tmp_path: Path, monkeypatch) -> None:
    from scholaraio.interfaces.cli.fetch_pdf import cmd_fetch_pdf
    from scholaraio.services.ingest import pipeline as pipeline_mod

    out_dir = tmp_path / "downloads"
    out_dir.mkdir()
    (out_dir / "unrelated.pdf").write_bytes(PDF_BYTES)
    captured: dict[str, object] = {}

    def fake_run_pipeline(_preset, _cfg, options) -> None:
        inbox_dir = Path(options["inbox_dir"])
        captured["same_as_out_dir"] = inbox_dir == out_dir
        captured["pdf_names"] = sorted(path.name for path in inbox_dir.glob("*.pdf"))

    monkeypatch.setattr(pipeline_mod, "run_pipeline", fake_run_pipeline)

    with _http_server({"/paper.pdf": (200, "application/pdf", PDF_BYTES)}) as base_url:
        cfg = _build_config({"paths": {"inbox_dir": "queues/inbox", "papers_dir": "papers"}}, tmp_path)
        args = argparse.Namespace(
            locator=f"{base_url}/paper.pdf",
            paper=None,
            all=False,
            out_dir=str(out_dir),
            direct=True,
            force=False,
            ingest=True,
            timeout=5.0,
        )

        cmd_fetch_pdf(args, cfg)

    assert captured["same_as_out_dir"] is False
    assert captured["pdf_names"] == ["paper.pdf"]
    assert (out_dir / "unrelated.pdf").read_bytes() == PDF_BYTES
    assert (out_dir / "paper.pdf").read_bytes() == PDF_BYTES


def test_fetch_pdf_cli_ingest_without_out_dir_reports_temporary_staging(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from scholaraio.interfaces.cli import fetch_pdf as fetch_pdf_cli
    from scholaraio.services.ingest import pipeline as pipeline_mod

    messages: list[str] = []
    captured: dict[str, object] = {}

    def fake_run_pipeline(_preset, _cfg, options) -> None:
        inbox_dir = Path(options["inbox_dir"])
        captured["same_as_configured_inbox"] = inbox_dir == _cfg.inbox_dir
        captured["pdf_names"] = sorted(path.name for path in inbox_dir.glob("*.pdf"))

    monkeypatch.setattr(fetch_pdf_cli, "_ui", lambda msg="": messages.append(msg))
    monkeypatch.setattr(pipeline_mod, "run_pipeline", fake_run_pipeline)

    with _http_server({"/paper.pdf": (200, "application/pdf", PDF_BYTES)}) as base_url:
        cfg = _build_config({"paths": {"inbox_dir": "queues/inbox", "papers_dir": "papers"}}, tmp_path)
        args = argparse.Namespace(
            locator=f"{base_url}/paper.pdf",
            paper=None,
            all=False,
            out_dir=None,
            direct=True,
            force=False,
            ingest=True,
            timeout=5.0,
        )

        fetch_pdf_cli.cmd_fetch_pdf(args, cfg)

    output = "\n".join(messages)
    assert "Staged PDF for ingest: paper.pdf" in output
    assert "Downloaded PDF:" not in output
    assert "scholaraio_pdf_fetch_" not in output
    assert "scholaraio_pdf_ingest_" not in output
    assert captured["same_as_configured_inbox"] is False
    assert captured["pdf_names"] == ["paper.pdf"]
    assert not list(cfg.inbox_dir.glob("*.pdf"))


def test_fetch_pdf_cli_reports_ingest_failure_separately(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from scholaraio.interfaces.cli import fetch_pdf as fetch_pdf_cli
    from scholaraio.services.ingest import pipeline as pipeline_mod

    messages: list[str] = []

    def fake_run_pipeline(_preset, _cfg, _options) -> None:
        raise RuntimeError("ingest exploded")

    monkeypatch.setattr(fetch_pdf_cli, "_ui", lambda msg="": messages.append(msg))
    monkeypatch.setattr(pipeline_mod, "run_pipeline", fake_run_pipeline)

    with _http_server({"/paper.pdf": (200, "application/pdf", PDF_BYTES)}) as base_url:
        out_dir = tmp_path / "downloads"
        cfg = _build_config({"paths": {"inbox_dir": "queues/inbox", "papers_dir": "papers"}}, tmp_path)
        args = argparse.Namespace(
            locator=f"{base_url}/paper.pdf",
            paper=None,
            all=False,
            out_dir=str(out_dir),
            direct=True,
            force=False,
            ingest=True,
            timeout=5.0,
        )

        with pytest.raises(SystemExit) as exc_info:
            fetch_pdf_cli.cmd_fetch_pdf(args, cfg)

    output = "\n".join(messages)
    assert exc_info.value.code == 1
    assert "PDF ingest failed: ingest exploded" in output
    assert "PDF fetch failed" not in output
    assert (out_dir / "paper.pdf").read_bytes() == PDF_BYTES


def test_fetch_pdf_parser_accepts_new_single_and_batch_modes() -> None:
    from scholaraio.interfaces.cli.fetch_pdf import cmd_fetch_pdf
    from scholaraio.interfaces.cli.parser import _build_parser

    parser = _build_parser()

    new_args = parser.parse_args(["fetch-pdf", "10.1000/example", "--direct"])
    single_args = parser.parse_args(["fetch-pdf", "--paper", "paper-1", "--force"])
    selected_args = parser.parse_args(["fetch-pdf", "--paper", "paper-1", "paper-2", "--force"])
    batch_args = parser.parse_args(["fetch-pdf", "--all", "--direct", "--force"])

    assert new_args.func is cmd_fetch_pdf
    assert new_args.locator == "10.1000/example"
    assert new_args.direct is True
    assert single_args.paper == ["paper-1"]
    assert selected_args.paper == ["paper-1", "paper-2"]
    assert batch_args.all is True


def test_fetch_pdf_cli_refetches_single_existing_paper(tmp_path: Path) -> None:
    from scholaraio.interfaces.cli.fetch_pdf import cmd_fetch_pdf

    routes: dict[str, tuple[int, str, bytes]] = {}
    with _http_server(routes) as base_url:
        papers_dir = tmp_path / "papers"
        paper_dir = papers_dir / "Doe-2026-CLI-Real-HTTP-Paper"
        paper_dir.mkdir(parents=True)
        (paper_dir / "meta.json").write_text(
            json.dumps({"id": "paper-1", "source_url": f"{base_url}/article"}),
            encoding="utf-8",
        )
        canonical_pdf = paper_dir / "Doe-2026-CLI-Real-HTTP-Paper.pdf"
        canonical_pdf.write_bytes(b"%PDF-1.4\nold\n%%EOF\n")
        routes["/article"] = (
            200,
            "text/html; charset=utf-8",
            f'<meta name="citation_pdf_url" content="{base_url}/new.pdf">'.encode(),
        )
        routes["/new.pdf"] = (200, "application/pdf", PDF_BYTES)

        cfg = _build_config({"paths": {"papers_dir": str(papers_dir)}}, tmp_path)
        args = argparse.Namespace(
            locator=None,
            paper=paper_dir.name,
            all=False,
            out_dir=None,
            direct=True,
            force=True,
            ingest=False,
            timeout=5.0,
        )

        cmd_fetch_pdf(args, cfg)

    assert canonical_pdf.read_bytes() == PDF_BYTES


def test_fetch_pdf_cli_batch_refetches_selected_existing_papers(tmp_path: Path) -> None:
    from scholaraio.interfaces.cli.fetch_pdf import cmd_fetch_pdf

    routes: dict[str, tuple[int, str, bytes]] = {}
    with _http_server(routes) as base_url:
        papers_dir = tmp_path / "papers"
        paper_ids: list[str] = []
        for idx in range(2):
            paper_dir = papers_dir / f"Doe-2026-Batch-Paper-{idx}"
            paper_ids.append(paper_dir.name)
            paper_dir.mkdir(parents=True)
            (paper_dir / "meta.json").write_text(
                json.dumps({"id": f"paper-{idx}", "source_url": f"{base_url}/article-{idx}"}),
                encoding="utf-8",
            )
            (paper_dir / f"{paper_dir.name}.pdf").write_bytes(b"%PDF-1.4\nold\n%%EOF\n")
            routes[f"/article-{idx}"] = (
                200,
                "text/html; charset=utf-8",
                f'<meta name="citation_pdf_url" content="{base_url}/paper-{idx}.pdf">'.encode(),
            )
            routes[f"/paper-{idx}.pdf"] = (200, "application/pdf", PDF_BYTES)

        cfg = _build_config({"paths": {"papers_dir": str(papers_dir)}}, tmp_path)
        args = argparse.Namespace(
            locator=None,
            paper=paper_ids,
            all=False,
            out_dir=None,
            direct=True,
            force=True,
            ingest=False,
            timeout=5.0,
        )

        cmd_fetch_pdf(args, cfg)

    for pdf in papers_dir.glob("*/*.pdf"):
        assert pdf.read_bytes() == PDF_BYTES
