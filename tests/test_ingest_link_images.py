"""Tests for web-link image localization helpers."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_localize_ingest_link_images_discovers_html_images_and_rewrites_to_local_dir(tmp_path: Path) -> None:
    from scholaraio.services.ingest.link_images import localize_ingest_link_images

    images_dir = tmp_path / "01-example-page_images"
    seen_urls: list[str] = []

    def fetch_bytes(url: str, *, timeout: float = 30.0) -> tuple[bytes, str]:
        seen_urls.append(url)
        return b"fake-png", "image/png"

    result = localize_ingest_link_images(
        markdown="# Example\n\nBody text.\n",
        html='<main><img src="/figures/main plot.png" alt="Main Plot"></main>',
        base_url="https://example.com/articles/index.html",
        images_dir=images_dir,
        fetch_bytes=fetch_bytes,
    )

    assert seen_urls == ["https://example.com/figures/main%20plot.png"]
    assert (images_dir / "main-plot.png").read_bytes() == b"fake-png"
    assert "## Image References" in result.markdown
    assert "![Main Plot](01-example-page_images/main-plot.png)" in result.markdown
    assert result.images[0].status == "downloaded"
    assert result.images[0].local_path == "01-example-page_images/main-plot.png"


def test_localize_ingest_link_images_preserves_external_url_when_download_fails(tmp_path: Path) -> None:
    from scholaraio.services.ingest.link_images import localize_ingest_link_images

    def fetch_bytes(url: str, *, timeout: float = 30.0) -> tuple[bytes, str]:
        raise OSError("403 forbidden")

    result = localize_ingest_link_images(
        markdown="# Example\n\n![Blocked](https://cdn.example.com/blocked.png)\n",
        html="",
        base_url="https://example.com/",
        images_dir=tmp_path / "01-example_images",
        fetch_bytes=fetch_bytes,
    )

    assert "![Blocked](https://cdn.example.com/blocked.png)" in result.markdown
    assert result.images[0].status == "failed"
    assert "403 forbidden" in (result.images[0].error or "")


def test_localize_ingest_link_images_rejects_non_image_responses(tmp_path: Path) -> None:
    from scholaraio.services.ingest.link_images import localize_ingest_link_images

    images_dir = tmp_path / "01-example_images"

    def fetch_bytes(url: str, *, timeout: float = 30.0) -> tuple[bytes, str]:
        return b"<html>not an image</html>", "text/html"

    result = localize_ingest_link_images(
        markdown="# Example\n\n![Not Image](https://example.com/web_sample1.html)\n",
        html="",
        base_url="https://example.com/",
        images_dir=images_dir,
        fetch_bytes=fetch_bytes,
    )

    assert "![Not Image](https://example.com/web_sample1.html)" in result.markdown
    assert not images_dir.exists()
    assert result.images[0].status == "failed"
    assert "unsupported image content type" in (result.images[0].error or "")


def test_read_url_bytes_preserves_missing_content_type_as_ambiguous(monkeypatch: pytest.MonkeyPatch) -> None:
    from email.message import Message

    from scholaraio.services.ingest import link_images

    class FakeResponse:
        headers = Message()
        headers["Server"] = "example"

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self, limit: int) -> bytes:
            assert limit == link_images.MAX_IMAGE_BYTES + 1
            return b"fake-png"

    def fake_urlopen(request: object, *, timeout: float) -> FakeResponse:
        assert timeout == 1.5
        return FakeResponse()

    monkeypatch.setattr(link_images.urllib.request, "urlopen", fake_urlopen)

    payload, content_type = link_images._read_url_bytes("https://example.com/plot.png", timeout=1.5)

    assert payload == b"fake-png"
    assert content_type == ""


def test_localize_ingest_link_images_skips_data_uris_without_creating_assets(tmp_path: Path) -> None:
    from scholaraio.services.ingest.link_images import localize_ingest_link_images

    images_dir = tmp_path / "01-example_images"
    result = localize_ingest_link_images(
        markdown="# Example\n\n![Inline](data:image/png;base64,AAAA)\n",
        html="",
        base_url="https://example.com/",
        images_dir=images_dir,
        fetch_bytes=lambda url, *, timeout=30.0: pytest.fail("data URI should not be downloaded"),
    )

    assert "data:image/png;base64,AAAA" in result.markdown
    assert not images_dir.exists()
    assert result.images[0].status == "skipped"
