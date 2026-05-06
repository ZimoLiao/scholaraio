"""Paper2Any MCP sidecar CLI command handlers."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any


def _ui(msg: str = "") -> None:
    try:
        from scholaraio.interfaces.cli import compat as cli_mod
    except ImportError:
        from scholaraio.core.log import ui as log_ui

        log_ui(msg)
        return
    cli_mod.ui(msg)


def cmd_paper2any(args: argparse.Namespace, cfg: object) -> None:
    """Paper2Any MCP sidecar integration."""
    action = getattr(args, "paper2any_action", "")
    if action == "setup":
        _cmd_setup(args, cfg)
        return
    if action == "mcp-serve":
        _cmd_mcp_serve(args, cfg)
        return
    if action == "backend-serve":
        _cmd_backend_serve(args, cfg)
        return
    if action == "status":
        _cmd_status(cfg)
        return
    if action == "tools":
        _cmd_tools(cfg)
        return
    if action == "call":
        _cmd_call(args, cfg)
        return
    _ui("Unknown paper2any action")
    sys.exit(2)


def _cmd_setup(args: argparse.Namespace, cfg: object) -> None:
    from scholaraio.providers.paper2any_setup import (
        DEFAULT_PAPER2ANY_REPO_URL,
        Paper2AnySetupError,
        setup_paper2any_runtime,
    )

    paper2any_cfg = getattr(cfg, "paper2any", None)
    root = getattr(args, "paper2any_root", "") or getattr(paper2any_cfg, "root", "")
    if not root and hasattr(cfg, "paper2any_root"):
        root = str(cfg.paper2any_root)

    try:
        result = setup_paper2any_runtime(
            root,
            repo_url=getattr(args, "repo_url", "") or DEFAULT_PAPER2ANY_REPO_URL,
            ref=getattr(args, "ref", "main") or "main",
            update=bool(getattr(args, "update", False)),
            install_runtime=bool(getattr(args, "install_runtime", False)),
            python=getattr(args, "python", sys.executable) or sys.executable,
            dry_run=bool(getattr(args, "dry_run", False)),
        )
    except Paper2AnySetupError as exc:
        _ui(f"Paper2Any setup failed: {exc}")
        sys.exit(1)

    verb = "would prepare" if result.dry_run else "prepared"
    _ui(f"Paper2Any runtime {verb}: {result.root}")
    for action in result.actions:
        _ui(f"- {action}")
    if getattr(args, "install_runtime", False):
        _ui(f"Runtime Python: {result.venv_python}")
    _ui("Next:")
    _ui("  scholaraio paper2any mcp-serve")
    _ui("  scholaraio paper2any backend-serve  # optional, for FastAPI workflows")
    _ui("  scholaraio paper2any status")


def _cmd_mcp_serve(args: argparse.Namespace, cfg: object) -> None:
    from scholaraio.providers.paper2any_mcp_server import Paper2AnySidecarConfig, run_paper2any_mcp_server

    paper2any_cfg = getattr(cfg, "paper2any", None)
    root = getattr(args, "paper2any_root", "") or getattr(paper2any_cfg, "root", "")
    if not root and hasattr(cfg, "paper2any_root"):
        root = str(cfg.paper2any_root)

    config = Paper2AnySidecarConfig(
        root=root,
        backend_url=getattr(args, "backend_url", "") or getattr(paper2any_cfg, "base_url", ""),
        backend_api_key=getattr(args, "backend_api_key", "") or getattr(paper2any_cfg, "backend_api_key", ""),
        bearer_token=getattr(args, "bearer_token", "") or getattr(paper2any_cfg, "api_key", ""),
        timeout=int(getattr(args, "timeout", 120) or 120),
    )
    host = str(getattr(args, "host", "127.0.0.1") or "127.0.0.1")
    port = int(getattr(args, "port", 8770) or 8770)
    _ui(f"Starting Paper2Any MCP sidecar at http://{host}:{port}/mcp")
    _ui(f"Paper2Any root: {config.paper2any_root or '(not configured)'}")
    run_paper2any_mcp_server(host=host, port=port, config=config)


def _cmd_backend_serve(args: argparse.Namespace, cfg: object) -> None:
    from scholaraio.providers.paper2any_setup import Paper2AnySetupError, serve_paper2any_backend

    paper2any_cfg = getattr(cfg, "paper2any", None)
    root = getattr(args, "paper2any_root", "") or getattr(paper2any_cfg, "root", "")
    if not root and hasattr(cfg, "paper2any_root"):
        root = str(cfg.paper2any_root)

    host = str(getattr(args, "host", "127.0.0.1") or "127.0.0.1")
    port = int(getattr(args, "port", 8000) or 8000)
    backend_api_key = (
        getattr(args, "backend_api_key", "")
        or getattr(paper2any_cfg, "backend_api_key", "")
        or os.environ.get("PAPER2ANY_BACKEND_API_KEY", "")
    )
    _ui(f"Starting Paper2Any backend at http://{host}:{port}")
    _ui(f"Paper2Any root: {root or '(not configured)'}")
    if not backend_api_key:
        _ui(
            "Warning: Paper2Any /api routes require BACKEND_API_KEY; set paper2any.backend_api_key or PAPER2ANY_BACKEND_API_KEY."
        )
    try:
        serve_paper2any_backend(
            root,
            host=host,
            port=port,
            python=getattr(args, "python", "") or "",
            backend_api_key=backend_api_key,
        )
    except Paper2AnySetupError as exc:
        _ui(f"Paper2Any backend failed: {exc}")
        sys.exit(1)


def _cmd_status(cfg: object) -> None:
    from scholaraio.providers.paper2any import Paper2AnyError, Paper2AnyServiceUnavailableError, call_paper2any_tool

    try:
        result = call_paper2any_tool("paper2any_status", {}, cfg=cfg)
    except Paper2AnyServiceUnavailableError as exc:
        _ui(f"Error: {exc}")
        _ui("Hint: start the sidecar with `scholaraio paper2any mcp-serve`.")
        sys.exit(1)
    except Paper2AnyError as exc:
        _ui(f"Paper2Any MCP failed: {exc}")
        sys.exit(1)
    _print_tool_result(result)
    if result.get("isError"):
        sys.exit(1)


def _cmd_tools(cfg: object) -> None:
    from scholaraio.providers.paper2any import Paper2AnyError, Paper2AnyServiceUnavailableError, list_paper2any_tools

    try:
        tools = list_paper2any_tools(cfg=cfg)
    except Paper2AnyServiceUnavailableError as exc:
        _ui(f"Error: {exc}")
        _ui("Hint: start the sidecar with `scholaraio paper2any mcp-serve`.")
        sys.exit(1)
    except Paper2AnyError as exc:
        _ui(f"Paper2Any MCP failed: {exc}")
        sys.exit(1)

    for tool in tools:
        name = str(tool.get("name") or "")
        description = str(tool.get("description") or "")
        print(f"{name}\t{description}" if description else name)


def _cmd_call(args: argparse.Namespace, cfg: object) -> None:
    from scholaraio.providers.paper2any import Paper2AnyError, Paper2AnyServiceUnavailableError, call_paper2any_tool

    try:
        arguments = _parse_json_object(getattr(args, "arguments_json", "{}"))
    except ValueError as exc:
        _ui(str(exc))
        sys.exit(2)

    try:
        result = call_paper2any_tool(args.tool, arguments, cfg=cfg)
    except Paper2AnyServiceUnavailableError as exc:
        _ui(f"Error: {exc}")
        _ui("Hint: start the sidecar with `scholaraio paper2any mcp-serve`.")
        sys.exit(1)
    except Paper2AnyError as exc:
        _ui(f"Paper2Any MCP failed: {exc}")
        sys.exit(1)

    _print_tool_result(result)
    if result.get("isError"):
        sys.exit(1)


def _parse_json_object(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"--arguments-json must be valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("--arguments-json must decode to a JSON object")
    return data


def _print_tool_result(result: dict[str, Any]) -> None:
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        print(json.dumps(structured, ensure_ascii=False, indent=2, sort_keys=True))
        return
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
