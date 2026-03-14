"""
config.py — ScholarAIO 配置加载
================================

优先级（从高到低）：
  1. config.local.yaml（不进 git，存 API key 等敏感信息）
  2. config.yaml（主配置）
  3. 代码默认值

查找 config.yaml 的路径顺序：
  1. 显式传入的 config_path
  2. 环境变量 SCHOLARAIO_CONFIG
  3. 当前工作目录逐级向上查找
  4. ~/.scholaraio/config.yaml（全局配置，插件模式使用）

LLM API key 查找顺序：
  1. config.local.yaml 中的 llm.api_key
  2. 环境变量 SCHOLARAIO_LLM_API_KEY
  3. 按 llm.backend 查找对应厂商环境变量，例如：
       - openai-compat: DEEPSEEK_API_KEY → OPENAI_API_KEY
       - anthropic: ANTHROPIC_API_KEY
       - google: GOOGLE_API_KEY → GEMINI_API_KEY
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# ============================================================================
#  Config dataclasses
# ============================================================================


@dataclass
class PathsConfig:
    """文件路径配置。

    Attributes:
        papers_dir: 已入库论文目录（相对于项目根目录）。
        index_db: SQLite 索引数据库路径（相对于项目根目录）。
    """

    papers_dir: str = "data/papers"
    index_db: str = "data/index.db"


@dataclass
class LLMConfig:
    """LLM 后端配置（支持多厂商协议）。

    Attributes:
        backend: LLM 协议类型。支持:
            - ``"openai-compat"`` — OpenAI 兼容协议（DeepSeek / OpenAI / vLLM / Ollama 等）
            - ``"anthropic"`` — Anthropic Messages API（Claude 系列）
            - ``"google"`` — Google Gemini API
        model: 模型名称。
        base_url: API 基础 URL（不含 ``/v1/...`` 后缀）。
        api_key: API 密钥，建议放 config.local.yaml 或环境变量。
        timeout: 普通 LLM 调用超时（秒）。
        timeout_toc: enrich-toc 调用超时（秒），标题列表较长。
        timeout_clean: validate_and_clean 调用超时（秒），结论全文较长。
        concurrency: enrich pipeline 最大并发 LLM 调用数。
    """

    backend: str = "openai-compat"
    model: str = "deepseek-chat"
    base_url: str = "https://api.deepseek.com"
    api_key: str = ""
    timeout: int = 30
    timeout_toc: int = 120
    timeout_clean: int = 90
    concurrency: int = 32


@dataclass
class SearchConfig:
    """FTS5 全文检索配置。

    Attributes:
        top_k: ``scholaraio search`` 默认返回条数。
    """

    top_k: int = 20


@dataclass
class EmbedConfig:
    """语义向量嵌入配置。

    Attributes:
        model: Sentence Transformer 模型名称或 HuggingFace ID。
        cache_dir: 本地模型缓存目录。
        device: 推理设备，``"auto"`` | ``"cpu"`` | ``"cuda"``。
        top_k: ``scholaraio vsearch`` 默认返回条数。
        source: 模型下载源，``"modelscope"`` | ``"huggingface"``。
    """

    model: str = "Qwen/Qwen3-Embedding-0.6B"
    cache_dir: str = "~/.cache/modelscope/hub/models"
    device: str = "auto"
    top_k: int = 10
    source: str = "modelscope"


@dataclass
class TopicsConfig:
    """BERTopic 主题建模配置。

    Attributes:
        min_topic_size: HDBSCAN 最小聚类大小。
        nr_topics: 目标主题数，``0`` 表示 ``"auto"``。
        model_dir: 主题模型保存目录（相对于项目根目录）。
    """

    min_topic_size: int = 5
    nr_topics: int = 0  # 0 means "auto"
    model_dir: str = "data/topic_model"


@dataclass
class LogConfig:
    """日志与指标配置。

    Attributes:
        level: 根日志级别，``"DEBUG"`` | ``"INFO"`` | ``"WARNING"``。
        file: 日志文件路径（相对于项目根目录）。
        max_bytes: 单个日志文件最大字节数，超出则轮转。
        backup_count: 轮转保留的旧日志文件数。
        metrics_db: 指标数据库路径（相对于项目根目录）。
    """

    level: str = "INFO"
    file: str = "data/scholaraio.log"
    max_bytes: int = 10_000_000  # 10 MB
    backup_count: int = 3
    metrics_db: str = "data/metrics.db"


@dataclass
class IngestConfig:
    """数据入库管道配置。

    Attributes:
        extractor: 元数据提取模式，``"regex"`` | ``"auto"`` | ``"llm"`` | ``"robust"``。
        mineru_endpoint: MinerU 本地 API 地址。
        mineru_cloud_url: MinerU 云 API 基础 URL。
        mineru_api_key: MinerU 云 API 密钥，建议放 config.local.yaml 或环境变量。
        abstract_llm_mode: abstract 提取时的 LLM 介入模式：

            - ``"off"``：纯正则，不使用 LLM。
            - ``"fallback"``：正则失败时才调用 LLM 提取。
            - ``"verify"``：正则成功后仍由 LLM 校验/修正，失败时 LLM 直接提取。

        contact_email: Crossref polite pool 联系邮箱（User-Agent），建议放 config.local.yaml。
        chunk_page_limit: 超长 PDF 自动切分的页数阈值。超过此值的 PDF 在 MinerU
            转换前自动拆分为多个短 PDF，转换后合并为单个 Markdown。
        mineru_batch_size: MinerU 云 API 每批提交文件数上限，默认 20。
    """

    extractor: str = "robust"  # regex | auto | llm | robust
    mineru_endpoint: str = "http://localhost:8000"
    mineru_cloud_url: str = "https://mineru.net/api/v4"
    mineru_api_key: str = ""
    abstract_llm_mode: str = "verify"  # off | fallback | verify
    contact_email: str = ""
    chunk_page_limit: int = 100  # auto-split PDFs exceeding this page count
    mineru_batch_size: int = 20  # cloud batch size per request


@dataclass
class NotifyConfig:
    """论文推送通知全局默认配置。

    单个工作区的 notify.json 可覆盖这里的所有字段。

    Attributes:
        default_schedule: 默认 Cron 调度计划（5 字段）。
        default_threshold: 默认语义相关性阈值（0-1）。
        default_max_papers: 每期默认最多收录论文数。
        default_sources: 默认论文来源列表。
    """

    default_schedule: str = "0 8 * * 1"
    default_threshold: float = 0.65
    default_max_papers: int = 10
    default_sources: list[str] = field(default_factory=lambda: ["openalex"])


@dataclass
class ZoteroConfig:
    """Zotero 集成配置。

    Attributes:
        api_key: Zotero Web API 密钥。
        library_id: Zotero 用户/群组 library ID。
        library_type: Library 类型，``"user"`` 或 ``"group"``。
    """

    api_key: str = ""
    library_id: str = ""
    library_type: str = "user"


@dataclass
class Config:
    """ScholarAIO 全局配置，由 :func:`load_config` 构建。

    Attributes:
        paths: 文件路径配置。
        llm: LLM 后端配置。
        ingest: 数据入库配置。
        embed: 语义向量配置。
        search: 全文检索配置。
        topics: BERTopic 主题建模配置。
        log: 日志与指标配置。
        zotero: Zotero 集成配置。
        notify: 论文推送通知全局默认配置。
    """

    paths: PathsConfig = field(default_factory=PathsConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    ingest: IngestConfig = field(default_factory=IngestConfig)
    embed: EmbedConfig = field(default_factory=EmbedConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    topics: TopicsConfig = field(default_factory=TopicsConfig)
    log: LogConfig = field(default_factory=LogConfig)
    zotero: ZoteroConfig = field(default_factory=ZoteroConfig)
    notify: NotifyConfig = field(default_factory=NotifyConfig)

    # Root directory of the config file (used to resolve relative paths)
    _root: Path = field(default_factory=Path.cwd, repr=False, compare=False)

    @property
    def papers_dir(self) -> Path:
        """已入库论文目录的绝对路径。"""
        return (self._root / self.paths.papers_dir).resolve()

    @property
    def index_db(self) -> Path:
        """SQLite 索引数据库的绝对路径。"""
        return (self._root / self.paths.index_db).resolve()

    @property
    def log_file(self) -> Path:
        """日志文件的绝对路径。"""
        return (self._root / self.log.file).resolve()

    @property
    def metrics_db_path(self) -> Path:
        """指标数据库的绝对路径。"""
        return (self._root / self.log.metrics_db).resolve()

    @property
    def topics_model_dir(self) -> Path:
        """BERTopic 模型保存目录的绝对路径。"""
        return (self._root / self.topics.model_dir).resolve()

    def ensure_dirs(self) -> None:
        """创建运行所需的目录（data/papers, data/inbox, data/pending, workspace 等）。"""
        for d in (
            self.papers_dir,
            self._root / "data" / "inbox",
            self._root / "data" / "inbox-thesis",
            self._root / "data" / "inbox-doc",
            self._root / "data" / "pending",
            self._root / "workspace",
            self.log_file.parent,
            self.metrics_db_path.parent,
        ):
            d.mkdir(parents=True, exist_ok=True)

    def resolved_api_key(self) -> str:
        """按优先级查找 LLM API key。

        查找顺序:
        1. config.local.yaml ``llm.api_key``
        2. 环境变量 ``SCHOLARAIO_LLM_API_KEY``
        3. 按 backend 查找对应厂商环境变量:
           - openai-compat: ``DEEPSEEK_API_KEY`` → ``OPENAI_API_KEY``
           - anthropic: ``ANTHROPIC_API_KEY``
           - google: ``GOOGLE_API_KEY`` → ``GEMINI_API_KEY``

        Returns:
            API key 字符串，未找到则返回空字符串。
        """
        if self.llm.api_key:
            return self.llm.api_key
        generic = os.environ.get("SCHOLARAIO_LLM_API_KEY", "")
        if generic:
            return generic
        backend_env_map: dict[str, tuple[str, ...]] = {
            "openai-compat": ("DEEPSEEK_API_KEY", "OPENAI_API_KEY"),
            "anthropic": ("ANTHROPIC_API_KEY",),
            "google": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
        }
        for env_var in backend_env_map.get(self.llm.backend, ("DEEPSEEK_API_KEY", "OPENAI_API_KEY")):
            val = os.environ.get(env_var, "")
            if val:
                return val
        return ""

    def resolved_zotero_api_key(self) -> str:
        """按优先级查找 Zotero API key。

        查找顺序: config ``zotero.api_key`` → 环境变量 ``ZOTERO_API_KEY``。

        Returns:
            API key 字符串，未找到则返回空字符串。
        """
        if self.zotero.api_key:
            return self.zotero.api_key
        return os.environ.get("ZOTERO_API_KEY", "")

    def resolved_zotero_library_id(self) -> str:
        """按优先级查找 Zotero library ID。

        查找顺序: config ``zotero.library_id`` → 环境变量 ``ZOTERO_LIBRARY_ID``。

        Returns:
            Library ID 字符串，未找到则返回空字符串。
        """
        if self.zotero.library_id:
            return self.zotero.library_id
        return os.environ.get("ZOTERO_LIBRARY_ID", "")

    def resolved_mineru_api_key(self) -> str:
        """按优先级查找 MinerU 云 API key。

        查找顺序: config ``ingest.mineru_api_key`` → 环境变量 ``MINERU_API_KEY``。

        Returns:
            API key 字符串，未找到则返回空字符串。
        """
        if self.ingest.mineru_api_key:
            return self.ingest.mineru_api_key
        return os.environ.get("MINERU_API_KEY", "")


# ============================================================================
#  Loading
# ============================================================================


def load_config(config_path: Path | None = None) -> Config:
    """加载并合并 YAML 配置文件。

    合并策略: ``config.yaml`` 为基础，``config.local.yaml`` 覆盖同名字段。

    Args:
        config_path: 配置文件路径。为 ``None`` 时依次查找环境变量
            ``SCHOLARAIO_CONFIG``、当前目录向上最多 6 级的 ``config.yaml``。

    Returns:
        合并后的 :class:`Config` 实例。
    """
    if config_path is None:
        env_path = os.environ.get("SCHOLARAIO_CONFIG")
        if env_path:
            config_path = Path(env_path)
        else:
            config_path = _find_config_file()

    data: dict = {}
    root = Path.cwd()

    if config_path and config_path.exists():
        root = config_path.parent
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        # config.local.yaml overrides config.yaml
        local_path = config_path.parent / "config.local.yaml"
        if local_path.exists():
            with open(local_path, encoding="utf-8") as f:
                local_data = yaml.safe_load(f) or {}
            data = _deep_merge(data, local_data)

    return _build_config(data, root)


def _find_config_file() -> Path | None:
    """Walk up from cwd to find config.yaml, then try ~/.scholaraio/."""
    # 1. Walk up from cwd (max 6 levels)
    current = Path.cwd()
    for _ in range(6):
        candidate = current / "config.yaml"
        if candidate.exists():
            return candidate
        parent = current.parent
        if parent == current:
            break
        current = parent
    # 2. Global fallback: ~/.scholaraio/config.yaml (plugin mode)
    try:
        global_cfg = Path.home() / ".scholaraio" / "config.yaml"
        if global_cfg.exists():
            return global_cfg
    except (RuntimeError, OSError):
        pass
    return None


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base (override wins)."""
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def _coerce_str_list(value: object) -> list[str]:
    """Coerce a YAML value to list[str]: wrap bare string, cast list items."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    return []


def _build_config(data: dict, root: Path) -> Config:
    """Build Config dataclass from raw dict."""
    paths_data = data.get("paths", {}) or {}
    llm_data = data.get("llm", {}) or {}
    ingest_data = data.get("ingest", {}) or {}

    paths = PathsConfig(
        papers_dir=paths_data.get("papers_dir", "data/papers"),
        index_db=paths_data.get("index_db", "data/index.db"),
    )

    llm = LLMConfig(
        backend=llm_data.get("backend", "openai-compat"),
        model=llm_data.get("model", "deepseek-chat"),
        base_url=llm_data.get("base_url", "https://api.deepseek.com"),
        api_key=llm_data.get("api_key") or "",
        timeout=int(llm_data.get("timeout", 30)),
        timeout_toc=int(llm_data.get("timeout_toc", 120)),
        timeout_clean=int(llm_data.get("timeout_clean", 90)),
        concurrency=max(1, int(llm_data.get("concurrency", 32))),
    )

    ingest = IngestConfig(
        extractor=ingest_data.get("extractor", "robust"),
        mineru_endpoint=ingest_data.get("mineru_endpoint", "http://localhost:8000"),
        mineru_cloud_url=ingest_data.get("mineru_cloud_url", "https://mineru.net/api/v4"),
        mineru_api_key=ingest_data.get("mineru_api_key") or "",
        abstract_llm_mode=ingest_data.get("abstract_llm_mode", "verify"),
        contact_email=ingest_data.get("contact_email") or "",
        mineru_batch_size=int(ingest_data.get("mineru_batch_size") or 20),
        chunk_page_limit=int(ingest_data.get("chunk_page_limit") or 100),
    )

    embed_data = data.get("embed", {}) or {}
    embed = EmbedConfig(
        model=embed_data.get("model", "Qwen/Qwen3-Embedding-0.6B"),
        cache_dir=embed_data.get("cache_dir", "~/.cache/modelscope/hub/models"),
        device=embed_data.get("device", "auto"),
        top_k=int(embed_data.get("top_k", 10)),
        source=embed_data.get("source", "modelscope"),
    )

    search_data = data.get("search", {}) or {}
    search = SearchConfig(
        top_k=int(search_data.get("top_k", 20)),
    )

    topics_data = data.get("topics", {}) or {}
    topics = TopicsConfig(
        min_topic_size=int(topics_data.get("min_topic_size", 5)),
        nr_topics=int(topics_data.get("nr_topics", 0)),
        model_dir=topics_data.get("model_dir", "data/topic_model"),
    )

    log_data = data.get("logging", {}) or {}
    log = LogConfig(
        level=log_data.get("level", "INFO"),
        file=log_data.get("file", "data/scholaraio.log"),
        max_bytes=int(log_data.get("max_bytes", 10_000_000)),
        backup_count=int(log_data.get("backup_count", 3)),
        metrics_db=log_data.get("metrics_db", "data/metrics.db"),
    )

    zotero_data = data.get("zotero", {}) or {}
    zotero = ZoteroConfig(
        api_key=zotero_data.get("api_key") or "",
        library_id=str(zotero_data.get("library_id") or ""),
        library_type=zotero_data.get("library_type", "user"),
    )

    notify_data = data.get("notify", {}) or {}
    notify = NotifyConfig(
        default_schedule=notify_data.get("default_schedule", "0 8 * * 1"),
        default_threshold=float(notify_data.get("default_threshold", 0.65)),
        default_max_papers=int(notify_data.get("default_max_papers", 10)),
        default_sources=_coerce_str_list(notify_data.get("default_sources", ["openalex"])),
    )

    return Config(
        paths=paths,
        llm=llm,
        ingest=ingest,
        embed=embed,
        search=search,
        topics=topics,
        log=log,
        zotero=zotero,
        notify=notify,
        _root=root,
    )
