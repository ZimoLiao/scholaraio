"""
audit.py — 已入库论文数据质量审计
====================================

扫描 data/papers/ 中的所有论文，检查元数据完整性、数据质量
和内容一致性问题。返回结构化的问题报告供用户审阅。

规则化检查（无需 LLM）：
  - 关键字段缺失（doi, abstract, year, authors, journal）
  - 配对完整性（目录内 meta.json / paper.md 是否齐全）
  - 文件名规范性（目录名不符合 Author-Year-Title 格式）
  - DOI 重复检测
  - MD 内容过短（可能转换失败）
  - JSON title 与 MD 首个 H1 不一致
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from scholaraio.papers import is_scrubbed, iter_paper_dirs

_log = logging.getLogger(__name__)

_PLACEHOLDER_TITLES = {"introduction", "tldr", "overview", "summary"}
_SUSPICIOUS_AUTHOR_VALUES = {"unknown", "anonymous", "contributor", "contributors"}
_DIRNAME_YEAR_PLACEHOLDER = re.compile(r"(^|-)XXXX(-|$)")
_AUTHOR_YEAR_TITLE_PATTERN = re.compile(r"^(.+?)-(\d{4})-(.+)$")
_DOI_EXPECTED_TYPES = frozenset(
    {"journal-article", "article", "journalarticle", "proceedings-article", "posted-content"}
)
_JOURNAL_EXPECTED_TYPES = frozenset({"journal-article", "article", "journalarticle", "proceedings-article"})
_ABSTRACT_OPTIONAL_TYPES = frozenset({"book", "book-chapter", "monograph"})
_ABSTRACT_OPTIONAL_TITLE_PREFIXES = ("erratum", "book review")
_NO_ABSTRACT_MARKERS = frozenset({"[no abstract]", "[no abstract available]"})
_TITLE_MISMATCH_SKIP_TYPES = frozenset(
    {
        "book",
        "book-chapter",
        "book-part",
        "book-section",
        "dissertation",
        "document",
        "edited-book",
        "lecture-notes",
        "manual",
        "meeting-notes",
        "monograph",
        "patent",
        "presentation",
        "reference-book",
        "report",
        "standard",
        "technical-report",
        "thesis",
        "white-paper",
    }
)
_TITLE_CANDIDATE_LINE_LIMIT = 80
_TITLE_CANDIDATE_MAX_CHARS = 240


@dataclass
class Issue:
    """单个审计问题。

    Attributes:
        paper_id: 论文 ID（目录名）。
        severity: 严重程度，``"error"`` | ``"warning"`` | ``"info"``。
        rule: 检查规则名称。
        message: 问题描述。
    """

    paper_id: str
    severity: str  # "error" | "warning" | "info"
    rule: str
    message: str


def audit_papers(papers_dir: Path) -> list[Issue]:
    """对论文目录执行全量数据质量审计。

    Args:
        papers_dir: 已入库论文目录（每篇一目录结构）。

    Returns:
        按严重程度排序的问题列表（error 在前）。
    """
    issues: list[Issue] = []

    # DOI duplicate detection
    doi_map: dict[str, list[str]] = {}

    for pdir in iter_paper_dirs(papers_dir):
        pid = pdir.name
        meta_file = pdir / "meta.json"
        md_file = pdir / "paper.md"
        has_md = md_file.exists()

        try:
            from scholaraio.papers import read_meta

            data = read_meta(pdir)
        except Exception as e:
            issues.append(Issue(pid, "error", "invalid_json", f"JSON 解析失败: {e}"))
            continue

        # -- Missing fields --
        _check_missing(issues, pid, data, has_md=has_md)

        # -- File pairing --
        if not has_md:
            issues.append(Issue(pid, "error", "missing_md", "缺少 paper.md 文件"))
        else:
            _check_content_consistency(issues, pid, data, md_file)

        # -- Directory name format --
        _check_filename(issues, pid, data)

        # -- DOI tracking --
        doi = (data.get("doi") or "").strip().lower()
        if doi:
            doi_map.setdefault(doi, []).append(pid)

    # DOI duplicates
    for doi, pids in doi_map.items():
        if len(pids) > 1:
            for pid in pids:
                others = [p for p in pids if p != pid]
                issues.append(Issue(pid, "error", "duplicate_doi", f"DOI 重复: {doi} (同: {', '.join(others)})"))

    # Sort: error > warning > info
    severity_order = {"error": 0, "warning": 1, "info": 2}
    issues.sort(key=lambda x: (severity_order.get(x.severity, 9), x.paper_id))
    return issues


def list_scrub_suspects(papers_dir: Path, *, include_scrubbed: bool = False) -> list[Issue]:
    """Return conservative metadata-quality suspects for the scrub workflow."""
    issues: list[Issue] = []

    for pdir in _iter_scrub_candidate_dirs(papers_dir):
        if not include_scrubbed and is_scrubbed(pdir):
            continue

        pid = pdir.name
        try:
            from scholaraio.papers import read_meta

            data = read_meta(pdir)
        except Exception as e:
            issues.append(Issue(pid, "warning", "invalid_metadata", f"无法读取元数据: {e}"))
            continue

        title = str(data.get("title") or "").strip()
        authors = data.get("authors") or []
        first_author_lastname = str(data.get("first_author_lastname") or "").strip()
        year = data.get("year")

        if _is_garbled_title(title):
            issues.append(Issue(pid, "warning", "garbled_title", "标题包含乱码或替换字符"))
        if _is_placeholder_title(title):
            issues.append(Issue(pid, "warning", "placeholder_title", "标题是占位词，需人工确认真实主题"))
        if _has_suspicious_author(authors, first_author_lastname):
            issues.append(Issue(pid, "warning", "suspicious_author", "作者信息缺失、占位或明显异常"))
        if _has_suspicious_year(year, pid):
            issues.append(Issue(pid, "warning", "suspicious_year", "年份缺失或目录名仍含占位年份"))
        if _has_suspicious_dirname(pid):
            issues.append(Issue(pid, "warning", "suspicious_dirname", "目录名格式异常，可能由坏元数据生成"))

    return issues


def _iter_scrub_candidate_dirs(papers_dir: Path):
    """Yield directories relevant to scrub, including partially broken records."""
    if not papers_dir.exists():
        return
    for d in sorted(papers_dir.iterdir()):
        if not d.is_dir():
            continue
        if (d / "meta.json").exists() or (d / "paper.md").exists():
            yield d


def _check_missing(issues: list[Issue], pid: str, data: dict, *, has_md: bool) -> None:
    """Check for missing critical fields."""
    from scholaraio.ingest.metadata._doc_extract import DOCUMENT_TYPES

    paper_type = _normalized_paper_type(data.get("paper_type"))
    if not data.get("doi") and (not paper_type or paper_type in _DOI_EXPECTED_TYPES):
        issues.append(Issue(pid, "warning", "missing_doi", "缺少 DOI"))
    if (
        has_md
        and not _has_available_abstract(data)
        and paper_type not in DOCUMENT_TYPES
        and paper_type not in _ABSTRACT_OPTIONAL_TYPES
        and not _has_optional_abstract_title(data)
    ):
        issues.append(Issue(pid, "warning", "missing_abstract", "缺少摘要"))
    if not data.get("year"):
        issues.append(Issue(pid, "warning", "missing_year", "缺少年份"))
    if not data.get("authors"):
        issues.append(Issue(pid, "warning", "missing_authors", "缺少作者"))
    if not data.get("journal") and (not paper_type or paper_type in _JOURNAL_EXPECTED_TYPES):
        issues.append(Issue(pid, "warning", "missing_journal", "缺少期刊名"))
    if not data.get("title"):
        issues.append(Issue(pid, "error", "missing_title", "缺少标题"))


def _is_garbled_title(title: str) -> bool:
    return "�" in title


def _is_placeholder_title(title: str) -> bool:
    normalized = title.strip().lower()
    return normalized in _PLACEHOLDER_TITLES


def _has_suspicious_author(authors: object, first_author_lastname: object) -> bool:
    if isinstance(authors, str):
        author_values = [authors]
    elif isinstance(authors, (list, tuple, set)):
        author_values = [str(author) for author in authors]
    else:
        author_values = []

    if not author_values:
        return True
    if not isinstance(first_author_lastname, str) or not first_author_lastname.strip():
        return True

    normalized_lastname = first_author_lastname.strip().lower()
    if normalized_lastname in _SUSPICIOUS_AUTHOR_VALUES:
        return True

    for author in author_values:
        normalized = author.strip().lower()
        if not normalized:
            return True
        if normalized in _SUSPICIOUS_AUTHOR_VALUES:
            return True
        if re.fullmatch(r"[a-z]", normalized):
            return True

    return False


def _has_suspicious_year(year: object, pid: str) -> bool:
    if year in (None, "", "XXXX"):
        return True
    if isinstance(year, str) and not year.isdigit():
        return True
    return bool(_DIRNAME_YEAR_PLACEHOLDER.search(pid))


def _has_suspicious_dirname(pid: str) -> bool:
    if pid.startswith("-"):
        return True
    if _DIRNAME_YEAR_PLACEHOLDER.search(pid):
        return True
    if re.match(r"^\d+-", pid):
        return True
    return _AUTHOR_YEAR_TITLE_PATTERN.match(pid) is None


def _check_content_consistency(
    issues: list[Issue],
    pid: str,
    data: dict,
    md_path: Path,
) -> None:
    """Check consistency between JSON metadata and MD content."""
    try:
        md_text = md_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        _log.debug("failed to read paper.md for %s: %s", pid, e)
        issues.append(Issue(pid, "error", "unreadable_md", "无法读取 paper.md 文件"))
        return

    # MD too short (likely conversion failure)
    if len(md_text.strip()) < 200:
        issues.append(
            Issue(pid, "warning", "short_md", f"paper.md 文件过短 ({len(md_text.strip())} 字符)，可能转换失败")
        )

    # Title vs first H1 mismatch
    title_variants = _title_variants(data)
    paper_type = _normalized_paper_type(data.get("paper_type"))
    if title_variants and paper_type not in _TITLE_MISMATCH_SKIP_TYPES:
        md_title, overlap, matched_title = _best_title_match(md_text, title_variants)
        if md_title and overlap < 0.3:
            issues.append(
                Issue(
                    pid,
                    "warning",
                    "title_mismatch",
                    f"JSON 标题与 MD 标题候选不一致\n  JSON: {matched_title[:80]}\n  MD: {md_title[:80]}",
                )
            )


def _check_filename(issues: list[Issue], pid: str, data: dict) -> None:
    """Check directory name format compliance."""
    # Expected: Author-Year-Title
    m = re.match(r"^(.+?)-(\d{4})-(.+)$", pid)
    if not m:
        issues.append(Issue(pid, "info", "nonstandard_filename", "目录名不符合 Author-Year-Title 格式"))
        return

    file_year = int(m.group(2))
    json_year = data.get("year")
    if json_year and file_year != json_year:
        issues.append(
            Issue(
                pid, "warning", "filename_year_mismatch", f"目录名年份 ({file_year}) 与 JSON 年份 ({json_year}) 不一致"
            )
        )


def _normalized_paper_type(paper_type: object) -> str:
    return str(paper_type or "").strip().lower()


def _has_available_abstract(data: dict) -> bool:
    abstract = str(data.get("abstract") or "").strip()
    if not abstract:
        return bool(data.get("abstract_unavailable"))
    return abstract.lower() in _NO_ABSTRACT_MARKERS or True


def _has_optional_abstract_title(data: dict) -> bool:
    title = str(data.get("title") or "").strip().lower()
    return any(title.startswith(prefix) for prefix in _ABSTRACT_OPTIONAL_TITLE_PREFIXES)


def _title_variants(data: dict) -> list[str]:
    variants: list[str] = []
    for key in ("title", "title_translated", "translated_title"):
        value = str(data.get(key) or "").strip()
        if value and value not in variants:
            variants.append(value)
    return variants


def _significant_words(text: str) -> set[str]:
    return set(re.findall(r"\w{4,}", text.lower()))


def _clean_title_candidate(line: str) -> str:
    candidate = re.sub(r"^#+\s*", "", line.strip())
    candidate = re.sub(r"\s+", " ", candidate)
    return candidate.strip()


def _iter_title_candidates(md_text: str):
    seen: set[str] = set()
    for raw in md_text.splitlines()[:_TITLE_CANDIDATE_LINE_LIMIT]:
        candidate = _clean_title_candidate(raw)
        if not candidate:
            continue
        if candidate.lower().startswith("## page"):
            continue
        if len(candidate) < 12 or len(candidate) > _TITLE_CANDIDATE_MAX_CHARS:
            continue
        if not re.search(r"[A-Za-z\u4e00-\u9fff]", candidate):
            continue
        normalized = candidate.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        yield candidate


def _best_title_candidate(md_text: str, json_words: set[str]) -> tuple[str | None, float]:
    best_candidate: str | None = None
    best_overlap = 0.0
    for candidate in _iter_title_candidates(md_text):
        candidate_words = _significant_words(candidate)
        if not candidate_words:
            continue
        overlap = len(json_words & candidate_words) / max(len(json_words), 1)
        if best_candidate is None or overlap > best_overlap:
            best_candidate = candidate
            best_overlap = overlap
    return best_candidate, best_overlap


def _best_title_match(md_text: str, titles: list[str]) -> tuple[str | None, float, str]:
    best_candidate: str | None = None
    best_overlap = 0.0
    best_title = titles[0]
    for title in titles:
        title_words = _significant_words(title)
        if not title_words:
            continue
        candidate, overlap = _best_title_candidate(md_text, title_words)
        if candidate is None:
            continue
        if best_candidate is None or overlap > best_overlap:
            best_candidate = candidate
            best_overlap = overlap
            best_title = title
    return best_candidate, best_overlap, best_title


def format_report(issues: list[Issue]) -> str:
    """将审计结果格式化为可读报告。

    Args:
        issues: :func:`audit_papers` 返回的问题列表。

    Returns:
        格式化的文本报告。
    """
    if not issues:
        return "审计通过，未发现问题。"

    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]
    infos = [i for i in issues if i.severity == "info"]

    lines = [f"审计完成: {len(errors)} 个错误, {len(warnings)} 个警告, {len(infos)} 个提示\n"]

    if errors:
        lines.append("=" * 60)
        lines.append("错误 (需要修复)")
        lines.append("=" * 60)
        for i in errors:
            lines.append(f"  [{i.rule}] {i.paper_id}")
            lines.append(f"    {i.message}")

    if warnings:
        lines.append("")
        lines.append("-" * 60)
        lines.append("警告 (建议关注)")
        lines.append("-" * 60)
        for i in warnings:
            lines.append(f"  [{i.rule}] {i.paper_id}")
            lines.append(f"    {i.message}")

    if infos:
        lines.append("")
        lines.append("· " * 30)
        lines.append("提示 (参考信息)")
        lines.append("· " * 30)
        for i in infos:
            lines.append(f"  [{i.rule}] {i.paper_id}")
            lines.append(f"    {i.message}")

    return "\n".join(lines)
