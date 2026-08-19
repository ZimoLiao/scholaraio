"""sources/zotero.py — Zotero Web API / 本地 SQLite 导入，转换为 PaperMetadata"""

from __future__ import annotations

import logging
import re
import sqlite3
from functools import lru_cache
from pathlib import Path

from scholaraio.core.log import ui
from scholaraio.services.ingest_metadata._extract import _extract_lastname
from scholaraio.services.ingest_metadata._models import PaperMetadata

_log = logging.getLogger("scholaraio.sources.zotero")

_DOI_PREFIX_RE = re.compile(r"^https?://(?:dx\.)?doi\.org/", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")

# Zotero itemType → Crossref-style paper_type
_ITEM_TYPE_MAP: dict[str, str] = {
    "journalArticle": "journal-article",
    "conferencePaper": "conference-paper",
    "thesis": "thesis",
    "book": "book",
    "bookSection": "book-chapter",
    "report": "report",
    "preprint": "preprint",
    "document": "",
}


# ============================================================================
#  Internal helpers
# ============================================================================


def _clean_doi(raw: str) -> str:
    """Strip URL prefix from DOI, return bare DOI."""
    if not raw:
        return ""
    return _DOI_PREFIX_RE.sub("", raw).strip()


def _parse_zotero_date(date_str: str) -> int | None:
    """Extract 4-digit year from Zotero date string.

    Handles "2024-01-15", "January 2024", "2024", "", "n.d.", etc.
    """
    if not date_str:
        return None
    m = _YEAR_RE.search(date_str)
    return int(m.group(1)) if m else None


def _creators_to_authors(creators: list[dict]) -> list[str]:
    """Convert Zotero creators list to author name strings.

    Only includes creators with ``creatorType == "author"``.
    Handles both ``{"firstName": ..., "lastName": ...}`` and
    single-field ``{"name": ...}`` formats.
    """
    authors: list[str] = []
    for c in creators:
        if c.get("creatorType", "author") != "author":
            continue
        if "name" in c:
            authors.append(c["name"])
        else:
            first = c.get("firstName", "").strip()
            last = c.get("lastName", "").strip()
            if first and last:
                authors.append(f"{first} {last}")
            elif last:
                authors.append(last)
            elif first:
                authors.append(first)
    return authors


def _zotero_item_to_meta(item_data: dict, source_label: str) -> PaperMetadata:
    """Convert Zotero item data dict to PaperMetadata."""
    authors = _creators_to_authors(item_data.get("creators", []))
    first_author = authors[0] if authors else ""
    first_author_lastname = _extract_lastname(first_author) if first_author else ""

    journal = item_data.get("publicationTitle") or item_data.get("proceedingsTitle") or item_data.get("bookTitle") or ""

    item_type = item_data.get("itemType", "")
    paper_type = _ITEM_TYPE_MAP.get(item_type, item_type)

    return PaperMetadata(
        title=item_data.get("title", ""),
        authors=authors,
        first_author=first_author,
        first_author_lastname=first_author_lastname,
        year=_parse_zotero_date(item_data.get("date", "")),
        doi=_clean_doi(item_data.get("DOI", "")),
        journal=journal,
        abstract=item_data.get("abstractNote", ""),
        paper_type=paper_type,
        volume=item_data.get("volume", "") or "",
        issue=item_data.get("issue", "") or "",
        pages=item_data.get("pages", "") or "",
        publisher=item_data.get("publisher", "") or "",
        issn=item_data.get("ISSN", "") or "",
        source_file=source_label,
        extraction_method="zotero",
    )


# ============================================================================
#  Web API mode (requires pyzotero)
# ============================================================================


def fetch_zotero_api(
    library_id: str,
    api_key: str,
    *,
    library_type: str = "user",
    collection_key: str | None = None,
    item_types: list[str] | None = None,
    download_pdfs: bool = True,
    pdf_dir: Path | None = None,
) -> tuple[list[PaperMetadata], list[Path | None]]:
    """从 Zotero Web API 获取文献元数据和 PDF。

    Args:
        library_id: Zotero library ID。
        api_key: Zotero API key。
        library_type: ``"user"`` 或 ``"group"``。
        collection_key: 仅导入指定 collection（为 ``None`` 时导入全部）。
        item_types: 限定 item 类型列表（如 ``["journalArticle"]``）。
        download_pdfs: 是否下载 PDF 附件。
        pdf_dir: PDF 下载目录（为 ``None`` 时使用临时目录）。

    Returns:
        ``(records, pdf_paths)``，两个列表长度相同、索引对齐。
    """
    from pyzotero import zotero as pyzotero

    zot = pyzotero.Zotero(library_id, library_type, api_key)

    # Build query parameters
    kwargs: dict = {}
    if item_types:
        kwargs["itemType"] = " || ".join(item_types)

    # Fetch items
    if collection_key:
        items = zot.everything(zot.collection_items(collection_key, **kwargs))
    else:
        items = zot.everything(zot.items(**kwargs))

    # Filter out attachments and notes (keep only top-level items)
    items = [it for it in items if it.get("data", {}).get("itemType") not in ("attachment", "note", "linkAttachment")]

    records: list[PaperMetadata] = []
    pdf_paths: list[Path | None] = []

    for idx, item in enumerate(items):
        data = item.get("data", {})
        meta = _zotero_item_to_meta(data, "zotero-api")
        records.append(meta)

        # PDF download
        pdf_path: Path | None = None
        if download_pdfs:
            try:
                children = zot.children(item["key"])
                for child in children:
                    cd = child.get("data", {})
                    if cd.get("contentType") == "application/pdf":
                        title_short = meta.title[:50] if meta.title else f"item-{idx}"
                        ui(f"[{idx + 1}/{len(items)}] 下载 PDF: {title_short}...")
                        target = pdf_dir or Path(".")
                        target.mkdir(parents=True, exist_ok=True)
                        # Use dump() to download the file
                        filename = cd.get("filename", f"{item['key']}.pdf")
                        out_path = target / filename
                        zot.dump(child["key"], filename, str(target))
                        if out_path.exists():
                            pdf_path = out_path
                        break
            except Exception as exc:
                _log.warning("下载 PDF 失败 (%s): %s", meta.title[:40], exc)

        pdf_paths.append(pdf_path)

    n_pdfs = sum(1 for p in pdf_paths if p is not None)
    _log.info("Zotero API: 获取 %d 条记录，%d 个 PDF", len(records), n_pdfs)
    return records, pdf_paths


def list_collections_api(
    library_id: str,
    api_key: str,
    *,
    library_type: str = "user",
) -> list[dict]:
    """列出 Zotero library 中的所有 collections。

    Args:
        library_id: Zotero library ID。
        api_key: Zotero API key。
        library_type: ``"user"`` 或 ``"group"``。

    Returns:
        Collection 列表，每项包含 ``key``、``name``、``numItems``。
    """
    from pyzotero import zotero as pyzotero

    zot = pyzotero.Zotero(library_id, library_type, api_key)
    collections = zot.collections()
    return [
        {
            "key": c["data"]["key"],
            "name": c["data"]["name"],
            "numItems": c["meta"].get("numItems", 0),
        }
        for c in collections
    ]


# ============================================================================
#  Local SQLite mode (no external dependencies)
# ============================================================================


def parse_zotero_local(
    db_path: Path,
    storage_dir: Path | None = None,
    *,
    collection_key: str | None = None,
    item_types: list[str] | None = None,
) -> tuple[list[PaperMetadata], list[Path | None]]:
    """从本地 Zotero SQLite 数据库解析文献元数据和 PDF 路径。

    Args:
        db_path: ``zotero.sqlite`` 文件路径。
        storage_dir: Zotero storage 目录（默认 ``db_path.parent / "storage"``）。
        collection_key: 仅导入指定 collection。
        item_types: 限定 item 类型列表。

    Returns:
        ``(records, pdf_paths)``，两个列表长度相同、索引对齐。
    """
    if not db_path.exists():
        raise FileNotFoundError(f"Zotero 数据库不存在: {db_path}")

    if storage_dir is None:
        storage_dir = db_path.parent / "storage"

    conn = sqlite3.connect(f"file:{db_path}?immutable=1", uri=True)
    conn.row_factory = sqlite3.Row

    try:
        # Build item ID filter for collection
        item_id_filter: set[int] | None = None
        if collection_key:
            rows = conn.execute(
                "SELECT itemID FROM collectionItems ci "
                "JOIN collections c ON ci.collectionID = c.collectionID "
                "WHERE c.key = ?",
                (collection_key,),
            ).fetchall()
            item_id_filter = {r["itemID"] for r in rows}

        # Get all top-level items (not attachments/notes)
        type_filter = ""
        if item_types:
            placeholders = ",".join("?" for _ in item_types)
            type_filter = f"AND it.typeName IN ({placeholders})"

        query = f"""
            SELECT i.itemID, i.key, it.typeName
            FROM items i
            JOIN itemTypes it ON i.itemTypeID = it.itemTypeID
            WHERE it.typeName NOT IN ('attachment', 'note')
            AND i.itemID NOT IN (SELECT itemID FROM deletedItems)
            {type_filter}
        """
        params: list = list(item_types) if item_types else []
        items_rows = conn.execute(query, params).fetchall()

        records: list[PaperMetadata] = []
        pdf_paths: list[Path | None] = []

        for row in items_rows:
            item_id = row["itemID"]
            item_key = row["key"]
            item_type = row["typeName"]

            if item_id_filter is not None and item_id not in item_id_filter:
                continue

            # Build item_data dict from itemData tables
            field_rows = conn.execute(
                "SELECT f.fieldName, idv.value "
                "FROM itemData id "
                "JOIN fields f ON id.fieldID = f.fieldID "
                "JOIN itemDataValues idv ON id.valueID = idv.valueID "
                "WHERE id.itemID = ?",
                (item_id,),
            ).fetchall()
            item_data: dict = {r["fieldName"]: r["value"] for r in field_rows}
            item_data["itemType"] = item_type

            # Get creators
            creator_rows = conn.execute(
                "SELECT c.firstName, c.lastName, ct.creatorType "
                "FROM itemCreators ic "
                "JOIN creators c ON ic.creatorID = c.creatorID "
                "JOIN creatorTypes ct ON ic.creatorTypeID = ct.creatorTypeID "
                "WHERE ic.itemID = ? "
                "ORDER BY ic.orderIndex",
                (item_id,),
            ).fetchall()
            item_data["creators"] = [
                {
                    "firstName": r["firstName"] or "",
                    "lastName": r["lastName"] or "",
                    "creatorType": r["creatorType"],
                }
                for r in creator_rows
            ]

            meta = _zotero_item_to_meta(item_data, "zotero.sqlite")
            records.append(meta)

            # Find PDF attachment
            pdf_path = _find_local_pdf(conn, item_id, storage_dir)
            pdf_paths.append(pdf_path)

        n_pdfs = sum(1 for p in pdf_paths if p is not None)
        _log.info("Zotero local: 解析 %d 条记录，%d 个 PDF", len(records), n_pdfs)
        return records, pdf_paths

    finally:
        conn.close()


_PREFS_BASE_PATH_RE = re.compile(
    r'user_pref\(\s*"extensions\.zotero\.baseAttachmentPath"\s*,\s*"((?:[^"\\]|\\.)*)"\s*\)'
)


@lru_cache(maxsize=8)
def _base_attachment_path(home: Path | None = None) -> Path | None:
    """读取 Zotero 的"链接附件基准目录"（linked attachment base directory）。

    Zotero 把 linked-file 附件的路径存成 ``attachments:<相对路径>``，需要配合本机
    profile 里的 ``extensions.zotero.baseAttachmentPath`` 才能还原成绝对路径。
    该设置只存在于 ``prefs.js``，不在 ``zotero.sqlite`` 里。

    Args:
        home: 用户主目录；为 ``None`` 时使用 ``Path.home()``（测试可显式注入）。

    Returns:
        基准目录；未配置或 profile 不存在时返回 ``None``。
    """
    base_home = home or Path.home()
    roots = [
        base_home / "Library" / "Application Support" / "Zotero" / "Profiles",  # macOS
        base_home / ".zotero" / "zotero",  # Linux
        base_home / "AppData" / "Roaming" / "Zotero" / "Zotero" / "Profiles",  # Windows
    ]
    for root in roots:
        if not root.is_dir():
            continue
        for prefs in sorted(root.glob("*/prefs.js")):
            try:
                text = prefs.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            m = _PREFS_BASE_PATH_RE.search(text)
            if m:
                base = Path(m.group(1).encode().decode("unicode_escape")).expanduser()
                if base.is_dir():
                    return base
    return None


def _find_local_pdf(conn: sqlite3.Connection, parent_id: int, storage_dir: Path) -> Path | None:
    """Find PDF attachment for a given item in local Zotero storage."""
    rows = conn.execute(
        "SELECT ia.path, i.key "
        "FROM itemAttachments ia "
        "JOIN items i ON ia.itemID = i.itemID "
        "WHERE ia.parentItemID = ? "
        "AND ia.contentType = 'application/pdf'",
        (parent_id,),
    ).fetchall()

    for r in rows:
        raw_path = r["path"] or ""
        att_key = r["key"]
        # Zotero stores paths as "storage:<filename>"
        if raw_path.startswith("storage:"):
            filename = raw_path[len("storage:") :]
            pdf_path = storage_dir / att_key / filename
            if pdf_path.exists():
                return pdf_path
        elif raw_path.startswith("attachments:"):
            # Linked file relative to Zotero's linked attachment base directory
            base = _base_attachment_path()
            if base is not None:
                pdf_path = base / raw_path[len("attachments:") :]
                if pdf_path.exists():
                    return pdf_path
        elif raw_path:
            # Absolute or relative linked file
            p = Path(raw_path)
            if p.exists():
                return p
    return None


def list_collections_local(db_path: Path) -> list[dict]:
    """列出本地 Zotero 数据库中的所有 collections。

    Args:
        db_path: ``zotero.sqlite`` 文件路径。

    Returns:
        Collection 列表，每项包含 ``key``、``name``、``numItems``。
    """
    conn = sqlite3.connect(f"file:{db_path}?immutable=1", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT c.key, c.collectionName, COUNT(ci.itemID) as numItems "
            "FROM collections c "
            "LEFT JOIN collectionItems ci ON c.collectionID = ci.collectionID "
            "GROUP BY c.collectionID "
            "ORDER BY c.collectionName",
        ).fetchall()
        return [{"key": r["key"], "name": r["collectionName"], "numItems": r["numItems"]} for r in rows]
    finally:
        conn.close()
