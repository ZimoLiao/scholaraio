"""JSON output, file renaming, and metadata re-fetch."""

from __future__ import annotations

import html
import json
import logging
import re
import unicodedata
from pathlib import Path

_log = logging.getLogger(__name__)

from ._models import PaperMetadata

# ============================================================================
#  JSON Serialization
# ============================================================================


def metadata_to_dict(meta: PaperMetadata) -> dict:
    """将 :class:`PaperMetadata` 转换为可序列化的字典。

    输出字段包括 ``title``, ``authors``, ``year``, ``doi``, ``journal``,
    ``abstract``, ``citation_count``, ``ids``, ``api_sources`` 等。

    Args:
        meta: 元数据实例。

    Returns:
        JSON 可序列化的字典。
    """
    d: dict = {
        "id": meta.id,
        "title": meta.title,
        "authors": meta.authors,
        "first_author": meta.first_author,
        "first_author_lastname": meta.first_author_lastname,
        "year": meta.year,
        "doi": meta.doi,
        "journal": meta.journal,
        "abstract": meta.abstract,
        "paper_type": meta.paper_type,
        "volume": meta.volume,
        "issue": meta.issue,
        "pages": meta.pages,
        "publisher": meta.publisher,
        "issn": meta.issn,
        "citation_count": {},
        "ids": {},
        "source_file": meta.source_file,
        "source_url": meta.source_url,
        "source_type": meta.source_type,
        "extraction_method": meta.extraction_method,
        "api_sources": meta.api_sources,
        "references": meta.references,
        "extracted_at": meta.extracted_at,
    }
    # Citation counts
    if meta.citation_count_crossref is not None:
        d["citation_count"]["crossref"] = meta.citation_count_crossref
    if meta.citation_count_s2 is not None:
        d["citation_count"]["semantic_scholar"] = meta.citation_count_s2
    if meta.citation_count_openalex is not None:
        d["citation_count"]["openalex"] = meta.citation_count_openalex
    # IDs
    if meta.doi:
        d["ids"]["doi"] = meta.doi
        d["ids"]["doi_url"] = f"https://doi.org/{meta.doi}"
    if meta.publication_number:
        d["ids"]["patent_publication_number"] = meta.publication_number
    if meta.arxiv_id:
        d["ids"]["arxiv"] = meta.arxiv_id
        d["ids"]["arxiv_url"] = f"https://arxiv.org/abs/{meta.arxiv_id}"
    if meta.s2_paper_id:
        d["ids"]["semantic_scholar"] = meta.s2_paper_id
        d["ids"]["semantic_scholar_url"] = f"https://www.semanticscholar.org/paper/{meta.s2_paper_id}"
    if meta.openalex_id:
        d["ids"]["openalex"] = meta.openalex_id
        d["ids"]["openalex_url"] = (
            meta.openalex_id.replace("https://openalex.org/", "https://openalex.org/works/")
            if "openalex.org" in meta.openalex_id and "/works/" not in meta.openalex_id
            else meta.openalex_id
        )
    return d


def write_metadata_json(meta: PaperMetadata, output_path: Path) -> None:
    """将元数据写入 JSON 文件（原子写入）。

    Args:
        meta: 元数据实例。
        output_path: 输出 JSON 文件路径。
    """
    from scholaraio.papers import write_meta

    d = metadata_to_dict(meta)
    write_meta(output_path.parent, d)


# ============================================================================
#  Refetch
# ============================================================================


def refetch_metadata(json_path: Path, *, references_only: bool = False) -> bool:
    """对已入库论文重新查询 API，补全引用量等字段。

    从 JSON 反构造 :class:`PaperMetadata`，调用 :func:`enrich_metadata`
    重新查询三个 API，然后将新数据合并回 JSON（保留 ``toc``、
    ``l3_conclusion`` 等已有富化字段）。

    Args:
        json_path: 已入库论文的 JSON 文件路径。

    Returns:
        ``True`` 表示有字段被更新，``False`` 表示无变化或查询失败。
    """
    from ._api import _collect_reference_dois, enrich_metadata, query_crossref, query_semantic_scholar

    data = json.loads(json_path.read_text(encoding="utf-8"))

    if references_only:
        doi = str(data.get("doi") or "").strip()
        if not doi:
            return False
        cr_data = query_crossref(doi=doi)
        s2_data = query_semantic_scholar(doi=doi)
        ref_dois = _collect_reference_dois(cr_data, s2_data)
        if not ref_dois or ref_dois == (data.get("references") or []):
            return False
        data["references"] = ref_dois
        from scholaraio.papers import write_meta

        write_meta(json_path.parent, data)
        return True

    meta = PaperMetadata(
        id=data.get("id", ""),
        title=data.get("title", ""),
        authors=data.get("authors", []),
        first_author=data.get("first_author", ""),
        first_author_lastname=data.get("first_author_lastname", ""),
        year=data.get("year"),
        doi=data.get("doi", ""),
        journal=data.get("journal", ""),
        abstract=data.get("abstract", ""),
        paper_type=data.get("paper_type", ""),
        volume=data.get("volume", ""),
        issue=data.get("issue", ""),
        pages=data.get("pages", ""),
        publisher=data.get("publisher", ""),
        issn=data.get("issn", ""),
        source_file=data.get("source_file", ""),
        source_url=data.get("source_url", ""),
        source_type=data.get("source_type", ""),
        extracted_at=data.get("extracted_at", ""),
        extraction_method=data.get("extraction_method", ""),
        references=data.get("references", []),
        api_sources=[],  # reset so enrich_metadata re-populates
    )
    # Restore existing IDs
    ids = data.get("ids", {})
    old_citation_count = data.get("citation_count", {})
    old_api_sources = list(data.get("api_sources", []))
    meta.s2_paper_id = ids.get("semantic_scholar", "")
    meta.openalex_id = ids.get("openalex", "")
    meta.crossref_doi = ids.get("doi", "")
    meta.arxiv_id = ids.get("arxiv", "")
    meta.publication_number = ids.get("patent_publication_number", "")

    enrich_metadata(meta)

    restored_old_api_state = False
    should_restore_old_api_state = not meta.api_sources or (
        set(meta.api_sources).issubset({"arxiv"}) and old_citation_count
    )
    if should_restore_old_api_state:
        meta.citation_count_crossref = old_citation_count.get("crossref")
        meta.citation_count_s2 = old_citation_count.get("semantic_scholar")
        meta.citation_count_openalex = old_citation_count.get("openalex")
        meta.api_sources = old_api_sources
        restored_old_api_state = True

    new_data = metadata_to_dict(meta)

    # Preserve enriched fields that are not part of metadata pipeline
    for key in data:
        if key.startswith(("toc", "l3_")) and key not in new_data:
            new_data[key] = data[key]

    # Check if anything changed
    def _normalize_ids_for_compare(ids_dict: dict | None) -> dict:
        ids_norm = dict(ids_dict or {})
        doi = ids_norm.get("doi", "")
        if doi and "doi_url" not in ids_norm:
            ids_norm["doi_url"] = f"https://doi.org/{doi}"
        arxiv = ids_norm.get("arxiv", "")
        if arxiv and "arxiv_url" not in ids_norm:
            ids_norm["arxiv_url"] = f"https://arxiv.org/abs/{arxiv}"
        s2 = ids_norm.get("semantic_scholar", "")
        if s2 and "semantic_scholar_url" not in ids_norm:
            ids_norm["semantic_scholar_url"] = f"https://www.semanticscholar.org/paper/{s2}"
        oa = ids_norm.get("openalex", "")
        if oa and "openalex_url" not in ids_norm:
            ids_norm["openalex_url"] = (
                oa.replace("https://openalex.org/", "https://openalex.org/works/")
                if "openalex.org" in oa and "/works/" not in oa
                else oa
            )
        return ids_norm

    if restored_old_api_state:
        new_data["citation_count"] = data.get("citation_count", {})
        new_data["api_sources"] = old_api_sources

    changed = False
    string_like_keys = {
        "title",
        "first_author",
        "first_author_lastname",
        "doi",
        "journal",
        "abstract",
        "paper_type",
        "volume",
        "issue",
        "pages",
        "publisher",
        "issn",
    }
    for key in (
        "title",
        "authors",
        "first_author",
        "first_author_lastname",
        "year",
        "doi",
        "journal",
        "citation_count",
        "ids",
        "api_sources",
        "abstract",
        "paper_type",
        "volume",
        "issue",
        "pages",
        "publisher",
        "issn",
        "references",
    ):
        old_value = data.get(key)
        new_value = new_data.get(key)
        if key in string_like_keys:
            old_value = old_value or ""
            new_value = new_value or ""
        elif key == "ids":
            old_value = _normalize_ids_for_compare(old_value)
            new_value = _normalize_ids_for_compare(new_value)
        if new_value != old_value:
            changed = True
            break

    if changed:
        from scholaraio.papers import write_meta

        write_meta(json_path.parent, new_data)
        # Rename directory if metadata now yields a better name
        new_path = rename_paper(json_path)
        if new_path:
            _log.debug("renamed: %s -> %s", json_path.parent.name, new_path.parent.name)

    return changed


# ============================================================================
#  File Renaming
# ============================================================================


def rename_paper(json_path: Path, *, dry_run: bool = False) -> Path | None:
    """根据 JSON 元数据重命名论文目录。

    读取 ``meta.json`` 中的 ``first_author_lastname``、``year``、``title``，
    用 :func:`generate_new_stem` 生成标准目录名。若新旧目录名一致则跳过。

    Args:
        json_path: 论文 ``meta.json`` 文件路径。
        dry_run: 为 ``True`` 时只返回新路径，不实际重命名。

    Returns:
        重命名后的新 ``meta.json`` 路径，未变更时返回 ``None``。
    """
    data = json.loads(json_path.read_text(encoding="utf-8"))
    meta = PaperMetadata(
        title=data.get("title", ""),
        first_author_lastname=data.get("first_author_lastname", ""),
        year=data.get("year"),
    )
    new_stem = generate_new_stem(meta)

    paper_d = json_path.parent
    old_stem = paper_d.name
    papers_root = paper_d.parent

    if new_stem == old_stem:
        return None

    new_dir = papers_root / new_stem

    # Avoid collision with existing directories
    if new_dir.exists() and new_dir != paper_d:
        suffix = 2
        while True:
            candidate = f"{new_stem}-{suffix}"
            candidate_dir = papers_root / candidate
            if candidate_dir == paper_d or not candidate_dir.exists():
                new_dir = candidate_dir
                break
            suffix += 1

    if new_dir == paper_d:
        return None

    if dry_run:
        return new_dir / "meta.json"

    paper_d.rename(new_dir)

    # Update papers_registry if index.db exists
    uuid = data.get("id")
    if uuid:
        # papers_root is data/papers/, index.db is at data/ (papers_root.parent)
        _update_registry_dir_name(papers_root.parent / "index.db", uuid, new_dir.name)

    return new_dir / "meta.json"


def generate_new_stem(meta: PaperMetadata) -> str:
    """生成标准化文件名 stem: ``{LastName}-{year}-{FullTitle}``。

    去除变音符号、LaTeX 公式、非法字符，适用于文件系统。

    Args:
        meta: 元数据实例。

    Returns:
        文件系统安全的文件名 stem（不含扩展名）。
    """
    lastname = _strip_diacritics(meta.first_author_lastname or "Unknown")
    year_str = str(meta.year) if meta.year else "XXXX"
    clean_title = _clean_title_for_filename(meta.title)
    stem = f"{lastname}-{year_str}-{clean_title}"
    # Reserve 4 bytes for collision suffix (e.g. "-99")
    return _sanitize_for_filename(stem, max_bytes=251)


def _clean_title_for_filename(title: str) -> str:
    """Clean title for use in filename: keep full title, strip math/formulas."""
    if not title:
        return "Untitled"
    # Decode HTML/XML entities (&#x007B; → {, &amp; → &, etc.)
    title = html.unescape(title)
    # Remove MathML / XML tags (only actual tags, not arbitrary <...> content)
    title = re.sub(r"</?[A-Za-z][A-Za-z0-9:-]*(?:\s[^<>]*)?>", "", title)
    # Remove LaTeX inline math: $...$
    title = re.sub(r"\$[^$]+\$", "", title)
    # Remove LaTeX commands with nested braces: \mathrm{{\rm BH}_8}
    for _ in range(3):  # handle up to 3 levels of nesting
        title = re.sub(r"\\[a-zA-Z]+\{[^}]*\}", "", title)
    # Remove remaining backslash commands
    title = re.sub(r"\\[a-zA-Z]+", "", title)
    # Remove standalone math symbols and braces
    title = re.sub(r"[=+<>~^{}|_\\$]", "", title)
    # Collapse whitespace
    title = re.sub(r"\s+", " ", title).strip()
    return title


def _strip_diacritics(text: str) -> str:
    """Jiménez → Jimenez, François → Francois."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _sanitize_for_filename(text: str, max_bytes: int = 255) -> str:
    """Make text filesystem-safe.

    Args:
        text: Raw text to sanitize.
        max_bytes: Maximum byte length for the resulting filename
            (ext4/NTFS limit is 255 bytes per path component).
    """
    # Replace whitespace with hyphens
    text = re.sub(r"\s+", "-", text)
    # Keep only safe characters (including Chinese)
    text = re.sub(r"[^\w\-\u4e00-\u9fff]", "", text)
    # Collapse multiple hyphens
    text = re.sub(r"-{2,}", "-", text)
    # Strip leading/trailing hyphens
    text = text.strip("-")
    # Truncate to max_bytes (respect multi-byte chars, cut at word boundary)
    encoded = text.encode("utf-8")
    if len(encoded) > max_bytes:
        trimmed = encoded[:max_bytes]
        text = trimmed.decode("utf-8", errors="ignore")
        # Only cut back to word boundary if we truncated mid-segment
        if "-" in text:
            next_byte = encoded[len(trimmed) : len(trimmed) + 1]
            if not text.endswith("-") and next_byte != b"-":
                text = text.rsplit("-", 1)[0].strip("-")
    return text


def rename_files(md_path: Path, json_path: Path, new_stem: str, dry_run: bool = False) -> tuple[Path, Path]:
    """Rename paper directory to new_stem, return new (md_path, json_path)."""
    paper_d = json_path.parent
    papers_root = paper_d.parent
    new_dir = papers_root / new_stem

    # Collision avoidance
    suffix = 2
    while new_dir.exists() and new_dir != paper_d:
        new_dir = papers_root / f"{new_stem}-{suffix}"
        suffix += 1

    new_json = new_dir / "meta.json"
    new_md = new_dir / "paper.md"

    if dry_run:
        _log.debug("would rename dir: %s -> %s", paper_d.name, new_dir.name)
        return new_md, new_json

    if paper_d != new_dir:
        paper_d.rename(new_dir)
        try:
            data = json.loads(new_json.read_text(encoding="utf-8"))
            uuid = str(data.get("id") or "").strip()
            if uuid:
                _update_registry_dir_name(papers_root.parent / "index.db", uuid, new_dir.name)
        except Exception as e:
            _log.debug("failed to update papers_registry during rename_files: %s", e)
    _log.debug("renamed dir: %s -> %s", paper_d.name, new_dir.name)
    return new_md, new_json


def _update_registry_dir_name(db_path: Path, uuid: str, new_dir_name: str) -> None:
    """Best-effort update of dir_name in papers_registry after rename."""
    import sqlite3

    if not db_path.exists():
        return
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "UPDATE papers_registry SET dir_name = ? WHERE id = ?",
                (new_dir_name, uuid),
            )
    except Exception as e:
        _log.debug("failed to update papers_registry after rename: %s", e)
