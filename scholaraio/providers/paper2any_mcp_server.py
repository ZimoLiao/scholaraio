"""Lightweight MCP sidecar for an external OpenDCAI/Paper2Any checkout."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from scholaraio import __version__
from scholaraio.providers.mcp import MCP_PROTOCOL_VERSION

DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8770

CLI_WORKFLOWS = {
    "paper2figure": "script/run_paper2figure_cli.py",
    "paper2ppt": "script/run_paper2ppt_cli.py",
    "paper2ppt_frontend": "script/run_paper2ppt_frontend_cli.py",
    "pdf2ppt": "script/run_pdf2ppt_cli.py",
    "image2ppt": "script/run_image2ppt_cli.py",
    "ppt2polish": "script/run_ppt2polish_cli.py",
    "paper2poster": "script/run_paper2poster_cli.py",
    "paper2video": "script/run_paper2video_cli.py",
}

API_CAPABILITIES = {
    "paper2figure": "/api/v1/paper2figure/*",
    "paper2ppt": "/api/v1/paper2ppt/*",
    "paper2citation": "/api/v1/paper2citation/*",
    "paper2video": "/api/v1/paper2video/*",
    "paper2poster": "/api/v1/paper2poster/*",
    "pdf2ppt": "/api/v1/pdf2ppt/*",
    "image2ppt": "/api/v1/image2ppt/*",
    "image2drawio": "/api/v1/image2drawio/*",
    "image_playground": "/api/v1/image-playground/*",
    "mindmap": "/api/v1/mindmap/*",
    "kb": "/api/v1/kb/*",
    "kb_workflows": "/api/v1/kb/generate-* | /api/v1/kb/deep-research",
    "kb_embedding": "/api/v1/kb/embedding | /api/v1/kb/list | /api/v1/kb/search",
    "files": "/api/v1/files/*",
    "paper2drawio": "/api/v1/paper2drawio/*",
    "paper2rebuttal": "/api/v1/paper2rebuttal/*",
}

_SECRET_PATTERNS = [
    re.compile(r"(sk-[A-Za-z0-9_\-]{8,})"),
    re.compile(r"(?i)(api[_ -]?key\s*[:=]\s*)(\S+)"),
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)(\S+)"),
    re.compile(r"(?i)(x-api-key\s*[:=]\s*)(\S+)"),
]


@dataclass
class Paper2AnySidecarConfig:
    """Runtime settings for the Paper2Any MCP sidecar."""

    root: str | Path | None = ""
    backend_url: str = ""
    backend_api_key: str = ""
    bearer_token: str = ""
    timeout: int = 120

    @property
    def paper2any_root(self) -> Path | None:
        root = str(self.root or os.environ.get("PAPER2ANY_ROOT", "")).strip()
        if not root:
            return None
        return Path(root).expanduser().resolve()

    @property
    def paper2any_backend_url(self) -> str:
        return (self.backend_url or os.environ.get("PAPER2ANY_BACKEND_URL") or DEFAULT_BACKEND_URL).strip()

    @property
    def paper2any_backend_api_key(self) -> str:
        return (self.backend_api_key or os.environ.get("PAPER2ANY_BACKEND_API_KEY", "")).strip()


def paper2any_tools() -> list[dict[str, Any]]:
    """Return MCP tool definitions exposed by the sidecar."""
    return [
        {
            "name": "paper2any_status",
            "description": "Inspect the external Paper2Any checkout and optional backend health.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "paper2any_capabilities",
            "description": "List known Paper2Any CLI workflows and backend API workflow families.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "paper2any_run_cli",
            "description": "Run a real standalone Paper2Any CLI script from the external checkout.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "workflow": {"type": "string"},
                    "input": {"type": "string"},
                    "output_dir": {"type": "string"},
                    "python": {"type": "string"},
                    "api_url": {"type": "string"},
                    "api_key": {"type": "string"},
                    "extra_args": {"type": "array", "items": {"type": "string"}},
                    "timeout": {"type": "integer"},
                },
                "required": ["workflow", "input", "output_dir"],
                "additionalProperties": False,
            },
        },
        {
            "name": "paper2any_call_api",
            "description": "Proxy a real Paper2Any backend JSON API route under /api/v1/ or /health.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "method": {"type": "string"},
                    "json": {"type": "object"},
                    "api_key": {"type": "string"},
                    "timeout": {"type": "integer"},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
        {
            "name": "paper2any_outputs",
            "description": "List files produced under a Paper2Any output directory.",
            "inputSchema": {
                "type": "object",
                "properties": {"output_dir": {"type": "string"}},
                "required": ["output_dir"],
                "additionalProperties": False,
            },
        },
    ]


def handle_mcp_jsonrpc_request(
    payload: dict[str, Any],
    config: Paper2AnySidecarConfig,
) -> tuple[int, dict[str, Any] | None, dict[str, str]]:
    """Handle one MCP Streamable HTTP JSON-RPC request."""
    request_id = payload.get("id")
    method = str(payload.get("method") or "")
    raw_params = payload.get("params")
    params: dict[str, Any] = cast(dict[str, Any], raw_params) if isinstance(raw_params, dict) else {}

    if method == "initialize":
        result = {
            "protocolVersion": str(params.get("protocolVersion") or MCP_PROTOCOL_VERSION),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "scholaraio-paper2any", "version": __version__},
        }
        return 200, _jsonrpc_result(request_id, result), {"Mcp-Session-Id": str(uuid.uuid4())}

    if method == "notifications/initialized":
        return 204, None, {}

    if method == "tools/list":
        return 200, _jsonrpc_result(request_id, {"tools": paper2any_tools()}), {}

    if method == "tools/call":
        name = str(params.get("name") or "")
        raw_arguments = params.get("arguments")
        arguments: dict[str, Any] = cast(dict[str, Any], raw_arguments) if isinstance(raw_arguments, dict) else {}
        return 200, _jsonrpc_result(request_id, _dispatch_tool(name, arguments, config)), {}

    return 200, _jsonrpc_error(request_id, -32601, f"Unsupported MCP method: {method}"), {}


def run_paper2any_mcp_server(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    config: Paper2AnySidecarConfig | None = None,
) -> None:
    """Serve the Paper2Any sidecar over MCP Streamable HTTP."""
    sidecar_config = config or Paper2AnySidecarConfig()

    class Handler(BaseHTTPRequestHandler):
        server_version = "ScholarAIOPaper2AnyMCP/1.0"

        def do_GET(self) -> None:
            if self.path == "/health":
                self._send_json(200, {"status": "ok", "service": "scholaraio-paper2any-mcp"})
                return
            self._send_json(404, {"error": "not found"})

        def do_POST(self) -> None:
            if self.path.rstrip("/") != "/mcp":
                self._send_json(404, {"error": "not found"})
                return
            if not self._authorized():
                self._send_json(401, {"error": "unauthorized"})
                return

            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except (ValueError, json.JSONDecodeError) as exc:
                self._send_json(400, {"error": f"invalid JSON-RPC request: {exc}"})
                return
            if not isinstance(payload, dict):
                self._send_json(400, {"error": "JSON-RPC request must be an object"})
                return

            status, body, headers = handle_mcp_jsonrpc_request(payload, sidecar_config)
            if body is None:
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.end_headers()
                return
            self._send_json(status, body, headers=headers)

        def log_message(self, format: str, *args: object) -> None:
            sys.stderr.write(f"{self.log_date_time_string()} {format % args}\n")

        def _authorized(self) -> bool:
            token = sidecar_config.bearer_token.strip()
            if not token:
                return True
            return self.headers.get("Authorization", "") == f"Bearer {token}"

        def _send_json(self, status: int, body: dict[str, Any], *, headers: dict[str, str] | None = None) -> None:
            raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(raw)

    httpd = ThreadingHTTPServer((host, port), Handler)
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()


def _dispatch_tool(name: str, arguments: dict[str, Any], config: Paper2AnySidecarConfig) -> dict[str, Any]:
    try:
        if name == "paper2any_status":
            return _tool_result("Paper2Any status", _status(config))
        if name == "paper2any_capabilities":
            return _tool_result("Paper2Any capabilities", _capabilities(config))
        if name == "paper2any_run_cli":
            return _run_cli(arguments, config)
        if name == "paper2any_call_api":
            return _call_api(arguments, config)
        if name == "paper2any_outputs":
            output_dir = str(arguments.get("output_dir") or "").strip()
            if not output_dir:
                return _tool_result("paper2any_outputs requires output_dir", arguments, is_error=True)
            return _tool_result("Paper2Any outputs", {"artifacts": _collect_artifacts(Path(output_dir).expanduser())})
        return _tool_result(f"Unknown Paper2Any tool: {name}", {"tool": name}, is_error=True)
    except Exception as exc:  # pragma: no cover - exercised through error tool results in integration paths.
        return _tool_result(str(exc), {"error": str(exc), "type": type(exc).__name__}, is_error=True)


def _status(config: Paper2AnySidecarConfig) -> dict[str, Any]:
    root = config.paper2any_root
    cli_scripts = _script_status(root)
    backend = _backend_health(config)
    return {
        "root": str(root) if root else "",
        "root_exists": bool(root and root.exists()),
        "cli_scripts": cli_scripts,
        "backend_url": config.paper2any_backend_url,
        "backend": backend,
        "ready": bool(root and root.exists()) or backend.get("ok", False),
    }


def _capabilities(config: Paper2AnySidecarConfig) -> dict[str, Any]:
    root = config.paper2any_root
    return {
        "cli_workflows": {
            name: {
                "script": script,
                "available": bool(root and (root / script).is_file()),
            }
            for name, script in CLI_WORKFLOWS.items()
        },
        "api_workflows": API_CAPABILITIES,
        "notes": [
            "Paper2Any is an external application; this sidecar does not vendor its dependencies.",
            "Use paper2any_run_cli for standalone upstream scripts and paper2any_call_api for backend-only routes.",
        ],
    }


def _script_status(root: Path | None) -> dict[str, dict[str, Any]]:
    return {
        name: {
            "path": str(root / script) if root else script,
            "available": bool(root and (root / script).is_file()),
        }
        for name, script in CLI_WORKFLOWS.items()
    }


def _backend_health(config: Paper2AnySidecarConfig) -> dict[str, Any]:
    url = f"{config.paper2any_backend_url.rstrip('/')}/health"
    headers = {}
    if config.paper2any_backend_api_key:
        headers["X-API-Key"] = config.paper2any_backend_api_key
    try:
        with urlopen(Request(url, headers=headers, method="GET"), timeout=min(config.timeout, 10)) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "url": url, "error": str(exc)}
    return {"ok": True, "url": url, "response": _decode_json_or_text(raw)}


def _run_cli(arguments: dict[str, Any], config: Paper2AnySidecarConfig) -> dict[str, Any]:
    root = config.paper2any_root
    if root is None:
        return _tool_result("Paper2Any root is not configured", {"root": ""}, is_error=True)
    if not root.exists():
        return _tool_result(f"Paper2Any root does not exist: {root}", {"root": str(root)}, is_error=True)

    workflow = str(arguments.get("workflow") or "").strip()
    script = CLI_WORKFLOWS.get(workflow)
    if script is None:
        return _tool_result(
            f"Unknown Paper2Any CLI workflow: {workflow}",
            {"workflow": workflow, "known_workflows": sorted(CLI_WORKFLOWS)},
            is_error=True,
        )
    script_path = root / script
    if not script_path.is_file():
        return _tool_result(
            f"Paper2Any CLI script is missing: {script_path}",
            {"workflow": workflow, "script": str(script_path)},
            is_error=True,
        )

    input_path = str(arguments.get("input") or "").strip()
    output_dir = str(arguments.get("output_dir") or "").strip()
    if not input_path or not output_dir:
        return _tool_result("paper2any_run_cli requires input and output_dir", arguments, is_error=True)
    normalized_input = _normalize_cli_input(input_path)
    requested_output_dir = Path(output_dir).expanduser().resolve()
    requested_output_dir.mkdir(parents=True, exist_ok=True)
    run_output_dir = _run_output_dir(root, requested_output_dir)
    run_output_dir.mkdir(parents=True, exist_ok=True)

    python_bin = _resolve_python_bin(root, str(arguments.get("python") or ""))
    cmd = [python_bin, str(script_path), "--input", normalized_input, "--output-dir", str(run_output_dir)]
    api_url = str(arguments.get("api_url") or "").strip()
    api_key = str(arguments.get("api_key") or "").strip()
    if api_url:
        cmd.extend(["--api-url", api_url])
    if api_key:
        cmd.extend(["--api-key", api_key])

    extra_args = arguments.get("extra_args") or []
    if not isinstance(extra_args, list) or not all(isinstance(arg, str) for arg in extra_args):
        return _tool_result("extra_args must be an array of strings", {"extra_args": extra_args}, is_error=True)
    cmd.extend(extra_args)

    env = os.environ.copy()
    if api_key:
        env["DF_API_KEY"] = api_key
        env["PAPER2ANY_API_KEY"] = api_key

    timeout = int(arguments.get("timeout") or config.timeout)
    try:
        completed = subprocess.run(
            cmd,
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return _tool_result(
            f"Paper2Any CLI timed out after {timeout}s",
            {
                "workflow": workflow,
                "command": _redact_text(" ".join(cmd)),
                "stdout": _redact_process_output(exc.stdout),
                "stderr": _redact_process_output(exc.stderr),
                "requested_output_dir": str(requested_output_dir),
                "paper2any_output_dir": str(run_output_dir),
                "timeout": timeout,
            },
            is_error=True,
        )

    if completed.returncode == 0 and run_output_dir != requested_output_dir:
        _copy_artifacts(run_output_dir, requested_output_dir)

    structured = {
        "workflow": workflow,
        "command": _redact_text(" ".join(cmd)),
        "returncode": completed.returncode,
        "stdout": _redact_text(completed.stdout),
        "stderr": _redact_text(completed.stderr),
        "requested_output_dir": str(requested_output_dir),
        "paper2any_output_dir": str(run_output_dir),
        "artifacts": _collect_artifacts(requested_output_dir),
    }
    is_error = completed.returncode != 0
    text = f"Paper2Any {workflow} exited with code {completed.returncode}"
    return _tool_result(text, structured, is_error=is_error)


def _call_api(arguments: dict[str, Any], config: Paper2AnySidecarConfig) -> dict[str, Any]:
    try:
        path = _normalize_api_path(str(arguments.get("path") or ""))
    except ValueError as exc:
        return _tool_result(str(exc), {"path": arguments.get("path")}, is_error=True)

    method = str(arguments.get("method") or "POST").upper()
    if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        return _tool_result(f"Unsupported HTTP method: {method}", {"method": method}, is_error=True)

    body = arguments.get("json", {})
    data = None if method == "GET" else json.dumps(body or {}, ensure_ascii=False).encode("utf-8")
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    api_key = str(arguments.get("api_key") or config.paper2any_backend_api_key).strip()
    if path != "/health" and not api_key:
        return _tool_result(
            "Paper2Any backend API key is required for /api/v1/ routes",
            {"path": path, "backend_url": config.paper2any_backend_url},
            is_error=True,
        )
    if api_key:
        headers["X-API-Key"] = api_key

    url = f"{config.paper2any_backend_url.rstrip('/')}{path}"
    timeout = int(arguments.get("timeout") or config.timeout)
    try:
        with urlopen(Request(url, data=data, headers=headers, method=method), timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            status = getattr(response, "status", 200)
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return _tool_result(
            f"Paper2Any backend HTTP {exc.code}",
            {"url": url, "status": exc.code, "response": _decode_json_or_text(raw)},
            is_error=True,
        )
    except (URLError, TimeoutError, OSError) as exc:
        return _tool_result(str(exc), {"url": url, "error": str(exc)}, is_error=True)

    return _tool_result(
        f"Paper2Any backend {method} {path} returned {status}",
        {"url": url, "status": status, "response": _decode_json_or_text(raw)},
    )


def _normalize_api_path(path: str) -> str:
    parsed = urlsplit(path)
    if parsed.scheme or parsed.netloc:
        raise ValueError("Only /api/v1/ and /health paths are allowed")
    if parsed.path != "/health" and not parsed.path.startswith("/api/v1/"):
        raise ValueError("Only /api/v1/ and /health paths are allowed")
    return path


def _collect_artifacts(output_dir: Path) -> list[dict[str, Any]]:
    if not output_dir.exists():
        return []
    artifacts = []
    for path in sorted(p for p in output_dir.rglob("*") if p.is_file()):
        artifacts.append(
            {
                "path": str(path),
                "relative_path": str(path.relative_to(output_dir)),
                "size": path.stat().st_size,
            }
        )
    return artifacts


def _normalize_cli_input(input_value: str) -> str:
    parsed = urlsplit(input_value)
    if parsed.scheme and parsed.netloc:
        return input_value
    input_path = Path(input_value).expanduser()
    if input_path.is_absolute():
        return str(input_path)
    if input_path.exists():
        return str(input_path.resolve())
    return input_value


def _run_output_dir(root: Path, requested_output_dir: Path) -> Path:
    upstream_outputs = (root / "outputs").resolve()
    if _is_relative_to(requested_output_dir, upstream_outputs):
        return requested_output_dir
    return upstream_outputs / "scholaraio-mcp" / uuid.uuid4().hex


def _resolve_python_bin(root: Path, requested_python: str = "") -> str:
    requested = requested_python.strip()
    if requested:
        return requested
    env_python = os.environ.get("PAPER2ANY_PYTHON", "").strip()
    if env_python:
        return env_python
    for candidate in (root.parent / ".venv" / "bin" / "python", root / ".venv" / "bin" / "python"):
        if candidate.exists():
            return str(candidate)
    return sys.executable


def _copy_artifacts(source_dir: Path, destination_dir: Path) -> None:
    for source in sorted(p for p in source_dir.rglob("*") if p.is_file()):
        relative_path = source.relative_to(source_dir)
        destination = destination_dir / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _tool_result(text: str, structured: dict[str, Any], *, is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": _redact_text(text)}],
        "structuredContent": _redact_obj(structured),
        "isError": is_error,
    }


def _redact_obj(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _redact_obj(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_obj(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _redact_text(text: str) -> str:
    redacted = text or ""
    for pattern in _SECRET_PATTERNS:
        if pattern.groups >= 2:
            redacted = pattern.sub(lambda match: f"{match.group(1)}[REDACTED]", redacted)
        else:
            redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def _redact_process_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return _redact_text(value.decode("utf-8", errors="replace"))
    return _redact_text(value)


def _decode_json_or_text(raw: str) -> Any:
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _jsonrpc_result(request_id: object, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _jsonrpc_error(request_id: object, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
