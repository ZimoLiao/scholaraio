"""
setup.py — ScholarAIO 环境检测与交互式安装向导
================================================

两种模式：
  scholaraio setup          交互式向导（bilingual EN/ZH）
  scholaraio setup check    环境状态诊断
"""

from __future__ import annotations

import contextlib
import importlib
import importlib.util
import io
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from scholaraio.core.config import Config, load_config

# ============================================================================
#  Bilingual strings
# ============================================================================

Lang = str  # "en" | "zh"

_S: dict[str, dict[Lang, str]] = {
    # -- check labels --
    "python_ver": {"en": "Python version", "zh": "Python 版本"},
    "core_deps": {"en": "Core deps", "zh": "核心依赖"},
    "embed_deps": {"en": "Embed deps", "zh": "嵌入依赖"},
    "topics_deps": {"en": "Topics deps", "zh": "主题依赖"},
    "import_deps": {"en": "Import deps", "zh": "导入依赖"},
    "pdf_deps": {"en": "PDF deps", "zh": "PDF 依赖"},
    "office_deps": {"en": "Office deps", "zh": "Office 依赖"},
    "draw_deps": {"en": "Draw deps", "zh": "绘图依赖"},
    "config_yaml": {"en": "config.yaml", "zh": "config.yaml"},
    "llm_key": {"en": "LLM API key", "zh": "LLM API key"},
    "mineru": {"en": "MinerU", "zh": "MinerU"},
    "docling": {"en": "Docling", "zh": "Docling"},
    "huggingface": {"en": "Hugging Face", "zh": "Hugging Face"},
    "parser_recommendation": {"en": "PDF parser recommendation", "zh": "PDF 解析器推荐"},
    "graphviz_dot": {"en": "Graphviz dot", "zh": "Graphviz dot"},
    "inkscape": {"en": "Inkscape", "zh": "Inkscape"},
    "contact_email": {"en": "Contact email", "zh": "联系邮箱"},
    "s2_key": {"en": "Semantic Scholar API key", "zh": "Semantic Scholar API key"},
    "zotero_key": {"en": "Zotero API key", "zh": "Zotero API key"},
    "paper2any": {"en": "Paper2Any", "zh": "Paper2Any"},
    "directories": {"en": "Directories", "zh": "目录结构"},
    "papers_count": {"en": "Papers", "zh": "论文数量"},
    "optional_s2_set": {
        "en": "configured ({masked}) | optional: authenticated Semantic Scholar access; some endpoints require a key",
        "zh": "已配置 ({masked}) | 可选：用于 Semantic Scholar 认证访问；部分端点需要 key",
    },
    "optional_s2_unset": {
        "en": "not set | optional: most endpoints still work anonymously, but some Semantic Scholar endpoints require a key",
        "zh": "未设置 | 可选：多数端点仍可匿名访问，但部分 Semantic Scholar 端点需要 key",
    },
    "optional_zotero_set": {
        "en": "configured ({masked}) | optional: used by Zotero Web API import",
        "zh": "已配置 ({masked}) | 可选：用于 Zotero Web API 导入",
    },
    "optional_zotero_unset": {
        "en": "not set | optional: our Zotero Web API path needs it; local zotero.sqlite import does not",
        "zh": "未设置 | 可选：我们当前的 Zotero Web API 路径需要它；本地 zotero.sqlite 导入不需要",
    },
    # -- check status --
    "installed": {"en": "installed", "zh": "已安装"},
    "not_installed": {"en": "not installed", "zh": "未安装"},
    "found": {"en": "found", "zh": "已找到"},
    "not_found": {"en": "not found", "zh": "未找到"},
    "configured": {"en": "configured", "zh": "已配置"},
    "not_set": {"en": "not set", "zh": "未设置"},
    "all_ok": {"en": "all exist", "zh": "全部存在"},
    # -- wizard --
    "lang_prompt": {
        "en": "Language:\n  1. English (default)\n  2. Chinese",
        "zh": "语言：\n  1. English（默认）\n  2. 中文",
    },
    "welcome": {"en": "\n=== ScholarAIO Setup Wizard ===\n", "zh": "\n=== ScholarAIO 安装向导 ===\n"},
    "step_deps": {"en": "Step 1: Checking dependencies...", "zh": "步骤 1: 检查依赖..."},
    "step_config": {"en": "Step 2: Configuration file", "zh": "步骤 2: 配置文件"},
    "step_keys": {
        "en": "Step 3: API keys & embedding backend (stored in config.local.yaml, not tracked by git)",
        "zh": "步骤 3: API 密钥与 embedding 后端（保存在 config.local.yaml，不进 git）",
    },
    "step_parser": {
        "en": "Step 3: Choose a PDF parser",
        "zh": "步骤 3: 选择 PDF 解析器",
    },
    "step_keys_followup": {
        "en": "Step 4: API keys (stored in config.local.yaml, not tracked by git)",
        "zh": "步骤 4: API 密钥（保存在 config.local.yaml，不进 git）",
    },
    "step_verify": {"en": "Step 5: Verification", "zh": "步骤 5: 验证"},
    "install_prompt": {
        "en": "  {group} deps missing: {pkgs}\n  Install? (pip install scholaraio[{group}])",
        "zh": "  {group} 依赖缺失: {pkgs}\n  是否安装？(pip install scholaraio[{group}])",
    },
    "yn": {"en": " [Y/n] ", "zh": " [Y/n] "},
    "skip": {"en": "  Skipped.", "zh": "  已跳过。"},
    "installing": {"en": "  Installing {group}...", "zh": "  正在安装 {group}..."},
    "install_ok": {"en": "  Installed successfully.", "zh": "  安装成功。"},
    "install_fail": {
        "en": "  Installation failed. You can install later with: pip install scholaraio[{group}]",
        "zh": "  安装失败。你可以稍后手动安装: pip install scholaraio[{group}]",
    },
    "config_exists": {"en": "  config.yaml already exists, skipping.", "zh": "  config.yaml 已存在，跳过。"},
    "config_created": {
        "en": "  Created config.yaml with default settings.",
        "zh": "  已创建 config.yaml（默认配置）。",
    },
    "llm_key_prompt": {
        "en": "  LLM API key (DeepSeek / OpenAI / Anthropic / Google).\n"
        "  This is usually billed separately by your provider; do not assume an agent subscription covers it.\n"
        "  Without it: metadata extraction degrades to regex-only, enrich unavailable.\n"
        "  Press Enter to skip.",
        "zh": "  LLM API key（DeepSeek / OpenAI / Anthropic / Google）。\n"
        "  这通常需要由所选提供商单独计费；不要默认认为 agent 订阅会自动覆盖它。\n"
        "  不配置：元数据提取降级为纯正则，enrich 不可用。\n"
        "  按 Enter 跳过。",
    },
    "mineru_key_prompt": {
        "en": "  MinerU token for `mineru-open-api extract` (free to apply at https://mineru.net/apiManage/token).\n"
        "  Without it: ScholarAIO can still use local MinerU / Docling / PyMuPDF, but precise MinerU cloud parsing is unavailable.\n"
        "  Press Enter to skip.",
        "zh": "  MinerU token（用于 `mineru-open-api extract`，免费，只需去 https://mineru.net/apiManage/token 申请）。\n"
        "  不配置：仍可使用本地 MinerU / Docling / PyMuPDF，但不能使用 MinerU 云端精准解析。\n"
        "  按 Enter 跳过。",
    },
    "parser_choice_prompt": {
        "en": "  Which PDF parser do you want to use?\n  1. MinerU\n  2. Docling\n  3. Not sure, test and recommend for me",
        "zh": "  你想使用哪个 PDF 解析器？\n  1. MinerU\n  2. Docling\n  3. 不确定，请帮我测试并推荐",
    },
    "parser_choice_mineru": {"en": "  Selected MinerU.", "zh": "  已选择 MinerU。"},
    "parser_choice_docling": {"en": "  Selected Docling.", "zh": "  已选择 Docling。"},
    "parser_choice_auto": {
        "en": "  Testing MinerU availability and Hugging Face reachability...",
        "zh": "  正在测试 MinerU 可用性与 Hugging Face 连通性...",
    },
    "parser_choice_auto_configured_mineru": {
        "en": "  Existing MinerU token detected; treat MinerU cloud path as available before network probing.",
        "zh": "  检测到现有 MinerU token；在网络探测前先视为 MinerU 云路径可用。",
    },
    "parser_choice_auto_token_without_cli": {
        "en": "  Existing MinerU token detected, but `mineru-open-api` is still missing; install it first (usually `pip install -e .` or `pip install mineru-open-api`), then continue with MinerU.",
        "zh": "  检测到现有 MinerU token，但当前还缺少 `mineru-open-api`；请先安装它（通常直接 `pip install -e .` 或 `pip install mineru-open-api`），再继续走 MinerU。",
    },
    "parser_choice_auto_cli_without_token": {
        "en": "  MinerU CLI is available, but no MinerU API token is configured yet; register the free token later if you want cloud mode.",
        "zh": "  检测到 MinerU CLI 可用，但尚未配置 MinerU API Token；如需使用云端模式，请稍后注册免费 token 并填写。",
    },
    "reachability_yes": {"en": "reachable", "zh": "可达"},
    "reachability_no": {"en": "unreachable", "zh": "不可达"},
    "availability_yes": {"en": "available", "zh": "可用"},
    "availability_no": {"en": "unavailable", "zh": "不可用"},
    "parser_recommend_mineru": {
        "en": "  Suggestion: prefer MinerU. Reason: {reason}",
        "zh": "  建议优先使用 MinerU。原因：{reason}",
    },
    "parser_recommend_docling": {
        "en": "  Suggestion: prefer Docling. Reason: {reason}",
        "zh": "  建议优先使用 Docling。原因：{reason}",
    },
    "parser_recommend_override": {
        "en": "  If you already know you want the other parser, keep your own choice.",
        "zh": "  如果你已经确定要用另一个解析器，也可以直接按你的选择配置。",
    },
    "reason_mineru_only": {
        "en": "MinerU is available while Hugging Face is not reachable.",
        "zh": "MinerU 可用而 Hugging Face 不可达。",
    },
    "reason_hf_only": {
        "en": "Hugging Face is reachable while MinerU is not available.",
        "zh": "Hugging Face 可达而 MinerU 不可用。",
    },
    "reason_both": {
        "en": "MinerU is available and Hugging Face is also reachable; prefer MinerU by default.",
        "zh": "MinerU 可用，且 Hugging Face 也可达；默认优先推荐 MinerU。",
    },
    "reason_neither": {
        "en": "MinerU is not available and Hugging Face is not reachable; prefer Docling local deployment because it does not depend on external MinerU service.",
        "zh": "MinerU 当前不可用，且 Hugging Face 不可达；优先推荐 Docling 本地部署，因为它不依赖外部 MinerU 服务。",
    },
    "mineru_local_prompt": {
        "en": "  Do you plan to deploy MinerU locally?",
        "zh": "  你打算本地部署 MinerU 吗？",
    },
    "mineru_cloud_note": {
        "en": "  If you do not plan local deployment, apply for a MinerU API key. It is free; you only need to register and apply.",
        "zh": "  如果你不打算本地部署，请去申请 MinerU API key。它是免费的，只需要注册并申请即可。",
    },
    "docling_guide_title": {"en": "  Docling local deployment guide:", "zh": "  Docling 本地部署指引："},
    "mineru_guide_title": {"en": "  MinerU local deployment guide:", "zh": "  MinerU 本地部署指引："},
    "docling_guide_body": {
        "en": "    1. Official install docs: https://docling-project.github.io/docling/getting_started/installation/\n"
        "    2. Official CLI docs: https://docling-project.github.io/docling/reference/cli/\n"
        "    3. GitHub: https://github.com/docling-project/docling\n"
        "    4. Quick start: pip install docling\n"
        "    5. CPU-only Linux example: pip install docling --extra-index-url https://download.pytorch.org/whl/cpu\n"
        "    6. After install, verify with: docling --help",
        "zh": "    1. 官方安装文档：https://docling-project.github.io/docling/getting_started/installation/\n"
        "    2. 官方 CLI 文档：https://docling-project.github.io/docling/reference/cli/\n"
        "    3. GitHub：https://github.com/docling-project/docling\n"
        "    4. 快速开始：pip install docling\n"
        "    5. Linux CPU-only 示例：pip install docling --extra-index-url https://download.pytorch.org/whl/cpu\n"
        "    6. 安装后用 docling --help 验证",
    },
    "mineru_guide_body": {
        "en": "    1. Official quick start: https://opendatalab.github.io/MinerU/quick_start/\n"
        "    2. Official Docker deployment: https://opendatalab.github.io/MinerU/quick_start/docker_deployment/\n"
        "    3. Official usage docs: https://opendatalab.github.io/MinerU/usage/quick_usage/\n"
        "    4. GitHub: https://github.com/opendatalab/MinerU\n"
        "    5. For local models, MinerU docs describe `mineru-models-download` and `mineru -p <input> -o <output> --source local`\n"
        "    6. If Hugging Face is blocked, MinerU docs suggest switching model source to ModelScope",
        "zh": "    1. 官方快速开始：https://opendatalab.github.io/MinerU/quick_start/\n"
        "    2. 官方 Docker 部署：https://opendatalab.github.io/MinerU/quick_start/docker_deployment/\n"
        "    3. 官方使用文档：https://opendatalab.github.io/MinerU/usage/quick_usage/\n"
        "    4. GitHub：https://github.com/opendatalab/MinerU\n"
        "    5. 本地模型可参考官方文档中的 mineru-models-download，以及 mineru -p <input> -o <output> --source local\n"
        "    6. 如果 Hugging Face 不通，官方文档建议切换到 ModelScope 模型源",
    },
    "email_prompt": {
        "en": "  Contact email (free; used for the Crossref polite pool so API responses are faster).\n  Press Enter to skip.",
        "zh": "  联系邮箱（免费；用于 Crossref polite pool，配置后 API 更快）。\n  按 Enter 跳过。",
    },
    "embed_backend_prompt": {
        "en": "  Embedding backend:\n"
        "    1) Local model (default, may download model on first use)\n"
        "    2) Cloud API (OpenAI-compatible /v1/embeddings)\n"
        "    3) Disable embeddings (keyword search only)\n"
        "  Choose [1/2/3], press Enter for default.",
        "zh": "  Embedding 后端：\n"
        "    1) 本地模型（默认，首次使用可能下载模型）\n"
        "    2) 云端 API（OpenAI-compatible /v1/embeddings）\n"
        "    3) 禁用 embedding（仅关键词检索）\n"
        "  请选择 [1/2/3]，直接回车使用默认。",
    },
    "embed_model_prompt": {
        "en": "  Embedding model name (e.g. text-embedding-3-small). Press Enter for default.",
        "zh": "  Embedding 模型名（例如 text-embedding-3-small）。回车使用默认值。",
    },
    "embed_api_base_prompt": {
        "en": "  Embedding API base URL (e.g. https://api.openai.com/v1). Press Enter for default.",
        "zh": "  Embedding API base URL（例如 https://api.openai.com/v1）。回车使用默认值。",
    },
    "embed_api_key_prompt": {
        "en": "  Embedding API key. Press Enter to reuse llm.api_key / env fallback.",
        "zh": "  Embedding API key。回车可复用 llm.api_key / 环境变量回退。",
    },
    "embed_saved": {
        "en": "  Embedding backend settings saved.",
        "zh": "  Embedding 后端配置已保存。",
    },
    "key_saved": {"en": "  Saved to config.local.yaml.", "zh": "  已保存到 config.local.yaml。"},
    "no_keys": {
        "en": "  No keys configured. You can add them later in config.local.yaml.",
        "zh": "  未配置任何密钥。你可以稍后在 config.local.yaml 中添加。",
    },
    "config_unchanged": {
        "en": "  Added no new settings; keeping the existing config.local.yaml.",
        "zh": "  未新增任何配置；保留现有 config.local.yaml。",
    },
    "import_hint": {
        "en": "\nTip: To import papers from Zotero or Endnote, use:\n"
        "  scholaraio import-endnote <xml-or-ris-file>\n"
        "  scholaraio import-zotero --library-id <ID> --api-key <API_KEY> --collection <COLLECTION_KEY>\n"
        "  scholaraio import-zotero --local /path/to/zotero.sqlite\n",
        "zh": "\n提示：导入 Zotero 或 Endnote 文献，使用：\n"
        "  scholaraio import-endnote <xml 或 ris 文件>\n"
        "  scholaraio import-zotero --library-id <ID> --api-key <API_KEY> --collection <COLLECTION_KEY>\n"
        "  scholaraio import-zotero --local /path/to/zotero.sqlite\n",
    },
    "done": {
        "en": "\nSetup complete! Put papers in data/spool/inbox/ and run:\n  scholaraio pipeline ingest\n",
        "zh": "\n配置完成！将论文放入 data/spool/inbox/，然后运行：\n  scholaraio pipeline ingest\n",
    },
}

MINERU_TOKEN_URL = "https://mineru.net/apiManage/token"
MINERU_DOCS_URL = "https://opendatalab.github.io/MinerU/quick_start/"
MINERU_DOCKER_URL = "https://opendatalab.github.io/MinerU/quick_start/docker_deployment/"
DOCLING_INSTALL_URL = "https://docling-project.github.io/docling/getting_started/installation/"
DOCLING_CLI_URL = "https://docling-project.github.io/docling/reference/cli/"
HUGGINGFACE_URL = "https://huggingface.co"
DEFAULT_PDF_PARSER = "mineru"


def t(key: str, lang: Lang) -> str:
    """Translate a string key to the specified language."""
    return _S.get(key, {}).get(lang, key)


@dataclass
class PromptResult:
    text: str
    from_eof: bool = False


@dataclass
class MinerUStatus:
    ok: bool
    detail: str
    recommendable: bool
    cloud_only: bool
    cli_available: bool
    token_configured: bool


def _prompt_result(prompt: str) -> PromptResult:
    """Read one prompt and preserve whether EOF was hit."""
    try:
        return PromptResult(input(prompt).strip(), from_eof=False)
    except (EOFError, StopIteration):
        return PromptResult("", from_eof=True)


def _prompt_text(prompt: str) -> str:
    """Read one line of user input, treating EOF as empty input.

    This keeps setup usable when driven by agents or piped stdin where the
    input stream may end before all optional prompts are answered.
    """
    return _prompt_result(prompt).text


# ============================================================================
#  Dependency checking
# ============================================================================

# (import_name, pip_name)
_DEP_GROUPS: dict[str, list[tuple[str, str]]] = {
    "core": [("requests", "requests"), ("yaml", "pyyaml"), ("mineru_open_api", "mineru-open-api")],
    "embed": [("sentence_transformers", "sentence-transformers"), ("faiss", "faiss-cpu"), ("numpy", "numpy")],
    "topics": [("bertopic", "bertopic"), ("pandas", "pandas")],
    "import": [("endnote_utils", "endnote-utils"), ("pyzotero", "pyzotero")],
    "pdf": [("fitz", "pymupdf")],
    "office": [
        ("markitdown", "markitdown[docx,pptx,xlsx]"),
        ("docx", "python-docx"),
        ("pptx", "python-pptx"),
        ("openpyxl", "openpyxl"),
    ],
    "draw": [("mermaid", "mermaid-py"), ("cli_anything", "cli-anything-inkscape")],
}

_SPEC_ONLY_IMPORTS = {"sentence_transformers", "faiss", "numpy"}


@dataclass
class DepGroupStatus:
    """Dependency group check result."""

    name: str
    installed: bool
    missing: list[str] = field(default_factory=list)


def check_dep_group(group: str) -> DepGroupStatus:
    """Check if all packages in a dependency group are importable.

    Args:
        group: Dependency group name (core/embed/topics/import/pdf/office/draw).

    Returns:
        DepGroupStatus with installed flag and list of missing pip package names.
    """
    pairs = _DEP_GROUPS.get(group, [])
    missing = []
    for import_name, pip_name in pairs:
        try:
            if import_name in _SPEC_ONLY_IMPORTS:
                if importlib.util.find_spec(import_name) is None:
                    missing.append(pip_name)
                continue
            if import_name == "bertopic":
                from scholaraio.services.topics import _ensure_numba_cache_dir

                _ensure_numba_cache_dir()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                importlib.import_module(import_name)
        except Exception:
            missing.append(pip_name)
    return DepGroupStatus(name=group, installed=not missing, missing=missing)


# ============================================================================
#  Status checks
# ============================================================================


@dataclass
class CheckResult:
    """Single check result."""

    label: str
    ok: bool
    detail: str


@dataclass
class ParserChoice:
    """Result of parser selection in setup wizard."""

    parser: str
    needs_mineru_key: bool = False


def run_check(cfg: Config | None = None, lang: Lang = "zh") -> list[CheckResult]:
    """Run all environment checks.

    Args:
        cfg: Config instance. If None, loads default config.
        lang: Display language.

    Returns:
        List of CheckResult items.
    """
    if cfg is None:
        cfg = load_config()

    results: list[CheckResult] = []

    # Python version
    vi = sys.version_info
    ver_str = f"{vi.major}.{vi.minor}.{vi.micro}"
    results.append(
        CheckResult(
            label=t("python_ver", lang),
            ok=vi >= (3, 10),
            detail=ver_str + (" ✓" if vi >= (3, 10) else " (need ≥3.10)"),
        )
    )

    # Dependency groups
    for group, label_key in [
        ("core", "core_deps"),
        ("embed", "embed_deps"),
        ("topics", "topics_deps"),
        ("import", "import_deps"),
        ("pdf", "pdf_deps"),
        ("office", "office_deps"),
        ("draw", "draw_deps"),
    ]:
        status = check_dep_group(group)
        if status.installed:
            pkgs = ", ".join(p for _, p in _DEP_GROUPS[group])
            results.append(CheckResult(t(label_key, lang), True, pkgs))
        else:
            hint = f"pip install scholaraio[{group}]"
            results.append(
                CheckResult(
                    t(label_key, lang),
                    False,
                    f"{t('not_installed', lang)}: {', '.join(status.missing)}  → {hint}",
                )
            )

    graphviz_ok, graphviz_detail = _check_graphviz_dot(lang)
    results.append(CheckResult(t("graphviz_dot", lang), graphviz_ok, graphviz_detail))
    inkscape_ok, inkscape_detail = _check_inkscape(lang)
    results.append(CheckResult(t("inkscape", lang), inkscape_ok, inkscape_detail))

    # config.yaml
    root = cfg._root
    config_path = root / "config.yaml"
    results.append(
        CheckResult(
            t("config_yaml", lang),
            config_path.exists(),
            t("found", lang) if config_path.exists() else t("not_found", lang),
        )
    )

    # LLM API key
    key = cfg.resolved_api_key()
    if key:
        masked = key[:3] + "***" + key[-3:] if len(key) > 8 else "***"
        results.append(CheckResult(t("llm_key", lang), True, f"{t('configured', lang)} ({masked})"))
    else:
        results.append(CheckResult(t("llm_key", lang), False, t("not_set", lang)))

    # MinerU
    mineru_status = _detect_mineru(cfg, lang)
    results.append(CheckResult(t("mineru", lang), mineru_status.ok, mineru_status.detail))
    docling_ok, docling_detail = _check_docling(lang)
    results.append(CheckResult(t("docling", lang), docling_ok, docling_detail))
    hf_ok, hf_detail = _check_huggingface(lang)
    results.append(CheckResult(t("huggingface", lang), hf_ok, hf_detail))
    parser_name, reason = recommend_pdf_parser(mineru_status.recommendable, hf_ok, lang)
    results.append(CheckResult(t("parser_recommendation", lang), True, f"{parser_name}: {reason}"))

    # Contact email
    email = cfg.ingest.contact_email
    if email:
        results.append(CheckResult(t("contact_email", lang), True, email))
    else:
        results.append(CheckResult(t("contact_email", lang), False, t("not_set", lang)))

    s2_key = cfg.resolved_s2_api_key()
    if s2_key:
        masked = s2_key[:3] + "***" + s2_key[-3:] if len(s2_key) > 8 else "***"
        results.append(
            CheckResult(
                t("s2_key", lang),
                True,
                t("optional_s2_set", lang).format(masked=masked),
            )
        )
    else:
        results.append(
            CheckResult(
                t("s2_key", lang),
                True,
                t("optional_s2_unset", lang),
            )
        )

    zotero_key = cfg.resolved_zotero_api_key()
    if zotero_key:
        masked = zotero_key[:3] + "***" + zotero_key[-3:] if len(zotero_key) > 8 else "***"
        results.append(
            CheckResult(
                t("zotero_key", lang),
                True,
                t("optional_zotero_set", lang).format(masked=masked),
            )
        )
    else:
        results.append(
            CheckResult(
                t("zotero_key", lang),
                True,
                t("optional_zotero_unset", lang),
            )
        )

    paper2any_root = cfg.paper2any_root
    paper2any_mcp_url = cfg.paper2any.mcp_url or "http://127.0.0.1:8770/mcp"
    if paper2any_root.exists():
        paper2any_detail = f"optional: OpenDCAI/Paper2Any checkout found at {paper2any_root}; MCP {paper2any_mcp_url}"
    else:
        paper2any_detail = (
            f"optional: checkout not found at {paper2any_root}; "
            f"agent can place OpenDCAI/Paper2Any there and start `scholaraio paper2any mcp-serve`"
        )
    results.append(CheckResult(t("paper2any", lang), True, paper2any_detail))

    # Directories
    dirs_to_check = [
        cfg.papers_dir,
        cfg.inbox_dir,
        cfg.pending_dir,
        cfg.workspace_dir,
    ]
    missing_dirs = [str(d) for d in dirs_to_check if not d.exists()]
    if missing_dirs:
        results.append(
            CheckResult(
                t("directories", lang),
                False,
                f"{t('not_found', lang)}: {', '.join(missing_dirs)}",
            )
        )
    else:
        results.append(CheckResult(t("directories", lang), True, t("all_ok", lang)))

    # Papers count
    papers_dir = cfg.papers_dir
    count = 0
    if papers_dir.exists():
        count = sum(1 for d in papers_dir.iterdir() if d.is_dir() and (d / "meta.json").exists())
    results.append(CheckResult(t("papers_count", lang), True, str(count)))

    return results


def _check_mineru(cfg: Config, lang: Lang) -> tuple[bool, str]:
    """Check MinerU availability (local server or cloud CLI + token)."""
    status = _detect_mineru(cfg, lang)
    return status.ok, status.detail


def _detect_mineru(cfg: Config, lang: Lang) -> MinerUStatus:
    """Collect MinerU status for both diagnostics and recommendation logic."""
    cli_path = shutil.which("mineru-open-api")
    token_configured = bool(cfg.resolved_mineru_api_key())

    try:
        import requests as _req

        r = _req.get(cfg.ingest.mineru_endpoint, timeout=2)
        if r.status_code < 500:
            return MinerUStatus(
                ok=True,
                detail=f"local server @ {cfg.ingest.mineru_endpoint}",
                recommendable=True,
                cloud_only=False,
                cli_available=bool(cli_path),
                token_configured=token_configured,
            )
    except Exception:
        pass

    if token_configured and cli_path:
        return MinerUStatus(
            ok=True,
            detail=f"mineru-open-api @ {cli_path} + token " + t("configured", lang),
            recommendable=True,
            cloud_only=True,
            cli_available=True,
            token_configured=True,
        )

    if cli_path and not token_configured:
        if lang == "zh":
            detail = (
                f"检测到 mineru-open-api @ {cli_path}，建议优先使用 MinerU；"
                f"如需云端精准解析，请注册免费 token：{MINERU_TOKEN_URL}"
            )
        else:
            detail = (
                f"detected mineru-open-api @ {cli_path}; prefer MinerU. "
                f"Register the free token for cloud mode: {MINERU_TOKEN_URL}"
            )
        return MinerUStatus(
            ok=False,
            detail=detail,
            recommendable=True,
            cloud_only=True,
            cli_available=True,
            token_configured=False,
        )

    if token_configured and not cli_path:
        if lang == "zh":
            detail = (
                "已配置 MinerU token，但未安装 mineru-open-api"
                f" → pip install mineru-open-api | 本地部署: {MINERU_DOCS_URL} | Docker: {MINERU_DOCKER_URL}"
            )
        else:
            detail = (
                "MinerU token configured, but mineru-open-api is not installed"
                f" → pip install mineru-open-api | local docs: {MINERU_DOCS_URL} | Docker: {MINERU_DOCKER_URL}"
            )
        return MinerUStatus(
            ok=False,
            detail=detail,
            recommendable=True,
            cloud_only=True,
            cli_available=False,
            token_configured=True,
        )

    if lang == "zh":
        detail = (
            "未配置 MinerU token / CLI，且本地 MinerU 服务不可达"
            f" → 安装 CLI: pip install mineru-open-api | token: {MINERU_TOKEN_URL} | 本地部署: {MINERU_DOCS_URL} | Docker: {MINERU_DOCKER_URL}"
        )
    else:
        detail = (
            "MinerU token / CLI not configured and local MinerU service is unreachable"
            f" → install CLI: pip install mineru-open-api | token: {MINERU_TOKEN_URL} | local docs: {MINERU_DOCS_URL} | Docker: {MINERU_DOCKER_URL}"
        )
    return MinerUStatus(
        ok=False,
        detail=detail,
        recommendable=False,
        cloud_only=False,
        cli_available=False,
        token_configured=False,
    )


def _check_docling(lang: Lang) -> tuple[bool, str]:
    """Check whether Docling CLI is installed locally."""
    cmd = shutil.which("docling")
    if cmd:
        return True, cmd
    if lang == "zh":
        return False, f"未安装 → pip install docling | 安装文档: {DOCLING_INSTALL_URL} | CLI: {DOCLING_CLI_URL}"
    return False, f"not installed → pip install docling | install docs: {DOCLING_INSTALL_URL} | CLI: {DOCLING_CLI_URL}"


def _check_graphviz_dot(lang: Lang) -> tuple[bool, str]:
    """Check whether Graphviz dot is available for diagram SVG rendering."""
    cmd = shutil.which("dot")
    if cmd:
        return True, cmd
    if lang == "zh":
        return (
            False,
            "未安装 → sudo apt-get install graphviz | macOS: brew install graphviz | "
            "conda: conda install -c conda-forge graphviz | 验证: dot -V",
        )
    return (
        False,
        "not installed → sudo apt-get install graphviz | macOS: brew install graphviz | "
        "conda: conda install -c conda-forge graphviz | verify: dot -V",
    )


def _check_inkscape(lang: Lang) -> tuple[bool, str]:
    """Check whether Inkscape is available for Beamer SVG inclusion."""
    cmd = shutil.which("inkscape")
    if cmd:
        return True, cmd
    if lang == "zh":
        return (
            False,
            "未安装 → sudo apt-get install inkscape | macOS: brew install --cask inkscape | "
            "Beamer \\includesvg 需要 Inkscape 与 -shell-escape",
        )
    return (
        False,
        "not installed → sudo apt-get install inkscape | macOS: brew install --cask inkscape | "
        "Beamer \\includesvg requires Inkscape and -shell-escape",
    )


def _probe_url(url: str, timeout: int = 2) -> bool:
    """Return whether a URL is reachable with a lightweight GET request."""
    try:
        import requests as _req

        r = _req.get(url, timeout=timeout, allow_redirects=True)
        return r.status_code < 500
    except Exception:
        return False


def _check_huggingface(lang: Lang) -> tuple[bool, str]:
    """Check whether Hugging Face is reachable from current network."""
    ok = _probe_url(HUGGINGFACE_URL)
    if ok:
        return True, t("reachability_yes", lang)
    if lang == "zh":
        return False, "不可达 → Docling 或 Hugging Face 模型下载可能失败；可优先考虑 MinerU / ModelScope"
    return False, "unreachable → Docling or Hugging Face model downloads may fail; prefer MinerU / ModelScope"


def _wizard_mineru_available(cfg: Config) -> tuple[bool, bool]:
    """Detect MinerU availability for setup wizard auto recommendation.

    Returns:
        A tuple of ``(available, cloud_only)`` where ``cloud_only`` means the
        detected path requires a MinerU token instead of local deployment.
    """
    status = _detect_mineru(cfg, "zh")
    return status.recommendable, status.cloud_only


def recommend_pdf_parser(mineru_available: bool, huggingface_reachable: bool, lang: Lang) -> tuple[str, str]:
    """Recommend MinerU or Docling from availability signals.

    Args:
        mineru_available: Whether MinerU is usable in the current setup flow.
            This can come from an existing cloud key, a reachable local service,
            or a lightweight heuristic used by the setup wizard.
        huggingface_reachable: Whether Hugging Face is reachable from the
            current network.
        lang: Output language.

    Returns:
        A tuple of ``(recommended_parser, reason)``.
    """
    if mineru_available and not huggingface_reachable:
        return "MinerU", t("reason_mineru_only", lang)
    if huggingface_reachable and not mineru_available:
        return "Docling", t("reason_hf_only", lang)
    if mineru_available and huggingface_reachable:
        return "MinerU", t("reason_both", lang)
    return "Docling", t("reason_neither", lang)


def format_check_results(results: list[CheckResult]) -> str:
    """Format check results as a readable table.

    Args:
        results: List of CheckResult from run_check().

    Returns:
        Formatted string with [OK]/[--] prefixes.
    """
    lines = []
    max_label = max(len(r.label) for r in results) if results else 0
    for r in results:
        mark = "[OK]" if r.ok else "[--]"
        lines.append(f"  {mark} {r.label:<{max_label}}  {r.detail}")
    return "\n".join(lines)


# ============================================================================
#  Interactive wizard
# ============================================================================


def run_wizard(cfg: Config | None = None) -> None:
    """Interactive setup wizard (bilingual EN/ZH).

    Args:
        cfg: Config instance. If None, loads default config.
    """
    # Language selection
    print(_S["lang_prompt"]["en"])
    choice = _prompt_text("> ")
    lang: Lang = "zh" if choice == "2" else "en"

    if cfg is None:
        cfg = load_config()
    root = cfg._root

    print(t("welcome", lang))

    # Step 1: Dependencies
    print(t("step_deps", lang))
    _wizard_deps(lang)

    # Step 2: config.yaml
    print(f"\n{t('step_config', lang)}")
    _wizard_config(root, lang)

    # Reload config after generating config.yaml
    cfg = load_config()
    cfg.ensure_dirs()

    # Step 3: PDF parser
    print(f"\n{t('step_parser', lang)}")
    parser_choice = _wizard_parser(cfg, lang)

    # Step 4: API keys
    print(f"\n{t('step_keys_followup', lang)}")
    _wizard_keys(root, lang, parser_choice)

    # Import hint
    print(t("import_hint", lang))

    # Step 5: Verify
    print(f"{t('step_verify', lang)}")
    cfg = load_config()  # reload with new keys
    results = run_check(cfg, lang)
    print(format_check_results(results))

    print(t("done", lang))


def _wizard_deps(lang: Lang) -> None:
    """Check and optionally install missing dependency groups."""
    for group in ("core", "embed", "topics", "import", "pdf", "office", "draw"):
        status = check_dep_group(group)
        label_key = f"{group}_deps"
        if status.installed:
            pkgs = ", ".join(p for _, p in _DEP_GROUPS[group])
            print(f"  [OK] {t(label_key, lang)}: {pkgs}")
        else:
            msg = t("install_prompt", lang).format(group=group, pkgs=", ".join(status.missing))
            print(msg)
            answer = _prompt_result(t("yn", lang))
            ans = answer.text.lower()
            if answer.from_eof:
                print(t("skip", lang))
                continue
            if ans in ("", "y", "yes"):
                print(t("installing", lang).format(group=group))
                ret = subprocess.run(
                    [sys.executable, "-m", "pip", "install", f"scholaraio[{group}]"],
                    capture_output=True,
                    text=True,
                )
                if ret.returncode == 0:
                    print(t("install_ok", lang))
                else:
                    print(t("install_fail", lang).format(group=group))
                    if ret.stderr:
                        # show last 3 lines of error
                        err_lines = ret.stderr.strip().splitlines()[-3:]
                        for line in err_lines:
                            print(f"    {line}")
            else:
                print(t("skip", lang))


def _wizard_config(root: Path, lang: Lang) -> None:
    """Generate config.yaml if it doesn't exist."""
    config_path = root / "config.yaml"
    if config_path.exists():
        print(t("config_exists", lang))
        return

    config_path.write_text(_CONFIG_TEMPLATE, encoding="utf-8")
    print(t("config_created", lang))


def _wizard_parser(cfg: Config, lang: Lang) -> ParserChoice:
    """Interactively help the user choose between MinerU and Docling."""
    print(t("parser_choice_prompt", lang))
    choice = _prompt_text("  > ")
    if choice == "1":
        print(t("parser_choice_mineru", lang))
        print(t("mineru_cloud_note", lang))
        use_local = _prompt_yes_no(t("mineru_local_prompt", lang), lang, default=False)
        print(t("mineru_guide_title", lang))
        print(t("mineru_guide_body", lang))
        if use_local:
            return ParserChoice(parser="mineru", needs_mineru_key=False)
        return ParserChoice(parser="mineru", needs_mineru_key=True)
    if choice == "2":
        print(t("parser_choice_docling", lang))
        print(t("docling_guide_title", lang))
        print(t("docling_guide_body", lang))
        return ParserChoice(parser="docling", needs_mineru_key=False)

    print(t("parser_choice_auto", lang))
    mineru_status = _detect_mineru(cfg, lang)
    mineru_available = mineru_status.recommendable
    if mineru_status.token_configured and not mineru_status.cli_available:
        print(t("parser_choice_auto_token_without_cli", lang))
    elif mineru_status.cloud_only and mineru_status.token_configured:
        print(t("parser_choice_auto_configured_mineru", lang))
    elif mineru_status.cloud_only:
        print(t("parser_choice_auto_cli_without_token", lang))
    hf_ok = _probe_url(HUGGINGFACE_URL)
    print(f"    MinerU: {t('availability_yes', lang) if mineru_available else t('availability_no', lang)}")
    print(f"    Hugging Face: {t('reachability_yes', lang) if hf_ok else t('reachability_no', lang)}")

    parser_name, reason = recommend_pdf_parser(mineru_available, hf_ok, lang)
    if parser_name == "MinerU":
        print(t("parser_recommend_mineru", lang).format(reason=reason))
        print(t("parser_recommend_override", lang))
        print(t("mineru_cloud_note", lang))
        use_local = _prompt_yes_no(t("mineru_local_prompt", lang), lang, default=False)
        print(t("mineru_guide_title", lang))
        print(t("mineru_guide_body", lang))
        if use_local:
            return ParserChoice(parser="mineru", needs_mineru_key=False)
        return ParserChoice(parser="mineru", needs_mineru_key=True)

    print(t("parser_recommend_docling", lang).format(reason=reason))
    print(t("parser_recommend_override", lang))
    print(t("docling_guide_title", lang))
    print(t("docling_guide_body", lang))
    return ParserChoice(parser="docling", needs_mineru_key=False)


def _prompt_yes_no(prompt: str, lang: Lang, *, default: bool = True) -> bool:
    """Simple bilingual yes/no prompt."""
    suffix = " [Y/n] " if default else " [y/N] "
    answer = _prompt_result(prompt + suffix)
    ans = answer.text.lower()
    if not ans:
        return default
    return ans in ("y", "yes")


def _wizard_keys(root: Path, lang: Lang, parser_choice: ParserChoice | None = None) -> None:
    """Interactively configure API keys, write to config.local.yaml."""
    local_path = root / "config.local.yaml"
    local_data: dict = {}
    if local_path.exists():
        local_data_raw = yaml.safe_load(local_path.read_text(encoding="utf-8")) or {}
        if isinstance(local_data_raw, dict):
            local_data = local_data_raw
        else:
            local_data = {}

    changed = False
    ingest_local_raw = local_data.get("ingest")
    ingest_local: dict[str, object] = ingest_local_raw if isinstance(ingest_local_raw, dict) else {}
    if ingest_local_raw is not None and not isinstance(ingest_local_raw, dict):
        changed = True

    llm_local_raw = local_data.get("llm")
    llm_local: dict[str, object] = llm_local_raw if isinstance(llm_local_raw, dict) else {}
    if llm_local_raw is not None and not isinstance(llm_local_raw, dict):
        changed = True

    if parser_choice is not None:
        existing_parser = ingest_local.get("pdf_preferred_parser")
        desired_parser = parser_choice.parser
        if desired_parser != DEFAULT_PDF_PARSER:
            if existing_parser != desired_parser:
                ingest_local["pdf_preferred_parser"] = desired_parser
                changed = True
        elif "pdf_preferred_parser" in ingest_local:
            ingest_local.pop("pdf_preferred_parser", None)
            changed = True

    # LLM key
    print(t("llm_key_prompt", lang))
    key = _prompt_text("  > ")
    if key:
        llm_local["api_key"] = key
        changed = True

    # MinerU token
    if parser_choice is None or parser_choice.needs_mineru_key:
        print(t("mineru_key_prompt", lang))
        key = _prompt_text("  > ")
        if key:
            ingest_local["mineru_api_key"] = key
            changed = True

    # Contact email
    print(t("email_prompt", lang))
    email = _prompt_text("  > ")
    if email:
        ingest_local["contact_email"] = email
        changed = True

    if llm_local:
        local_data["llm"] = llm_local
    else:
        local_data.pop("llm", None)

    # Embedding backend
    print(t("embed_backend_prompt", lang))
    embed_choice = _prompt_text("  > ")

    embed_cfg_raw = local_data.get("embed")
    embed_cfg: dict[str, object] = embed_cfg_raw if isinstance(embed_cfg_raw, dict) else {}
    if embed_cfg_raw is not None and not isinstance(embed_cfg_raw, dict):
        changed = True
    local_data["embed"] = embed_cfg

    if not embed_choice:
        pass
    elif embed_choice == "1":
        if embed_cfg.get("provider") != "local":
            embed_cfg["provider"] = "local"
            changed = True
    elif embed_choice == "2":
        embed_cfg["provider"] = "openai-compat"

        print(t("embed_model_prompt", lang))
        model = _prompt_text("  > ")
        embed_cfg["model"] = model or "text-embedding-3-small"

        print(t("embed_api_base_prompt", lang))
        api_base = _prompt_text("  > ")
        if api_base:
            embed_cfg["api_base"] = api_base

        print(t("embed_api_key_prompt", lang))
        embed_key = _prompt_text("  > ")
        if embed_key:
            embed_cfg["api_key"] = embed_key

        changed = True
    elif embed_choice == "3":
        if embed_cfg.get("provider") != "none":
            embed_cfg["provider"] = "none"
            changed = True

    if embed_choice in ("1", "2", "3"):
        print(t("embed_saved", lang))

    if not embed_cfg:
        local_data.pop("embed", None)

    if ingest_local:
        local_data["ingest"] = ingest_local
    else:
        local_data.pop("ingest", None)

    if changed:
        if local_data:
            local_path.write_text(
                yaml.dump(local_data, allow_unicode=True, default_flow_style=False),
                encoding="utf-8",
            )
            print(t("key_saved", lang))
        else:
            if local_path.exists():
                local_path.unlink()
            print(t("no_keys", lang))
    else:
        if local_path.exists():
            print(t("config_unchanged", lang))
        else:
            print(t("no_keys", lang))


# ============================================================================
#  Config template
# ============================================================================

_CONFIG_TEMPLATE = """\
# ScholarAIO configuration
# Sensitive values (API keys) go in config.local.yaml (git-ignored).

paths:
  # papers_dir: data/libraries/papers
  state_root: data/state
  cache_root: data/cache
  runtime_root: data/runtime
  # index_db: data/state/search/index.db  # optional override; omitted by default so existing data/index.db can still be discovered

# LLM backend (multi-provider support)
# API key: set in config.local.yaml or env var
#   SCHOLARAIO_LLM_API_KEY (generic fallback), or provider-specific:
#   DEEPSEEK_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY / GOOGLE_API_KEY / GEMINI_API_KEY
llm:
  backend: openai-compat   # openai-compat | anthropic | google
  model: deepseek-chat
  base_url: https://api.deepseek.com
  timeout: 30
  timeout_toc: 120
  timeout_clean: 90

# Ingestion pipeline
ingest:
  extractor: robust         # auto | regex | llm | robust
  pdf_preferred_parser: mineru       # mineru | docling | pymupdf
  mineru_endpoint: http://localhost:8000
  mineru_cloud_url: https://mineru.net/api/v4  # mineru-open-api --base-url override for private deployments
  mineru_backend_local: pipeline      # local-only backend; keep default unless you self-host MinerU
  mineru_model_version_cloud: pipeline # mineru-open-api extract --model: pipeline | vlm
  mineru_lang: ch                     # keep ch for Chinese/mixed Chinese-English PDFs; switch to en for English-only PDFs
  mineru_parse_method: auto           # auto | txt | ocr; mineru-open-api only maps ocr -> --ocr
  mineru_enable_formula: true         # only effective for pipeline / vlm
  mineru_enable_table: true           # only effective for pipeline / vlm
  abstract_llm_mode: verify # off | fallback | verify

# Semantic embeddings (Qwen3-Embedding-0.6B, ~1.2 GB, auto-downloaded)
embed:
  provider: local          # local | openai-compat | none
  model: Qwen/Qwen3-Embedding-0.6B
  cache_dir: ~/.cache/modelscope/hub/models
  device: auto              # auto | cpu | cuda
  top_k: 10
  source: modelscope        # modelscope | huggingface
  hf_endpoint: null         # optional HuggingFace mirror endpoint
  api_base: null            # OpenAI-compatible endpoint, e.g. https://api.openai.com/v1
  api_key: null             # -> config.local.yaml or env SCHOLARAIO_EMBED_API_KEY
  api_timeout: 30
  batch_size: 64
  max_retries: 3

search:
  top_k: 20

logging:
  level: INFO
  file: data/scholaraio.log
  max_bytes: 10000000
  backup_count: 3
  # metrics_db: data/state/metrics/metrics.db  # optional override

topics:
  min_topic_size: 5
  nr_topics: 0              # 0=auto, -1=no merging, positive=target count
  # model_dir: data/state/topics  # optional override

translate:
  auto_translate: false
  target_lang: zh
  chunk_size: 4000
  concurrency: 20

zotero:
  library_type: user
"""
