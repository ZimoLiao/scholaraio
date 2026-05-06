"""Tests for the lightweight Paper2Any MCP adapter."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.error import URLError

import pytest


class _FakeResponse:
    def __init__(self, payload: object, *, status: int = 200, headers: dict[str, str] | None = None):
        self._payload = payload
        self.status = status
        self._headers = headers or {}

    def read(self) -> bytes:
        if isinstance(self._payload, bytes):
            return self._payload
        if isinstance(self._payload, str):
            return self._payload.encode("utf-8")
        return json.dumps(self._payload, ensure_ascii=False).encode("utf-8")

    def getheader(self, name: str, default: str | None = None) -> str | None:
        for key, value in self._headers.items():
            if key.lower() == name.lower():
                return value
        return default

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _header(req, name: str) -> str | None:
    value = req.get_header(name)
    if value is not None:
        return value
    for key, header_value in req.header_items():
        if key.lower() == name.lower():
            return header_value
    return None


def test_paper2any_provider_uses_configured_mcp_transport(monkeypatch, tmp_path: Path) -> None:
    seen: dict[str, object] = {}

    def fake_urlopen(req, timeout=0):
        body = json.loads(req.data.decode("utf-8"))
        seen.setdefault("methods", []).append(body["method"])
        seen["url"] = req.full_url
        seen["auth"] = _header(req, "Authorization")
        if body["method"] == "initialize":
            return _FakeResponse(
                {
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}},
                },
                headers={"Mcp-Session-Id": "paper2any-session"},
            )
        if body["method"] == "notifications/initialized":
            return _FakeResponse("", status=202)
        if body["method"] == "tools/call":
            seen["body"] = body
            return _FakeResponse(
                {
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {
                        "content": [{"type": "text", "text": "Paper2Any ready"}],
                        "structuredContent": {"ready": True},
                        "isError": False,
                    },
                }
            )
        raise AssertionError(f"unexpected method: {body['method']}")

    monkeypatch.setattr("scholaraio.providers.mcp.urlopen", fake_urlopen)

    from scholaraio.core.config import _build_config
    from scholaraio.providers.paper2any import call_paper2any_tool

    cfg = _build_config(
        {"paper2any": {"transport": "mcp", "mcp_url": "http://remote.example/mcp", "api_key": "cfg-secret"}},
        tmp_path,
    )

    result = call_paper2any_tool("paper2any_status", {}, cfg=cfg)

    assert seen["url"] == "http://remote.example/mcp"
    assert seen["auth"] == "Bearer cfg-secret"
    assert seen["methods"] == ["initialize", "notifications/initialized", "tools/call"]
    assert seen["body"]["params"] == {"name": "paper2any_status", "arguments": {}}
    assert result["structuredContent"]["ready"] is True


def test_paper2any_provider_env_mcp_url_overrides_empty_config(monkeypatch, tmp_path: Path) -> None:
    seen: dict[str, object] = {}

    def fake_urlopen(req, timeout=0):
        body = json.loads(req.data.decode("utf-8"))
        seen["url"] = req.full_url
        if body["method"] == "initialize":
            return _FakeResponse(
                {
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}},
                }
            )
        if body["method"] == "notifications/initialized":
            return _FakeResponse("", status=202)
        return _FakeResponse({"jsonrpc": "2.0", "id": body["id"], "result": {"tools": []}})

    monkeypatch.setenv("PAPER2ANY_MCP_URL", "http://env.example/mcp")
    monkeypatch.setattr("scholaraio.providers.mcp.urlopen", fake_urlopen)

    from scholaraio.core.config import _build_config
    from scholaraio.providers.paper2any import list_paper2any_tools

    list_paper2any_tools(cfg=_build_config({}, tmp_path))

    assert seen["url"] == "http://env.example/mcp"


def test_paper2any_provider_translates_tools_transport_errors(monkeypatch, tmp_path: Path) -> None:
    def fake_urlopen(req, timeout=0):
        raise URLError("down")

    monkeypatch.setattr("scholaraio.providers.mcp.urlopen", fake_urlopen)

    from scholaraio.core.config import _build_config
    from scholaraio.providers.paper2any import Paper2AnyServiceUnavailableError, list_paper2any_tools

    with pytest.raises(Paper2AnyServiceUnavailableError):
        list_paper2any_tools(cfg=_build_config({}, tmp_path))


def test_paper2any_mcp_sidecar_lists_tools() -> None:
    from scholaraio.providers.paper2any_mcp_server import Paper2AnySidecarConfig, handle_mcp_jsonrpc_request

    init_status, init_body, init_headers = handle_mcp_jsonrpc_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        Paper2AnySidecarConfig(),
    )
    list_status, list_body, _ = handle_mcp_jsonrpc_request(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        Paper2AnySidecarConfig(),
    )

    assert init_status == 200
    assert init_body["result"]["serverInfo"]["name"] == "scholaraio-paper2any"
    assert init_headers["Mcp-Session-Id"]
    assert list_status == 200
    names = {tool["name"] for tool in list_body["result"]["tools"]}
    assert {
        "paper2any_status",
        "paper2any_capabilities",
        "paper2any_run_cli",
        "paper2any_call_api",
        "paper2any_outputs",
    } <= names


def test_paper2any_mcp_sidecar_runs_real_cli_script_and_redacts_keys(tmp_path: Path) -> None:
    from scholaraio.providers.paper2any_mcp_server import Paper2AnySidecarConfig, handle_mcp_jsonrpc_request

    root = tmp_path / "Paper2Any"
    script_dir = root / "script"
    script_dir.mkdir(parents=True)
    (script_dir / "run_paper2figure_cli.py").write_text(
        """
import argparse
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--input", required=True)
parser.add_argument("--output-dir", required=True)
parser.add_argument("--graph-type", required=True)
parser.add_argument("--api-key")
args = parser.parse_args()
out = Path(args.output_dir)
out.mkdir(parents=True, exist_ok=True)
(out / "figure.svg").write_text("<svg>ok</svg>", encoding="utf-8")
print("API Key: sk-test-secret")
""".lstrip(),
        encoding="utf-8",
    )
    input_pdf = tmp_path / "paper.pdf"
    input_pdf.write_bytes(b"%PDF")
    output_dir = tmp_path / "outputs"

    status, body, _ = handle_mcp_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "paper2any_run_cli",
                "arguments": {
                    "workflow": "paper2figure",
                    "input": str(input_pdf),
                    "output_dir": str(output_dir),
                    "python": sys.executable,
                    "api_key": "sk-test-secret",
                    "extra_args": ["--graph-type", "model_arch"],
                    "timeout": 20,
                },
            },
        },
        Paper2AnySidecarConfig(root=root),
    )

    structured = body["result"]["structuredContent"]
    assert status == 200
    assert body["result"]["isError"] is False
    assert structured["returncode"] == 0
    assert "sk-test-secret" not in structured["stdout"]
    assert structured["requested_output_dir"] == str(output_dir.resolve())
    assert structured["paper2any_output_dir"] != structured["requested_output_dir"]
    assert structured["artifacts"][0]["path"].endswith("figure.svg")
    assert (output_dir / "figure.svg").read_text(encoding="utf-8") == "<svg>ok</svg>"


def test_paper2any_mcp_sidecar_resolves_relative_cli_input_before_changing_cwd(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from scholaraio.providers.paper2any_mcp_server import Paper2AnySidecarConfig, handle_mcp_jsonrpc_request

    root = tmp_path / "Paper2Any"
    script_dir = root / "script"
    script_dir.mkdir(parents=True)
    (script_dir / "run_paper2figure_cli.py").write_text(
        """
import argparse
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--input", required=True)
parser.add_argument("--output-dir", required=True)
args = parser.parse_args()
input_path = Path(args.input)
if not input_path.is_file():
    raise SystemExit(f"missing input: {input_path}")
out = Path(args.output_dir)
out.mkdir(parents=True, exist_ok=True)
(out / "seen.txt").write_text(str(input_path), encoding="utf-8")
""".lstrip(),
        encoding="utf-8",
    )
    workspace_pdf = tmp_path / "workspace" / "example" / "paper.pdf"
    workspace_pdf.parent.mkdir(parents=True)
    workspace_pdf.write_bytes(b"%PDF")
    monkeypatch.chdir(tmp_path)

    status, body, _ = handle_mcp_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": 33,
            "method": "tools/call",
            "params": {
                "name": "paper2any_run_cli",
                "arguments": {
                    "workflow": "paper2figure",
                    "input": "workspace/example/paper.pdf",
                    "output_dir": "workspace/_system/paper2any/example-figure",
                    "python": sys.executable,
                    "timeout": 20,
                },
            },
        },
        Paper2AnySidecarConfig(root=root),
    )

    structured = body["result"]["structuredContent"]
    assert status == 200
    assert body["result"]["isError"] is False
    assert structured["returncode"] == 0
    assert structured["artifacts"][0]["path"].endswith("seen.txt")


def test_paper2any_mcp_sidecar_preserves_non_file_text_input_with_periods(
    tmp_path: Path,
) -> None:
    from scholaraio.providers.paper2any_mcp_server import Paper2AnySidecarConfig, handle_mcp_jsonrpc_request

    root = tmp_path / "Paper2Any"
    script_dir = root / "script"
    script_dir.mkdir(parents=True)
    (script_dir / "run_paper2figure_cli.py").write_text(
        """
import argparse
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--input", required=True)
parser.add_argument("--output-dir", required=True)
parser.add_argument("--input-type")
args = parser.parse_args()
out = Path(args.output_dir)
out.mkdir(parents=True, exist_ok=True)
(out / "input.txt").write_text(args.input, encoding="utf-8")
""".lstrip(),
        encoding="utf-8",
    )

    status, body, _ = handle_mcp_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": 35,
            "method": "tools/call",
            "params": {
                "name": "paper2any_run_cli",
                "arguments": {
                    "workflow": "paper2figure",
                    "input": "Model v1.0 architecture",
                    "output_dir": str(tmp_path / "outputs"),
                    "python": sys.executable,
                    "extra_args": ["--input-type", "TEXT"],
                    "timeout": 20,
                },
            },
        },
        Paper2AnySidecarConfig(root=root),
    )

    structured = body["result"]["structuredContent"]
    output_dir = Path(structured["requested_output_dir"])
    assert status == 200
    assert body["result"]["isError"] is False
    assert (output_dir / "input.txt").read_text(encoding="utf-8") == "Model v1.0 architecture"


def test_paper2any_mcp_sidecar_rejects_empty_cli_output_dir(tmp_path: Path) -> None:
    from scholaraio.providers.paper2any_mcp_server import Paper2AnySidecarConfig, handle_mcp_jsonrpc_request

    root = tmp_path / "Paper2Any"
    script_dir = root / "script"
    script_dir.mkdir(parents=True)
    (script_dir / "run_pdf2ppt_cli.py").write_text("raise SystemExit('should not run')\n", encoding="utf-8")

    status, body, _ = handle_mcp_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": 31,
            "method": "tools/call",
            "params": {
                "name": "paper2any_run_cli",
                "arguments": {
                    "workflow": "pdf2ppt",
                    "input": "paper.pdf",
                    "output_dir": "",
                    "python": sys.executable,
                },
            },
        },
        Paper2AnySidecarConfig(root=root),
    )

    assert status == 200
    assert body["result"]["isError"] is True
    assert "requires input and output_dir" in body["result"]["content"][0]["text"]


def test_paper2any_mcp_sidecar_rejects_empty_outputs_dir() -> None:
    from scholaraio.providers.paper2any_mcp_server import Paper2AnySidecarConfig, handle_mcp_jsonrpc_request

    status, body, _ = handle_mcp_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": 32,
            "method": "tools/call",
            "params": {"name": "paper2any_outputs", "arguments": {"output_dir": ""}},
        },
        Paper2AnySidecarConfig(),
    )

    assert status == 200
    assert body["result"]["isError"] is True
    assert "requires output_dir" in body["result"]["content"][0]["text"]


def test_paper2any_mcp_sidecar_prefers_isolated_runtime_python(tmp_path: Path) -> None:
    from scholaraio.providers.paper2any_mcp_server import _resolve_python_bin

    root = tmp_path / "paper2any" / "Paper2Any"
    runtime_python = root.parent / ".venv" / "bin" / "python"
    runtime_python.parent.mkdir(parents=True)
    runtime_python.write_text("#!/usr/bin/env python\n", encoding="utf-8")

    assert _resolve_python_bin(root) == str(runtime_python)
    assert _resolve_python_bin(root, sys.executable) == sys.executable


def test_paper2any_setup_clones_external_checkout_without_installing_deps(monkeypatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd, check=False):
        calls.append(cmd)
        clone_target = Path(cmd[-1])
        if cmd[:3] == ["git", "clone", "--depth"]:
            clone_target.mkdir(parents=True)
            (clone_target / ".git").mkdir()
        return None

    monkeypatch.setattr("scholaraio.providers.paper2any_setup.subprocess.run", fake_run)

    from scholaraio.providers.paper2any_setup import setup_paper2any_runtime

    root = tmp_path / "runtime" / "extensions" / "paper2any" / "Paper2Any"
    result = setup_paper2any_runtime(root)

    assert result.root == root.resolve()
    assert calls == [
        [
            "git",
            "clone",
            "--depth",
            "1",
            "--branch",
            "main",
            "https://github.com/OpenDCAI/Paper2Any.git",
            str(root.resolve()),
        ]
    ]
    assert result.actions[-1] == "skip upstream dependency install"


def test_paper2any_backend_serve_uses_isolated_runtime_and_backend_key(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return None

    monkeypatch.setattr("scholaraio.providers.paper2any_setup.subprocess.run", fake_run)

    from scholaraio.providers.paper2any_setup import serve_paper2any_backend

    root = tmp_path / "runtime" / "extensions" / "paper2any" / "Paper2Any"
    (root / "fastapi_app").mkdir(parents=True)
    (root / "fastapi_app" / "main.py").write_text("app = object()\n", encoding="utf-8")
    runtime_python = root.parent / ".venv" / "bin" / "python"
    runtime_python.parent.mkdir(parents=True)
    runtime_python.write_text("#!/usr/bin/env python\n", encoding="utf-8")

    serve_paper2any_backend(root, host="127.0.0.1", port=18000, backend_api_key="backend-secret")

    assert calls
    cmd, kwargs = calls[0]
    assert cmd == [
        str(runtime_python),
        "-m",
        "uvicorn",
        "fastapi_app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "18000",
    ]
    assert kwargs["check"] is True
    assert kwargs["cwd"] == str(root.resolve())
    assert kwargs["env"]["BACKEND_API_KEY"] == "backend-secret"


def test_paper2any_mcp_sidecar_proxies_allowed_api_with_backend_key(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def fake_urlopen(req, timeout=0):
        seen["url"] = req.full_url
        seen["method"] = req.get_method()
        seen["api_key"] = _header(req, "X-API-Key")
        seen["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeResponse({"ok": True})

    monkeypatch.setattr("scholaraio.providers.paper2any_mcp_server.urlopen", fake_urlopen)

    from scholaraio.providers.paper2any_mcp_server import Paper2AnySidecarConfig, handle_mcp_jsonrpc_request

    status, body, _ = handle_mcp_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "paper2any_call_api",
                "arguments": {"path": "/api/v1/system/verify-llm", "json": {"model": "gpt-4o"}},
            },
        },
        Paper2AnySidecarConfig(backend_url="http://127.0.0.1:8000", backend_api_key="backend-secret"),
    )

    assert status == 200
    assert seen == {
        "url": "http://127.0.0.1:8000/api/v1/system/verify-llm",
        "method": "POST",
        "api_key": "backend-secret",
        "body": {"model": "gpt-4o"},
    }
    assert body["result"]["structuredContent"]["response"] == {"ok": True}


def test_paper2any_mcp_sidecar_requires_backend_key_for_api_routes(monkeypatch) -> None:
    def fake_urlopen(req, timeout=0):
        raise AssertionError("backend should not be called without a key")

    monkeypatch.setattr("scholaraio.providers.paper2any_mcp_server.urlopen", fake_urlopen)

    from scholaraio.providers.paper2any_mcp_server import Paper2AnySidecarConfig, handle_mcp_jsonrpc_request

    status, body, _ = handle_mcp_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": 34,
            "method": "tools/call",
            "params": {
                "name": "paper2any_call_api",
                "arguments": {"path": "/api/v1/system/verify-llm", "json": {"model": "gpt-4o"}},
            },
        },
        Paper2AnySidecarConfig(backend_url="http://127.0.0.1:8000"),
    )

    assert status == 200
    assert body["result"]["isError"] is True
    assert "backend API key is required" in body["result"]["content"][0]["text"]


def test_paper2any_mcp_capabilities_use_real_upstream_api_prefixes() -> None:
    from scholaraio.providers.paper2any_mcp_server import API_CAPABILITIES

    assert API_CAPABILITIES["image_playground"] == "/api/v1/image-playground/*"
    assert API_CAPABILITIES["kb_workflows"].startswith("/api/v1/kb/")
    assert API_CAPABILITIES["kb_embedding"].startswith("/api/v1/kb/")


def test_paper2any_mcp_sidecar_rejects_api_paths_outside_paper2any_backend() -> None:
    from scholaraio.providers.paper2any_mcp_server import Paper2AnySidecarConfig, handle_mcp_jsonrpc_request

    status, body, _ = handle_mcp_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "paper2any_call_api", "arguments": {"path": "https://example.com/steal"}},
        },
        Paper2AnySidecarConfig(backend_url="http://127.0.0.1:8000"),
    )

    assert status == 200
    assert body["result"]["isError"] is True
    assert "Only /api/v1/ and /health paths are allowed" in body["result"]["content"][0]["text"]
