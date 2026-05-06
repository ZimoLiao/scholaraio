"""Image discovery and localization for rendered web-link ingest."""

from __future__ import annotations

import mimetypes
import re
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit

MAX_IMAGE_BYTES = 25 * 1024 * 1024
_MARKDOWN_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\"\s]+)(?:\s+\"[^\"]*\")?\)")
_SAFE_EXTENSIONS = {
    ".apng",
    ".avif",
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".svg",
    ".webp",
}
_AMBIGUOUS_CONTENT_TYPES = {"", "application/octet-stream", "binary/octet-stream"}


@dataclass(frozen=True)
class ImageLocalizationItem:
    original_url: str
    resolved_url: str
    alt_text: str
    status: str
    local_path: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class ImageLocalizationResult:
    markdown: str
    images: list[ImageLocalizationItem]


@dataclass(frozen=True)
class _ImageRef:
    original: str
    alt_text: str
    url: str


class _HTMLImageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.refs: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "img":
            return
        attr_map = {name.lower(): value or "" for name, value in attrs}
        src = attr_map.get("src") or attr_map.get("data-src") or attr_map.get("data-original")
        if not src and attr_map.get("srcset"):
            src = _first_srcset_url(attr_map["srcset"])
        if not src:
            return
        self.refs.append((attr_map.get("alt") or "image", src))


def localize_ingest_link_images(
    *,
    markdown: str,
    html: str,
    base_url: str,
    images_dir: Path,
    fetch_bytes=None,
    timeout: float = 30.0,
) -> ImageLocalizationResult:
    """Download Markdown/HTML images and rewrite successful references locally.

    Failed downloads intentionally leave the original external URL in place so
    extracted content remains useful even when a remote host blocks image fetches.
    """
    fetch = fetch_bytes or _read_url_bytes
    content, refs = _append_html_image_refs(markdown, html, base_url)
    content_out = content
    items: list[ImageLocalizationItem] = []

    for ref in refs:
        resolved_url = _resolve_image_url(ref.url, base_url)
        if not resolved_url:
            items.append(
                ImageLocalizationItem(
                    original_url=ref.url,
                    resolved_url="",
                    alt_text=ref.alt_text,
                    status="skipped",
                    error="unsupported image URL",
                )
            )
            continue

        try:
            payload, content_type = fetch(resolved_url, timeout=timeout)
            _validate_image_content_type(resolved_url, content_type)
            filename = _unique_filename(images_dir, resolved_url, content_type)
            images_dir.mkdir(parents=True, exist_ok=True)
            (images_dir / filename).write_bytes(payload)
        except Exception as exc:
            items.append(
                ImageLocalizationItem(
                    original_url=ref.url,
                    resolved_url=resolved_url,
                    alt_text=ref.alt_text,
                    status="failed",
                    error=str(exc),
                )
            )
            continue

        local_path = f"{images_dir.name}/{filename}"
        replacement = f"![{_markdown_alt(ref.alt_text)}]({local_path})"
        content_out = content_out.replace(ref.original, replacement)
        items.append(
            ImageLocalizationItem(
                original_url=ref.url,
                resolved_url=resolved_url,
                alt_text=ref.alt_text,
                status="downloaded",
                local_path=local_path,
            )
        )

    return ImageLocalizationResult(markdown=content_out, images=items)


def _append_html_image_refs(markdown: str, html: str, base_url: str) -> tuple[str, list[_ImageRef]]:
    refs = _markdown_refs(markdown)
    seen = {_normalized_seen_url(ref.url, base_url) for ref in refs}
    html_refs = _html_refs(html)
    appended: list[_ImageRef] = []

    for alt_text, raw_url in html_refs:
        normalized = _normalized_seen_url(raw_url, base_url)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        original = f"![{_markdown_alt(alt_text)}]({raw_url})"
        appended.append(_ImageRef(original=original, alt_text=alt_text, url=raw_url))

    if appended:
        suffix = "\n\n## Image References\n\n" + "\n\n".join(ref.original for ref in appended)
        markdown = markdown.rstrip() + suffix + "\n"

    return markdown, [*refs, *appended]


def _markdown_refs(markdown: str) -> list[_ImageRef]:
    refs: list[_ImageRef] = []
    for match in _MARKDOWN_IMAGE_RE.finditer(markdown):
        refs.append(_ImageRef(original=match.group(0), alt_text=match.group(1) or "image", url=match.group(2)))
    return refs


def _html_refs(html: str) -> list[tuple[str, str]]:
    if not html:
        return []
    parser = _HTMLImageParser()
    parser.feed(html)
    return parser.refs


def _first_srcset_url(srcset: str) -> str:
    first = srcset.split(",", 1)[0].strip()
    return first.split(None, 1)[0] if first else ""


def _resolve_image_url(raw_url: str, base_url: str) -> str:
    raw = (raw_url or "").strip()
    if not raw or raw.lower().startswith("data:"):
        return ""
    parsed = urlsplit(urljoin(base_url, raw))
    if parsed.scheme not in {"http", "https"}:
        return ""
    path = quote(unquote(parsed.path), safe="/%:@")
    query = quote(unquote(parsed.query), safe="=&?/%:+,;@")
    return urlunsplit((parsed.scheme, parsed.netloc, path, query, parsed.fragment))


def _normalized_seen_url(raw_url: str, base_url: str) -> str:
    return _resolve_image_url(raw_url, base_url) or raw_url.strip()


def _read_url_bytes(url: str, *, timeout: float = 30.0) -> tuple[bytes, str]:
    headers = {
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "User-Agent": "ScholarAIO/1.4 (+https://github.com/ZimoLiao/scholaraio)",
    }
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        content_type = response.headers.get("Content-Type", "") if response.headers else ""
        payload = response.read(MAX_IMAGE_BYTES + 1)
    if len(payload) > MAX_IMAGE_BYTES:
        raise ValueError(f"image exceeds {MAX_IMAGE_BYTES} bytes")
    return payload, content_type


def _validate_image_content_type(url: str, content_type: str) -> None:
    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    if normalized.startswith("image/"):
        return
    if normalized in _AMBIGUOUS_CONTENT_TYPES and Path(_filename_from_url(url)).suffix.lower() in _SAFE_EXTENSIONS:
        return
    display_type = normalized or "missing"
    raise ValueError(f"unsupported image content type: {display_type}")


def _unique_filename(images_dir: Path, url: str, content_type: str) -> str:
    base = _filename_from_url(url)
    suffix = Path(base).suffix.lower()
    if suffix not in _SAFE_EXTENSIONS:
        guessed = mimetypes.guess_extension((content_type or "").split(";", 1)[0].strip())
        suffix = guessed if guessed in _SAFE_EXTENSIONS else ".jpg"
        base = f"{Path(base).stem}{suffix}"

    candidate = base
    counter = 1
    while (images_dir / candidate).exists():
        stem = Path(base).stem
        suffix = Path(base).suffix
        candidate = f"{stem}-{counter}{suffix}"
        counter += 1
    return candidate


def _filename_from_url(url: str) -> str:
    path_name = unquote(Path(urlsplit(url).path).name)
    if not path_name:
        path_name = "image.jpg"
    stem = Path(path_name).stem or "image"
    suffix = Path(path_name).suffix.lower()
    safe_stem = re.sub(r"[^a-zA-Z0-9._-]+", "-", stem).strip(".-_").lower()
    safe_stem = safe_stem[:96].strip(".-_") or "image"
    return f"{safe_stem}{suffix}"


def _markdown_alt(alt_text: str) -> str:
    return (alt_text or "image").replace("[", "(").replace("]", ")").replace("\n", " ").strip() or "image"
