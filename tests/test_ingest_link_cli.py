"""Tests for the ingest-link CLI command."""

from __future__ import annotations

import json
from argparse import Namespace
from types import SimpleNamespace

from scholaraio import cli
from scholaraio import log as scholaraio_log


class TestIngestLinkCommand:
    def test_ingest_link_dry_run_reports_urls(self, tmp_path, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)

        called = {"extract": 0, "pipeline": 0}
        monkeypatch.setattr(
            "scholaraio.sources.webtools.extract_web",
            lambda *args, **kwargs: called.__setitem__("extract", called["extract"] + 1),
        )
        monkeypatch.setattr(
            "scholaraio.ingest.pipeline.run_pipeline",
            lambda *args, **kwargs: called.__setitem__("pipeline", called["pipeline"] + 1),
        )

        cfg = SimpleNamespace(_root=tmp_path, papers_dir=tmp_path / "data" / "papers")
        args = Namespace(
            urls=["https://example.com/a", "https://example.com/b"],
            dry_run=True,
            force=False,
            pdf=False,
            no_index=False,
            json=False,
        )

        cli.cmd_ingest_link(args, cfg)

        assert called == {"extract": 0, "pipeline": 0}
        assert any("[dry-run]" in m and "2 个链接" in m for m in messages)

    def test_ingest_link_uses_temp_doc_inbox_pipeline(self, tmp_path, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)

        def fake_extract(url, *, pdf=None, cfg=None, include_html=False, timeout=120.0):
            assert pdf is None
            return {
                "url": url,
                "title": "Example Page",
                "text": "## Intro\n\nHello from the web.",
                "html": "<html></html>",
                "error": "",
            }

        seen: dict[str, object] = {}

        def fake_run_pipeline(step_names, cfg, opts):
            seen["steps"] = step_names
            seen["doc_inbox_dir"] = opts["doc_inbox_dir"]
            seen["opts"] = opts
            inbox = opts["doc_inbox_dir"]
            md_files = sorted(inbox.glob("*.md"))
            json_files = sorted(inbox.glob("*.json"))
            seen["md_text"] = md_files[0].read_text(encoding="utf-8")
            seen["sidecar"] = json.loads(json_files[0].read_text(encoding="utf-8"))

        monkeypatch.setattr("scholaraio.sources.webtools.extract_web", fake_extract)
        monkeypatch.setattr("scholaraio.ingest.pipeline.run_pipeline", fake_run_pipeline)

        cfg = SimpleNamespace(_root=tmp_path, papers_dir=tmp_path / "data" / "papers")
        args = Namespace(
            urls=["https://example.com/article"],
            dry_run=False,
            force=True,
            pdf=False,
            no_index=False,
            json=False,
        )

        cli.cmd_ingest_link(args, cfg)

        assert seen["steps"] == ["extract_doc", "ingest", "embed", "index"]
        assert seen["doc_inbox_dir"] != cfg._root / "data" / "inbox-doc"
        assert seen["opts"]["inbox_dir"] != cfg._root / "data" / "inbox"
        assert seen["opts"]["include_aux_inboxes"] is False
        assert seen["opts"]["force"] is True
        assert "# Example Page" in seen["md_text"]
        assert "Source URL: https://example.com/article" in seen["md_text"]
        assert seen["sidecar"]["source_url"] == "https://example.com/article"
        assert seen["sidecar"]["source_type"] == "web"
        assert seen["sidecar"]["extraction_method"] == "qt-web-extractor"
        assert any("开始直接入库链接" in m for m in messages)

    def test_ingest_link_no_index_skips_global_steps(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "scholaraio.sources.webtools.extract_web",
            lambda url, *, pdf=None, cfg=None, include_html=False, timeout=120.0: {
                "url": url,
                "title": "Example Page",
                "text": "Body",
                "html": "",
                "error": "",
            },
        )

        seen: dict[str, object] = {}

        def fake_run_pipeline(step_names, cfg, opts):
            seen["steps"] = step_names

        monkeypatch.setattr("scholaraio.ingest.pipeline.run_pipeline", fake_run_pipeline)

        cfg = SimpleNamespace(_root=tmp_path, papers_dir=tmp_path / "data" / "papers")
        args = Namespace(
            urls=["https://example.com/article"],
            dry_run=False,
            force=False,
            pdf=False,
            no_index=True,
            json=False,
        )

        cli.cmd_ingest_link(args, cfg)

        assert seen["steps"] == ["extract_doc", "ingest"]

    def test_ingest_link_json_outputs_extracted_summary(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(
            "scholaraio.sources.webtools.extract_web",
            lambda url, *, pdf=None, cfg=None, include_html=False, timeout=120.0: {
                "url": url,
                "title": "Example Page",
                "text": "Body",
                "html": "",
                "error": "",
            },
        )
        monkeypatch.setattr("scholaraio.ingest.pipeline.run_pipeline", lambda *args, **kwargs: None)

        cfg = SimpleNamespace(_root=tmp_path, papers_dir=tmp_path / "data" / "papers")
        args = Namespace(
            urls=["https://example.com/article"],
            dry_run=False,
            force=False,
            pdf=False,
            no_index=False,
            json=True,
        )

        cli.cmd_ingest_link(args, cfg)

        payload = json.loads(capsys.readouterr().out)
        assert payload == [
            {
                "url": "https://example.com/article",
                "title": "Example Page",
                "markdown_file": "01-example-page.md",
            }
        ]

    def test_ingest_link_json_keeps_stdout_parseable(self, tmp_path, monkeypatch, capsys):
        scholaraio_log.reset()
        scholaraio_log.setup(
            SimpleNamespace(
                log_file=tmp_path / "scholaraio.log",
                log=SimpleNamespace(max_bytes=100000, backup_count=1, level="INFO"),
            )
        )

        monkeypatch.setattr(
            "scholaraio.sources.webtools.extract_web",
            lambda url, *, pdf=None, cfg=None, include_html=False, timeout=120.0: {
                "url": url,
                "title": "Example Page",
                "text": "Body",
                "html": "",
                "error": "",
            },
        )

        def fake_run_pipeline(*args, **kwargs):
            from scholaraio.ingest.pipeline import ui as pipeline_ui

            pipeline_ui("pipeline progress")

        monkeypatch.setattr("scholaraio.ingest.pipeline.run_pipeline", fake_run_pipeline)

        cfg = SimpleNamespace(_root=tmp_path, papers_dir=tmp_path / "data" / "papers")
        args = Namespace(
            urls=["https://example.com/article"],
            dry_run=False,
            force=False,
            pdf=False,
            no_index=False,
            json=True,
        )

        try:
            cli.cmd_ingest_link(args, cfg)
            captured = capsys.readouterr()
        finally:
            scholaraio_log.reset()

        payload = json.loads(captured.out)
        assert payload == [
            {
                "url": "https://example.com/article",
                "title": "Example Page",
                "markdown_file": "01-example-page.md",
            }
        ]
        assert "pipeline progress" in captured.err

    def test_ingest_link_pdf_flag_only_sent_when_requested(self, tmp_path, monkeypatch):
        seen: list[bool | None] = []

        def fake_extract(url, *, pdf=None, cfg=None, include_html=False, timeout=120.0):
            seen.append(pdf)
            return {
                "url": url,
                "title": "Example Page",
                "text": "Body",
                "html": "",
                "error": "",
            }

        monkeypatch.setattr("scholaraio.sources.webtools.extract_web", fake_extract)
        monkeypatch.setattr("scholaraio.ingest.pipeline.run_pipeline", lambda *args, **kwargs: None)

        cfg = SimpleNamespace(_root=tmp_path, papers_dir=tmp_path / "data" / "papers")

        cli.cmd_ingest_link(
            Namespace(
                urls=["https://example.com/article"],
                dry_run=False,
                force=False,
                pdf=False,
                no_index=True,
                json=False,
            ),
            cfg,
        )
        cli.cmd_ingest_link(
            Namespace(
                urls=["https://example.com/report.pdf"],
                dry_run=False,
                force=False,
                pdf=True,
                no_index=True,
                json=False,
            ),
            cfg,
        )

        assert seen == [None, True]

    def test_ingest_link_uses_cfg_backed_extract_web(self, tmp_path, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)

        seen: dict[str, object] = {}

        def fake_extract_web(url, *, pdf=None, cfg=None, include_html=False, timeout=120.0):
            seen["url"] = url
            seen["pdf"] = pdf
            seen["cfg"] = cfg
            return {
                "url": url,
                "title": "Example Page",
                "text": "Body",
                "html": "",
                "error": "",
            }

        def fail_legacy_webextract(*args, **kwargs):
            raise AssertionError("legacy webextract should not be used")

        monkeypatch.setattr("scholaraio.sources.webtools.extract_web", fake_extract_web)
        monkeypatch.setattr("scholaraio.sources.webtools.webextract", fail_legacy_webextract)

        called: dict[str, object] = {}
        monkeypatch.setattr(
            "scholaraio.ingest.pipeline.run_pipeline",
            lambda *args, **kwargs: called.__setitem__("pipeline", True),
        )

        cfg = SimpleNamespace(
            _root=tmp_path,
            papers_dir=tmp_path / "data" / "papers",
            webextract=SimpleNamespace(base_url="http://localhost:9999", api_key="cfg-secret"),
        )

        cli.cmd_ingest_link(
            Namespace(
                urls=["https://example.com/article"],
                dry_run=False,
                force=False,
                pdf=False,
                no_index=True,
                json=False,
            ),
            cfg,
        )

        assert seen["url"] == "https://example.com/article"
        assert seen["pdf"] is None
        assert seen["cfg"] is cfg
        assert called["pipeline"] is True

    def test_ingest_link_skips_failed_urls_but_keeps_successful_items(self, tmp_path, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)

        responses = {
            "https://example.com/good": {
                "url": "https://example.com/good",
                "title": "First Page",
                "text": "First body",
                "html": "",
                "error": "",
            },
            "https://example.com/bad": {
                "url": "https://example.com/bad",
                "title": "",
                "text": "",
                "html": "",
                "error": "network timeout",
            },
            "https://example.com/also-good": {
                "url": "https://example.com/also-good",
                "title": "Second Page",
                "text": "Second body",
                "html": "",
                "error": "",
            },
        }
        monkeypatch.setattr(
            "scholaraio.sources.webtools.extract_web",
            lambda url, *, pdf=None, cfg=None, include_html=False, timeout=120.0: responses[url],
        )

        seen: dict[str, object] = {}

        def fake_run_pipeline(step_names, cfg, opts):
            seen["steps"] = step_names
            seen["files"] = sorted(path.name for path in opts["doc_inbox_dir"].glob("*.md"))

        monkeypatch.setattr("scholaraio.ingest.pipeline.run_pipeline", fake_run_pipeline)

        cli.cmd_ingest_link(
            Namespace(
                urls=[
                    "https://example.com/good",
                    "https://example.com/bad",
                    "https://example.com/also-good",
                ],
                dry_run=False,
                force=False,
                pdf=False,
                no_index=True,
                json=False,
            ),
            SimpleNamespace(_root=tmp_path, papers_dir=tmp_path / "data" / "papers"),
        )

        assert seen["steps"] == ["extract_doc", "ingest"]
        assert seen["files"] == ["01-first-page.md", "03-second-page.md"]
        assert any("已跳过" in message and "network timeout" in message for message in messages)

    def test_ingest_link_keeps_warned_extractions_with_text(self, tmp_path, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)

        monkeypatch.setattr(
            "scholaraio.sources.webtools.extract_web",
            lambda url, *, pdf=None, cfg=None, include_html=False, timeout=120.0: {
                "url": url,
                "title": "Warned Page",
                "text": "Recovered body",
                "html": "",
                "error": "partial extraction",
            },
        )

        seen: dict[str, object] = {}

        def fake_run_pipeline(step_names, cfg, opts):
            md_files = sorted(opts["doc_inbox_dir"].glob("*.md"))
            seen["steps"] = step_names
            seen["files"] = [path.name for path in md_files]
            seen["md_text"] = md_files[0].read_text(encoding="utf-8")

        monkeypatch.setattr("scholaraio.ingest.pipeline.run_pipeline", fake_run_pipeline)

        cli.cmd_ingest_link(
            Namespace(
                urls=["https://example.com/warned"],
                dry_run=False,
                force=False,
                pdf=False,
                no_index=True,
                json=False,
            ),
            SimpleNamespace(_root=tmp_path, papers_dir=tmp_path / "data" / "papers"),
        )

        assert seen["steps"] == ["extract_doc", "ingest"]
        assert seen["files"] == ["01-warned-page.md"]
        assert "Recovered body" in seen["md_text"]
        assert any("继续入库" in message and "partial extraction" in message for message in messages)

    def test_ingest_link_uses_short_fallback_name_for_titleless_long_urls(self, tmp_path, monkeypatch):
        long_url = "https://example.com/download?token=" + ("a" * 400)
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)

        monkeypatch.setattr(
            "scholaraio.sources.webtools.extract_web",
            lambda url, *, pdf=None, cfg=None, include_html=False, timeout=120.0: {
                "url": url,
                "title": "",
                "text": "Recovered body",
                "html": "",
                "error": "",
            },
        )

        seen: dict[str, object] = {}

        def fake_run_pipeline(step_names, cfg, opts):
            md_files = sorted(opts["doc_inbox_dir"].glob("*.md"))
            seen["steps"] = step_names
            seen["md_name"] = md_files[0].name

        monkeypatch.setattr("scholaraio.ingest.pipeline.run_pipeline", fake_run_pipeline)

        cli.cmd_ingest_link(
            Namespace(
                urls=[long_url],
                dry_run=False,
                force=False,
                pdf=False,
                no_index=True,
                json=False,
            ),
            SimpleNamespace(_root=tmp_path, papers_dir=tmp_path / "data" / "papers"),
        )

        assert seen["steps"] == ["extract_doc", "ingest"]
        assert seen["md_name"] == "01-download.md"
        assert len(seen["md_name"].encode("utf-8")) < 255
        assert not any("失败" in message for message in messages)

    def test_ingest_link_retries_transient_extraction_exception(self, tmp_path, monkeypatch):
        messages: list[str] = []
        sleep_calls: list[float] = []
        attempts = {"count": 0}
        monkeypatch.setattr(cli, "ui", messages.append)
        monkeypatch.setattr(cli.time, "sleep", sleep_calls.append)

        def fake_extract(url, *, pdf=None, cfg=None, include_html=False, timeout=120.0):
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise RuntimeError("temporary outage")
            return {
                "url": url,
                "title": "Recovered Page",
                "text": "Recovered body",
                "html": "",
                "error": "",
            }

        monkeypatch.setattr("scholaraio.sources.webtools.extract_web", fake_extract)

        seen: dict[str, object] = {}

        def fake_run_pipeline(step_names, cfg, opts):
            seen["steps"] = step_names
            seen["files"] = sorted(path.name for path in opts["doc_inbox_dir"].glob("*.md"))

        monkeypatch.setattr("scholaraio.ingest.pipeline.run_pipeline", fake_run_pipeline)

        cli.cmd_ingest_link(
            Namespace(
                urls=["https://example.com/retry"],
                dry_run=False,
                force=False,
                pdf=False,
                no_index=True,
                json=False,
            ),
            SimpleNamespace(_root=tmp_path, papers_dir=tmp_path / "data" / "papers"),
        )

        assert attempts["count"] == 3
        assert sleep_calls == [1.0, 2.0]
        assert seen["steps"] == ["extract_doc", "ingest"]
        assert seen["files"] == ["01-recovered-page.md"]
        assert any("提取失败，准备重试" in message for message in messages)
        assert any("重试后成功" in message for message in messages)

    def test_ingest_link_skips_url_after_retry_budget_exhausted(self, tmp_path, monkeypatch):
        messages: list[str] = []
        sleep_calls: list[float] = []
        attempts = {"count": 0}
        monkeypatch.setattr(cli, "ui", messages.append)
        monkeypatch.setattr(cli.time, "sleep", sleep_calls.append)

        def fake_extract(url, *, pdf=None, cfg=None, include_html=False, timeout=120.0):
            attempts["count"] += 1
            raise RuntimeError("temporary outage")

        monkeypatch.setattr("scholaraio.sources.webtools.extract_web", fake_extract)

        pipeline_called = {"value": False}

        def fake_run_pipeline(*args, **kwargs):
            pipeline_called["value"] = True

        monkeypatch.setattr("scholaraio.ingest.pipeline.run_pipeline", fake_run_pipeline)

        cli.cmd_ingest_link(
            Namespace(
                urls=["https://example.com/retry"],
                dry_run=False,
                force=False,
                pdf=False,
                no_index=True,
                json=False,
            ),
            SimpleNamespace(_root=tmp_path, papers_dir=tmp_path / "data" / "papers"),
        )

        assert attempts["count"] == 3
        assert sleep_calls == [1.0, 2.0]
        assert pipeline_called["value"] is False
        assert any("已跳过" in message and "temporary outage" in message for message in messages)
        assert any("没有可入库的链接内容" in message for message in messages)
