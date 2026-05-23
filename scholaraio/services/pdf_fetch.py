"""Lightweight, rights-respecting PDF acquisition helpers."""

from __future__ import annotations

import re
import shutil
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import requests

from scholaraio.services.ingest_metadata import _sanitize_for_filename
from scholaraio.stores.papers import iter_paper_dirs, pdf_path, read_meta

PDF_MIME_HINTS = {
    "application/pdf",
    "application/x-pdf",
    "application/octet-stream",
    "binary/octet-stream",
}
PDF_URL_RE = re.compile(r"https?://[^\s\"'<>]+\.pdf(?:\?[^\s\"'<>]*)?", re.IGNORECASE)
META_PDF_RE = re.compile(
    r"<meta\b[^>]*(?:name|property)=[\"'](?P<name>citation_pdf_url|dc\.identifier|eprints\.document_url)[\"'][^>]*>",
    re.IGNORECASE,
)
CONTENT_RE = re.compile(r"\bcontent=[\"'](?P<content>[^\"']+)[\"']", re.IGNORECASE)
HREF_RE = re.compile(r"<a\b[^>]*\bhref=[\"'](?P<href>[^\"']+)[\"'][^>]*>", re.IGNORECASE)
TITLE_RE = re.compile(r"<meta\b[^>]*name=[\"']citation_title[\"'][^>]*>", re.IGNORECASE)
DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)


class PdfFetchError(RuntimeError):
    """Raised when a locator cannot produce a valid PDF."""


@dataclass
class PdfFetchResult:
    status: str
    locator: str
    pdf_url: str = ""
    path: Path | None = None
    source: str = ""
    bytes_downloaded: int = 0
    content_type: str = ""
    message: str = ""


def _session(*, direct: bool, timeout: float) -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "ScholarAIO/1.0 (https://github.com/ZimoLiao/scholaraio)",
            "Accept": "application/pdf,text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        }
    )
    session.trust_env = not direct
    session.request = _with_default_timeout(session.request, timeout)  # type: ignore[method-assign]
    return session


def _with_default_timeout(fn, timeout: float):
    def wrapped(method, url, **kwargs):
        kwargs.setdefault("timeout", timeout)
        return fn(method, url, **kwargs)

    return wrapped


def _is_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _is_pdf_url(url: str) -> bool:
    path = unquote(urlparse(url).path).lower()
    return path.endswith(".pdf")


def _safe_filename(text: str, *, default: str = "paper.pdf") -> str:
    raw = unquote(Path(urlparse(text).path).name if _is_url(text) else text).strip()
    if not raw:
        raw = default
    raw = re.sub(r"[^\w.\-]+", "-", raw, flags=re.UNICODE).strip(".-")
    if not raw:
        raw = default
    if not raw.lower().endswith(".pdf"):
        raw += ".pdf"
    stem = _sanitize_for_filename(raw[:-4], max_bytes=251).rstrip(".-")
    if not stem:
        stem = "paper"
    return f"{stem}.pdf"


def _extract_content(tag: str) -> str:
    match = CONTENT_RE.search(tag)
    return match.group("content").strip() if match else ""


def _extract_title(html: str) -> str:
    match = TITLE_RE.search(html)
    if not match:
        return ""
    return _extract_content(match.group(0))


def _candidate_pdf_urls(html: str, base_url: str) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(url: str, source: str) -> None:
        absolute = urljoin(base_url, url.strip())
        if not absolute or absolute in seen:
            return
        seen.add(absolute)
        candidates.append((absolute, source))

    for match in META_PDF_RE.finditer(html):
        content = _extract_content(match.group(0))
        if content and (content.lower().startswith("http") or ".pdf" in content.lower()):
            meta_name = match.group("name").lower()
            source = "landing:citation_pdf_url" if meta_name == "citation_pdf_url" else f"landing:meta:{meta_name}"
            add(content, source)

    for match in HREF_RE.finditer(html):
        href = match.group("href")
        href_lower = href.lower()
        if ".pdf" in href_lower or "/pdf/" in href_lower or "type=pdf" in href_lower:
            add(href, "landing:pdf_link")

    for match in PDF_URL_RE.finditer(html):
        add(match.group(0), "landing:pdf_text")

    return candidates


def _locator_to_url(locator: str) -> str:
    text = locator.strip()
    doi_url_prefix = "https://doi.org/"
    if text.lower().startswith(doi_url_prefix):
        text = text[len(doi_url_prefix) :].strip()
    if _is_url(text):
        return text
    if text.lower().startswith("doi:"):
        text = text.split(":", 1)[1].strip()
    if DOI_RE.match(text):
        return f"https://doi.org/{text}"
    from scholaraio.services.ingest_metadata import query_crossref

    data = query_crossref(title=text)
    doi = str(data.get("DOI") or "").strip()
    if doi:
        return f"https://doi.org/{doi}"
    raise PdfFetchError(f"Could not resolve title to DOI: {locator}")


def _valid_pdf_payload(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            head = fh.read(1024)
    except OSError:
        return False
    return b"%PDF-" in head


def _normalize_pdf_header(path: Path) -> None:
    tmp_path: Path | None = None
    try:
        with path.open("rb") as src:
            head = src.read(1024)
            offset = head.find(b"%PDF-")
            if offset <= 0:
                return
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
                tmp_path = Path(tmp.name)
                tmp.write(head[offset:])
                shutil.copyfileobj(src, tmp)
        if tmp_path is not None:
            tmp_path.replace(path)
            tmp_path = None
    except Exception:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
        raise


def _save_pdf_response(
    response: requests.Response,
    out_dir: Path,
    *,
    locator: str,
    filename: str | None = None,
    force: bool = False,
    source: str,
) -> PdfFetchResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / (filename or _safe_filename(response.url or locator))
    if target.exists() and not force:
        return PdfFetchResult(
            status="skipped",
            locator=locator,
            pdf_url=response.url,
            path=target,
            source=source,
            message=f"PDF already exists: {target}",
        )

    content_type = response.headers.get("Content-Type", "")
    tmp_path: Path | None = None
    bytes_downloaded = 0
    try:
        with tempfile.NamedTemporaryFile(dir=out_dir, delete=False) as tmp:
            tmp_path = Path(tmp.name)
            for chunk in response.iter_content(chunk_size=1024 * 128):
                if not chunk:
                    continue
                bytes_downloaded += len(chunk)
                tmp.write(chunk)

        if not _valid_pdf_payload(tmp_path):
            raise PdfFetchError(
                f"Downloaded payload is not a PDF: {locator} ({content_type or 'unknown content type'})"
            )
        _normalize_pdf_header(tmp_path)

        tmp_path.replace(target)
    except Exception:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
        raise

    return PdfFetchResult(
        status="downloaded",
        locator=locator,
        pdf_url=response.url,
        path=target,
        source=source,
        bytes_downloaded=bytes_downloaded,
        content_type=content_type,
    )


def _download_pdf_url(
    url: str,
    out_dir: Path,
    *,
    session: requests.Session,
    filename: str | None = None,
    force: bool = False,
    source: str = "direct_pdf_url",
) -> PdfFetchResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    with session.get(url, stream=True, allow_redirects=True) as response:
        response.raise_for_status()
        return _save_pdf_response(
            response,
            out_dir,
            locator=url,
            filename=filename,
            force=force,
            source=source,
        )


def fetch_pdf(
    locator: str,
    out_dir: Path,
    *,
    direct: bool = False,
    filename: str | None = None,
    force: bool = False,
    timeout: float = 60.0,
    session: requests.Session | None = None,
) -> PdfFetchResult:
    """Resolve and download a PDF using the current network access context."""
    if session is None:
        with _session(direct=direct, timeout=timeout) as owned_session:
            return fetch_pdf(
                locator,
                out_dir,
                direct=direct,
                filename=filename,
                force=force,
                timeout=timeout,
                session=owned_session,
            )

    url = _locator_to_url(locator)
    if _is_pdf_url(url):
        return _download_pdf_url(url, out_dir, session=session, filename=filename, force=force)

    with session.get(url, stream=True, allow_redirects=True) as response:
        content_type = response.headers.get("Content-Type", "")
        response.raise_for_status()
        if content_type.split(";", 1)[0].strip().lower() in PDF_MIME_HINTS:
            return _save_pdf_response(
                response,
                out_dir,
                locator=locator,
                filename=filename,
                force=force,
                source="direct_pdf_response",
            )

        html = response.text
        title = _extract_title(html)
        inferred_name = filename or (_safe_filename(title) if title else None)
        errors: list[str] = []
        for pdf_url, source in _candidate_pdf_urls(html, response.url):
            try:
                return _download_pdf_url(
                    pdf_url,
                    out_dir,
                    session=session,
                    filename=inferred_name,
                    force=force,
                    source=source,
                )
            except (requests.RequestException, PdfFetchError) as exc:
                errors.append(f"{pdf_url}: {exc}")
    detail = "; ".join(errors) if errors else "no PDF link found"
    raise PdfFetchError(f"Could not fetch PDF for {locator}: {detail}")


def _paper_locator(meta: dict) -> str:
    source_url = str(meta.get("source_url") or "").strip()
    if source_url:
        return source_url
    doi = str(meta.get("doi") or "").strip()
    if doi:
        return doi
    ids_raw = meta.get("ids")
    ids = ids_raw if isinstance(ids_raw, dict) else {}
    doi_from_ids = str(ids.get("doi") or "").strip()
    return doi_from_ids


def refetch_paper_pdf(
    paper_dir: Path,
    cfg,
    *,
    direct: bool = False,
    force: bool = False,
    timeout: float = 60.0,
    session: requests.Session | None = None,
) -> PdfFetchResult:
    meta = read_meta(paper_dir)
    locator = _paper_locator(meta)
    if not locator:
        return PdfFetchResult(
            status="skipped",
            locator=paper_dir.name,
            message="Paper has no DOI or source_url",
        )
    target = pdf_path(paper_dir)
    if target.exists() and not force:
        return PdfFetchResult(
            status="skipped",
            locator=locator,
            path=target,
            message=f"PDF already exists: {target.name}",
        )
    return fetch_pdf(
        locator,
        paper_dir,
        direct=direct,
        filename=target.name,
        force=force,
        timeout=timeout,
        session=session,
    )


def batch_refetch_pdfs(
    cfg,
    *,
    paper_dirs: Iterable[Path] | None = None,
    direct: bool = False,
    force: bool = False,
    timeout: float = 60.0,
) -> list[PdfFetchResult]:
    selected = list(paper_dirs) if paper_dirs is not None else list(iter_paper_dirs(cfg.papers_dir))
    results: list[PdfFetchResult] = []
    with _session(direct=direct, timeout=timeout) as session:
        for paper_dir in selected:
            try:
                results.append(
                    refetch_paper_pdf(
                        paper_dir,
                        cfg,
                        direct=direct,
                        force=force,
                        timeout=timeout,
                        session=session,
                    )
                )
            except (OSError, ValueError, requests.RequestException, PdfFetchError) as exc:
                results.append(
                    PdfFetchResult(
                        status="failed",
                        locator=paper_dir.name,
                        message=str(exc),
                    )
                )
    return results
