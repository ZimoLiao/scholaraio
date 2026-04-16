"""
ingest/mineru.py — MinerU PDF → Markdown helpers
===============================================

本模块提供两层能力：

1. 本地 MinerU API 转换（默认 ``http://localhost:8000``），支持单文件转换和目录批量转换
2. `mineru-open-api` 云端 CLI 辅助函数，供 ingest pipeline / attach-pdf 等主流程调用

前置条件
--------
    需要先启动 MinerU API 服务，默认监听 http://localhost:8000。
    可用 ``python -m scholaraio.ingest.mineru status`` 检查服务是否在线。

工作流程
--------
1. 扫描 PDF 文件 (单个或目录批量)
2. 检查是否已有同名 .md 输出 — 有则跳过 (--force 可强制重新转换)
3. 调用 MinerU POST /file_parse 接口上传 PDF 并获取 Markdown
4. 将 Markdown 写入指定目录 (默认与 PDF 同目录), 文件名 = PDF名.md
5. 可选同时保存 content_list JSON (--save-content-list)

输出文件
--------
    <pdf_stem>.md               主输出, MinerU 转换后的 Markdown
    <pdf_stem>_content_list.json  (可选) MinerU 结构化内容列表

    输出位置: 默认与 PDF 同目录, 可通过 -o/--output-dir 指定统一输出目录。

命令行用法
----------
    # 检查 MinerU 服务状态
    python -m scholaraio.ingest.mineru status
    python -m scholaraio.ingest.mineru status --api-url http://host:port

    # 单文件转换
    python -m scholaraio.ingest.mineru convert paper.pdf
    python -m scholaraio.ingest.mineru convert paper.pdf -o ./output/       # 指定输出目录
    python -m scholaraio.ingest.mineru convert paper.pdf --start-page 0 --end-page 10
    python -m scholaraio.ingest.mineru convert paper.pdf --backend vlm-auto-engine
    python -m scholaraio.ingest.mineru convert paper.pdf --lang en          # 英文 PDF
    python -m scholaraio.ingest.mineru convert paper.pdf --parse-method ocr # 强制 OCR
    python -m scholaraio.ingest.mineru convert paper.pdf --no-formula --no-table
    python -m scholaraio.ingest.mineru convert paper.pdf --save-content-list
    python -m scholaraio.ingest.mineru convert paper.pdf --dry-run          # 预览, 不写文件

    # 批量处理
    python -m scholaraio.ingest.mineru batch ./papers/                      # 目录下所有 PDF
    python -m scholaraio.ingest.mineru batch ./papers/ -r                   # 递归子目录
    python -m scholaraio.ingest.mineru batch ./papers/ -o ./md_output/      # 指定输出目录
    python -m scholaraio.ingest.mineru batch ./papers/ --force              # 重新转换已有 .md 的
    python -m scholaraio.ingest.mineru batch ./papers/ --dry-run            # 干跑预览
    python -m scholaraio.ingest.mineru batch ./papers/ --backend pipeline --lang ch

公共选项 (convert / batch 共用)
-------------------------------
    -o, --output-dir DIR    输出目录 (默认: 与 PDF 同目录)
    --api-url URL           MinerU 服务地址 (默认: http://localhost:8000)
    --backend BACKEND       解析后端 (见下方, 默认: pipeline)
    --lang LANG             OCR 语言: ch(中英), en, latin 等 (默认: ch)
    --parse-method METHOD   PDF 解析方式: auto / txt / ocr (默认: auto)
    --no-formula            禁用公式解析
    --no-table              禁用表格解析
    --save-content-list     同时保存 content_list JSON
    --dry-run               预览操作, 不实际写文件

MinerU 后端选项 (--backend)
---------------------------
    pipeline            通用, 支持多语言, 无幻觉 (默认, 推荐)
    vlm-auto-engine     本地算力高精度, 仅中英文
    vlm-http-client     远程算力高精度 (OpenAI 兼容), 仅中英文
    hybrid-auto-engine  新一代本地高精度, 支持多语言
    hybrid-http-client  远程+少量本地算力, 支持多语言

依赖
----
    Python 3.10+, requests
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path

import requests

_log = logging.getLogger(__name__)

# ============================================================================
#  Constants
# ============================================================================

DEFAULT_API_URL = "http://localhost:8000"
PARSE_ENDPOINT = "/file_parse"

VALID_BACKENDS = [
    "pipeline",
    "vlm-auto-engine",
    "vlm-http-client",
    "hybrid-auto-engine",
    "hybrid-http-client",
]
VALID_CLOUD_MODEL_VERSIONS = ["pipeline", "vlm", "MinerU-HTML"]
PDF_CLOUD_MODEL_VERSIONS = {"pipeline", "vlm"}

DEFAULT_BACKEND = "pipeline"
DEFAULT_LANG = "ch"
API_TIMEOUT = 600  # PDF parsing can take a long time
DEFAULT_UPLOAD_TIMEOUT = 120
DEFAULT_DOWNLOAD_TIMEOUT = 120
DEFAULT_UPLOAD_RETRIES = 3
DEFAULT_DOWNLOAD_RETRIES = 3
DEFAULT_UPLOAD_WORKERS = 4
DEFAULT_POLL_TIMEOUT = 900
PDF_VALIDATION_ERROR_KIND = "pdf_validation"
CLOUD_SAFE_FILENAME_THRESHOLD = 100
CLOUD_SAFE_FILENAME_MAX_CHARS = 128
CLOUD_SAFE_FILENAME_MAX_BYTES = 128
CLOUD_SAFE_FILENAME_PREFIX_CHARS = 100


# ============================================================================
#  Data Structures
# ============================================================================


@dataclass
class ConvertResult:
    """单次 PDF → Markdown 转换的结果。

    Attributes:
        pdf_path: 原始 PDF 文件路径。
        md_path: 输出的 Markdown 文件路径，转换失败时为 ``None``。
        success: 转换是否成功。
        pages_parsed: 解析的页数。
        elapsed_seconds: 转换耗时（秒）。
        error: 失败时的错误信息，成功时为 ``None``。
        error_kind: 机器可读的错误类型，用于决定是否允许 fallback。
        md_size: 输出 Markdown 的字节数。
    """

    pdf_path: Path
    md_path: Path | None = None
    success: bool = False
    pages_parsed: int = 0
    elapsed_seconds: float = 0.0
    error: str | None = None
    error_kind: str | None = None
    md_size: int = 0  # bytes


@dataclass
class ConvertOptions:
    """PDF 转换选项。

    Attributes:
        api_url: MinerU 服务地址。
        output_dir: 输出目录，为 ``None`` 时与 PDF 同目录。
        backend: MinerU 解析后端（``pipeline`` | ``vlm-auto-engine`` 等）。
        cloud_model_version: `mineru-open-api extract --model` 对应模型（``pipeline`` | ``vlm`` | ``MinerU-HTML``）。
            留空时根据 ``backend`` 做兼容映射。
        lang: OCR 语言（``ch`` | ``en`` | ``latin`` 等）。
        parse_method: 解析方式（``auto`` | ``txt`` | ``ocr``）。
        formula_enable: 是否启用公式解析。
        table_enable: 是否启用表格解析。
        start_page: 起始页（0-indexed）。
        end_page: 结束页（0-indexed）。
        save_content_list: 是否同时保存 content_list JSON。
        force: 是否强制重新转换已有 ``.md`` 的文件。
        dry_run: 预览模式，不写文件。
    """

    api_url: str = DEFAULT_API_URL
    output_dir: Path | None = None
    backend: str = DEFAULT_BACKEND
    cloud_model_version: str = ""
    lang: str = DEFAULT_LANG
    parse_method: str = "auto"
    formula_enable: bool = True
    table_enable: bool = True
    start_page: int = 0
    end_page: int = 99999
    save_content_list: bool = False
    force: bool = False
    dry_run: bool = False
    upload_workers: int = DEFAULT_UPLOAD_WORKERS
    upload_retries: int = DEFAULT_UPLOAD_RETRIES
    download_retries: int = DEFAULT_DOWNLOAD_RETRIES
    poll_timeout: int = DEFAULT_POLL_TIMEOUT


@dataclass(frozen=True)
class PDFValidationResult:
    """Result of checking whether a PDF is safe to hand to a parser."""

    ok: bool
    error: str | None = None
    page_count: int | None = None
    encrypted: bool = False
    deep_checked: bool = False


@dataclass(frozen=True)
class CloudInputAlias:
    """Temporary cloud upload input that keeps original PDF identity separate."""

    path: Path
    output_stem: str
    aliased: bool = False


# ============================================================================
#  MinerU API
# ============================================================================


def check_server(api_url: str = DEFAULT_API_URL) -> bool:
    """检查 MinerU 服务是否可达。

    Args:
        api_url: MinerU 服务地址，默认 ``http://localhost:8000``。

    Returns:
        可达返回 ``True``，不可达返回 ``False``。
    """
    try:
        resp = requests.get(f"{api_url}/docs", timeout=5)
        return resp.status_code == 200
    except requests.ConnectionError:
        return False


def validate_pdf_for_mineru(pdf_path: Path, *, deep: bool = True) -> PDFValidationResult:
    """Validate a PDF before submitting it to MinerU.

    The cheap checks always run. When PyMuPDF or pikepdf is available, a deeper
    open/page-count check catches encrypted or structurally broken PDFs before
    they reach MinerU.
    """
    try:
        if not pdf_path.exists():
            return _invalid_pdf(f"file not found: {pdf_path}")
        if not pdf_path.is_file():
            return _invalid_pdf(f"not a regular file: {pdf_path}")
        size = pdf_path.stat().st_size
    except OSError as exc:
        return _invalid_pdf(f"cannot stat file: {pdf_path}: {_format_exception(exc)}")

    if size <= 0:
        return _invalid_pdf(f"file is empty: {pdf_path.name}")

    try:
        with open(pdf_path, "rb") as fh:
            header = fh.read(5)
    except OSError as exc:
        return _invalid_pdf(f"cannot read file header: {pdf_path.name}: {_format_exception(exc)}")

    if header != b"%PDF-":
        return _invalid_pdf(f"invalid PDF header: {pdf_path.name}")

    if not deep:
        return PDFValidationResult(ok=True, deep_checked=False)

    deep_result = _validate_pdf_with_pymupdf(pdf_path)
    if deep_result is not None:
        return deep_result

    deep_result = _validate_pdf_with_pikepdf(pdf_path)
    if deep_result is not None:
        return deep_result

    _log.warning("cannot deep-check PDF structure (install pymupdf or pikepdf): %s", pdf_path.name)
    return PDFValidationResult(ok=True, deep_checked=False)


def is_pdf_validation_error(result: ConvertResult | None) -> bool:
    """Return whether a conversion failed before parser submission due to bad input."""
    return bool(result and result.error_kind == PDF_VALIDATION_ERROR_KIND)


def _invalid_pdf(message: str, *, encrypted: bool = False, deep_checked: bool = False) -> PDFValidationResult:
    return PDFValidationResult(
        ok=False, error=f"PDF validation failed: {message}", encrypted=encrypted, deep_checked=deep_checked
    )


def _validation_failure_result(pdf_path: Path, validation: PDFValidationResult, started_at: float) -> ConvertResult:
    return ConvertResult(
        pdf_path=pdf_path,
        success=False,
        error=validation.error or "PDF validation failed",
        error_kind=PDF_VALIDATION_ERROR_KIND,
        elapsed_seconds=time.time() - started_at,
    )


def _format_exception(exc: BaseException) -> str:
    message = str(exc).strip()
    if not message:
        message = exc.__class__.__name__
    return message.splitlines()[0][:200]


def _validate_pdf_with_pymupdf(pdf_path: Path) -> PDFValidationResult | None:
    try:
        import pymupdf
    except ImportError:
        return None

    try:
        with pymupdf.open(pdf_path) as doc:
            encrypted = bool(getattr(doc, "needs_pass", False)) or bool(getattr(doc, "is_encrypted", False))
            if encrypted:
                return _invalid_pdf(
                    f"encrypted/password-protected PDF is not supported: {pdf_path.name}",
                    encrypted=True,
                    deep_checked=True,
                )
            page_count = len(doc)
    except Exception as exc:
        return _invalid_pdf(
            f"cannot open PDF structure: {pdf_path.name}: {_format_exception(exc)}",
            deep_checked=True,
        )

    if page_count <= 0:
        return _invalid_pdf(f"PDF has no pages: {pdf_path.name}", deep_checked=True)
    return PDFValidationResult(ok=True, page_count=page_count, deep_checked=True)


def _validate_pdf_with_pikepdf(pdf_path: Path) -> PDFValidationResult | None:
    try:
        import pikepdf
    except ImportError:
        return None

    try:
        with pikepdf.open(pdf_path) as pdf:
            encrypted = bool(getattr(pdf, "is_encrypted", False))
            if encrypted:
                return _invalid_pdf(
                    f"encrypted/password-protected PDF is not supported: {pdf_path.name}",
                    encrypted=True,
                    deep_checked=True,
                )
            page_count = len(pdf.pages)
    except Exception as exc:
        return _invalid_pdf(
            f"cannot open PDF structure: {pdf_path.name}: {_format_exception(exc)}",
            deep_checked=True,
        )

    if page_count <= 0:
        return _invalid_pdf(f"PDF has no pages: {pdf_path.name}", deep_checked=True)
    return PDFValidationResult(ok=True, page_count=page_count, deep_checked=True)


def convert_pdf(pdf_path: Path, opts: ConvertOptions) -> ConvertResult:
    """通过 MinerU API 将单个 PDF 转换为 Markdown。

    将 PDF 上传到本地 MinerU 服务，接收 Markdown 内容并写入磁盘。

    Args:
        pdf_path: PDF 文件路径。
        opts: 转换选项（API 地址、后端、输出目录等）。

    Returns:
        :class:`ConvertResult` 实例，包含转换结果和状态。
    """
    result = ConvertResult(pdf_path=pdf_path)
    t0 = time.time()

    # Determine output path
    if opts.output_dir:
        out_dir = opts.output_dir
        out_dir.mkdir(parents=True, exist_ok=True)
    else:
        out_dir = pdf_path.parent

    md_path = out_dir / (pdf_path.stem + ".md")
    result.md_path = md_path

    # Dry run: just report what would happen
    if opts.dry_run:
        exists_tag = " (exists, would overwrite)" if md_path.exists() else ""
        _log.debug("dry-run: %s%s", md_path.name, exists_tag)
        result.success = True
        return result

    # Skip if already exists (unless --force)
    if md_path.exists() and not opts.force:
        _log.debug("skip (already exists): %s", md_path.name)
        result.success = True
        result.md_path = md_path
        return result

    validation = validate_pdf_for_mineru(pdf_path)
    if not validation.ok:
        return _validation_failure_result(pdf_path, validation, t0)

    # Build multipart form data
    url = f"{opts.api_url}{PARSE_ENDPOINT}"

    form_data = {
        "backend": (None, opts.backend),
        "parse_method": (None, opts.parse_method),
        "formula_enable": (None, str(opts.formula_enable).lower()),
        "table_enable": (None, str(opts.table_enable).lower()),
        "return_md": (None, "true"),
        "return_middle_json": (None, "false"),
        "return_content_list": (None, str(opts.save_content_list).lower()),
        "return_model_output": (None, "false"),
        "return_images": (None, "false"),
        "start_page_id": (None, str(opts.start_page)),
        "end_page_id": (None, str(opts.end_page)),
    }

    # lang_list needs to be sent as repeated form fields
    # requests handles this via the files parameter
    try:
        with open(pdf_path, "rb") as f:
            files = {
                "files": (pdf_path.name, f, "application/pdf"),
            }
            # Add lang_list as a form field
            form_data["lang_list"] = (None, opts.lang)

            resp = requests.post(url, files={**files, **form_data}, timeout=API_TIMEOUT)

    except requests.ConnectionError:
        result.error = f"Cannot connect to MinerU server at {opts.api_url}"
        result.elapsed_seconds = time.time() - t0
        return result
    except requests.Timeout:
        result.error = f"Request timed out after {API_TIMEOUT}s"
        result.elapsed_seconds = time.time() - t0
        return result

    result.elapsed_seconds = time.time() - t0

    if resp.status_code != 200:
        result.error = f"HTTP {resp.status_code}: {resp.text[:200]}"
        return result

    # Parse response
    try:
        data = resp.json()
    except ValueError:
        result.error = "Invalid JSON response from server"
        return result

    # Extract markdown content from response
    # MinerU API returns a list (one entry per uploaded file)
    md_content = _extract_markdown(data)
    if md_content is None:
        result.error = f"No markdown content in response. Keys: {list(data.keys()) if isinstance(data, dict) else type(data).__name__}"
        return result

    # Write markdown
    md_path.write_text(md_content, encoding="utf-8")
    result.success = True
    result.md_size = len(md_content.encode("utf-8"))

    # Optionally save content_list JSON
    if opts.save_content_list:
        cl = _extract_field(data, "content_list")
        if cl:
            cl_path = out_dir / f"{_safe_pdf_artifact_stem(pdf_path)}_content_list.json"
            cl_path.write_text(json.dumps(cl, ensure_ascii=False, indent=2), encoding="utf-8")

    _log.info("-> %s (%s, %.1fs)", md_path.name, _fmt_size(result.md_size), result.elapsed_seconds)
    return result


def _extract_markdown(data) -> str | None:
    """Extract markdown text from MinerU API response.

    Actual response format (MinerU ≥2.7):
        {
          "backend": "pipeline",
          "version": "2.7.6",
          "results": {
            "<filename_stem>": {
              "md_content": "..."
            }
          }
        }
    """
    if not isinstance(data, dict):
        return None

    # Primary path: results → {filename} → md_content
    results = data.get("results")
    if isinstance(results, dict):
        for _filename, entry in results.items():
            if isinstance(entry, dict):
                md = entry.get("md_content")
                if isinstance(md, str) and md.strip():
                    return md

    # Fallback: direct md_content at top level
    for key in ("md_content", "md", "markdown", "content"):
        if key in data and isinstance(data[key], str) and data[key].strip():
            return data[key]

    return None


def _extract_field(data, field_name):
    """Extract a named field from MinerU API response.

    Navigates: data["results"][first_key][field_name]
    """
    if not isinstance(data, dict):
        return None
    results = data.get("results")
    if isinstance(results, dict):
        for _filename, entry in results.items():
            if isinstance(entry, dict) and field_name in entry:
                return entry[field_name]
    return data.get(field_name)


# ============================================================================
#  Cloud API
# ============================================================================

CLOUD_API_URL = "https://mineru.net/api/v4"
MINERU_OPEN_API_BIN = "mineru-open-api"


def _cloud_cli_retry_attempts(opts: ConvertOptions) -> int:
    """Return the number of CLI attempts for MinerU cloud extraction."""
    return max(1, int(opts.upload_retries or DEFAULT_UPLOAD_RETRIES))


def _cloud_safe_pdf_name(pdf_path: Path) -> str:
    """Return a MinerU-cloud-safe filename without changing the user's file."""
    original_name = pdf_path.name
    if (
        len(original_name) <= CLOUD_SAFE_FILENAME_THRESHOLD
        and _utf8_size(original_name) <= CLOUD_SAFE_FILENAME_MAX_BYTES
    ):
        return original_name

    suffix = pdf_path.suffix or ".pdf"
    if len(suffix) >= CLOUD_SAFE_FILENAME_MAX_CHARS or _utf8_size(suffix) >= CLOUD_SAFE_FILENAME_MAX_BYTES:
        suffix = ".pdf"
    digest = hashlib.md5(original_name.encode("utf-8")).hexdigest()[:16]
    max_prefix_chars = CLOUD_SAFE_FILENAME_MAX_CHARS - len(suffix) - len(digest) - 1
    max_prefix_bytes = CLOUD_SAFE_FILENAME_MAX_BYTES - _utf8_size(suffix) - len(digest) - 1
    prefix = _truncate_utf8_prefix(
        pdf_path.stem,
        max_chars=min(CLOUD_SAFE_FILENAME_PREFIX_CHARS, max_prefix_chars),
        max_bytes=max_prefix_bytes,
    ).rstrip(" ._-")
    if not prefix:
        prefix = _truncate_utf8_prefix("document", max_chars=max_prefix_chars, max_bytes=max_prefix_bytes) or "d"
    return f"{prefix}-{digest}{suffix}"


def _utf8_size(value: str) -> int:
    return len(value.encode("utf-8"))


def _truncate_utf8_prefix(value: str, *, max_chars: int, max_bytes: int) -> str:
    """Truncate without splitting UTF-8 code points."""
    if max_chars <= 0 or max_bytes <= 0:
        return ""

    chars: list[str] = []
    used_bytes = 0
    for char in value:
        if len(chars) >= max_chars:
            break
        char_bytes = _utf8_size(char)
        if used_bytes + char_bytes > max_bytes:
            break
        chars.append(char)
        used_bytes += char_bytes
    return "".join(chars)


def _cloud_safe_pdf_stem(pdf_path: Path) -> str:
    """Return the stem corresponding to the cloud-safe filename."""
    return _safe_pdf_artifact_stem(pdf_path)


def _safe_pdf_artifact_stem(pdf_path: Path) -> str:
    """Return a bounded, stable stem for internal artifacts derived from a PDF."""
    return Path(_cloud_safe_pdf_name(pdf_path)).stem


@contextmanager
def cloud_safe_input_path(pdf_path: Path) -> Iterator[CloudInputAlias]:
    """Yield a path whose basename is safe for MinerU Cloud's data_id limit."""
    safe_name = _cloud_safe_pdf_name(pdf_path)
    if safe_name == pdf_path.name:
        yield CloudInputAlias(path=pdf_path, output_stem=pdf_path.stem, aliased=False)
        return

    with tempfile.TemporaryDirectory(prefix="scholaraio-mineru-cloud-") as tmp:
        alias_path = Path(tmp) / safe_name
        source_path = pdf_path.resolve()
        try:
            os.link(source_path, alias_path)
        except OSError:
            try:
                os.symlink(source_path, alias_path)
            except OSError:
                shutil.copy2(source_path, alias_path)
        yield CloudInputAlias(path=alias_path, output_stem=alias_path.stem, aliased=True)


def convert_pdf_cloud(
    pdf_path: Path,
    opts: ConvertOptions,
    *,
    api_key: str,
    cloud_url: str = CLOUD_API_URL,
) -> ConvertResult:
    """通过 `mineru-open-api extract` 将单个 PDF 转换为 Markdown。"""
    result = ConvertResult(pdf_path=pdf_path)
    t0 = time.time()

    out_dir = opts.output_dir if opts.output_dir else pdf_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / (pdf_path.stem + ".md")
    cloud_output_stem = Path(_cloud_safe_pdf_name(pdf_path)).stem
    existing_md_path = _locate_cloud_markdown_output(out_dir, cloud_output_stem)
    if existing_md_path is None and cloud_output_stem != pdf_path.stem:
        existing_md_path = _locate_cloud_markdown_output(out_dir, pdf_path.stem)
    result.md_path = existing_md_path or md_path

    if opts.dry_run:
        display_md_path = existing_md_path or md_path
        exists_tag = " (exists, would overwrite)" if existing_md_path is not None else ""
        _log.debug("dry-run [cloud]: %s%s", display_md_path.name, exists_tag)
        result.success = True
        return result

    if existing_md_path is not None and not opts.force:
        _log.debug("skip (already exists): %s", existing_md_path.name)
        result.success = True
        return result

    validation = validate_pdf_for_mineru(pdf_path)
    if not validation.ok:
        return _validation_failure_result(pdf_path, validation, t0)

    cli_path = shutil.which(MINERU_OPEN_API_BIN)
    if not cli_path:
        result.error = (
            "未找到 mineru-open-api CLI，请先安装：`pip install mineru-open-api`，"
            "或参考 ModelScope skill / npm / go 安装方式。"
        )
        result.elapsed_seconds = time.time() - t0
        return result

    with cloud_safe_input_path(pdf_path) as cloud_input:
        cmd = _build_cloud_cli_command(cli_path, cloud_input.path, out_dir, opts, cloud_url=cloud_url)
        env = os.environ.copy()
        if api_key:
            env["MINERU_TOKEN"] = api_key

        attempts = _cloud_cli_retry_attempts(opts)
        for attempt in range(1, attempts + 1):
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    cwd=str(cloud_input.path.parent),
                    env=env,
                    timeout=max(30, int(opts.poll_timeout or DEFAULT_POLL_TIMEOUT)) + 60,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                result.error = f"mineru-open-api 执行超时: {exc}"
            except OSError as exc:
                result.error = f"无法启动 mineru-open-api: {exc}"
                result.elapsed_seconds = time.time() - t0
                return result
            else:
                if proc.returncode != 0:
                    detail = (proc.stderr or proc.stdout or "").strip()
                    result.error = f"mineru-open-api exit code {proc.returncode}: {detail or 'unknown error'}"
                else:
                    actual_md_path = _locate_cloud_markdown_output(out_dir, cloud_input.output_stem)
                    if actual_md_path is None and cloud_input.output_stem != pdf_path.stem:
                        actual_md_path = _locate_cloud_markdown_output(out_dir, pdf_path.stem)
                    if actual_md_path is None:
                        detail = (proc.stderr or proc.stdout or "").strip()
                        result.error = f"mineru-open-api 未生成 Markdown 输出: {detail or 'missing .md file'}"
                    else:
                        result.md_path = actual_md_path
                        result.success = True
                        result.md_size = len(actual_md_path.read_bytes())
                        result.elapsed_seconds = time.time() - t0
                        _log.info(
                            "-> [cloud-cli] %s (%s, %.1fs)",
                            actual_md_path.name,
                            _fmt_size(result.md_size),
                            result.elapsed_seconds,
                        )
                        return result

            if attempt >= attempts:
                result.elapsed_seconds = time.time() - t0
                return result

            backoff_seconds = float(2 ** (attempt - 1))
            _log.warning(
                "mineru-open-api attempt %d/%d failed for %s: %s; retrying in %.1fs",
                attempt,
                attempts,
                pdf_path.name,
                result.error,
                backoff_seconds,
            )
            time.sleep(backoff_seconds)

    result.elapsed_seconds = time.time() - t0
    return result


_DEFAULT_CLOUD_BATCH_SIZE = 20  # max files per batch request


def convert_pdfs_cloud_batch(
    pdf_paths: list[Path],
    opts: ConvertOptions,
    *,
    api_key: str,
    cloud_url: str = CLOUD_API_URL,
    batch_size: int = _DEFAULT_CLOUD_BATCH_SIZE,
) -> list[ConvertResult]:
    """通过 `mineru-open-api` 批量转换 PDF 为 Markdown。"""
    if not pdf_paths:
        return []

    # Split into chunks
    all_results: list[ConvertResult] = []
    for chunk_start in range(0, len(pdf_paths), batch_size):
        indexed_chunk = list(enumerate(pdf_paths[chunk_start : chunk_start + batch_size], start=chunk_start))
        chunk_results = _convert_chunk_cloud(indexed_chunk, opts, api_key=api_key, cloud_url=cloud_url)
        all_results.extend(chunk_results)
    return all_results


def _convert_chunk_cloud(
    indexed_pdf_paths: list[tuple[int, Path]],
    opts: ConvertOptions,
    *,
    api_key: str,
    cloud_url: str,
) -> list[ConvertResult]:
    """Process a single batch chunk via bounded concurrent CLI invocations."""
    max_workers = min(len(indexed_pdf_paths), max(1, int(opts.upload_workers or DEFAULT_UPLOAD_WORKERS)))

    def _run_one(item: tuple[int, Path]) -> ConvertResult:
        global_idx, pdf_path = item
        item_opts = opts
        if opts.output_dir is not None:
            item_opts = replace(opts, output_dir=opts.output_dir / f"{global_idx:04d}_{_cloud_safe_pdf_stem(pdf_path)}")
        return convert_pdf_cloud(pdf_path, item_opts, api_key=api_key, cloud_url=cloud_url)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        return list(pool.map(_run_one, indexed_pdf_paths))


def _build_cloud_cli_command(
    cli_path: str,
    pdf_path: Path,
    out_dir: Path,
    opts: ConvertOptions,
    *,
    cloud_url: str,
) -> list[str]:
    """Build the `mineru-open-api extract` command for a single PDF."""
    model_version = _resolve_cloud_model_version(opts)
    model_flag = "html" if model_version == "MinerU-HTML" else model_version
    timeout = max(1, int(opts.poll_timeout or DEFAULT_POLL_TIMEOUT))

    cmd = [
        cli_path,
        "extract",
        str(pdf_path),
        "-o",
        str(out_dir),
        "--language",
        opts.lang,
        "--model",
        model_flag,
    ]
    if model_version in PDF_CLOUD_MODEL_VERSIONS:
        if opts.parse_method == "ocr":
            cmd.append("--ocr")
        elif opts.parse_method == "txt":
            _log.warning("mineru-open-api extract has no txt-only mode; parse_method=txt is treated as default mode")
        cmd.append(f"--formula={'true' if opts.formula_enable else 'false'}")
        cmd.append(f"--table={'true' if opts.table_enable else 'false'}")
    elif opts.parse_method in {"ocr", "txt"}:
        _log.warning("MinerU cloud model_version=%s ignores parse_method=%s", model_version, opts.parse_method)

    cmd.extend(["--timeout", str(timeout)])
    if cloud_url and cloud_url.rstrip("/") != CLOUD_API_URL.rstrip("/"):
        cmd.extend(["--base-url", cloud_url])
    return cmd


def _locate_cloud_markdown_output(out_dir: Path, stem: str) -> Path | None:
    """Locate the markdown file produced by `mineru-open-api`."""
    candidates = [
        out_dir / f"{stem}.md",
        out_dir / stem / f"{stem}.md",
        out_dir / stem / "index.md",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    matches = sorted(path for path in out_dir.rglob("*.md") if path.is_file())
    for match in matches:
        if match.stem == stem:
            return match
        if match.stem == "index" and match.parent.name == stem:
            return match
    return None


# ============================================================================
#  Utilities
# ============================================================================


def _fmt_size(nbytes: int) -> str:
    """Format byte count as human-readable string."""
    if nbytes < 1024:
        return f"{nbytes} B"
    elif nbytes < 1024 * 1024:
        return f"{nbytes / 1024:.1f} KB"
    else:
        return f"{nbytes / (1024 * 1024):.1f} MB"


def _find_pdfs(dirpath: Path, recursive: bool = False) -> list[Path]:
    """Find all PDF files in a directory."""
    pattern = "**/*.pdf" if recursive else "*.pdf"
    return sorted(dirpath.glob(pattern))


# ============================================================================
#  Long PDF splitting & merging
# ============================================================================

DEFAULT_CHUNK_PAGES = 100
# MinerU web docs still mention 600 pages, but the current cloud extract CLI
# returns -60006 once a document exceeds 200 pages. Plan chunks against the
# effective runtime limit to avoid avoidable retries/failures.
MINERU_CLOUD_MAX_PAGES = 200
MINERU_CLOUD_MAX_BYTES = 200 * 1024 * 1024


def _get_pdf_size_bytes(pdf_path: Path) -> int:
    """Return file size in bytes, or -1 when unavailable."""
    try:
        return pdf_path.stat().st_size
    except OSError:
        return -1


def _fmt_mb(nbytes: int) -> str:
    """Format bytes as MB with one decimal place."""
    return f"{nbytes / (1024 * 1024):.1f} MB"


def _plan_cloud_chunking(
    pdf_path: Path,
    *,
    default_chunk_size: int = DEFAULT_CHUNK_PAGES,
    max_pages: int = MINERU_CLOUD_MAX_PAGES,
    max_bytes: int = MINERU_CLOUD_MAX_BYTES,
) -> tuple[bool, int, str]:
    """Decide whether MinerU cloud CLI should split a PDF and choose a chunk size.

    Cloud extraction supports up to ``max_pages`` pages and ``max_bytes`` per document.
    When only the file size is too large, estimate a page-based chunk size from the
    average bytes per page. If page count is unavailable, fall back to
    ``default_chunk_size``.
    """
    page_count = _get_pdf_page_count(pdf_path)
    size_bytes = _get_pdf_size_bytes(pdf_path)

    reasons: list[str] = []
    if page_count > max_pages:
        reasons.append(f"{page_count} pages > {max_pages}")
    if size_bytes > max_bytes:
        reasons.append(f"{_fmt_mb(size_bytes)} > {_fmt_mb(max_bytes)}")

    if not reasons:
        return False, max_pages, ""

    chunk_size = max_pages
    if size_bytes > max_bytes and page_count > 0:
        avg_bytes_per_page = size_bytes / page_count
        if avg_bytes_per_page > 0:
            size_bound_pages = max(1, int(max_bytes // avg_bytes_per_page))
            chunk_size = min(chunk_size, size_bound_pages)
    elif size_bytes > max_bytes:
        chunk_size = min(max_pages, max(1, default_chunk_size))

    return True, max(1, chunk_size), "; ".join(reasons)


def _get_pdf_page_count(pdf_path: Path) -> int:
    """Get the number of pages in a PDF.

    Tries pymupdf first, falls back to pikepdf.

    Returns:
        Page count, or -1 if unable to determine.
    """
    validation = validate_pdf_for_mineru(pdf_path)
    if validation.ok and validation.page_count is not None:
        return validation.page_count
    if validation.ok:
        _log.warning("cannot detect page count (install pymupdf or pikepdf): %s", pdf_path.name)
    else:
        _log.warning("cannot detect page count: %s", validation.error)
    return -1


def _split_pdf(pdf_path: Path, chunk_size: int = DEFAULT_CHUNK_PAGES, output_dir: Path | None = None) -> list[Path]:
    """Split a long PDF into multiple smaller PDFs.

    Args:
        pdf_path: Original PDF file path.
        chunk_size: Maximum pages per chunk.
        output_dir: Where to write chunks (default: ``.{stem}_chunks/``
            next to the PDF).

    Returns:
        List of chunk PDF paths in page order.
        If total pages <= chunk_size, returns ``[pdf_path]`` unchanged.
    """
    try:
        import pymupdf
    except ImportError:
        raise ImportError("pymupdf is required for splitting long PDFs. Install it with: pip install scholaraio[pdf]")

    page_count = _get_pdf_page_count(pdf_path)
    if page_count <= chunk_size:
        return [pdf_path]

    artifact_stem = _safe_pdf_artifact_stem(pdf_path)
    if output_dir is None:
        output_dir = pdf_path.parent / f".{artifact_stem}_chunks"
    output_dir.mkdir(parents=True, exist_ok=True)

    chunks: list[Path] = []
    with pymupdf.open(pdf_path) as src_doc:
        for start in range(0, page_count, chunk_size):
            end = min(start + chunk_size, page_count)  # exclusive
            chunk_name = f"{artifact_stem}_p{start:04d}-{end - 1:04d}.pdf"
            chunk_path = output_dir / chunk_name

            if chunk_path.exists():
                # Idempotent: reuse existing chunk
                chunks.append(chunk_path)
                continue

            chunk_doc = pymupdf.open()
            chunk_doc.insert_pdf(src_doc, from_page=start, to_page=end - 1)
            chunk_doc.save(str(chunk_path))
            chunk_doc.close()
            chunks.append(chunk_path)

    _log.info("split %s (%d pages) into %d chunks of ≤%d pages", pdf_path.name, page_count, len(chunks), chunk_size)
    return chunks


def _merge_chunk_results(
    chunk_results: list[ConvertResult],
    original_pdf: Path,
    output_dir: Path,
) -> ConvertResult:
    """Merge multiple chunk ConvertResults into a single result.

    Handles:
    - Markdown text concatenation
    - Image file deduplication/renaming (``c{idx}_{name}`` prefix)
    - Error aggregation for partial failures

    Args:
        chunk_results: Ordered ConvertResult list (one per chunk).
        original_pdf: The original unsplit PDF path.
        output_dir: Final output directory for merged result.

    Returns:
        Merged ConvertResult.
    """
    merged = ConvertResult(pdf_path=original_pdf)
    final_md_path = output_dir / (original_pdf.stem + ".md")
    final_images_dir = output_dir / "images"

    md_parts: list[str] = []
    errors: list[str] = []
    total_elapsed = 0.0

    for idx, cr in enumerate(chunk_results):
        total_elapsed += cr.elapsed_seconds

        if not cr.success:
            errors.append(f"chunk {idx}: {cr.error}")
            continue

        if not cr.md_path or not cr.md_path.exists():
            errors.append(f"chunk {idx}: md file not found")
            continue

        chunk_md = cr.md_path.read_text(encoding="utf-8", errors="replace")

        # Find chunk's images directory
        chunk_images_dir = None
        for candidate in [
            cr.md_path.parent / "images",
            cr.md_path.parent / f"{cr.md_path.stem}_mineru_images",
            cr.md_path.parent / f"{cr.md_path.stem}_images",
        ]:
            if candidate.is_dir():
                chunk_images_dir = candidate
                break

        if chunk_images_dir and any(chunk_images_dir.iterdir()):
            final_images_dir.mkdir(parents=True, exist_ok=True)
            for img_file in sorted(chunk_images_dir.iterdir()):
                if not img_file.is_file():
                    continue
                new_name = f"c{idx:02d}_{img_file.name}"
                new_path = final_images_dir / new_name
                shutil.copy2(img_file, new_path)
                # Remap image references in markdown
                old_ref = f"images/{img_file.name}"
                new_ref = f"images/{new_name}"
                chunk_md = chunk_md.replace(old_ref, new_ref)
                # Also handle _mineru_images/ variant
                for prefix in [f"{cr.md_path.stem}_mineru_images", f"{cr.md_path.stem}_images"]:
                    old_ref2 = f"{prefix}/{img_file.name}"
                    chunk_md = chunk_md.replace(old_ref2, new_ref)

        md_parts.append(chunk_md)

    if not md_parts:
        merged.error = "all chunks failed: " + "; ".join(errors)
        merged.elapsed_seconds = total_elapsed
        return merged

    final_md = "\n\n".join(md_parts)
    final_md_path.write_text(final_md, encoding="utf-8")

    merged.success = True
    merged.md_path = final_md_path
    merged.md_size = len(final_md.encode("utf-8"))
    merged.elapsed_seconds = total_elapsed

    if errors:
        _log.warning("some chunks failed during merge: %s", "; ".join(errors))

    return merged


def _resolve_cloud_model_version(opts: ConvertOptions) -> str:
    """Resolve cloud ``model_version`` from options with backward compatibility."""
    model_version = (opts.cloud_model_version or "").strip()
    if model_version in VALID_CLOUD_MODEL_VERSIONS:
        return model_version

    # Backward-compatible fallback from local-style backend names.
    if opts.backend in {"vlm-auto-engine", "vlm-http-client", "vlm"}:
        return "vlm"
    if opts.backend in {"pipeline", "hybrid-auto-engine", "hybrid-http-client"}:
        return "pipeline"

    _log.warning("unknown cloud model_version/backend '%s', fallback to pipeline", model_version or opts.backend)
    return "pipeline"


def _convert_long_pdf(pdf_path: Path, opts: ConvertOptions, chunk_size: int = DEFAULT_CHUNK_PAGES) -> ConvertResult:
    """Handle a long PDF: split → convert each chunk → merge results.

    Uses the local MinerU API for each chunk sequentially.
    """
    t0 = time.time()
    validation = validate_pdf_for_mineru(pdf_path)
    if not validation.ok:
        return _validation_failure_result(pdf_path, validation, t0)

    out_dir = opts.output_dir if opts.output_dir else pdf_path.parent
    chunks_dir = out_dir / f".{_safe_pdf_artifact_stem(pdf_path)}_chunks"

    chunk_paths = _split_pdf(pdf_path, chunk_size=chunk_size, output_dir=chunks_dir)

    chunk_results: list[ConvertResult] = []
    for i, chunk_pdf in enumerate(chunk_paths):
        _log.info("converting chunk %d/%d: %s", i + 1, len(chunk_paths), chunk_pdf.name)
        chunk_opts = ConvertOptions(
            api_url=opts.api_url,
            output_dir=chunks_dir,
            backend=opts.backend,
            lang=opts.lang,
            parse_method=opts.parse_method,
            formula_enable=opts.formula_enable,
            table_enable=opts.table_enable,
            save_content_list=opts.save_content_list,
            force=opts.force,
            dry_run=opts.dry_run,
            upload_workers=opts.upload_workers,
            upload_retries=opts.upload_retries,
            download_retries=opts.download_retries,
            poll_timeout=opts.poll_timeout,
        )
        cr = convert_pdf(chunk_pdf, chunk_opts)
        chunk_results.append(cr)

    merged = _merge_chunk_results(chunk_results, pdf_path, out_dir)

    if merged.success and chunks_dir.exists():
        shutil.rmtree(chunks_dir)
        _log.debug("cleaned up chunks dir: %s", chunks_dir)

    return merged


def _convert_long_pdf_cloud(
    pdf_path: Path,
    opts: ConvertOptions,
    *,
    api_key: str,
    cloud_url: str,
    chunk_size: int = DEFAULT_CHUNK_PAGES,
) -> ConvertResult:
    """Handle a long PDF via MinerU cloud CLI: split → convert → merge."""
    t0 = time.time()
    validation = validate_pdf_for_mineru(pdf_path)
    if not validation.ok:
        return _validation_failure_result(pdf_path, validation, t0)

    out_dir = opts.output_dir if opts.output_dir else pdf_path.parent
    chunks_dir = out_dir / f".{_safe_pdf_artifact_stem(pdf_path)}_chunks"

    chunk_paths = _split_pdf(pdf_path, chunk_size=chunk_size, output_dir=chunks_dir)

    chunk_opts = ConvertOptions(
        output_dir=chunks_dir,
        backend=opts.backend,
        cloud_model_version=opts.cloud_model_version,
        lang=opts.lang,
        parse_method=opts.parse_method,
        formula_enable=opts.formula_enable,
        table_enable=opts.table_enable,
        save_content_list=opts.save_content_list,
        upload_workers=opts.upload_workers,
        upload_retries=opts.upload_retries,
        download_retries=opts.download_retries,
        poll_timeout=opts.poll_timeout,
    )
    batch_results = convert_pdfs_cloud_batch(
        chunk_paths,
        chunk_opts,
        api_key=api_key,
        cloud_url=cloud_url,
    )

    merged = _merge_chunk_results(batch_results, pdf_path, out_dir)

    if merged.success and chunks_dir.exists():
        shutil.rmtree(chunks_dir)
        _log.debug("cleaned up chunks dir: %s", chunks_dir)

    return merged


# ============================================================================
#  CLI Commands
# ============================================================================


def cmd_status(args: argparse.Namespace) -> None:
    """Check MinerU server status."""
    api_url = args.api_url
    _log.info("Checking MinerU server at %s", api_url)
    if check_server(api_url):
        _log.info("Server is UP and reachable")
    else:
        _log.error("Server is DOWN or unreachable at %s", api_url)
        sys.exit(1)


def cmd_convert(args: argparse.Namespace) -> None:
    """Convert a single PDF file."""
    pdf_path = Path(args.file).resolve()
    if not pdf_path.exists():
        _log.error("File not found: %s", pdf_path)
        sys.exit(1)
    if pdf_path.suffix.lower() != ".pdf":
        _log.warning("%s does not have .pdf extension", pdf_path.name)

    opts = _build_options(args)

    _log.info("Converting: %s", pdf_path.name)
    if opts.dry_run:
        _log.debug("dry run - no files will be written")

    result = convert_pdf(pdf_path, opts)

    if not result.success:
        _log.error("FAILED: %s", result.error)
        sys.exit(1)


def cmd_batch(args: argparse.Namespace) -> None:
    """Batch-convert all PDFs in a directory."""
    dirpath = Path(args.directory).resolve()
    if not dirpath.is_dir():
        _log.error("Not a directory: %s", dirpath)
        sys.exit(1)

    opts = _build_options(args)

    # Find PDFs
    all_pdfs = _find_pdfs(dirpath, recursive=args.recursive)
    if not all_pdfs:
        _log.info("No PDF files found in %s", dirpath)
        return

    # Determine output dir for skip-check
    out_dir = opts.output_dir if opts.output_dir else None

    # Filter already-converted (unless --force)
    if opts.force or opts.dry_run:
        targets = all_pdfs
    else:
        targets = []
        for p in all_pdfs:
            check_dir = out_dir if out_dir else p.parent
            md_file = check_dir / (p.stem + ".md")
            if not md_file.exists():
                targets.append(p)

    skipped = len(all_pdfs) - len(targets)
    if not targets:
        msg = "No unprocessed PDFs in %s"
        if all_pdfs:
            msg += " (use --force to reconvert)"
        _log.info(msg, dirpath)
        return

    if skipped:
        _log.info("Found %d PDF(s) to convert (%d skipped, already have .md)", len(targets), skipped)
    else:
        _log.info("Found %d PDF(s) to convert", len(targets))
    if opts.dry_run:
        _log.debug("dry run - no files will be written")

    # Check server before starting batch
    if not opts.dry_run:
        if not check_server(opts.api_url):
            _log.error("MinerU server not reachable at %s", opts.api_url)
            sys.exit(1)

    succeeded = 0
    failed = 0
    total = len(targets)

    for i, pdf_path in enumerate(targets, 1):
        _log.info("[%d/%d] %s", i, total, pdf_path.name)
        try:
            result = convert_pdf(pdf_path, opts)
            if result.success:
                succeeded += 1
            else:
                _log.error("FAILED: %s", result.error)
                failed += 1
        except Exception as e:
            _log.error("ERROR: %s", e)
            failed += 1

    # Summary
    _log.info("Batch complete: %d succeeded, %d failed, %d skipped", succeeded, failed, skipped)


def _build_options(args: argparse.Namespace) -> ConvertOptions:
    """Build ConvertOptions from parsed CLI arguments."""
    opts = ConvertOptions(
        api_url=args.api_url,
        backend=args.backend,
        lang=args.lang,
        formula_enable=not args.no_formula,
        table_enable=not args.no_table,
        force=getattr(args, "force", False),
        dry_run=getattr(args, "dry_run", False),
        save_content_list=getattr(args, "save_content_list", False),
    )
    if hasattr(args, "output_dir") and args.output_dir:
        opts.output_dir = Path(args.output_dir).resolve()
    if hasattr(args, "start_page") and args.start_page is not None:
        opts.start_page = args.start_page
    if hasattr(args, "end_page") and args.end_page is not None:
        opts.end_page = args.end_page
    if hasattr(args, "parse_method") and args.parse_method:
        opts.parse_method = args.parse_method
    return opts


# ============================================================================
#  Argument Parser
# ============================================================================


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    """Add arguments shared by convert and batch subcommands."""
    parser.add_argument(
        "-o",
        "--output-dir",
        type=str,
        default=None,
        help="Output directory for .md files (default: same as PDF)",
    )
    parser.add_argument(
        "--api-url",
        type=str,
        default=DEFAULT_API_URL,
        help=f"MinerU server URL (default: {DEFAULT_API_URL})",
    )
    parser.add_argument(
        "--backend",
        type=str,
        default=DEFAULT_BACKEND,
        choices=VALID_BACKENDS,
        help=f"MinerU parsing backend (default: {DEFAULT_BACKEND})",
    )
    parser.add_argument(
        "--lang",
        type=str,
        default=DEFAULT_LANG,
        help=f"OCR language: ch, en, latin, etc. (default: {DEFAULT_LANG})",
    )
    parser.add_argument(
        "--parse-method",
        type=str,
        default="auto",
        choices=["auto", "txt", "ocr"],
        help="PDF parse method (default: auto)",
    )
    parser.add_argument(
        "--no-formula",
        action="store_true",
        help="Disable formula parsing",
    )
    parser.add_argument(
        "--no-table",
        action="store_true",
        help="Disable table parsing",
    )
    parser.add_argument(
        "--save-content-list",
        action="store_true",
        help="Also save content_list JSON from MinerU",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be done, without writing files",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="scholaraio ingest mineru",
        description="Convert PDF files to Markdown using local MinerU server.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- status ---
    p_status = sub.add_parser("status", help="Check MinerU server status")
    p_status.add_argument(
        "--api-url",
        type=str,
        default=DEFAULT_API_URL,
        help=f"MinerU server URL (default: {DEFAULT_API_URL})",
    )

    # --- convert (single file) ---
    p_convert = sub.add_parser("convert", help="Convert a single PDF to Markdown")
    p_convert.add_argument("file", type=str, help="Path to PDF file")
    p_convert.add_argument(
        "--start-page",
        type=int,
        default=None,
        help="Start page (0-indexed, default: 0)",
    )
    p_convert.add_argument(
        "--end-page",
        type=int,
        default=None,
        help="End page (0-indexed, default: all pages)",
    )
    _add_common_args(p_convert)

    # --- batch ---
    p_batch = sub.add_parser("batch", help="Batch-convert all PDFs in a directory")
    p_batch.add_argument("directory", type=str, help="Directory containing PDF files")
    p_batch.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        help="Recurse into subdirectories",
    )
    p_batch.add_argument(
        "--force",
        action="store_true",
        help="Reconvert PDFs that already have .md output",
    )
    _add_common_args(p_batch)

    args = parser.parse_args()
    if args.command == "status":
        cmd_status(args)
    elif args.command == "convert":
        cmd_convert(args)
    elif args.command == "batch":
        cmd_batch(args)


if __name__ == "__main__":
    main()
