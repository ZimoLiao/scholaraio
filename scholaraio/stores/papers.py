"""
papers.py — 论文目录结构的唯一真相源
======================================

所有模块通过此模块访问论文路径，不自行拼路径。

目录结构：
    <configured papers_dir>/<dir_name>/
    ├── meta.json    # 含 "id": "<uuid>" 字段
    └── paper.md
"""

from __future__ import annotations

import html
import json
import re
import shutil
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

from scholaraio.core.fileio import atomic_write_text, file_lock

_REVIEW_ONLY_JOURNAL_PREFIXES = (
    "annual review of ",
    "current opinion in ",
    "foundations and trends in ",
    "living reviews in ",
    "nature reviews ",
)

_REVIEW_ONLY_JOURNALS = frozenset(
    {
        "applied mechanics reviews",
        "physics reports",
        "progress in aerospace sciences",
        "progress in energy and combustion science",
        "renewable and sustainable energy reviews",
        "reports on progress in physics",
        "reviews in chemical engineering",
        "reviews of geophysics",
        "reviews of modern physics",
        "space science reviews",
    }
)


def _normalized_journal_name(value: object) -> str:
    text = html.unescape(str(value or "")).replace("®", " ")
    return re.sub(r"\s+", " ", text).strip().casefold()


def is_review_only_journal(value: object) -> bool:
    """Return whether a venue publishes review articles by design.

    The allowlist is deliberately conservative.  Generic names containing
    words such as ``Review`` or ``Progress`` are not enough because journals
    such as Physical Review and ordinary research venues would be false
    positives.
    """
    journal = _normalized_journal_name(value)
    return journal in _REVIEW_ONLY_JOURNALS or journal.startswith(_REVIEW_ONLY_JOURNAL_PREFIXES)


def normalize_paper_type(value: object, journal: object = "", doi: object = "") -> str:
    """Return the canonical paper type used in metadata, filters, and views."""
    raw = str(value or "").strip()
    text = ""
    compact = ""
    if raw:
        text = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", raw)
        text = re.sub(r"[\s_]+", "-", text).lower().strip("-")
        text = re.sub(r"-+", "-", text)
        compact = re.sub(r"[^a-z0-9]", "", text)
    aliases = {
        "article": "journal-article",
        "jour": "journal-article",
        "journalarticle": "journal-article",
        "monograph": "book",
        "researcharticle": "journal-article",
        "proceedingsarticle": "conference-paper",
        "conferencearticle": "conference-paper",
        "conferencepaper": "conference-paper",
        "bookchapter": "book-chapter",
    }
    paper_type = aliases.get(compact, text)
    if not paper_type and str(journal or "").strip() and str(doi or "").strip():
        paper_type = "journal-article"
    if paper_type in {"", "journal-article"} and is_review_only_journal(journal):
        return "review"
    return paper_type


def normalize_paper_metadata(data: dict) -> dict:
    """Return a shallow copy with ``paper_type`` normalized canonically."""
    normalized = dict(data)
    paper_type = normalize_paper_type(
        normalized.get("paper_type"),
        normalized.get("journal"),
        normalized.get("doi"),
    )
    if paper_type or "paper_type" in normalized:
        normalized["paper_type"] = paper_type
    return normalized


def authors_text(authors: object) -> str:
    """Return display/search text for supported author metadata shapes."""
    if isinstance(authors, str):
        return authors
    if isinstance(authors, (list, tuple)):
        return ", ".join(str(author) for author in authors if author)
    return ""


def paper_dir(papers_dir: Path, dir_name: str) -> Path:
    """Return the directory path for a paper."""
    return papers_dir / dir_name


def meta_path(papers_dir: Path, dir_name: str) -> Path:
    """Return the meta.json path for a paper."""
    return papers_dir / dir_name / "meta.json"


def md_path(papers_dir: Path, dir_name: str) -> Path:
    """Return the paper.md path for a paper."""
    return papers_dir / dir_name / "paper.md"


def pdf_path(paper_d: Path) -> Path:
    """Return the canonical PDF path for a paper directory."""
    return paper_d / f"{paper_d.name}.pdf"


def find_pdf(paper_d: Path) -> Path | None:
    """Return the best available PDF for a paper directory, if present."""
    canonical = pdf_path(paper_d)
    if canonical.is_file():
        return canonical
    legacy = paper_d / "paper.pdf"
    if legacy.is_file():
        return legacy
    pdfs = sorted(p for p in paper_d.glob("*.pdf") if p.is_file())
    return pdfs[0] if pdfs else None


def copy_pdf_to_paper_dir(src_pdf: Path, paper_d: Path) -> Path:
    """Copy a PDF into a paper directory using the directory-name convention."""
    dest = pdf_path(paper_d)
    paper_d.mkdir(parents=True, exist_ok=True)
    if src_pdf.resolve() != dest.resolve():
        shutil.copy2(str(src_pdf), str(dest))
    return dest


def move_pdf_to_paper_dir(src_pdf: Path, paper_d: Path) -> Path:
    """Move a PDF into a paper directory using the directory-name convention."""
    dest = pdf_path(paper_d)
    paper_d.mkdir(parents=True, exist_ok=True)
    if src_pdf.resolve() != dest.resolve():
        if dest.exists():
            dest.unlink()
        shutil.move(str(src_pdf), str(dest))
    return dest


def normalize_pdf_name(paper_d: Path, current_pdf: Path) -> Path:
    """Normalize an in-directory PDF to the canonical paper-directory filename.

    When the canonical destination already exists, the non-canonical
    ``current_pdf`` is removed so an existing curated PDF is not overwritten.
    """
    dest = pdf_path(paper_d)
    if current_pdf.resolve() == dest.resolve():
        return dest
    if not current_pdf.exists():
        return dest
    if dest.exists():
        current_pdf.unlink()
        return dest
    current_pdf.rename(dest)
    return dest


def scrub_marker_path(paper_d: Path) -> Path:
    """Return the `.scrubbed` marker path for a paper directory."""
    return paper_d / ".scrubbed"


def is_scrubbed(paper_d: Path) -> bool:
    """Return True when the paper directory has already been scrub-reviewed."""
    return scrub_marker_path(paper_d).exists()


def mark_scrubbed(paper_d: Path) -> None:
    """Create the `.scrubbed` marker file for a paper directory."""
    scrub_marker_path(paper_d).touch(exist_ok=True)


def iter_paper_dirs(papers_dir: Path) -> Iterator[Path]:
    """Yield sorted subdirectories containing meta.json.

    Args:
        papers_dir: Root papers directory.

    Yields:
        Path to each paper subdirectory that contains a ``meta.json``.
    """
    if not papers_dir.exists():
        return
    for d in sorted(papers_dir.iterdir()):
        if d.is_dir() and (d / "meta.json").exists():
            yield d


def generate_uuid() -> str:
    """Generate a new UUID string for a paper."""
    return str(uuid.uuid4())


def best_citation(meta: dict) -> int:
    """从 ``citation_count`` 中取最佳引用数。

    Args:
        meta: 论文元数据字典。

    Returns:
        最大引用数，无数据时返回 0。
    """
    cc = meta.get("citation_count")
    if not cc:
        return 0
    if isinstance(cc, (int, float)):
        return int(cc)
    if not isinstance(cc, dict):
        return 0
    vals = [v for v in cc.values() if isinstance(v, (int, float))]
    return int(max(vals)) if vals else 0


def parse_year_range(year: str) -> tuple[int | None, int | None]:
    """解析年份过滤表达式，返回 ``(start, end)``。

    支持格式: ``"2023"`` (单年), ``"2020-2024"`` (范围),
    ``"2020-"`` (起始年至今), ``"-2024"`` (截至某年)。

    Args:
        year: 年份过滤表达式。

    Returns:
        ``(start, end)`` 二元组，缺失端为 ``None``。
        单年返回 ``(2023, 2023)``。
    """
    year = year.strip()
    if "-" in year:
        parts = year.split("-", 1)
        start, end = parts[0].strip(), parts[1].strip()
        try:
            return (int(start) if start else None, int(end) if end else None)
        except ValueError as e:
            raise ValueError(f"Cannot parse year range: {year!r} (formats: 2020, 2020-2024, 2020-, -2024)") from e
    try:
        y = int(year)
    except ValueError as e:
        raise ValueError(f"Cannot parse year: {year!r} (formats: 2020, 2020-2024, 2020-, -2024)") from e
    return (y, y)


def read_meta(paper_d: Path) -> dict:
    """Read and parse meta.json from a paper directory.

    Args:
        paper_d: Paper directory path.

    Returns:
        Parsed JSON dict.

    Raises:
        ValueError: If the JSON file is malformed (wraps ``json.JSONDecodeError``
            with the file path for context).
        FileNotFoundError: If meta.json does not exist.
    """
    p = paper_d / "meta.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Metadata must be a JSON object: {p}")
        return data
    except json.JSONDecodeError as e:
        raise ValueError(f"Malformed JSON in {p}: {e}") from e


def write_meta(paper_d: Path, data: dict) -> None:
    """Atomically write meta.json to a paper directory.

    Writes to a temporary file first, then renames to avoid corruption
    if the process is interrupted mid-write.

    Args:
        paper_d: Paper directory path.
        data: Metadata dict to serialize.
    """
    p = paper_d / "meta.json"
    with file_lock(p):
        _write_meta_unlocked(p, data)


def _write_meta_unlocked(path: Path, data: dict) -> None:
    atomic_write_text(path, json.dumps(normalize_paper_metadata(data), indent=2, ensure_ascii=False) + "\n")
    from scholaraio.stores.library_state import notify_metadata_write

    notify_metadata_write(path)


def modify_meta(paper_d: Path, edit: Callable[[dict], None]) -> dict:
    """Apply a short in-memory edit to the latest metadata under a record lock.

    Do expensive extraction/network work before entering this transaction.
    ``write_meta`` replaces a whole record; use this or ``update_meta`` when
    changing fields of an existing record so unrelated concurrent edits survive.
    """
    with file_lock(paper_d / "meta.json"):
        data = read_meta(paper_d)
        edit(data)
        data = normalize_paper_metadata(data)
        _write_meta_unlocked(paper_d / "meta.json", data)
        return data


def update_meta(paper_d: Path, **fields) -> dict:
    """Read meta.json, merge fields, and atomically write back.

    Args:
        paper_d: Paper directory path.
        **fields: Key-value pairs to merge into the metadata dict.

    Returns:
        The updated metadata dict.
    """
    return modify_meta(paper_d, lambda data: data.update(fields))
