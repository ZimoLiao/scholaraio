"""
index.py — SQLite FTS5 全文检索索引
=====================================

索引字段：title + abstract + conclusion（均可检索）
其余字段（paper_id, authors, year, journal, doi, paper_type, citation_count, md_path）
存储但不参与检索。

用法：
    from scholaraio.index import build_index, search
    build_index(papers_dir, db_path)
    results = search("turbulent boundary layer", db_path)
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

from scholaraio.papers import best_citation, parse_year_range

if TYPE_CHECKING:
    from scholaraio.config import Config

_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS papers USING fts5(
    paper_id       UNINDEXED,
    title,
    authors,
    year,
    journal,
    abstract,
    conclusion,
    doi            UNINDEXED,
    paper_type     UNINDEXED,
    citation_count UNINDEXED,
    md_path        UNINDEXED,
    tokenize       = 'unicode61'
);
"""


_HASH_SCHEMA = """
CREATE TABLE IF NOT EXISTS papers_hash (
    paper_id     TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL
);
"""

_REGISTRY_SCHEMA = """
CREATE TABLE IF NOT EXISTS papers_registry (
    id                   TEXT PRIMARY KEY,
    dir_name             TEXT NOT NULL UNIQUE,
    title                TEXT,
    doi                  TEXT,
    publication_number   TEXT,
    year                 INTEGER,
    first_author         TEXT
);
"""

_REGISTRY_DOI_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_registry_doi
    ON papers_registry(doi) WHERE doi IS NOT NULL AND doi != '';
"""

_REGISTRY_PUBNUM_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_registry_publication_number
    ON papers_registry(publication_number) WHERE publication_number IS NOT NULL AND publication_number != '';
"""

_CITATIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS citations (
    source_id   TEXT NOT NULL,
    target_doi  TEXT NOT NULL,
    target_id   TEXT,
    PRIMARY KEY (source_id, target_doi)
);
"""
_CITATIONS_IDX_TARGET_DOI = "CREATE INDEX IF NOT EXISTS idx_cit_target_doi ON citations(target_doi);"
_CITATIONS_IDX_TARGET_ID = (
    "CREATE INDEX IF NOT EXISTS idx_cit_target_id ON citations(target_id) WHERE target_id IS NOT NULL;"
)

_CHUNK_VECTORS_SCHEMA = """
CREATE TABLE IF NOT EXISTS chunk_vectors (
    chunk_id       TEXT PRIMARY KEY,
    paper_id       TEXT NOT NULL,
    section_title  TEXT,
    start_line     INTEGER NOT NULL,
    end_line       INTEGER NOT NULL,
    content_hash   TEXT NOT NULL,
    embedding      BLOB NOT NULL
);
"""

_CHUNK_VECTORS_PAPER_IDX = "CREATE INDEX IF NOT EXISTS idx_chunk_vectors_paper_id ON chunk_vectors(paper_id);"


def _index_hash(meta: dict) -> str:
    """Compute a short hash of the fields indexed in FTS5."""
    parts = [
        meta.get("title") or "",
        ", ".join(meta.get("authors") or []),
        str(meta.get("year") or ""),
        meta.get("journal") or "",
        meta.get("abstract") or "",
        meta.get("l3_conclusion") or "",
        meta.get("doi") or "",
        meta.get("paper_type") or "",
        ((meta.get("ids") or {}).get("patent_publication_number", "") or ""),
    ]
    cc = meta.get("citation_count")
    if cc and isinstance(cc, dict):
        vals = [v for v in cc.values() if isinstance(v, (int, float))]
        parts.append(str(max(vals)) if vals else "")
    parts.append(json.dumps(meta.get("references", []), sort_keys=True))
    text = "\n".join(parts)
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:12]


_best_citation = best_citation  # backward compat alias


def build_index(papers_dir: Path, db_path: Path, rebuild: bool = False) -> int:
    """建立或增量更新 SQLite FTS5 全文检索索引。

    索引字段: ``title`` + ``abstract`` + ``conclusion``，
    均参与全文检索。其余字段（``paper_id``, ``authors`` 等）仅存储。

    Args:
        papers_dir: 已入库论文目录，扫描其中的 ``*.json``。
        db_path: SQLite 数据库路径，不存在时自动创建。
        rebuild: 为 ``True`` 时清空旧数据后重建。

    Returns:
        本次索引的论文数量。
    """
    from scholaraio.papers import iter_paper_dirs
    from scholaraio.papers import read_meta as _read_meta

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(_SCHEMA)
        conn.execute(_HASH_SCHEMA)
        conn.execute(_REGISTRY_SCHEMA)
        conn.execute(_CITATIONS_SCHEMA)
        conn.execute(_CHUNK_VECTORS_SCHEMA)
        try:
            conn.execute(_REGISTRY_DOI_INDEX)
        except sqlite3.OperationalError:
            pass  # index already exists
        # Migrate: add publication_number column if missing (pre-existing DB)
        try:
            conn.execute("SELECT publication_number FROM papers_registry LIMIT 0")
        except sqlite3.OperationalError:
            try:
                conn.execute("ALTER TABLE papers_registry ADD COLUMN publication_number TEXT")
            except sqlite3.OperationalError:
                pass
        try:
            conn.execute(_REGISTRY_PUBNUM_INDEX)
        except sqlite3.OperationalError:
            pass
        except sqlite3.IntegrityError:
            import logging

            logging.getLogger(__name__).warning(
                "cannot create UNIQUE index on publication_number: duplicate values exist; "
                "falling back to non-unique index"
            )
            try:
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_registry_publication_number "
                    "ON papers_registry(publication_number) "
                    "WHERE publication_number IS NOT NULL AND publication_number != ''"
                )
            except sqlite3.OperationalError:
                pass
        try:
            conn.execute(_CITATIONS_IDX_TARGET_DOI)
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute(_CITATIONS_IDX_TARGET_ID)
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute(_CHUNK_VECTORS_PAPER_IDX)
        except sqlite3.OperationalError:
            pass

        if rebuild:
            conn.execute("DROP TABLE IF EXISTS papers")
            conn.execute(_SCHEMA)
            conn.execute("DELETE FROM papers_hash")
            conn.execute("DELETE FROM papers_registry")
            conn.execute("DELETE FROM citations")

        # Load existing hashes for incremental change detection
        existing_hashes: dict[str, str] = {}
        if not rebuild:
            for row in conn.execute("SELECT paper_id, content_hash FROM papers_hash").fetchall():
                existing_hashes[row[0]] = row[1]

        count = 0
        for pdir in iter_paper_dirs(papers_dir):
            try:
                meta = _read_meta(pdir)
            except (ValueError, FileNotFoundError):
                continue
            paper_id = meta.get("id") or pdir.name
            h = _index_hash(meta)
            if not rebuild and existing_hashes.get(paper_id) == h:
                continue  # unchanged, skip

            if not rebuild:
                conn.execute("DELETE FROM papers WHERE paper_id = ?", (paper_id,))

            best_cite = _best_citation(meta)
            md_file = pdir / "paper.md"
            conn.execute(
                """
                INSERT INTO papers
                    (paper_id, title, authors, year, journal, abstract, conclusion,
                     doi, paper_type, citation_count, md_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    paper_id,
                    meta.get("title") or "",
                    ", ".join(meta.get("authors") or []),
                    str(meta.get("year") or ""),
                    meta.get("journal") or "",
                    meta.get("abstract") or "",
                    meta.get("l3_conclusion") or "",
                    meta.get("doi") or "",
                    meta.get("paper_type") or "",
                    str(best_cite) if best_cite is not None else "",
                    str(md_file) if md_file.exists() else "",
                ),
            )
            conn.execute(
                "INSERT OR REPLACE INTO papers_hash (paper_id, content_hash) VALUES (?, ?)",
                (paper_id, h),
            )

            # Update papers_registry — use ON CONFLICT(id) DO UPDATE so that
            # a publication_number UNIQUE violation is surfaced rather than
            # silently deleting a different paper's row (which INSERT OR REPLACE
            # would do when the new pub_num collides with another id's row).
            dir_name = pdir.name
            pub_num = ((meta.get("ids") or {}).get("patent_publication_number", "") or "").upper().strip()
            try:
                doi_norm = (meta.get("doi") or "").lower().strip()
                conn.execute(
                    """INSERT INTO papers_registry
                       (id, dir_name, title, doi, publication_number, year, first_author)
                       VALUES (?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(id) DO UPDATE SET
                           dir_name=excluded.dir_name,
                           title=excluded.title,
                           doi=excluded.doi,
                           publication_number=excluded.publication_number,
                           year=excluded.year,
                           first_author=excluded.first_author""",
                    (
                        paper_id,
                        dir_name,
                        meta.get("title") or "",
                        doi_norm,
                        pub_num,
                        meta.get("year"),
                        meta.get("first_author_lastname") or "",
                    ),
                )
            except sqlite3.IntegrityError as exc:
                import logging

                _idx_log = logging.getLogger(__name__)
                err_msg = str(exc).lower()
                if "publication_number" in err_msg and pub_num:
                    _idx_log.warning(
                        "publication_number %r for paper %s conflicts with another paper; "
                        "storing without publication_number",
                        pub_num,
                        paper_id,
                    )
                    conn.execute(
                        """INSERT INTO papers_registry
                           (id, dir_name, title, doi, publication_number, year, first_author)
                           VALUES (?, ?, ?, ?, ?, ?, ?)
                           ON CONFLICT(id) DO UPDATE SET
                               dir_name=excluded.dir_name,
                               title=excluded.title,
                               doi=excluded.doi,
                               publication_number=excluded.publication_number,
                               year=excluded.year,
                               first_author=excluded.first_author""",
                        (
                            paper_id,
                            dir_name,
                            meta.get("title") or "",
                            doi_norm,
                            "",  # clear conflicting pub_num
                            meta.get("year"),
                            meta.get("first_author_lastname") or "",
                        ),
                    )
                else:
                    _idx_log.warning(
                        "IntegrityError for paper %s: %s; skipping registry update",
                        paper_id,
                        exc,
                    )

            # Insert references into citations table
            refs = _reference_dois(meta.get("references") or [])
            if refs:
                conn.execute("DELETE FROM citations WHERE source_id = ?", (paper_id,))
                conn.executemany(
                    "INSERT OR IGNORE INTO citations (source_id, target_doi, target_id) VALUES (?, ?, NULL)",
                    [(paper_id, doi) for doi in refs],
                )

            count += 1

        # Bulk resolve target_id for citations where target paper is in library
        conn.execute("""
            UPDATE citations SET target_id = (
                SELECT pr.id FROM papers_registry pr
                WHERE LOWER(pr.doi) = LOWER(citations.target_doi)
            ) WHERE target_id IS NULL
        """)

        conn.commit()
    finally:
        conn.close()
    return count


_SEARCH_COLS = "paper_id, title, authors, year, journal, doi, paper_type, citation_count"


def _reference_dois(refs: list) -> list[str]:
    """Extract DOI strings from heterogeneous reference entries.

    Supports both the canonical list[str] shape and dict entries that may
    come from manually curated metadata or external APIs.
    """
    dois: list[str] = []
    for ref in refs:
        doi = ""
        if isinstance(ref, str):
            doi = ref
        elif isinstance(ref, dict):
            external_ids = ref.get("externalIds")
            if not isinstance(external_ids, dict):
                external_ids = {}
            external_ids_alt = ref.get("external_ids")
            if not isinstance(external_ids_alt, dict):
                external_ids_alt = {}
            doi = (
                str(ref.get("doi") or "")
                or str(ref.get("DOI") or "")
                or str(external_ids.get("DOI") or "")
                or str(external_ids_alt.get("DOI") or "")
            )
        doi = (doi or "").strip().lower()
        if doi:
            dois.append(doi)
    return dois


def _ensure_fts_table(conn: sqlite3.Connection) -> None:
    """Raise FileNotFoundError if the FTS5 papers table does not exist."""
    has_table = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='papers'").fetchone()
    if not has_table:
        raise FileNotFoundError("FTS5 索引表不存在，请先运行 `scholaraio index`")


def search(
    query: str,
    db_path: Path,
    top_k: int | None = None,
    cfg: Config | None = None,
    *,
    year: str | None = None,
    journal: str | None = None,
    paper_type: str | None = None,
    paper_ids: set[str] | None = None,
) -> list[dict]:
    """FTS5 关键词全文检索。

    在 ``title``、``abstract``、``conclusion`` 字段上执行 FTS5 MATCH，
    按 BM25 相关性排序返回结果。

    Args:
        query: 检索词（多词用空格分隔，FTS5 语法）。
        db_path: SQLite 索引数据库路径。
        top_k: 最多返回条数，为 ``None`` 时从 ``cfg.search.top_k`` 读取。
        cfg: 可选的 :class:`~scholaraio.config.Config` 实例。
        year: 年份过滤（``"2023"`` / ``"2020-2024"`` / ``"2020-"``）。
        journal: 期刊名过滤（LIKE 模糊匹配）。
        paper_type: 论文类型过滤（如 ``"review"``、``"journal-article"``）。
        paper_ids: 论文 UUID 白名单，仅返回集合内的结果。

    Returns:
        匹配的论文字典列表，每项包含 ``paper_id``, ``title``,
        ``authors``, ``year``, ``journal``, ``doi``, ``paper_type``,
        ``citation_count``。

    Raises:
        FileNotFoundError: 索引文件或 FTS5 表不存在。
    """
    if top_k is None:
        top_k = cfg.search.top_k if cfg is not None else 20

    if not db_path.exists():
        raise FileNotFoundError(f"索引文件不存在：{db_path}\n请先运行 `scholaraio index`")

    conn = sqlite3.connect(db_path)
    try:
        _ensure_fts_table(conn)

        conn.row_factory = sqlite3.Row
        filter_sql, filter_params = _build_filter_clause(year=year, journal=journal, paper_type=paper_type)

        # Over-fetch when post-filtering by paper_ids to avoid empty results
        fetch_k = top_k * 5 if paper_ids else top_k

        rows = conn.execute(
            f"""
            SELECT {_SEARCH_COLS}
            FROM papers
            WHERE papers MATCH ?{filter_sql}
            ORDER BY rank
            LIMIT ?
            """,
            [_safe_query(query), *filter_params, fetch_k],
        ).fetchall()
        results = [dict(r) for r in rows]
        _enrich_dir_names(results, conn)
    finally:
        conn.close()
    if paper_ids is not None:
        results = [r for r in results if r["paper_id"] in paper_ids]
    return results[:top_k]


def search_author(
    query: str,
    db_path: Path,
    top_k: int | None = None,
    cfg: Config | None = None,
    *,
    year: str | None = None,
    journal: str | None = None,
    paper_type: str | None = None,
    paper_ids: set[str] | None = None,
) -> list[dict]:
    """按作者名搜索论文（LIKE 模糊匹配）。

    Args:
        query: 作者名（或部分名字），不区分大小写。
        db_path: SQLite 索引数据库路径。
        top_k: 最多返回条数，为 ``None`` 时从 ``cfg.search.top_k`` 读取。
        cfg: 可选的 :class:`~scholaraio.config.Config` 实例。
        year: 年份过滤（``"2023"`` / ``"2020-2024"`` / ``"2020-"``）。
        journal: 期刊名过滤（LIKE 模糊匹配）。
        paper_type: 论文类型过滤（如 ``"review"``、``"journal-article"``）。
        paper_ids: 论文 UUID 白名单，仅返回集合内的结果。

    Returns:
        匹配的论文字典列表。
    """
    if top_k is None:
        top_k = cfg.search.top_k if cfg is not None else 20

    if not db_path.exists():
        raise FileNotFoundError(f"索引文件不存在：{db_path}\n请先运行 `scholaraio index`")

    conn = sqlite3.connect(db_path)
    try:
        _ensure_fts_table(conn)

        conn.row_factory = sqlite3.Row
        filter_sql, filter_params = _build_filter_clause(year=year, journal=journal, paper_type=paper_type)

        # Over-fetch when post-filtering by paper_ids to avoid empty results
        fetch_k = top_k * 5 if paper_ids else top_k

        rows = conn.execute(
            f"""
            SELECT {_SEARCH_COLS}
            FROM papers
            WHERE authors LIKE ?{filter_sql}
            ORDER BY year DESC
            LIMIT ?
            """,
            [f"%{query}%", *filter_params, fetch_k],
        ).fetchall()
        results = [dict(r) for r in rows]
        _enrich_dir_names(results, conn)
    finally:
        conn.close()
    if paper_ids is not None:
        results = [r for r in results if r["paper_id"] in paper_ids]
    return results[:top_k]


def top_cited(
    db_path: Path,
    top_k: int = 10,
    *,
    year: str | None = None,
    journal: str | None = None,
    paper_type: str | None = None,
    paper_ids: set[str] | None = None,
) -> list[dict]:
    """按引用量降序返回论文。

    Args:
        db_path: SQLite 索引数据库路径。
        top_k: 最多返回条数。
        year: 年份过滤（``"2023"`` / ``"2020-2024"`` / ``"2020-"``）。
        journal: 期刊名过滤（LIKE 模糊匹配）。
        paper_type: 论文类型过滤（如 ``"review"``、``"journal-article"``）。
        paper_ids: 论文 UUID 白名单，仅返回集合内的结果。

    Returns:
        论文字典列表，按 ``citation_count`` 降序排列。

    Raises:
        FileNotFoundError: 索引文件或 FTS5 表不存在。
    """
    if not db_path.exists():
        raise FileNotFoundError(f"索引文件不存在：{db_path}\n请先运行 `scholaraio index`")

    conn = sqlite3.connect(db_path)
    try:
        _ensure_fts_table(conn)

        conn.row_factory = sqlite3.Row
        filter_sql, filter_params = _build_filter_clause(year=year, journal=journal, paper_type=paper_type)

        # Skip SQL LIMIT when post-filtering by paper_ids (workspace scope)
        limit_clause = "" if paper_ids else "LIMIT ?"
        limit_params = [] if paper_ids else [top_k]

        rows = conn.execute(
            f"""
            SELECT {_SEARCH_COLS}
            FROM papers
            WHERE citation_count != ''{filter_sql}
            ORDER BY CAST(citation_count AS INTEGER) DESC
            {limit_clause}
            """,
            [*filter_params, *limit_params],
        ).fetchall()
        results = [dict(r) for r in rows]
        _enrich_dir_names(results, conn)
    finally:
        conn.close()
    if paper_ids is not None:
        results = [r for r in results if r["paper_id"] in paper_ids]
    return results[:top_k]


def _parse_year_filter(year: str) -> tuple[str, list[str]]:
    """解析年份过滤表达式，返回 SQL WHERE 片段和参数。

    支持格式: ``"2023"`` (单年), ``"2020-2024"`` (范围), ``"2020-"`` (起始年至今)。

    Args:
        year: 年份过滤表达式。

    Returns:
        ``(where_clause, params)`` 二元组。
    """
    start, end = parse_year_range(year)
    if start is not None and end is not None:
        if start == end:
            return "year = ?", [str(start)]
        return "year >= ? AND year <= ?", [str(start), str(end)]
    elif start is not None:
        return "year >= ?", [str(start)]
    elif end is not None:
        return "year <= ?", [str(end)]
    return "1=1", []


def _build_filter_clause(
    year: str | None = None,
    journal: str | None = None,
    paper_type: str | None = None,
) -> tuple[str, list[str]]:
    """构建过滤 WHERE 子句（不含前导 AND/WHERE）。

    Args:
        year: 年份过滤表达式，为 ``None`` 时不过滤。
        journal: 期刊名（LIKE 模糊匹配），为 ``None`` 时不过滤。
        paper_type: 论文类型（LIKE 模糊匹配，如 ``review``、``journal-article``），
            为 ``None`` 时不过滤。

    Returns:
        ``(clauses_str, params)``，clauses_str 每个条件前带 ``AND``。
    """
    clauses: list[str] = []
    params: list[str] = []
    if year:
        yc, yp = _parse_year_filter(year)
        clauses.append(yc)
        params.extend(yp)
    if journal:
        clauses.append("journal LIKE ?")
        params.append(f"%{journal}%")
    if paper_type:
        clauses.append("paper_type LIKE ?")
        params.append(f"%{paper_type}%")
    sql = "".join(f" AND {c}" for c in clauses)
    return sql, params


def _safe_query(query: str) -> str:
    """去除 FTS5 特殊字符，避免语法错误。"""
    return re.sub(r"[^\w\s]", " ", query).strip()


def _enrich_dir_names(results: list[dict], conn: sqlite3.Connection) -> list[dict]:
    """Enrich search results with dir_name from papers_registry."""
    has_reg = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='papers_registry'").fetchone()
    if not has_reg:
        return results
    id_to_dir: dict[str, str] = {}
    for row in conn.execute("SELECT id, dir_name FROM papers_registry").fetchall():
        id_to_dir[row[0]] = row[1]
    for r in results:
        r["dir_name"] = id_to_dir.get(r["paper_id"], "")
    return results


def lookup_paper(db_path: Path, user_input: str) -> dict | None:
    """查找论文：支持 UUID、dir_name、DOI、专利公开号。

    按以下顺序尝试匹配: UUID → dir_name → DOI → publication_number。
    公开号查询会自动归一化为大写。

    Args:
        db_path: SQLite 数据库路径。
        user_input: UUID、目录名、DOI 或专利公开号。

    Returns:
        ``papers_registry`` 行字典，找不到时返回 ``None``。
    """
    if not db_path.exists():
        return None
    conn = sqlite3.connect(db_path)
    try:
        has_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='papers_registry'"
        ).fetchone()
        if not has_table:
            return None
        conn.row_factory = sqlite3.Row
        # Try UUID
        row = conn.execute("SELECT * FROM papers_registry WHERE id = ?", (user_input,)).fetchone()
        if row:
            return dict(row)
        # Try dir_name
        row = conn.execute("SELECT * FROM papers_registry WHERE dir_name = ?", (user_input,)).fetchone()
        if row:
            return dict(row)
        # Try DOI (new DBs store lowercase DOI; old DBs may still contain mixed case)
        normalized_doi = user_input.strip().lower()
        row = conn.execute(
            "SELECT * FROM papers_registry WHERE doi = ?",
            (normalized_doi,),
        ).fetchone()
        if not row:
            # Backward compatibility for pre-normalization registries.
            row = conn.execute(
                "SELECT * FROM papers_registry WHERE LOWER(doi) = ?",
                (normalized_doi,),
            ).fetchone()
        if row:
            return dict(row)
        # Try patent publication number (normalize to uppercase)
        try:
            row = conn.execute(
                "SELECT * FROM papers_registry WHERE publication_number = ?",
                (user_input.upper().strip(),),
            ).fetchone()
            if row:
                return dict(row)
        except sqlite3.OperationalError:
            pass  # column may not exist in old DB
    finally:
        conn.close()
    return None


def unified_search(
    query: str,
    db_path: Path,
    top_k: int | None = None,
    cfg: Config | None = None,
    *,
    year: str | None = None,
    journal: str | None = None,
    paper_type: str | None = None,
    paper_ids: set[str] | None = None,
) -> list[dict]:
    """融合检索：FTS5 关键词 + FAISS 语义向量，合并去重排序。

    两路并行检索，各取 ``top_k`` 条候选，按 ``paper_id`` 去重后
    以综合得分排序返回。FTS5 命中的论文获得排名加分，向量检索的
    论文按余弦相似度得分。同时命中的论文得分叠加，排名更靠前。

    当向量索引不可用时（未运行 ``embed``），自动降级为纯 FTS5 检索。

    Args:
        query: 自然语言查询文本。
        db_path: SQLite 数据库路径。
        top_k: 最多返回条数，为 ``None`` 时从配置读取。
        cfg: 可选的 :class:`~scholaraio.config.Config` 实例。
        year: 年份过滤。
        journal: 期刊名过滤。
        paper_type: 论文类型过滤。
        paper_ids: 论文 UUID 白名单，仅返回集合内的结果。

    Returns:
        论文字典列表，按综合得分降序。每项包含 ``paper_id``, ``title``,
        ``authors``, ``year``, ``journal``, ``score``, ``match``
        （``"fts"`` / ``"vec"`` / ``"both"``）。
    """
    if top_k is None:
        top_k = cfg.search.top_k if cfg is not None else 20

    # -- FTS5 leg --
    fts_results: list[dict] = []
    try:
        fts_results = search(
            query,
            db_path,
            top_k=top_k,
            cfg=cfg,
            year=year,
            journal=journal,
            paper_type=paper_type,
            paper_ids=paper_ids,
        )
    except FileNotFoundError:
        pass

    # -- Vector leg (graceful degradation) --
    vec_results: list[dict] = []
    try:
        from scholaraio.vectors import vsearch

        vec_results = vsearch(
            query,
            db_path,
            top_k=top_k,
            cfg=cfg,
            year=year,
            journal=journal,
            paper_type=paper_type,
            paper_ids=paper_ids,
        )
    except (FileNotFoundError, ImportError):
        pass

    # -- Merge via Reciprocal Rank Fusion (RRF) --
    # RRF score = sum of 1/(k + rank) across retrieval legs.
    # k=60 is the standard constant from Cormack et al. (2009).
    rrf_k = 60
    merged: dict[str, dict] = {}  # paper_id → result dict

    for rank, r in enumerate(fts_results):
        pid = r["paper_id"]
        merged[pid] = {
            **r,
            "score": 1.0 / (rrf_k + rank + 1),
            "match": "fts",
        }

    for rank, r in enumerate(vec_results):
        pid = r["paper_id"]
        rrf_score = 1.0 / (rrf_k + rank + 1)
        if pid in merged:
            merged[pid]["score"] += rrf_score
            merged[pid]["match"] = "both"
        else:
            merged[pid] = {
                **r,
                "score": rrf_score,
                "match": "vec",
            }

    results = sorted(merged.values(), key=lambda x: x["score"], reverse=True)
    return results[:top_k]


# ============================================================================
#  Citation graph queries
# ============================================================================


def get_references(
    paper_id: str,
    db_path: Path,
    *,
    paper_ids: set[str] | None = None,
) -> list[dict]:
    """查询论文的参考文献列表。

    Args:
        paper_id: 论文 UUID。
        db_path: SQLite 数据库路径。
        paper_ids: 论文 UUID 白名单（仅过滤库内结果）。

    Returns:
        参考文献列表，每项含 ``target_doi``、``target_id``，
        库内论文另含 ``title``、``dir_name``、``year``、``first_author``。
    """
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT c.target_doi, c.target_id,
                      pr.title, pr.dir_name, pr.year, pr.first_author
               FROM citations c
               LEFT JOIN papers_registry pr ON c.target_id = pr.id
               WHERE c.source_id = ?
               ORDER BY pr.year DESC NULLS LAST, c.target_doi""",
            (paper_id,),
        ).fetchall()
    finally:
        conn.close()
    results = [dict(r) for r in rows]
    if paper_ids is not None:
        results = [r for r in results if r.get("target_id") is None or r["target_id"] in paper_ids]
    return results


def get_citing_papers(
    paper_id: str,
    db_path: Path,
    *,
    paper_ids: set[str] | None = None,
) -> list[dict]:
    """查询哪些本地论文引用了指定论文（库内反向查找）。

    Args:
        paper_id: 被引论文的 UUID。
        db_path: SQLite 数据库路径。
        paper_ids: 论文 UUID 白名单。

    Returns:
        引用方论文列表，每项含 ``source_id``、``dir_name``、``title``、``year``。
    """
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        # Get DOI of target paper
        row = conn.execute("SELECT doi FROM papers_registry WHERE id = ?", (paper_id,)).fetchone()
        target_doi = row["doi"] if row else ""

        # Find papers that cite this paper (by target_id or target_doi)
        params: list = [paper_id]
        doi_clause = ""
        if target_doi:
            doi_clause = " OR LOWER(c.target_doi) = LOWER(?)"
            params.append(target_doi)

        rows = conn.execute(
            f"""SELECT DISTINCT c.source_id,
                       pr.dir_name, pr.title, pr.year, pr.first_author
                FROM citations c
                JOIN papers_registry pr ON c.source_id = pr.id
                WHERE (c.target_id = ?{doi_clause})
                ORDER BY pr.year DESC""",
            params,
        ).fetchall()
    finally:
        conn.close()
    results = [dict(r) for r in rows]
    if paper_ids is not None:
        results = [r for r in results if r["source_id"] in paper_ids]
    return results


def get_shared_references(
    paper_id_list: list[str],
    db_path: Path,
    min_shared: int = 2,
    *,
    paper_ids: set[str] | None = None,
) -> list[dict]:
    """查询多篇论文的共同参考文献。

    Args:
        paper_id_list: 论文 UUID 列表。
        db_path: SQLite 数据库路径。
        min_shared: 最少被几篇论文共同引用才纳入结果。
        paper_ids: 论文 UUID 白名单（仅过滤库内结果）。

    Returns:
        共同引用列表，每项含 ``target_doi``、``shared_count``、``target_id``，
        库内论文另含 ``title``、``dir_name``。
    """
    if not db_path.exists() or not paper_id_list:
        return []
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        placeholders = ",".join("?" for _ in paper_id_list)
        rows = conn.execute(
            f"""SELECT c.target_doi,
                       COUNT(DISTINCT c.source_id) AS shared_count,
                       c.target_id,
                       pr.title, pr.dir_name, pr.year
                FROM citations c
                LEFT JOIN papers_registry pr ON c.target_id = pr.id
                WHERE c.source_id IN ({placeholders})
                GROUP BY LOWER(c.target_doi)
                HAVING shared_count >= ?
                ORDER BY shared_count DESC, c.target_doi""",
            [*paper_id_list, min_shared],
        ).fetchall()
    finally:
        conn.close()
    results = [dict(r) for r in rows]
    if paper_ids is not None:
        results = [r for r in results if r.get("target_id") is None or r["target_id"] in paper_ids]
    return results
