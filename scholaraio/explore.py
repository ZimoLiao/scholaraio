"""
explore.py — 学术探索
======================

从 OpenAlex 批量拉取论文（支持 ISSN / concept / author / institution /
keyword 等多维度 filter），本地嵌入 + FAISS 语义搜索 + FTS5 关键词检索 +
RRF 融合检索。主题建模、可视化、查询复用 ``topics.py``（通过 ``papers_map``
参数）。数据存储在 ``data/explore/<name>/``，与主库完全隔离。

用法::

    from scholaraio.explore import fetch_explore, build_explore_vectors, build_explore_topics
    fetch_explore("jfm", issn="0022-1120")
    fetch_explore("turbulence", concept="C62520636", year_range="2020-2025")
    build_explore_vectors("jfm")
    build_explore_topics("jfm")
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import requests

from scholaraio.log import ui

_log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from scholaraio.config import Config

# ============================================================================
#  Config / paths
# ============================================================================

_DEFAULT_EXPLORE_DIR = Path("data/explore")


def _explore_dir(name: str, cfg: Config | None = None) -> Path:
    if cfg is not None:
        return cfg._root / "data" / "explore" / name
    return _DEFAULT_EXPLORE_DIR / name


def _papers_path(name: str, cfg: Config | None = None) -> Path:
    return _explore_dir(name, cfg) / "papers.jsonl"


def _db_path(name: str, cfg: Config | None = None) -> Path:
    return _explore_dir(name, cfg) / "explore.db"


def explore_db_path(name: str, cfg: Config | None = None) -> Path:
    """Return the SQLite DB path for an explore library.

    Args:
        name: Explore library name.
        cfg: Optional Config instance; resolved from environment if omitted.

    Returns:
        Path to ``explore.db`` inside the library directory.
    """
    return _db_path(name, cfg)


def validate_explore_name(name: str) -> bool:
    """Return True if *name* is a safe, non-traversing library identifier.

    Rejects empty strings, absolute paths, and names that contain path
    separators or ``..`` components so that callers cannot escape the
    ``data/explore/`` directory.

    Args:
        name: Candidate explore library name supplied by the user.

    Returns:
        ``True`` when the name is safe to use in path construction.
    """
    if not name:
        return False
    import os

    # Reject absolute paths and names that contain any path separator.
    if os.path.isabs(name):
        return False
    if "/" in name or "\\" in name:
        return False
    # Reject any name containing "..".
    return ".." not in name


def _meta_path(name: str, cfg: Config | None = None) -> Path:
    return _explore_dir(name, cfg) / "meta.json"


# ============================================================================
#  Fetch from OpenAlex
# ============================================================================


def _is_boilerplate(abstract: str) -> bool:
    """Detect publisher boilerplate instead of real abstract."""
    low = abstract.lower()
    return "abstract is not available" in low or "preview has been provided" in low or "access link" in low


_OA_WORKS = "https://api.openalex.org/works"
_PER_PAGE = 200


def _reconstruct_abstract(inverted_index: dict | None) -> str:
    """Reconstruct abstract from OpenAlex inverted index format."""
    if not inverted_index:
        return ""
    word_positions: list[tuple[int, str]] = []
    for word, positions in inverted_index.items():
        for pos in positions:
            word_positions.append((pos, word))
    word_positions.sort()
    return " ".join(w for _, w in word_positions)


def _build_filter(
    *,
    issn: str | None = None,
    concept: str | None = None,
    topic: str | None = None,
    author: str | None = None,
    institution: str | None = None,
    source_type: str | None = None,
    year_range: str | None = None,
    min_citations: int | None = None,
    oa_type: str | None = None,
) -> tuple[str, dict]:
    """Build an OpenAlex filter string and extra query params.

    Returns:
        (filter_string, extra_params) — extra_params may contain ``search``.
    """
    parts: list[str] = []
    extra: dict[str, str] = {}

    if issn:
        parts.append(f"primary_location.source.issn:{issn}")
    if concept:
        parts.append(f"concepts.id:{concept}")
    if topic:
        parts.append(f"topics.id:{topic}")
    if author:
        parts.append(f"authorships.author.id:{author}")
    if institution:
        parts.append(f"authorships.institutions.id:{institution}")
    if source_type:
        parts.append(f"primary_location.source.type:{source_type}")
    if year_range:
        parts.append(f"publication_year:{year_range}")
    # OpenAlex cited_by_count filter expects a meaningful lower bound.
    # Non-positive values are treated as "no filter" to avoid invalid/odd expressions.
    if min_citations is not None and min_citations > 0:
        parts.append(f"cited_by_count:>{min_citations - 1}")
    if oa_type:
        parts.append(f"type:{oa_type}")

    return ",".join(parts), extra


def _oa_api_key() -> str:
    try:
        from scholaraio.config import load_config

        return load_config().openalex.api_key or ""
    except Exception:
        return ""


def _fetch_page(
    filt: str,
    extra_params: dict | None = None,
    *,
    cursor: str = "*",
    keyword: str | None = None,
) -> tuple[list[dict], str | None]:
    """Fetch one page of results from OpenAlex.

    Args:
        filt: Pre-built OpenAlex filter string.
        extra_params: Additional query params (e.g. search).
        cursor: Cursor for pagination.
        keyword: Free-text search keyword (OpenAlex ``search`` param).
    """
    params: dict[str, str | int] = {
        "per_page": _PER_PAGE,
        "cursor": cursor,
        "select": "id,title,publication_year,doi,authorships,abstract_inverted_index,"
        "primary_location,cited_by_count,type",
        "sort": "publication_year:asc",
    }
    if filt:
        params["filter"] = filt
    if keyword:
        params["search"] = keyword
    if extra_params:
        params.update(extra_params)
    api_key = _oa_api_key()
    if api_key:
        params["api_key"] = api_key
    # Retry with exponential backoff for transient errors
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            resp = requests.get(_OA_WORKS, params=params, timeout=30, proxies={"http": None, "https": None})
            if resp.status_code == 429:
                wait = 2**attempt
                _log.warning("OpenAlex 429 rate limit, retrying in %ds", wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            break
        except (requests.ConnectionError, requests.Timeout) as e:
            last_exc = e
            wait = 2**attempt
            _log.warning("OpenAlex request failed (attempt %d/3): %s, retrying in %ds", attempt + 1, e, wait)
            time.sleep(wait)
    else:
        if last_exc:
            raise last_exc
        raise requests.HTTPError("OpenAlex API returned 429 after 3 retries")

    papers = []
    for item in data.get("results", []):
        doi_raw = item.get("doi") or ""
        doi = doi_raw.replace("https://doi.org/", "") if doi_raw else ""

        authors = []
        for a in item.get("authorships") or []:
            name = (a.get("author") or {}).get("display_name")
            if name:
                authors.append(name)

        abstract = _reconstruct_abstract(item.get("abstract_inverted_index"))

        # Strip HTML tags from title (OpenAlex includes <b>, <scp>, <i>, etc.)
        raw_title = item.get("title") or ""
        clean_title = re.sub(r"<[^>]+>", "", raw_title)

        papers.append(
            {
                "openalex_id": item.get("id", ""),
                "doi": doi,
                "title": clean_title,
                "abstract": abstract,
                "authors": authors,
                "year": item.get("publication_year"),
                "cited_by_count": item.get("cited_by_count", 0),
                "type": item.get("type", ""),
            }
        )

    next_cursor = data.get("meta", {}).get("next_cursor")
    return papers, next_cursor


def fetch_explore(
    name: str,
    *,
    issn: str | None = None,
    concept: str | None = None,
    topic: str | None = None,
    author: str | None = None,
    institution: str | None = None,
    keyword: str | None = None,
    source_type: str | None = None,
    year_range: str | None = None,
    min_citations: int | None = None,
    oa_type: str | None = None,
    incremental: bool = False,
    limit: int | None = None,
    cfg: Config | None = None,
) -> int:
    """从 OpenAlex 批量拉取论文（支持多维度 filter）。

    使用 cursor-based 分页遍历符合条件的所有论文，
    提取 title、abstract、authors 等字段，写入 JSONL 文件。

    Args:
        name: 探索库名称（如 ``"jfm"``），用作目录名。
        issn: 期刊 ISSN 过滤（如 ``"0022-1120"``）。
        concept: OpenAlex concept ID（如 ``"C62520636"`` = Turbulence）。
        topic: OpenAlex topic ID。
        author: OpenAlex author ID。
        institution: OpenAlex institution ID。
        keyword: 标题/摘要关键词搜索。
        source_type: 来源类型过滤（journal / conference / repository）。
        year_range: 年份过滤（如 ``"2020-2025"``）。
        min_citations: 最小引用量过滤。
        oa_type: OpenAlex work type 过滤（article / review 等）。
        incremental: 为 ``True`` 时追加到现有 JSONL，基于 DOI 去重。
        limit: 最多拉取的论文数量上限（``None`` 表示无限制）。
        cfg: 可选的全局配置。

    Returns:
        本次新拉取的论文数量。
    """
    if limit is not None and limit <= 0:
        raise ValueError(f"limit 必须为正整数，当前为: {limit}")

    out_dir = _explore_dir(name, cfg)
    out_dir.mkdir(parents=True, exist_ok=True)
    papers_file = _papers_path(name, cfg)
    meta_file = _meta_path(name, cfg)

    filt, extra_params = _build_filter(
        issn=issn,
        concept=concept,
        topic=topic,
        author=author,
        institution=institution,
        source_type=source_type,
        year_range=year_range,
        min_citations=min_citations,
        oa_type=oa_type,
    )
    if not filt and not keyword:
        raise ValueError("至少需要一个过滤条件（issn / concept / author / keyword 等）")

    # Incremental mode: load existing IDs (DOI or openalex_id) to skip duplicates
    existing_pids: set[str] = set()
    if incremental and papers_file.exists():
        for p in iter_papers(name, cfg):
            pid = p.get("doi", "").lower() or p.get("openalex_id", "")
            if pid:
                existing_pids.add(pid)
        _log.info("incremental mode: %d existing papers loaded", len(existing_pids))

    from scholaraio.metrics import timer

    total = 0
    cursor: str | None = "*"

    with timer("explore.fetch", "api") as t:
        if incremental and papers_file.exists():
            f_handle = open(papers_file, "a", encoding="utf-8")
        else:
            tmp_file = papers_file.with_suffix(".jsonl.tmp")
            f_handle = open(tmp_file, "w", encoding="utf-8")

        try:
            page = 0
            while cursor:
                if limit is not None and total >= limit:
                    break
                page += 1
                papers, cursor = _fetch_page(
                    filt,
                    extra_params,
                    cursor=cursor,
                    keyword=keyword,
                )
                if not papers:
                    break
                written = 0
                for p in papers:
                    if limit is not None and total >= limit:
                        break
                    # Skip duplicates in incremental mode (by DOI or openalex_id)
                    if incremental:
                        pid = p.get("doi", "").lower() or p.get("openalex_id", "")
                        if pid and pid in existing_pids:
                            continue
                    f_handle.write(json.dumps(p, ensure_ascii=False) + "\n")
                    total += 1
                    written += 1
                    if incremental:
                        pid = p.get("doi", "").lower() or p.get("openalex_id", "")
                        if pid:
                            existing_pids.add(pid)
                _log.info(
                    "page %d: fetched=%d, written=%d (total %d, %.0fs)",
                    page,
                    len(papers),
                    written,
                    total,
                    t.elapsed,
                )
        finally:
            f_handle.close()

        if not incremental or not papers_file.exists():
            tmp_file.replace(papers_file)  # type: ignore[possibly-undefined]

    # Build query record for meta.json
    query_params: dict[str, str | int | None] = {}
    for key, val in [
        ("issn", issn),
        ("concept", concept),
        ("topic", topic),
        ("author", author),
        ("institution", institution),
        ("keyword", keyword),
        ("source_type", source_type),
        ("year_range", year_range),
        ("min_citations", min_citations),
        ("oa_type", oa_type),
    ]:
        if val is not None:
            query_params[key] = val

    # Update count: for incremental mode, add to existing count
    total_count = total
    if incremental and meta_file.exists():
        old_meta = json.loads(meta_file.read_text("utf-8"))
        total_count = old_meta.get("count", 0) + total

    meta = {
        "name": name,
        "source": "openalex",
        "query": query_params,
        # Keep "issn" at top level for backward compatibility
        "issn": issn or "",
        "year_range": year_range,
        "count": total_count,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "elapsed_seconds": round(t.elapsed, 1),
    }
    meta_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    ui(f"Done: {total} {'new ' if incremental else ''}papers, {t.elapsed:.0f}s -> {papers_file}")
    return total


def fetch_journal(
    name: str,
    issn: str,
    *,
    year_range: str | None = None,
    cfg: Config | None = None,
) -> int:
    """从 OpenAlex 拉取期刊全量论文（向后兼容别名）。

    等价于 ``fetch_explore(name, issn=issn, year_range=year_range, cfg=cfg)``。
    """
    return fetch_explore(name, issn=issn, year_range=year_range, cfg=cfg)


# ============================================================================
#  Load papers from JSONL
# ============================================================================


def iter_papers(name: str, cfg: Config | None = None) -> Iterator[dict]:
    """逐行读取 JSONL，yield 论文字典。"""
    path = _papers_path(name, cfg)
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def count_papers(name: str, cfg: Config | None = None) -> int:
    """返回探索库中的论文数量。"""
    meta_file = _meta_path(name, cfg)
    if meta_file.exists():
        return json.loads(meta_file.read_text("utf-8")).get("count", 0)
    return sum(1 for _ in iter_papers(name, cfg))


# ============================================================================
#  Embedding
# ============================================================================


def build_explore_vectors(name: str, *, rebuild: bool = False, cfg: Config | None = None) -> int:
    """为探索库生成语义向量。

    复用主库的 Qwen3-Embedding 模型，向量存入探索库自己的
    ``explore.db``。

    Args:
        name: 探索库名称。
        rebuild: 为 ``True`` 时清空重建。
        cfg: 可选的全局配置（用于模型加载）。

    Returns:
        本次新嵌入的论文数量。
    """
    from scholaraio.vectors import (
        _append_faiss_files,
        _embed_batch,
        _embed_provider,
        _embed_signature,
        _ensure_schema,
        _pack,
        _sync_embedding_signature,
    )

    db = _db_path(name, cfg)
    conn = sqlite3.connect(db)
    try:
        _ensure_schema(conn)

        signature = _embed_signature(cfg)
        rebuild, rebuild_reason = _sync_embedding_signature(
            conn,
            signature=signature,
            rebuild=rebuild,
        )
        if rebuild_reason == "signature_changed":
            _log.warning("探索库 embedding 配置已变更，自动执行全量重建: %s", signature)
        elif rebuild_reason == "legacy_unknown":
            _log.warning("探索库检测到旧版向量库缺少签名元数据，自动执行一次全量重建")

        if rebuild:
            conn.execute("DELETE FROM paper_vectors")
            explore_dir = _explore_dir(name, cfg)
            (explore_dir / "faiss.index").unlink(missing_ok=True)
            (explore_dir / "faiss_ids.json").unlink(missing_ok=True)

        if _embed_provider(cfg) == "none":
            conn.commit()
            _log.info("embed.provider=none，跳过探索库向量生成")
            build_explore_fts(name, cfg=cfg)
            return 0

        existing = set()
        if not rebuild:
            existing = {row[0] for row in conn.execute("SELECT paper_id FROM paper_vectors").fetchall()}

        to_embed: list[tuple[str, str]] = []
        for p in iter_papers(name, cfg):
            pid = p.get("doi") or p.get("openalex_id", "")
            if not pid or pid in existing:
                continue
            title = (p.get("title") or "").strip()
            abstract = (p.get("abstract") or "").strip()
            if not abstract or _is_boilerplate(abstract):
                continue
            if p.get("type") in ("paratext", "erratum", "editorial"):
                continue
            text = f"{title}\n\n{abstract}" if title else abstract
            to_embed.append((pid, text))

        if not to_embed:
            conn.commit()
            return 0

        _log.info("Embedding %d papers...", len(to_embed))

        chunk_size = 256  # DB commit chunk; GPU batching is adaptive inside _embed_batch
        total = 0
        all_new_ids: list[str] = []
        all_new_vecs: list[list[float]] = []
        for i in range(0, len(to_embed), chunk_size):
            chunk = to_embed[i : i + chunk_size]
            texts = [t for _, t in chunk]
            vecs = _embed_batch(texts, cfg)
            for (pid, _), vec in zip(chunk, vecs):
                blob = _pack(vec)
                conn.execute(
                    "INSERT OR REPLACE INTO paper_vectors (paper_id, embedding) VALUES (?, ?)",
                    (pid, blob),
                )
                all_new_ids.append(pid)
                all_new_vecs.append(vec)
            total += len(chunk)
            _log.info("Progress: %d/%d", total, len(to_embed))

        conn.commit()
    finally:
        conn.close()

    if all_new_ids:
        explore_dir = _explore_dir(name, cfg)
        _append_faiss_files(
            explore_dir / "faiss.index",
            explore_dir / "faiss_ids.json",
            all_new_ids,
            all_new_vecs,
        )

    # Also build FTS5 index (cheap, ensures keyword search is available)
    build_explore_fts(name, cfg=cfg)

    return len(to_embed)


# ============================================================================
#  Topics (BERTopic) — delegates to topics.py
# ============================================================================


def build_papers_map(name: str, cfg: Config | None = None) -> dict[str, dict]:
    """从 JSONL 构建 paper_id → metadata 映射。

    Args:
        name: 探索库名称。
        cfg: 可选的全局配置。

    Returns:
        ``{paper_id: paper_dict}`` 映射，paper_id 为 DOI 或 openalex_id。
    """
    pm: dict[str, dict] = {}
    for p in iter_papers(name, cfg):
        pid = p.get("doi") or p.get("openalex_id", "")
        if pid:
            pm[pid] = p
    return pm


def build_explore_topics(
    name: str,
    *,
    rebuild: bool = False,
    min_topic_size: int = 30,
    nr_topics: int | str | None = None,
    cfg: Config | None = None,
) -> dict:
    """对探索库运行 BERTopic 主题建模。

    复用主库的 ``build_topics()`` 流程，但参数针对大规模数据调整
    （默认 ``min_topic_size=30``）。模型以统一格式保存（bertopic_model.pkl +
    scholaraio_meta.pkl），可直接用 ``topics.load_model()`` 加载。

    Args:
        name: 探索库名称。
        rebuild: 为 ``True`` 时重建模型。
        min_topic_size: HDBSCAN 最小聚类大小。
        nr_topics: 目标主题数。``"auto"`` 自动合并。
        cfg: 可选的全局配置。

    Returns:
        统计字典：``{"n_topics": N, "n_outliers": N, "n_papers": N}``。
    """
    from scholaraio.vectors import _embed_provider

    if _embed_provider(cfg) == "none":
        raise FileNotFoundError("当前 embed.provider=none，无法构建主题模型，请先启用向量后端并运行 embed")

    model_dir = _explore_dir(name, cfg) / "topic_model"
    if model_dir.exists() and not rebuild:
        return _load_topic_info(name, cfg)

    db = _db_path(name, cfg)
    if not db.exists():
        raise FileNotFoundError(f"向量库不存在: {db}\n请先运行 explore embed --name {name}")

    papers_map = build_papers_map(name, cfg)

    from scholaraio.topics import build_topics

    # Compute explore-tuned hyperparameters
    n = len(papers_map)
    model = build_topics(
        db,
        papers_map=papers_map,
        min_topic_size=min_topic_size,
        nr_topics=nr_topics,
        save_path=model_dir,
        cfg=cfg,
        n_neighbors=min(15, max(5, n // 50)),
        n_components=min(5, max(2, n // 200)),
        min_samples=max(1, min_topic_size // 5),
        ngram_range=(1, 2),
        min_df=1,
    )

    # Write info.json for quick stats retrieval
    topics = getattr(model, "_topics", [])
    n_topics = len(set(topics)) - (1 if -1 in topics else 0)
    n_outliers = sum(1 for t in topics if t == -1)
    info = {"n_topics": n_topics, "n_outliers": n_outliers, "n_papers": len(topics)}
    (model_dir / "info.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    return info


def _load_topic_info(name: str, cfg: Config | None = None) -> dict:
    info_path = _explore_dir(name, cfg) / "topic_model" / "info.json"
    if info_path.exists():
        return json.loads(info_path.read_text("utf-8"))
    return {}


def _build_faiss_index(name: str, cfg: Config | None = None):
    """Build or load a FAISS index for an explore silo."""
    from scholaraio.vectors import _build_faiss_from_db

    explore_dir = _explore_dir(name, cfg)
    return _build_faiss_from_db(
        _db_path(name, cfg),
        explore_dir / "faiss.index",
        explore_dir / "faiss_ids.json",
        empty_msg=f"向量库为空: {_db_path(name, cfg)}",
    )


def explore_vsearch(name: str, query: str, *, top_k: int = 10, cfg: Config | None = None) -> list[dict]:
    """在探索库中进行语义搜索（FAISS 加速）。

    Args:
        name: 探索库名称。
        query: 查询文本。
        top_k: 返回条数。
        cfg: 可选的全局配置。

    Returns:
        论文列表，按 cosine similarity 降序。
    """
    from scholaraio.vectors import _embed_query_vector, _ensure_vector_search_ready, _vsearch_faiss

    db_path = _db_path(name, cfg)
    _ensure_vector_search_ready(
        db_path,
        missing_table_msg=f"向量库为空: {db_path}",
        empty_msg=f"向量库为空: {db_path}",
    )
    # Prepare the query embedding before FAISS import/load to avoid macOS crashes.
    q_vec = _embed_query_vector(query, cfg)
    index, paper_ids = _build_faiss_index(name, cfg)
    hits = _vsearch_faiss(q_vec, index, paper_ids, top_k, cfg=cfg)

    paper_map = {}
    for p in iter_papers(name, cfg):
        pid = p.get("doi") or p.get("openalex_id", "")
        if pid:
            paper_map[pid] = p

    results = []
    for pid, score in hits:
        p = paper_map.get(pid, {})
        results.append({**p, "score": score})
    return results


# ============================================================================
#  FTS5 keyword search for explore silos
# ============================================================================

_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS papers_fts USING fts5(
    paper_id   UNINDEXED,
    title,
    authors,
    abstract,
    year       UNINDEXED,
    tokenize='unicode61'
);
"""


def _ensure_fts(db_path: Path) -> None:
    """Create FTS5 table in explore.db if it doesn't exist."""
    conn = sqlite3.connect(db_path)
    conn.executescript(_FTS_SCHEMA)
    conn.close()


def build_explore_fts(name: str, *, rebuild: bool = False, cfg: Config | None = None) -> int:
    """为探索库构建 FTS5 全文索引。

    Args:
        name: 探索库名称。
        rebuild: 为 ``True`` 时清空重建。
        cfg: 可选的全局配置。

    Returns:
        索引的论文数量。
    """
    db = _db_path(name, cfg)
    _ensure_fts(db)
    conn = sqlite3.connect(db)
    try:
        if rebuild:
            conn.execute("DELETE FROM papers_fts")
            conn.commit()

        existing = {row[0] for row in conn.execute("SELECT paper_id FROM papers_fts").fetchall()}

        count = 0
        for p in iter_papers(name, cfg):
            pid = p.get("doi") or p.get("openalex_id", "")
            if not pid or pid in existing:
                continue
            title = (p.get("title") or "").strip()
            abstract = (p.get("abstract") or "").strip()
            if not title:
                continue
            authors = ", ".join(p.get("authors") or [])
            year = str(p.get("year") or "")
            conn.execute(
                "INSERT INTO papers_fts (paper_id, title, authors, abstract, year) VALUES (?, ?, ?, ?, ?)",
                (pid, title, authors, abstract, year),
            )
            count += 1

        conn.commit()
    finally:
        conn.close()

    _log.info("FTS5 index: %d papers indexed for %s", count, name)
    return count


def explore_search(name: str, query: str, *, top_k: int = 20, cfg: Config | None = None) -> list[dict]:
    """在探索库中进行 FTS5 关键词搜索。

    Args:
        name: 探索库名称。
        query: 查询文本。
        top_k: 返回条数。
        cfg: 可选的全局配置。

    Returns:
        论文列表，按 BM25 排名。
    """
    db = _db_path(name, cfg)
    if not db.exists():
        return []

    _ensure_fts(db)

    # Auto-build if FTS table is empty
    conn = sqlite3.connect(db)
    try:
        fts_count = conn.execute("SELECT COUNT(*) FROM papers_fts").fetchone()[0]
    finally:
        conn.close()

    if fts_count == 0:
        build_explore_fts(name, cfg=cfg)

    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            "SELECT paper_id, rank FROM papers_fts WHERE papers_fts MATCH ? ORDER BY rank LIMIT ?",
            (query, top_k),
        ).fetchall()
    except Exception:
        # FTS query syntax error — try quoting
        safe_query = '"' + query.replace('"', "") + '"'
        try:
            rows = conn.execute(
                "SELECT paper_id, rank FROM papers_fts WHERE papers_fts MATCH ? ORDER BY rank LIMIT ?",
                (safe_query, top_k),
            ).fetchall()
        except Exception:
            rows = []
    finally:
        conn.close()

    if not rows:
        return []

    paper_map = build_papers_map(name, cfg)
    results = []
    for pid, rank in rows:
        p = paper_map.get(pid, {})
        results.append({**p, "score": -rank, "match": "fts"})
    return results


def explore_unified_search(name: str, query: str, *, top_k: int = 20, cfg: Config | None = None) -> list[dict]:
    """探索库融合检索：FTS5 关键词 + FAISS 语义，RRF 合并排序。

    Args:
        name: 探索库名称。
        query: 查询文本。
        top_k: 返回条数。
        cfg: 可选的全局配置。

    Returns:
        论文列表，按 RRF 综合得分降序。
    """
    fts_results = explore_search(name, query, top_k=top_k, cfg=cfg)

    vec_results: list[dict] = []
    try:
        vec_results = explore_vsearch(name, query, top_k=top_k, cfg=cfg)
    except (FileNotFoundError, ImportError):
        pass

    # RRF merge (k=60, same as main library)
    rrf_k = 60
    merged: dict[str, dict] = {}

    for rank, r in enumerate(fts_results):
        pid = r.get("doi") or r.get("openalex_id", "")
        if not pid:
            continue
        merged[pid] = {**r, "score": 1.0 / (rrf_k + rank + 1), "match": "fts"}

    for rank, r in enumerate(vec_results):
        pid = r.get("doi") or r.get("openalex_id", "")
        if not pid:
            continue
        rrf_score = 1.0 / (rrf_k + rank + 1)
        if pid in merged:
            merged[pid]["score"] += rrf_score
            merged[pid]["match"] = "both"
        else:
            merged[pid] = {**r, "score": rrf_score, "match": "vec"}

    results = sorted(merged.values(), key=lambda x: x["score"], reverse=True)
    return results[:top_k]


def list_explore_libs(cfg: Config | None = None) -> list[str]:
    """列出所有探索库名称。"""
    if cfg is not None:
        root = cfg._root / "data" / "explore"
    else:
        root = _DEFAULT_EXPLORE_DIR
    if not root.exists():
        return []
    return sorted(d.name for d in root.iterdir() if d.is_dir() and (d / "papers.jsonl").exists())
