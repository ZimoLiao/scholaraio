"""Tests for scholaraio.sources.webtools HTTP connector helpers."""

from __future__ import annotations

import json

import pytest


class _FakeResponse:
    def __init__(self, payload: object, status: int = 200):
        self._payload = payload
        self.status = status

    def read(self) -> bytes:
        if isinstance(self._payload, bytes):
            return self._payload
        if isinstance(self._payload, str):
            return self._payload.encode("utf-8")
        return json.dumps(self._payload, ensure_ascii=False).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class TestWebtoolsConnector:
    def test_check_webextract_health(self, monkeypatch):
        seen: dict[str, object] = {}

        def fake_urlopen(req, timeout=0):
            seen["url"] = req.full_url
            seen["method"] = req.get_method()
            return _FakeResponse({"status": "ok"})

        monkeypatch.setattr("scholaraio.sources.webtools.urlopen", fake_urlopen)

        from scholaraio.sources.webtools import check_webextract_health

        result = check_webextract_health()

        assert result == {"status": "ok"}
        assert seen["url"] == "http://127.0.0.1:8766/health"
        assert seen["method"] == "GET"

    def test_check_websearch_health_uses_env_base_url(self, monkeypatch):
        seen: dict[str, object] = {}

        def fake_urlopen(req, timeout=0):
            seen["url"] = req.full_url
            return _FakeResponse({"status": "ok"})

        monkeypatch.setenv("WEBSEARCH_URL", "http://localhost:9999")
        monkeypatch.setattr("scholaraio.sources.webtools.urlopen", fake_urlopen)

        from scholaraio.sources.webtools import check_websearch_health

        result = check_websearch_health()

        assert result["status"] == "ok"
        assert seen["url"] == "http://localhost:9999/health"

    def test_websearch_posts_query_and_count(self, monkeypatch):
        seen: dict[str, object] = {}

        def fake_urlopen(req, timeout=0):
            seen["url"] = req.full_url
            seen["method"] = req.get_method()
            seen["body"] = json.loads(req.data.decode("utf-8"))
            return _FakeResponse([{"title": "Example", "link": "https://example.com", "snippet": "snippet"}])

        monkeypatch.setattr("scholaraio.sources.webtools.urlopen", fake_urlopen)

        from scholaraio.sources.webtools import websearch

        result = websearch("wall turbulence", count=7)

        assert result[0]["title"] == "Example"
        assert seen["url"] == "http://127.0.0.1:8765/search"
        assert seen["method"] == "POST"
        assert seen["body"] == {"query": "wall turbulence", "count": 7}

    def test_webextract_single_posts_extract_payload(self, monkeypatch):
        seen: dict[str, object] = {}

        def fake_urlopen(req, timeout=0):
            seen["url"] = req.full_url
            seen["method"] = req.get_method()
            seen["body"] = json.loads(req.data.decode("utf-8"))
            return _FakeResponse(
                {
                    "url": "https://example.com",
                    "title": "Example Domain",
                    "text": "# Example Domain",
                    "html": "<html></html>",
                    "error": "",
                }
            )

        monkeypatch.setattr("scholaraio.sources.webtools.urlopen", fake_urlopen)

        from scholaraio.sources.webtools import webextract

        result = webextract("https://example.com")

        assert result["title"] == "Example Domain"
        assert seen["url"] == "http://127.0.0.1:8766/extract"
        assert seen["method"] == "POST"
        assert seen["body"] == {"url": "https://example.com"}

    def test_webextract_single_includes_pdf_flag_when_set(self, monkeypatch):
        seen: dict[str, object] = {}

        def fake_urlopen(req, timeout=0):
            seen["body"] = json.loads(req.data.decode("utf-8"))
            return _FakeResponse(
                {
                    "url": "https://example.com/file",
                    "title": "PDF",
                    "text": "body",
                    "html": "",
                    "error": "",
                }
            )

        monkeypatch.setattr("scholaraio.sources.webtools.urlopen", fake_urlopen)

        from scholaraio.sources.webtools import webextract

        webextract("https://example.com/file", pdf=True)

        assert seen["body"] == {"url": "https://example.com/file", "pdf": True}

    def test_webextract_batch_posts_open_webui_payload(self, monkeypatch):
        seen: dict[str, object] = {}

        def fake_urlopen(req, timeout=0):
            seen["url"] = req.full_url
            seen["body"] = json.loads(req.data.decode("utf-8"))
            return _FakeResponse(
                [
                    {
                        "page_content": "# Example",
                        "metadata": {"source": "https://example.com", "title": "Example"},
                    }
                ]
            )

        monkeypatch.setattr("scholaraio.sources.webtools.urlopen", fake_urlopen)

        from scholaraio.sources.webtools import webextract_batch

        result = webextract_batch(["https://example.com"])

        assert result[0]["metadata"]["title"] == "Example"
        assert seen["url"] == "http://127.0.0.1:8766"
        assert seen["body"] == {"urls": ["https://example.com"]}

    def test_webextract_raises_runtime_error_on_invalid_json(self, monkeypatch):
        def fake_urlopen(req, timeout=0):
            return _FakeResponse("{not-json")

        monkeypatch.setattr("scholaraio.sources.webtools.urlopen", fake_urlopen)

        from scholaraio.sources.webtools import webextract

        with pytest.raises(RuntimeError, match="解析响应失败"):
            webextract("https://example.com")

    def test_websearch_includes_bearer_token_when_env_key_is_set(self, monkeypatch):
        seen: dict[str, object] = {}

        def fake_urlopen(req, timeout=0):
            seen["auth"] = req.headers.get("Authorization")
            return _FakeResponse([])

        monkeypatch.setenv("WEBSEARCH_API_KEY", "secret-key")
        monkeypatch.setattr("scholaraio.sources.webtools.urlopen", fake_urlopen)

        from scholaraio.sources.webtools import websearch

        websearch("test query")

        assert seen["auth"] == "Bearer secret-key"


class TestWebtoolsEnhancedSearch:
    def test_search_web_uses_cfg_base_url_and_api_key(self, monkeypatch, tmp_path):
        seen: dict[str, object] = {}

        def fake_urlopen(req, timeout=0):
            seen["url"] = req.full_url
            seen["auth"] = req.headers.get("Authorization")
            return _FakeResponse([])

        monkeypatch.setattr("scholaraio.sources.webtools.urlopen", fake_urlopen)

        from scholaraio.config import _build_config
        from scholaraio.sources.webtools import search_web

        cfg = _build_config(
            {
                "websearch": {
                    "base_url": "http://localhost:9999",
                    "api_key": "cfg-secret",
                }
            },
            tmp_path,
        )

        search_web("query", cfg=cfg)

        assert seen["url"] == "http://localhost:9999/search"
        assert seen["auth"] == "Bearer cfg-secret"

    def test_search_web_returns_websearchresult_list(self, monkeypatch):
        def fake_urlopen(req, timeout=0):
            return _FakeResponse(
                [
                    {"title": "T1", "link": "https://a.com", "snippet": "S1"},
                    {"title": "T2", "link": "https://b.com", "snippet": "S2"},
                ]
            )

        monkeypatch.setattr("scholaraio.sources.webtools.urlopen", fake_urlopen)

        from scholaraio.sources.webtools import search_web

        results = search_web("query")

        assert len(results) == 2
        assert results[0].title == "T1"
        assert results[0].link == "https://a.com"
        assert results[0].snippet == "S1"

    def test_search_web_raises_service_unavailable_on_health_failure(self, monkeypatch):
        def fake_urlopen(req, timeout=0):
            raise OSError("connection refused")

        monkeypatch.setattr("scholaraio.sources.webtools.urlopen", fake_urlopen)

        from scholaraio.sources.webtools import ServiceUnavailableError, search_web

        with pytest.raises(ServiceUnavailableError):
            search_web("query")

    def test_search_and_display_prints_results(self, monkeypatch, capsys):
        def fake_urlopen(req, timeout=0):
            return _FakeResponse([{"title": "T", "link": "https://x.com", "snippet": "S"}])

        monkeypatch.setattr("scholaraio.sources.webtools.urlopen", fake_urlopen)

        from scholaraio.sources.webtools import search_and_display

        results = search_and_display("q", count=1)

        assert len(results) == 1
        captured = capsys.readouterr()
        assert "T" in captured.out
        assert "https://x.com" in captured.out

    def test_search_and_display_propagates_service_unavailable(self, monkeypatch):
        from scholaraio.sources.webtools import ServiceUnavailableError, search_and_display

        def fake_search_web(*args, **kwargs):
            raise ServiceUnavailableError("service down")

        monkeypatch.setattr("scholaraio.sources.webtools.search_web", fake_search_web)

        with pytest.raises(ServiceUnavailableError, match="service down"):
            search_and_display("q")

    def test_search_and_fetch_arxiv_filters_results(self, monkeypatch):
        def fake_urlopen(req, timeout=0):
            return _FakeResponse(
                [
                    {"title": "ArXiv", "link": "https://arxiv.org/abs/2301.12345", "snippet": "s"},
                    {"title": "Other", "link": "https://example.com", "snippet": "s"},
                ]
            )

        monkeypatch.setattr("scholaraio.sources.webtools.urlopen", fake_urlopen)

        from scholaraio.sources.webtools import search_and_fetch_arxiv

        papers = search_and_fetch_arxiv("q")

        assert len(papers) == 1
        assert papers[0]["arxiv_id"] == "2301.12345"


class TestWebtoolsEnhancedExtract:
    def test_extract_web_returns_dict(self, monkeypatch):
        def fake_urlopen(req, timeout=0):
            return _FakeResponse({"title": "Page", "text": "body"})

        monkeypatch.setattr("scholaraio.sources.webtools.urlopen", fake_urlopen)

        from scholaraio.sources.webtools import extract_web

        result = extract_web("https://example.com")

        assert result["title"] == "Page"
        assert result["text"] == "body"

    def test_extract_web_raises_on_service_unavailable(self, monkeypatch):
        def fake_urlopen(req, timeout=0):
            raise OSError("refused")

        monkeypatch.setattr("scholaraio.sources.webtools.urlopen", fake_urlopen)

        from scholaraio.sources.webtools import WebExtractServiceUnavailableError, extract_web

        with pytest.raises(WebExtractServiceUnavailableError):
            extract_web("https://example.com")

    def test_extract_and_display_prints_text(self, monkeypatch, capsys):
        def fake_urlopen(req, timeout=0):
            return _FakeResponse({"title": "Page", "text": "markdown body"})

        monkeypatch.setattr("scholaraio.sources.webtools.urlopen", fake_urlopen)

        from scholaraio.sources.webtools import extract_and_display

        result = extract_and_display("https://example.com")

        assert result is not None
        assert result["title"] == "Page"
        captured = capsys.readouterr()
        assert "markdown body" in captured.out
