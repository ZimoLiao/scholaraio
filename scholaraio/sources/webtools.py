"""HTTP connector helpers for external web search/extraction services."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

if TYPE_CHECKING:
    from scholaraio.config import Config

_log = logging.getLogger(__name__)

_DEFAULT_WEBSEARCH_URL = "http://127.0.0.1:8765"
_DEFAULT_WEBEXTRACT_URL = "http://127.0.0.1:8766"


# ---------------------------------------------------------------------------
# Base helpers
# ---------------------------------------------------------------------------


def _resolve_base_url(explicit: str | None, env_name: str, default: str) -> str:
    return (explicit or os.environ.get(env_name) or default).rstrip("/")


def _resolve_api_key(env_name: str) -> str:
    return os.environ.get(env_name, "").strip()


def _get_cfg_section_value(cfg: object | None, section_name: str, field_name: str) -> str:
    if cfg is None:
        return ""
    section = getattr(cfg, section_name, None)
    if section is None:
        return ""
    if isinstance(section, dict):
        value = section.get(field_name, "")
    else:
        value = getattr(section, field_name, "")
    return str(value or "").strip()


def _headers(api_key: str) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _load_json_response(req: Request, *, timeout: int, error_prefix: str):
    try:
        with urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            raise RuntimeError(f"{error_prefix} (HTTP {exc.code}): {body}") from exc
        raise RuntimeError(f"{error_prefix}: {data.get('error', body)}") from exc
    except URLError as exc:
        raise RuntimeError(f"无法连接到服务: {exc.reason}") from exc

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"解析响应失败: {exc}") from exc


# ---------------------------------------------------------------------------
# Web search
# ---------------------------------------------------------------------------


def check_websearch_health(base_url: str | None = None) -> dict:
    """Check whether the external web search service is healthy."""
    base = _resolve_base_url(base_url, "WEBSEARCH_URL", _DEFAULT_WEBSEARCH_URL)
    req = Request(f"{base}/health", method="GET")
    return _load_json_response(req, timeout=5, error_prefix="搜索服务健康检查失败")


def websearch(
    query: str,
    count: int = 10,
    base_url: str | None = None,
    api_key: str | None = None,
) -> list[dict]:
    """Run a web search request against the configured external service."""
    base = _resolve_base_url(base_url, "WEBSEARCH_URL", _DEFAULT_WEBSEARCH_URL)
    resolved_api_key = _resolve_api_key("WEBSEARCH_API_KEY") if api_key is None else api_key.strip()
    payload = json.dumps({"query": query, "count": count}).encode("utf-8")
    req = Request(f"{base}/search", data=payload, headers=_headers(resolved_api_key), method="POST")
    return _load_json_response(req, timeout=30, error_prefix="搜索失败")


@dataclass
class WebSearchResult:
    """网页搜索结果条目。"""

    title: str
    link: str
    snippet: str

    def to_dict(self) -> dict:
        return {"title": self.title, "link": self.link, "snippet": self.snippet}


class WebSearchError(RuntimeError):
    """搜索服务异常。"""

    pass


class ServiceUnavailableError(WebSearchError):
    """搜索服务未启动或不可达。"""

    pass


def _get_websearch_base_url(cfg: Config | None = None) -> str:
    """从配置或环境变量获取搜索服务地址。"""
    url = _get_cfg_section_value(cfg, "websearch", "base_url")
    if url:
        return url.rstrip("/")
    env_url = os.environ.get("WEBSEARCH_URL", "")
    if env_url:
        return env_url.rstrip("/")
    return _DEFAULT_WEBSEARCH_URL


def _get_websearch_api_key(cfg: Config | None = None) -> str | None:
    """获取 API key（如配置了认证）。"""
    key = _get_cfg_section_value(cfg, "websearch", "api_key")
    if key:
        return key
    return os.environ.get("WEBSEARCH_API_KEY") or None


def check_websearch_service(cfg: Config | None = None, timeout: float = 3.0) -> bool:
    """检查搜索服务是否可用。"""
    try:
        check_websearch_health(_get_websearch_base_url(cfg))
        return True
    except Exception as e:
        _log.debug("Health check failed: %s", e)
        return False


def search_web(
    query: str,
    *,
    count: int = 10,
    offset: int = 0,
    cfg: Config | None = None,
    timeout: float = 30.0,
) -> list[WebSearchResult]:
    """执行实时网页搜索。

    调用本地 GUILessBingSearch HTTP API 获取 Bing 搜索结果。

    Args:
        query: 搜索查询词。
        count: 返回结果数量（默认 10）。
        offset: 分页偏移（默认 0）。
        cfg: 配置对象，用于读取服务地址和 API key。
        timeout: 请求超时（秒）。

    Returns:
        WebSearchResult 列表。

    Raises:
        ServiceUnavailableError: 搜索服务未启动或不可达。
        WebSearchError: 搜索请求失败或返回错误。
    """
    base_url = _get_websearch_base_url(cfg)

    if not check_websearch_service(cfg, timeout=3.0):
        raise ServiceUnavailableError(
            f"搜索服务未启动或不可达: {base_url}\n"
            "请确保 GUILessBingSearch 服务已运行:\n"
            "  安装: https://github.com/wszqkzqk/GUILessBingSearch\n"
            "  启动: python guiless_bing_search.py"
        )

    try:
        data = websearch(
            query,
            count=count,
            base_url=base_url,
            api_key=_get_websearch_api_key(cfg),
        )
    except RuntimeError as e:
        raise WebSearchError(str(e)) from e

    results = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                results.append(
                    WebSearchResult(
                        title=item.get("title", ""),
                        link=item.get("link", ""),
                        snippet=item.get("snippet", ""),
                    )
                )
    _log.info("Web search: '%s' -> %d results", query, len(results))
    return results


def search_and_display(
    query: str,
    *,
    count: int = 10,
    cfg: Config | None = None,
) -> list[WebSearchResult]:
    """执行搜索并输出到 UI。"""
    from scholaraio.log import ui

    results = search_web(query, count=count, cfg=cfg)
    if not results:
        ui(f"未找到与 '{query}' 相关的结果")
        return []

    ui(f"找到 {len(results)} 条结果（'{query}'）：")
    for i, r in enumerate(results, 1):
        print(f"\n[{i}] {r.title}")
        print(f"    {r.link}")
        if r.snippet:
            snippet = r.snippet.replace("\n", " ")
            print(f"    {snippet[:200]}{'...' if len(snippet) > 200 else ''}")

    return results


def search_and_fetch_arxiv(
    query: str,
    *,
    count: int = 10,
    cfg: Config | None = None,
) -> list[dict]:
    """搜索并尝试提取 arXiv 论文链接。"""
    from scholaraio.log import ui

    results = search_web(query, count=count, cfg=cfg)
    arxiv_pattern = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d+\.\d+)")

    arxiv_papers = []
    for r in results:
        match = arxiv_pattern.search(r.link)
        if match:
            arxiv_id = match.group(1)
            arxiv_papers.append(
                {
                    "arxiv_id": arxiv_id,
                    "title": r.title,
                    "link": r.link,
                    "snippet": r.snippet,
                }
            )

    if arxiv_papers:
        ui(f"找到 {len(arxiv_papers)} 篇 arXiv 论文：")
        for p in arxiv_papers:
            print(f"  - arXiv:{p['arxiv_id']} - {p['title'][:60]}...")

    return arxiv_papers


# ---------------------------------------------------------------------------
# Web extract
# ---------------------------------------------------------------------------


def check_webextract_health(base_url: str | None = None) -> dict:
    """Check whether the external web extraction service is healthy."""
    base = _resolve_base_url(base_url, "WEBEXTRACT_URL", _DEFAULT_WEBEXTRACT_URL)
    req = Request(f"{base}/health", method="GET")
    return _load_json_response(req, timeout=5, error_prefix="提取服务健康检查失败")


def webextract(url: str, pdf: bool | None = None, base_url: str | None = None) -> dict:
    """Extract rendered page content from a URL via the external extractor service."""
    base = _resolve_base_url(base_url, "WEBEXTRACT_URL", _DEFAULT_WEBEXTRACT_URL)
    api_key = _resolve_api_key("WEBEXTRACT_API_KEY")
    body: dict[str, object] = {"url": url}
    if pdf is not None:
        body["pdf"] = pdf
    req = Request(
        f"{base}/extract",
        data=json.dumps(body).encode("utf-8"),
        headers=_headers(api_key),
        method="POST",
    )
    return _load_json_response(req, timeout=60, error_prefix="提取失败")


def webextract_batch(urls: list[str], base_url: str | None = None) -> list[dict]:
    """Extract multiple URLs through the Open WebUI-compatible batch endpoint."""
    base = _resolve_base_url(base_url, "WEBEXTRACT_URL", _DEFAULT_WEBEXTRACT_URL)
    api_key = _resolve_api_key("WEBEXTRACT_API_KEY")
    req = Request(
        base,
        data=json.dumps({"urls": urls}).encode("utf-8"),
        headers=_headers(api_key),
        method="POST",
    )
    return _load_json_response(req, timeout=120, error_prefix="批量提取失败")


class WebExtractError(RuntimeError):
    """网页提取服务异常。"""

    pass


class WebExtractServiceUnavailableError(WebExtractError):
    """提取服务未启动或不可达。"""

    pass


def _get_webextract_base_url(cfg: Config | None = None) -> str:
    """从配置或环境变量获取提取服务地址。"""
    url = _get_cfg_section_value(cfg, "webextract", "base_url")
    if url:
        return url.rstrip("/")
    env_url = os.environ.get("WEBEXTRACT_URL", "")
    if env_url:
        return env_url.rstrip("/")
    return _DEFAULT_WEBEXTRACT_URL


def _get_webextract_api_key(cfg: Config | None = None) -> str | None:
    """获取 API key（如配置了认证）。"""
    key = _get_cfg_section_value(cfg, "webextract", "api_key")
    if key:
        return key
    return os.environ.get("WEBEXTRACT_API_KEY") or None


def check_webextract_service(cfg: Config | None = None, timeout: float = 3.0) -> bool:
    """检查提取服务是否可用。"""
    try:
        check_webextract_health(_get_webextract_base_url(cfg))
        return True
    except Exception as e:
        _log.debug("Health check failed: %s", e)
        return False


def extract_web(
    url: str,
    *,
    pdf: bool | None = None,
    include_html: bool = False,
    cfg: Config | None = None,
    timeout: float = 120.0,
) -> dict:
    """提取单个 URL 的内容。

    调用本地 qt-web-extractor HTTP API 获取网页 Markdown 内容。

    Args:
        url: 要提取的 URL。
        pdf: 是否为 PDF 文件；为 ``None`` 时交给服务端自动判断。
        include_html: 是否包含原始 HTML（默认 False）。
        cfg: 配置对象，用于读取服务地址和 API key。
        timeout: 请求超时（秒）。

    Returns:
        提取结果字典，包含 title、text（Markdown 格式）等字段。

    Raises:
        WebExtractServiceUnavailableError: 提取服务未启动或不可达。
        WebExtractError: 提取请求失败或返回错误。
    """
    base_url = _get_webextract_base_url(cfg)

    if not check_webextract_service(cfg, timeout=3.0):
        raise WebExtractServiceUnavailableError(
            f"提取服务未启动或不可达: {base_url}\n请确保 qt-web-extractor 服务已运行"
        )

    body: dict[str, object] = {"url": url}
    if pdf is not None:
        body["pdf"] = pdf
    if include_html:
        body["include_html"] = include_html

    api_key = _get_webextract_api_key(cfg) or ""
    req = Request(
        f"{base_url}/extract",
        data=json.dumps(body).encode("utf-8"),
        headers=_headers(api_key),
        method="POST",
    )
    try:
        return _load_json_response(req, timeout=int(timeout), error_prefix="提取失败")
    except RuntimeError as e:
        raise WebExtractError(str(e)) from e


def extract_and_display(
    url: str,
    *,
    pdf: bool = False,
    cfg: Config | None = None,
) -> dict | None:
    """执行提取并输出到 UI。"""
    from scholaraio.log import ui

    try:
        result = extract_web(url, pdf=pdf, cfg=cfg)
    except WebExtractServiceUnavailableError as e:
        ui(f"错误: {e}")
        return None
    except WebExtractError as e:
        ui(f"提取失败: {e}")
        return None

    title = result.get("title", "")
    text = result.get("text", "")
    ui(f"提取成功: {title or url}")
    if text:
        print(text)
    return result


# Keep old alias for backward compatibility
CheckWebsearchHealth = check_websearch_health
CheckWebextractHealth = check_webextract_health
WebSearch = websearch
WebExtract = webextract
WebExtractBatch = webextract_batch
