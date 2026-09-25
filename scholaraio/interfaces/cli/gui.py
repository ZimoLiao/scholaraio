"""Local read-only WebUI for browsing ScholarAIO libraries."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import logging
import mimetypes
import os
import re
import secrets
import sqlite3
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, quote, unquote, urlparse

from scholaraio.services.library_catalog import LibraryCatalog

if TYPE_CHECKING:
    from scholaraio.core.config import Config
    from scholaraio.services.pdf_edit_mirror import PdfEditMirrorService

_LOG = logging.getLogger(__name__)

_MAX_JSON_BODY_BYTES = 64 * 1024
_NATIVE_PDF_OPEN_PATHS = frozenset({"/api/main/open-pdf", "/api/proceedings/open-pdf"})
_PDF_RECOVERY_WRITE_PATHS = frozenset({"/api/main/resolve-pdf", "/api/proceedings/resolve-pdf"})
_CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; frame-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'"
)
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


def _ui(msg: str = "") -> None:
    from scholaraio.core import log

    log.ui(msg)


def _static_dir() -> Path:
    return Path(__file__).resolve().parent / "library-view"


def _json_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _pdf_content_disposition(filename: str, *, attachment: bool = False) -> str:
    safe_name = filename.replace("\\", "_").replace('"', "_").replace("\r", "_").replace("\n", "_").strip()
    if not safe_name:
        safe_name = "paper.pdf"
    try:
        fallback = safe_name.encode("ascii").decode("ascii")
    except UnicodeEncodeError:
        fallback = "paper.pdf"
    fallback = (
        fallback.replace("\\", "_").replace('"', "_").replace("\r", "_").replace("\n", "_").strip() or "paper.pdf"
    )
    encoded = quote(safe_name, safe="")
    disposition = "attachment" if attachment else "inline"
    return f"{disposition}; filename=\"{fallback}\"; filename*=UTF-8''{encoded}"


def _browser_url(host: str, port: int) -> str:
    browser_host = (host or "127.0.0.1").strip() or "127.0.0.1"
    if browser_host in {"0.0.0.0", "::", "[::]"}:
        browser_host = "127.0.0.1"
    elif ":" in browser_host and not browser_host.startswith("["):
        browser_host = f"[{browser_host}]"
    return f"http://{browser_host}:{port}"


def _is_loopback_host(host: str) -> bool:
    candidate = str(host or "").strip().strip("[]")
    if candidate.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(candidate).is_loopback
    except ValueError:
        return False


class LibraryViewRequestHandler(BaseHTTPRequestHandler):
    """Request handler configured by :func:`create_library_view_server`."""

    cfg: Config
    catalogs: dict[str, LibraryCatalog]
    static_dir: Path
    csrf_token: str
    native_pdf_open_enabled: bool
    native_pdf_open_reason: str
    pdf_delivery: dict[str, str]
    pdf_edit_mirror_service: PdfEditMirrorService | None

    server_version = "ScholarAIOLibraryGUI/2.0"

    def log_message(self, _format: str, *_args) -> None:
        return

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        """Keep protocol/parser failures on the same secure JSON surface."""
        del explain
        try:
            status = HTTPStatus(code)
        except ValueError:
            status = HTTPStatus.INTERNAL_SERVER_ERROR
        self._send_error_json(status, message or status.phrase, code="http_error")

    def _send_security_headers(self, *, allow_same_origin_frame: bool = False) -> None:
        frame_ancestors = "'self'" if allow_same_origin_frame else "'none'"
        self.send_header(
            "Content-Security-Policy",
            f"{_CONTENT_SECURITY_POLICY}; frame-ancestors {frame_ancestors}",
        )
        self.send_header("X-Frame-Options", "SAMEORIGIN" if allow_same_origin_frame else "DENY")
        for name, value in _SECURITY_HEADERS.items():
            self.send_header(name, value)

    def _send_bytes(
        self,
        status: HTTPStatus,
        body: bytes,
        content_type: str,
        *,
        headers: dict[str, str] | None = None,
        allow_same_origin_frame: bool = False,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        if status != HTTPStatus.NOT_MODIFIED:
            self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", (headers or {}).get("Cache-Control", "no-store"))
        self._send_security_headers(allow_same_origin_frame=allow_same_origin_frame)
        for name, value in (headers or {}).items():
            if name.lower() != "cache-control":
                self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_json(self, status: HTTPStatus, payload: object, *, headers: dict[str, str] | None = None) -> None:
        self._send_bytes(status, _json_bytes(payload), "application/json; charset=utf-8", headers=headers)

    def _send_error_json(
        self,
        status: HTTPStatus,
        message: str,
        *,
        code: str = "request_failed",
        headers: dict[str, str] | None = None,
    ) -> None:
        self._send_json(
            status,
            {"error": message, "code": code, "status": status.value},
            headers=headers,
        )

    def _query_value(self, name: str) -> str:
        parsed = urlparse(self.path)
        values = parse_qs(parsed.query).get(name) or [""]
        return values[0]

    def _query_id(self) -> str:
        return self._query_value("id")

    def _required_query_id(self) -> str | None:
        paper_id = self._query_id()
        if paper_id:
            return paper_id
        self._send_error_json(
            HTTPStatus.BAD_REQUEST,
            "missing id query parameter",
            code="missing_paper_id",
        )
        return None

    def _origin_is_same_loopback_server(self) -> bool:
        origin = str(self.headers.get("Origin") or "").strip()
        if not origin:
            return False
        try:
            parsed = urlparse(origin)
            port = parsed.port
        except ValueError:
            return False
        return (
            parsed.scheme == "http"
            and bool(parsed.hostname)
            and _is_loopback_host(parsed.hostname or "")
            and port == getattr(self.server, "server_port", None)
        )

    def _read_json_object(self) -> dict | None:
        content_type = str(self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            self._send_error_json(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                "Content-Type must be application/json",
                code="unsupported_media_type",
            )
            return None
        try:
            content_length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            self._send_error_json(
                HTTPStatus.BAD_REQUEST,
                "Invalid Content-Length",
                code="invalid_content_length",
            )
            return None
        if content_length <= 0:
            self._send_error_json(
                HTTPStatus.BAD_REQUEST,
                "A JSON request body is required",
                code="invalid_request_body",
            )
            return None
        if content_length > _MAX_JSON_BODY_BYTES:
            self.close_connection = True
            self._send_error_json(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                "JSON request body is too large",
                code="request_too_large",
                headers={"Connection": "close"},
            )
            return None
        try:
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_error_json(
                HTTPStatus.BAD_REQUEST,
                "Request body must be valid UTF-8 JSON",
                code="invalid_json",
            )
            return None
        if not isinstance(payload, dict):
            self._send_error_json(
                HTTPStatus.BAD_REQUEST,
                "Request body must be a JSON object",
                code="invalid_request_body",
            )
            return None
        return payload

    def _send_catalog_page(self, source: str) -> None:
        params = {
            key: self._query_value(key)
            for key in (
                "offset",
                "limit",
                "sort",
                "direction",
                "revision",
                "q",
                "title",
                "author",
                "journal",
                "doi",
                "paper_type",
                "volume",
                "year_from",
                "year_to",
                "ids",
                "refresh",
            )
            if self._query_value(key)
        }
        try:
            payload = self.catalogs[source].page(params)
        except (ValueError, TypeError) as exc:
            self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc), code="invalid_page_query")
            return
        self._send_library(payload)

    def _send_library(self, payload: dict) -> None:
        # generated_at describes response generation, not a library mutation.
        version = {key: value for key, value in payload.items() if key != "generated_at"}
        if "audit" in version:
            version["audit"] = {"state": version["audit"]["state"]}
        etag = '"' + hashlib.sha256(_json_bytes(version)).hexdigest() + '"'
        headers = {"ETag": etag, "Cache-Control": "private, no-cache"}
        if self._etag_matches(etag):
            self._send_bytes(HTTPStatus.NOT_MODIFIED, b"", "application/json", headers=headers)
        else:
            self._send_json(HTTPStatus.OK, payload, headers=headers)

    def _etag_matches(self, etag: str) -> bool:
        values = [value.strip() for value in self.headers.get("If-None-Match", "").split(",")]
        return "*" in values or any(value.removeprefix("W/") == etag for value in values)

    def _send_pdf(self, pdf_path: Path, *, attachment: bool = False) -> None:
        try:
            pdf_path.stat()
            stream = pdf_path.open("rb")
        except FileNotFoundError:
            self._send_error_json(HTTPStatus.NOT_FOUND, "PDF file not found")
            return
        except OSError as exc:
            self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
            return

        with stream:
            stat = os.fstat(stream.fileno())
            size = stat.st_size
            etag = f'"{stat.st_dev:x}-{stat.st_ino:x}-{stat.st_size:x}-{stat.st_mtime_ns:x}-{stat.st_ctime_ns:x}"'
            headers = {"ETag": etag, "Cache-Control": "private, no-cache", "Accept-Ranges": "bytes"}
            if self._etag_matches(etag):
                self._send_bytes(
                    HTTPStatus.NOT_MODIFIED, b"", "application/pdf", headers=headers, allow_same_origin_frame=True
                )
                return
            start, end = 0, size - 1
            status = HTTPStatus.OK
            requested = self.headers.get("Range", "") if self.command != "HEAD" else ""
            if requested and self.headers.get("If-Range", etag) == etag:
                match = re.fullmatch(r"bytes=(\d*)-(\d*)", requested.strip())
                # Ignore unsupported units/multipart ranges; browsers use a single range.
                if match and any(match.groups()):
                    first, last = match.groups()
                    try:
                        if first:
                            start = int(first)
                            end = min(int(last), size - 1) if last else size - 1
                        else:
                            suffix = int(last)
                            start = max(0, size - suffix)
                        valid = 0 <= start <= end < size
                    except ValueError:
                        valid = False
                    if not valid:
                        self._send_bytes(
                            HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE,
                            b"",
                            "application/pdf",
                            headers={**headers, "Content-Range": f"bytes */{size}"},
                        )
                        return
                    status = HTTPStatus.PARTIAL_CONTENT
                    headers["Content-Range"] = f"bytes {start}-{end}/{size}"

            self.send_response(status)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(max(0, end - start + 1)))
            self.send_header("Content-Disposition", _pdf_content_disposition(pdf_path.name, attachment=attachment))
            for name, value in headers.items():
                self.send_header(name, value)
            self._send_security_headers(allow_same_origin_frame=True)
            self.end_headers()
            if self.command == "HEAD":
                return
            try:
                stream.seek(start)
                remaining = end - start + 1
                while remaining > 0:
                    chunk = stream.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
            except OSError:
                return

    def _handle_api(self, path: str) -> None:
        from scholaraio.services.library_search import (
            DEFAULT_LIBRARY_SEARCH_RESULTS,
            LibrarySearchFilters,
            LibrarySearchRequestError,
            search_main_library,
        )
        from scholaraio.services.library_view import (
            build_main_library_view,
            build_proceedings_library_view,
            get_main_paper_bibtex,
            get_main_paper_detail,
            get_main_paper_pdf,
            get_proceedings_paper_bibtex,
            get_proceedings_paper_detail,
            get_proceedings_paper_pdf,
            resolve_pdf_edit_mirror_target,
        )

        def pdf_sync_status(source: str, paper_id: str, *, validate_paper: bool = True) -> dict[str, object]:
            if validate_paper:
                resolution = resolve_pdf_edit_mirror_target(self.cfg, source, paper_id)
                if resolution.target is None:
                    raise KeyError(paper_id)
            if self.pdf_edit_mirror_service is None:
                return {
                    "state": "not_opened",
                    "retryable": False,
                    "last_success_at": "",
                    "message": "",
                }
            return self.pdf_edit_mirror_service.status(source, paper_id)

        try:
            if path == "/api/health":
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "status": "ok",
                        "readonly": True,
                        "native_pdf_open": self.native_pdf_open_enabled,
                    },
                )
                return
            if path == "/api/capabilities":
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "csrf_token": self.csrf_token,
                        "native_pdf_open": {
                            "enabled": self.native_pdf_open_enabled,
                            "reason": self.native_pdf_open_reason,
                        },
                        "pdf_delivery": self.pdf_delivery,
                        "search_modes": {
                            "main": ["metadata", "keyword", "semantic", "unified"],
                            "proceedings": ["metadata"],
                        },
                    },
                )
                return
            if path == "/api/main/papers":
                if self._query_value("limit"):
                    self._send_catalog_page("main")
                else:
                    self._send_library(build_main_library_view(self.cfg, background_audit=True))
                return
            if path == "/api/main/search":
                try:
                    raw_limit = self._query_value("limit")
                    limit = int(raw_limit) if raw_limit else DEFAULT_LIBRARY_SEARCH_RESULTS
                except ValueError:
                    raise LibrarySearchRequestError(
                        "Search limit must be a positive integer",
                        code="invalid_search_limit",
                    )
                filters = LibrarySearchFilters.from_strings(
                    title=self._query_value("title"),
                    author=self._query_value("author"),
                    year_from=self._query_value("year_from"),
                    year_to=self._query_value("year_to"),
                    journal=self._query_value("journal"),
                    paper_type=self._query_value("paper_type"),
                    doi=self._query_value("doi"),
                )
                payload = search_main_library(
                    self.cfg,
                    query=self._query_value("q"),
                    mode=self._query_value("mode"),
                    filters=filters,
                    limit=limit,
                )
                self._send_json(HTTPStatus.OK, payload)
                return
            if path == "/api/main/detail":
                paper_id = self._required_query_id()
                if paper_id is None:
                    return
                detail = get_main_paper_detail(self.cfg, paper_id, background_audit=True)
                detail["pdf_sync"] = pdf_sync_status("main", paper_id, validate_paper=False)
                self._send_json(HTTPStatus.OK, detail)
                return
            if path == "/api/main/pdf-sync":
                paper_id = self._required_query_id()
                if paper_id is None:
                    return
                self._send_json(HTTPStatus.OK, pdf_sync_status("main", paper_id))
                return
            if path == "/api/main/bibtex":
                paper_id = self._required_query_id()
                if paper_id is None:
                    return
                self._send_json(
                    HTTPStatus.OK,
                    {"paper_id": paper_id, "bibtex": get_main_paper_bibtex(self.cfg, paper_id)},
                )
                return
            if path == "/api/main/pdf":
                paper_id = self._required_query_id()
                if paper_id is None:
                    return
                self._send_pdf(
                    get_main_paper_pdf(self.cfg, paper_id),
                    attachment=self._query_value("download") == "1",
                )
                return
            if path == "/api/proceedings/papers":
                if self._query_value("limit"):
                    self._send_catalog_page("proceedings")
                else:
                    self._send_library(build_proceedings_library_view(self.cfg))
                return
            if path == "/api/proceedings/detail":
                paper_id = self._required_query_id()
                if paper_id is None:
                    return
                detail = get_proceedings_paper_detail(self.cfg, paper_id)
                detail["pdf_sync"] = pdf_sync_status("proceedings", paper_id, validate_paper=False)
                self._send_json(HTTPStatus.OK, detail)
                return
            if path == "/api/proceedings/pdf-sync":
                paper_id = self._required_query_id()
                if paper_id is None:
                    return
                self._send_json(HTTPStatus.OK, pdf_sync_status("proceedings", paper_id))
                return
            if path == "/api/proceedings/bibtex":
                paper_id = self._required_query_id()
                if paper_id is None:
                    return
                self._send_json(
                    HTTPStatus.OK,
                    {"paper_id": paper_id, "bibtex": get_proceedings_paper_bibtex(self.cfg, paper_id)},
                )
                return
            if path == "/api/proceedings/pdf":
                paper_id = self._required_query_id()
                if paper_id is None:
                    return
                self._send_pdf(
                    get_proceedings_paper_pdf(self.cfg, paper_id),
                    attachment=self._query_value("download") == "1",
                )
                return
        except LibrarySearchRequestError as exc:
            self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc), code=exc.code)
            return
        except KeyError as exc:
            self._send_error_json(
                HTTPStatus.NOT_FOUND,
                f"paper not found: {exc.args[0]}",
                code="paper_not_found",
            )
            return
        except Exception as exc:
            self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc), code="internal_error")
            return
        self._send_error_json(HTTPStatus.NOT_FOUND, "unknown API route", code="unknown_route")

    def _serve_static(self, path: str) -> None:
        if path == "/":
            rel = "index.html"
        else:
            rel = unquote(path.lstrip("/"))
        candidate = (self.static_dir / rel).resolve()
        root = self.static_dir.resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            self._send_error_json(HTTPStatus.FORBIDDEN, "forbidden path")
            return
        if not candidate.is_file():
            self._send_error_json(HTTPStatus.NOT_FOUND, "file not found")
            return
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        if candidate.suffix == ".html":
            content_type = "text/html; charset=utf-8"
        elif candidate.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        elif candidate.suffix == ".js":
            content_type = "text/javascript; charset=utf-8"
        self._send_bytes(HTTPStatus.OK, candidate.read_bytes(), content_type)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in {"/api/main/pdf-recovery", "/api/proceedings/pdf-recovery"}:
            self._handle_pdf_recovery(path.split("/")[2])
            return
        if path in (_NATIVE_PDF_OPEN_PATHS | _PDF_RECOVERY_WRITE_PATHS):
            self._reject_write(allowed="POST")
            return
        if path.startswith("/api/"):
            self._handle_api(path)
            return
        self._serve_static(path)

    def do_HEAD(self) -> None:
        self.do_GET()

    def _reject_write(self, *, allowed: str | None = None) -> None:
        path = urlparse(getattr(self, "path", "")).path
        allowed = allowed or ("POST" if path in (_NATIVE_PDF_OPEN_PATHS | _PDF_RECOVERY_WRITE_PATHS) else "GET, HEAD")
        self.close_connection = True
        self._send_error_json(
            HTTPStatus.METHOD_NOT_ALLOWED,
            "this library WebUI is read-only for library data and does not allow that method on this route",
            headers={"Allow": allowed, "Connection": "close"},
        )

    def _handle_native_pdf_open(self, source: str) -> None:
        from scholaraio.services.library_view import (
            LibraryPaperNotFoundError,
            LibraryPdfNotFoundError,
            get_main_paper_pdf,
            get_proceedings_paper_pdf,
            resolve_pdf_edit_mirror_target,
        )
        from scholaraio.services.system_open import (
            DefaultApplicationOpenError,
            open_with_default_application,
            open_wsl_windows_file,
        )

        if not self.native_pdf_open_enabled:
            self._send_error_json(
                HTTPStatus.FORBIDDEN,
                self.native_pdf_open_reason or "Native PDF launch is unavailable",
                code="native_open_disabled",
            )
            return
        if not self._origin_is_same_loopback_server():
            self._send_error_json(
                HTTPStatus.FORBIDDEN,
                "Request Origin must match this loopback GUI server",
                code="origin_rejected",
            )
            return
        supplied_token = str(self.headers.get("X-ScholarAIO-CSRF") or "")
        if not supplied_token or not secrets.compare_digest(supplied_token, self.csrf_token):
            self._send_error_json(
                HTTPStatus.FORBIDDEN,
                "CSRF token is missing or invalid",
                code="csrf_rejected",
            )
            return
        payload = self._read_json_object()
        if payload is None:
            return
        paper_id = payload.get("id")
        if set(payload) != {"id"} or not isinstance(paper_id, str) or not paper_id.strip():
            self._send_error_json(
                HTTPStatus.BAD_REQUEST,
                "Request body must contain only a non-empty string `id`",
                code="invalid_request_body",
            )
            return

        started = time.perf_counter()
        timings = {}
        try:
            if source == "main":
                pdf_path = get_main_paper_pdf(self.cfg, paper_id)
            else:
                pdf_path = get_proceedings_paper_pdf(self.cfg, paper_id)
            timings["lookup"] = (time.perf_counter() - started) * 1000
            stage_started = time.perf_counter()
            if self.pdf_edit_mirror_service is not None:
                resolution = resolve_pdf_edit_mirror_target(self.cfg, source, paper_id)
                if resolution.target is None:
                    raise LibraryPaperNotFoundError(paper_id)
                prepared = self.pdf_edit_mirror_service.prepare_for_open(resolution.target)
                if prepared.status.get("state") == "conflict":
                    self._send_error_json(
                        HTTPStatus.CONFLICT,
                        str(prepared.status["message"]),
                        code="pdf_sync_conflict",
                    )
                    return
                if not prepared.launchable:
                    message = str(prepared.status.get("message") or "A safe synchronized PDF mirror is unavailable")
                    raise DefaultApplicationOpenError(message)
                timings["prepare"] = (time.perf_counter() - stage_started) * 1000
                stage_started = time.perf_counter()
                open_wsl_windows_file(prepared.mirror_path)
            else:
                open_with_default_application(pdf_path.resolve())
            timings["launch"] = (time.perf_counter() - stage_started) * 1000
        except LibraryPaperNotFoundError:
            self._send_error_json(
                HTTPStatus.NOT_FOUND,
                f"paper not found: {paper_id}",
                code="paper_not_found",
            )
            return
        except LibraryPdfNotFoundError:
            self._send_error_json(
                HTTPStatus.NOT_FOUND,
                f"PDF not found for paper: {paper_id}",
                code="pdf_not_found",
            )
            return
        except DefaultApplicationOpenError as exc:
            self._send_error_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                str(exc),
                code="native_open_failed",
            )
            return
        except (OSError, sqlite3.Error) as exc:
            _LOG.warning("PDF native-open failed (%s)", type(exc).__name__)
            self._send_error_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "PDF preparation failed; retry after any active save completes",
                code="native_open_failed",
            )
            return
        _LOG.info("PDF native-open stages_ms=%s", {key: round(value, 1) for key, value in timings.items()})
        self._send_json(
            HTTPStatus.OK,
            {"status": "opened", "paper_id": paper_id},
            headers={"Server-Timing": ", ".join(f"{key};dur={value:.1f}" for key, value in timings.items())},
        )

    def _handle_pdf_recovery(self, source: str, *, write: bool = False) -> None:
        from scholaraio.services.pdf_conflicts import (
            PdfConflictChanged,
            inspect_conflict,
            resolve_conflict,
            version_path,
        )

        service = self.pdf_edit_mirror_service
        if service is None or not self.native_pdf_open_enabled:
            self._send_error_json(HTTPStatus.FORBIDDEN, "PDF recovery is unavailable", code="recovery_disabled")
            return
        if write:
            token = str(self.headers.get("X-ScholarAIO-CSRF") or "")
            if not self._origin_is_same_loopback_server() or not secrets.compare_digest(token, self.csrf_token):
                self._send_error_json(
                    HTTPStatus.FORBIDDEN, "Recovery requires same-origin CSRF authorization", code="csrf_rejected"
                )
                return
            payload = self._read_json_object()
            if payload is None:
                return
        else:
            payload = {key: self._query_value(key) for key in ("id", "version", "token", "download")}
        try:
            for key in ("id", "version", "token"):
                if key in payload and not isinstance(payload[key], str):
                    raise ValueError(f"{key} must be a string")
            record = service.store.get_by_paper(source, payload.get("id", ""))
            if record is None:
                raise KeyError("No editable mirror exists for this paper")
            if write:
                if payload.get("readers_closed") is not True:
                    raise ValueError("Close PDF readers before resolving and confirm readers_closed")
                result = resolve_conflict(
                    service.reconciler,
                    record.sync_id,
                    token=payload.get("token", ""),
                    version=payload.get("version", ""),
                )
                self._send_json(HTTPStatus.OK, result)
            elif payload.get("version"):
                pdf = version_path(service.reconciler, record.sync_id, payload["version"], payload.get("token", ""))
                self._send_pdf(pdf, attachment=payload.get("download") == "1")
            else:
                self._send_json(HTTPStatus.OK, inspect_conflict(service.reconciler, record.sync_id))
        except PdfConflictChanged as exc:
            self._send_error_json(HTTPStatus.CONFLICT, str(exc), code="pdf_versions_changed")
        except KeyError as exc:
            self._send_error_json(HTTPStatus.NOT_FOUND, str(exc), code="pdf_version_not_found")
        except (ValueError, OSError, TimeoutError) as exc:
            self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc), code="pdf_recovery_failed")

    def do_POST(self) -> None:
        path = urlparse(getattr(self, "path", "")).path
        if path in _PDF_RECOVERY_WRITE_PATHS:
            self._handle_pdf_recovery(path.split("/")[2], write=True)
            return
        if path == "/api/main/open-pdf":
            self._handle_native_pdf_open("main")
            return
        if path == "/api/proceedings/open-pdf":
            self._handle_native_pdf_open("proceedings")
            return
        self._reject_write()

    def do_PUT(self) -> None:
        self._reject_write()

    def do_PATCH(self) -> None:
        self._reject_write()

    def do_DELETE(self) -> None:
        self._reject_write()

    def do_OPTIONS(self) -> None:
        self._reject_write()

    def do_TRACE(self) -> None:
        self._reject_write()

    def do_CONNECT(self) -> None:
        self._reject_write()


class LibraryViewHTTPServer(ThreadingHTTPServer):
    """HTTP server that owns and stops its PDF synchronization monitor."""

    pdf_edit_mirror_service: PdfEditMirrorService | None = None

    def server_close(self) -> None:
        service = self.pdf_edit_mirror_service
        self.pdf_edit_mirror_service = None
        try:
            if service is not None:
                service.stop()
        finally:
            super().server_close()
            for catalog in getattr(self.RequestHandlerClass, "catalogs", {}).values():
                catalog.close()


def create_library_view_server(cfg: Config, *, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    """Create the local, library-read-only HTTP server."""

    from scholaraio.services.library_view import resolve_pdf_edit_mirror_target
    from scholaraio.services.pdf_edit_mirror import PdfEditMirrorService
    from scholaraio.services.system_open import DefaultApplicationOpenError, default_application_open_capability

    static_dir = _static_dir()

    class ConfiguredHandler(LibraryViewRequestHandler):
        pass

    from scholaraio.services.library_catalog import LibraryCatalog

    ConfiguredHandler.catalogs = {source: LibraryCatalog(cfg, source) for source in ("main", "proceedings")}
    ConfiguredHandler.cfg = cfg
    ConfiguredHandler.static_dir = static_dir
    ConfiguredHandler.csrf_token = secrets.token_urlsafe(32)
    host_is_loopback = _is_loopback_host(host)
    host_capability = default_application_open_capability()
    ConfiguredHandler.native_pdf_open_enabled = host_is_loopback and host_capability.enabled
    mirror_service = None
    if ConfiguredHandler.native_pdf_open_enabled and host_capability.target == "windows":
        try:
            mirror_service = PdfEditMirrorService.for_wsl(
                cfg,
                resolver=lambda record: resolve_pdf_edit_mirror_target(
                    cfg,
                    record.library_kind,
                    record.paper_id,
                    record=record,
                ),
            )
        except (DefaultApplicationOpenError, OSError, sqlite3.Error) as exc:
            _ui(f"WARNING: WSL PDF edit mirror is unavailable: {exc}")
            ConfiguredHandler.native_pdf_open_enabled = False
            host_capability = type(host_capability)(False, None, "WSL PDF edit mirror could not be initialized.")
    if not host_is_loopback:
        reason = "Native PDF launch is available only when the GUI binds to a loopback host."
    elif not host_capability.enabled:
        reason = host_capability.reason
    else:
        reason = ""
    ConfiguredHandler.native_pdf_open_reason = reason
    ConfiguredHandler.pdf_edit_mirror_service = mirror_service
    if ConfiguredHandler.native_pdf_open_enabled:
        ConfiguredHandler.pdf_delivery = {
            "mode": "native",
            "target": host_capability.target or "host",
            "label": "Open in default viewer",
            "reason": "",
        }
        if mirror_service is not None:
            ConfiguredHandler.pdf_delivery["sync"] = "automatic"
    else:
        ConfiguredHandler.pdf_delivery = {
            "mode": "download",
            "target": "client",
            "label": "Download PDF",
            "reason": reason,
        }
    try:
        server = LibraryViewHTTPServer((host, int(port)), ConfiguredHandler)
    except OSError:
        if mirror_service is not None:
            mirror_service.stop()
        raise
    server.pdf_edit_mirror_service = mirror_service
    return server


def serve_library_view(
    cfg: Config,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> None:
    """Run the local read-only WebUI until interrupted."""

    server = create_library_view_server(cfg, host=host, port=port)
    url = _browser_url(host, server.server_port)
    if open_browser:
        threading.Timer(0.2, lambda: webbrowser.open(url)).start()
    _ui(f"ScholarAIO library WebUI (read-only): {url}")
    _ui("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _ui("Stopping ScholarAIO library WebUI.")
    finally:
        server.server_close()


def cmd_gui(args: argparse.Namespace, cfg: Config) -> None:
    """CLI command handler for the read-only library WebUI."""

    serve_library_view(
        cfg,
        host=args.host,
        port=args.port,
        open_browser=not args.no_open,
    )
