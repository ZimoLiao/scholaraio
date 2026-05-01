"""Paper2Any MCP sidecar client helpers."""

from __future__ import annotations

import os
from typing import Any

from scholaraio.providers.mcp import McpProtocolError, McpTransportError, StreamableHttpMcpClient

DEFAULT_PAPER2ANY_MCP_URL = "http://127.0.0.1:8770/mcp"


class Paper2AnyError(RuntimeError):
    """Base class for Paper2Any integration failures."""


class Paper2AnyServiceUnavailableError(Paper2AnyError):
    """Raised when the configured Paper2Any MCP sidecar is unreachable."""


def list_paper2any_tools(*, cfg: object | None = None, timeout: int = 120) -> list[dict[str, Any]]:
    """List tools exposed by the configured Paper2Any MCP sidecar."""
    try:
        result = _client(cfg=cfg, timeout=timeout).list_tools()
    except McpTransportError as exc:
        raise Paper2AnyServiceUnavailableError(str(exc)) from exc
    except McpProtocolError as exc:
        raise Paper2AnyError(str(exc)) from exc
    tools = result.get("tools")
    if not isinstance(tools, list):
        raise Paper2AnyError("Paper2Any MCP tools/list did not return a tools array")
    return [tool for tool in tools if isinstance(tool, dict)]


def call_paper2any_tool(
    name: str,
    arguments: dict[str, Any] | None = None,
    *,
    cfg: object | None = None,
    timeout: int = 120,
) -> dict[str, Any]:
    """Call one Paper2Any MCP tool and return the MCP tool result."""
    try:
        return _client(cfg=cfg, timeout=timeout).call_tool(name, arguments or {})
    except McpTransportError as exc:
        raise Paper2AnyServiceUnavailableError(str(exc)) from exc
    except McpProtocolError as exc:
        raise Paper2AnyError(str(exc)) from exc


def _client(*, cfg: object | None, timeout: int) -> StreamableHttpMcpClient:
    return StreamableHttpMcpClient(
        _paper2any_mcp_url(cfg),
        api_key=_paper2any_mcp_api_key(cfg),
        client_name="scholaraio-paper2any-client",
        timeout=timeout,
    )


def _paper2any_mcp_url(cfg: object | None) -> str:
    env_url = os.environ.get("PAPER2ANY_MCP_URL", "").strip()
    if env_url:
        return env_url
    section = getattr(cfg, "paper2any", None)
    config_url = str(getattr(section, "mcp_url", "") or "").strip()
    return config_url or DEFAULT_PAPER2ANY_MCP_URL


def _paper2any_mcp_api_key(cfg: object | None) -> str:
    env_key = os.environ.get("PAPER2ANY_MCP_API_KEY", "").strip()
    if env_key:
        return env_key
    legacy_env_key = os.environ.get("PAPER2ANY_API_KEY", "").strip()
    if legacy_env_key:
        return legacy_env_key
    section = getattr(cfg, "paper2any", None)
    return str(getattr(section, "api_key", "") or "").strip()
