"""
loader.py — 分层内容加载 + TOC 提取 + L3 结论提取
====================================================

L1: title / authors / year / journal / doi  ← JSON 字段
L2: abstract                                ← JSON 字段
L3: conclusion                              ← JSON 字段（需先运行 enrich_l3 提取）
L4: full markdown                           ← 读 .md 文件

TOC 提取（enrich_toc）
-----------------------
1. regex 提取所有 # 标题 + 行号
2. LLM 过滤 noise（author running headers、期刊名、论文标题重复等），
   并为每个真实节标题分配层级（level）
3. 写入 JSON["toc"]：[{"line": N, "level": N, "title": "..."}]

L3 提取（enrich_l3）
---------------------
若 JSON 已有 TOC，直接从中定位结论节（跳过第一次 LLM 调用）。
否则走 Primary path：LLM 从原始标题列表选出结论节 → Python 截取 → LLM 校验。
Fallback path：LLM 直接给出起止行号 → Python 截取 → LLM 校验。
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scholaraio.core.config import Config

_log = logging.getLogger("scholaraio.loader")

# Paper types for which L3 conclusion extraction is skipped.
# These long-form or non-article documents don't have a standard
# conclusion section suitable for the current extraction strategy.
L3_SKIP_TYPES = frozenset(
    {
        "thesis",
        "dissertation",
        "book",
        "monograph",
        "edited-book",
        "reference-book",
        "book-chapter",
        "book-section",
        "book-part",
        "document",
        "technical-report",
        "lecture-notes",
        "patent",
    }
)


# ============================================================================
#  Public load functions (L1–L4)
# ============================================================================


def load_l1(json_path: Path) -> dict:
    """加载 L1 层元数据（标题、作者、年份、期刊、DOI）。

    Args:
        json_path: 论文 JSON 元数据文件路径。

    Returns:
        包含 ``paper_id``, ``title``, ``authors``, ``year``,
        ``journal``, ``doi`` 的字典。
    """
    data = json.loads(json_path.read_text(encoding="utf-8"))
    return {
        "paper_id": data.get("id") or json_path.parent.name,
        "title": data.get("title") or "",
        "authors": data.get("authors") or [],
        "year": data.get("year"),
        "journal": data.get("journal") or "",
        "doi": data.get("doi") or "",
        "paper_type": data.get("paper_type") or "",
        "citation_count": data.get("citation_count") or {},
        "ids": data.get("ids") or {},
    }


def load_l2(json_path: Path) -> str:
    """加载 L2 层摘要文本。

    Args:
        json_path: 论文 JSON 元数据文件路径。

    Returns:
        摘要文本，无摘要时返回 ``"[No abstract available]"``。
    """
    data = json.loads(json_path.read_text(encoding="utf-8"))
    return data.get("abstract") or "[No abstract available]"


def load_l3(json_path: Path) -> str | None:
    """加载 L3 层结论文本。

    需先运行 :func:`enrich_l3` 提取结论段到 JSON。

    Args:
        json_path: 论文 JSON 元数据文件路径。

    Returns:
        结论文本，尚未提取时返回 ``None``。
    """
    data = json.loads(json_path.read_text(encoding="utf-8"))
    return data.get("l3_conclusion") or None


def load_l4(md_path: Path, *, lang: str | None = None) -> str:
    """加载 L4 层全文 Markdown，可选加载翻译版本。

    当指定 ``lang`` 时，优先加载 ``paper_{lang}.md``（如 ``paper_zh.md``），
    不存在则回退到原文 ``paper.md``。

    Args:
        md_path: MinerU 输出的 ``.md`` 文件路径。
        lang: 目标语言代码（如 ``"zh"``），为 ``None`` 时加载原文。

    Returns:
        完整 Markdown 文本。
    """
    if lang:
        # Normalize + validate lang to prevent path traversal
        try:
            from scholaraio.services.translate import validate_lang
        except ImportError:
            _log.warning("failed to import validate_lang, falling back to original", exc_info=True)
            lang = None
        else:
            try:
                lang = validate_lang(lang)
            except ValueError:
                _log.warning("invalid lang code %r, falling back to original", lang)
                lang = None
            else:
                translated = md_path.parent / f"paper_{lang}.md"
                if translated.exists():
                    return translated.read_text(encoding="utf-8", errors="replace")
    return md_path.read_text(encoding="utf-8", errors="replace")


# ============================================================================
#  Agent notes (T2 persistent analysis notes)
# ============================================================================

_NOTES_FILENAME = "notes.md"


def load_notes(paper_dir: Path) -> str | None:
    """加载论文的 agent 分析笔记。

    笔记文件 (``notes.md``) 由 agent 在分析论文时自动创建和追加，
    用于跨会话、跨工作区复用分析结论。

    Args:
        paper_dir: 论文目录路径（包含 ``meta.json`` 的目录）。

    Returns:
        笔记文本，不存在时返回 ``None``。
    """
    notes_path = paper_dir / _NOTES_FILENAME
    if notes_path.exists():
        text = notes_path.read_text(encoding="utf-8")
        if not text.strip():
            return None
        return text
    return None


def append_notes(paper_dir: Path, section: str) -> None:
    """向论文笔记文件追加一条分析记录。

    如果 ``notes.md`` 不存在则创建。每条记录之间用空行分隔。

    Args:
        paper_dir: 论文目录路径。
        section: 要追加的笔记内容（Markdown 格式，建议以 ``## 日期 | 来源`` 开头）。
    """
    notes_path = paper_dir / _NOTES_FILENAME
    section = section.rstrip("\n")
    if notes_path.exists():
        # Only add enough newlines to get exactly one blank line separator
        tail = b""
        try:
            with open(notes_path, "rb") as f:
                f.seek(0, 2)
                pos = f.tell()
                n = min(pos, 4)
                f.seek(pos - n)
                tail = f.read(n)
        except OSError:
            pass
        trailing = 0
        for i in range(len(tail) - 1, -1, -1):
            if tail[i : i + 1] == b"\n":
                trailing += 1
            else:
                break
        prefix = "\n" * max(0, 2 - trailing)
        with open(notes_path, "a", encoding="utf-8") as f:
            f.write(prefix + section + "\n")
    else:
        notes_path.write_text(section + "\n", encoding="utf-8")
    _log.debug("appended notes to %s", notes_path)


# ============================================================================
#  TOC extraction
# ============================================================================


def enrich_toc(
    json_path: Path,
    md_path: Path,
    config: Config,
    *,
    force: bool = False,
    inspect: bool = False,
) -> bool:
    """用 LLM 提取论文目录结构，写入 ``JSON["toc"]``。

    从 Markdown 中提取所有 ``#`` 标题，通过 LLM 过滤 running headers、
    期刊名、作者名等噪声，为真实节标题分配层级。

    Args:
        json_path: 论文 JSON 元数据文件路径（结果写回此文件）。
        md_path: 论文 Markdown 文件路径。
        config: 全局配置（用于 LLM 调用）。
        force: 为 ``True`` 时覆盖已有 TOC。
        inspect: 为 ``True`` 时打印过滤过程详情。

    Returns:
        提取成功返回 ``True``，失败返回 ``False``。
    """
    from scholaraio.stores.papers import read_meta, update_meta

    paper_d = json_path.parent
    data = read_meta(paper_d)

    if data.get("toc") and not force:
        _log.debug("existing TOC (%d entries), skipping", len(data["toc"]))
        return True

    lines = md_path.read_text(encoding="utf-8", errors="replace").splitlines()
    raw_headers = _extract_headers(lines)

    _log.debug("regex found %d headers", len(raw_headers))

    # Threshold: if many headers, rules are more reliable than LLM
    # (LLM struggles to output 100+ JSON entries without format errors)
    _RULE_THRESHOLD = 80

    title = data.get("title", "")
    toc: list[dict] | None = None

    if len(raw_headers) >= _RULE_THRESHOLD:
        _log.debug("header count %d >= %d, using rule-based extraction", len(raw_headers), _RULE_THRESHOLD)
        toc = _toc_from_rules(raw_headers, title)
        if toc:
            _log.debug("rule-based extraction: %d entries", len(toc))

    if toc is None:
        # LLM path for normal papers
        _log.debug("sending %d headers to LLM", len(raw_headers))
        prompt = (
            "The following are ALL lines starting with '#' extracted from an academic paper "
            "markdown file (converted from PDF by MinerU). Some are real section headers; "
            "others are NOISE to discard: author running headers (e.g. '# Smith and others'), "
            "journal name headers (e.g. '# Journal of Fluid Mechanics'), repeated paper titles, "
            "or publisher metadata (e.g. '# ARTICLEINFO', '# AFFILIATIONS', '# Articles You May Be Interested In').\n\n"
            "KEEP the following as real headers (they are needed as section boundary markers):\n"
            "- Numbered/lettered sections and subsections\n"
            "- Introduction, Abstract, Conclusion, Conclusions, Concluding Remarks, Summary\n"
            "- References, Bibliography\n"
            "- Appendix (any variant)\n"
            "- Post-matter sections: Acknowledgments, Acknowledgements, Funding, "
            "CRediT authorship contribution statement, Declaration of competing interest, "
            "Conflict of interest, Data availability, Author contributions, Author ORCIDs, "
            "Declaration of interests\n\n"
            "Assign level: 1=top-level, 2=subsection (e.g. '2.1'), 3=sub-subsection (e.g. '2.1.1').\n\n"
            "Headers:\n"
            + "\n".join(f"Line {h['line']}: {'#' * h['level']} {h['text']}" for h in raw_headers)
            + "\n\nReturn JSON only:\n"
            '{"toc": [{"line": <N>, "level": <1|2|3>, "title": "<title>"}, ...]}'
        )

        try:
            result = _parse_json(_call_llm(prompt, config, timeout=config.llm.timeout_toc))
            toc = result.get("toc") or []
        except Exception as e:
            _log.error("TOC extraction failed: %s", e)
            # fallback: try rules even for small docs
            toc = _toc_from_rules(raw_headers, title)

    if not toc:
        _log.error("could not extract TOC (both rules and LLM failed)")
        return False

    _log.debug("final TOC: %d entries", len(toc))
    for entry in toc:
        indent = "  " * (entry.get("level", 1) - 1)
        _log.debug("  line %4d  %s%s", entry["line"], indent, entry["title"])

    data["toc"] = toc
    data["toc_extracted_at"] = datetime.now().isoformat(timespec="seconds")
    update_meta(paper_d, toc=toc, toc_extracted_at=data["toc_extracted_at"])
    _log.debug("TOC written to JSON")
    return True


# ============================================================================
#  L3 extraction entry point
# ============================================================================


def enrich_l3(
    json_path: Path,
    md_path: Path,
    config: Config,
    *,
    force: bool = False,
    max_retries: int = 2,
    inspect: bool = False,
) -> bool:
    """用 LLM 提取结论段，写入 ``JSON["l3_conclusion"]``。

    提取策略（按优先级）:
      1. 从已有 TOC 定位结论节 → Python 截取 → LLM 校验清洗
      2. Primary path: LLM 从标题列表选出结论节 → 截取 → 校验
      3. Fallback path: LLM 直接给出起止行号 → 截取 → 校验

    Args:
        json_path: 论文 JSON 元数据文件路径（结果写回此文件）。
        md_path: 论文 Markdown 文件路径。
        config: 全局配置（用于 LLM 调用）。
        force: 为 ``True`` 时覆盖已有结论。
        max_retries: 每条路径的最大重试次数。
        inspect: 为 ``True`` 时打印提取过程详情。

    Returns:
        提取成功返回 ``True``，失败返回 ``False``。
    """
    from scholaraio.stores.papers import modify_meta, read_meta, update_meta

    paper_d = json_path.parent
    data = read_meta(paper_d)

    # Skip L3 for non-article types (thesis, book, document, etc.)
    paper_type = (data.get("paper_type") or "").lower().strip()
    if paper_type in L3_SKIP_TYPES:
        if data.get("l3_extraction_method") == "skipped":
            return True  # already marked, idempotent
        _log.debug("skipping L3 for paper_type=%s: %s", paper_type, paper_d.name)
        data.pop("l3_conclusion", None)  # clear stale conclusion if any
        data["l3_extraction_method"] = "skipped"
        data["l3_extracted_at"] = datetime.now().isoformat(timespec="seconds")

        def skip_l3(current):
            current.pop("l3_conclusion", None)
            current.update(l3_extraction_method="skipped", l3_extracted_at=data["l3_extracted_at"])

        modify_meta(paper_d, skip_l3)
        return True

    if data.get("l3_conclusion") and not force:
        _log.debug("existing L3 (method: %s), skipping", data.get("l3_extraction_method", "?"))
        return True

    lines = md_path.read_text(encoding="utf-8", errors="replace").splitlines()

    conclusion = method = None

    # --- Try locating conclusion via existing TOC (skip first LLM call) ---
    toc = data.get("toc")
    if toc:
        conclusion, method = _l3_from_toc(lines, toc, config, max_retries, inspect)

    # --- Primary path (when TOC is unavailable) ---
    if conclusion is None:
        headers = _extract_headers(lines)
        _log.debug("[Primary] found %d headers", len(headers))
        for h in headers:
            _log.debug("  line %4d  %s %s", h["line"], "#" * h["level"], h["text"])
        if headers:
            conclusion, method = _primary_path(lines, headers, config, max_retries, inspect)

    # --- Fallback path ---
    if conclusion is None:
        _log.debug("[Fallback] Primary path failed, switching to fallback")
        conclusion, method = _fallback_path(lines, config, max_retries, inspect)

    if conclusion is None:
        _log.error("all paths failed to extract conclusion")
        return False

    # Write back
    data["l3_conclusion"] = conclusion
    data["l3_extraction_method"] = method
    data["l3_extracted_at"] = datetime.now().isoformat(timespec="seconds")
    update_meta(paper_d, l3_conclusion=conclusion, l3_extraction_method=method, l3_extracted_at=data["l3_extracted_at"])
    _log.debug("L3 written to JSON (method: %s, %d chars)", method, len(conclusion))
    return True


# ============================================================================
#  L3 from TOC (no extra LLM call for header identification)
# ============================================================================

_CONCLUSION_KEYWORDS = re.compile(r"\b(conclusion|conclusions|concluding|summary|closing)\b", re.IGNORECASE)


def _l3_from_toc(
    lines: list[str],
    toc: list[dict],
    config: Config,
    max_retries: int,
    inspect: bool,
) -> tuple[str | None, str | None]:
    """用已有 TOC 定位结论节，Python 截取，LLM 校验。"""
    # Find conclusion entry in TOC
    conclusion_entry = None
    for entry in toc:
        if _CONCLUSION_KEYWORDS.search(entry.get("title", "")):
            conclusion_entry = entry
            break

    if not conclusion_entry:
        _log.debug("[TOC] no conclusion section found in TOC, switching to Primary")
        return None, None

    start_line = conclusion_entry["line"]
    _log.debug("[TOC] found conclusion: line %d %s", start_line, conclusion_entry["title"])

    # Find end: next TOC entry after conclusion
    end_line = None
    found = False
    for entry in toc:
        if found:
            end_line = entry["line"] - 1
            break
        if entry["line"] == start_line:
            found = True

    extracted = _slice_lines(lines, start_line, end_line)
    _log.debug("[TOC] extracted lines %d-%s, %d chars", start_line, end_line or "EOF", len(extracted))

    cleaned, reason = _validate_and_clean(extracted, config)
    _log.debug("[TOC] validate: %s %s", "PASS" if cleaned else "FAIL", reason)
    if cleaned:
        return cleaned, "toc"

    return None, None


# ============================================================================
#  Primary path
# ============================================================================


_REAL_SECTION_RE = re.compile(
    r"^(?:"
    r"\d[\d.]*[\s.]|"  # 阿拉伯数字编号: 1, 1.1, 2., etc.
    r"[IVX]+[\s.)]|"  # 罗马数字: I., II., IV.
    r"[A-F][\s.)]|"  # 字母编号: A., B.
    r"(?:abstract|introduction|method|result|discussion|"
    r"conclusion|concluding|summary|reference|bibliography|"
    r"appendix|acknowledge|funding|credit|declaration|"
    r"data\s+avail|author\s+contrib|conflict)\b"
    r")",
    re.IGNORECASE,
)


def _is_real_section(title: str) -> bool:
    """判断标题是否为真实节标题（非 running header）。"""
    return bool(_REAL_SECTION_RE.match(title.strip()))


def _extract_headers(lines: list[str]) -> list[dict]:
    """提取所有 # 标题及行号（1-indexed）。"""
    headers = []
    for i, line in enumerate(lines, start=1):
        m = re.match(r"^(#{1,4})\s+(.+)", line.rstrip())
        if m:
            headers.append({"line": i, "level": len(m.group(1)), "text": m.group(2).strip()})
    return headers


# -- regex-based TOC extraction (no LLM) ------------------------------------

# Numbered section pattern: "1", "1.2", "1.2.3", with optional trailing dot
# Also matches "1.", "2.1.", "1.2.3." (common in some journals/books)
# Allows number followed by space, CJK char, or dot-then-space
_RE_NUMBERED = re.compile(r"^(\d+(?:\.\d+)*)\.?(?:\s|(?=[\u4e00-\u9fff]))")
# "Chapter 1 Title" or Chinese "第一章" / "第1章" pattern
_RE_CHAPTER = re.compile(r"^Chapter\s+(\d+)\b", re.IGNORECASE)
_RE_CHAPTER_ZH = re.compile(r"^第\s*([一二三四五六七八九十百\d]+)\s*章")
# TOC-area entries have trailing page numbers like "Title 123" or "Title . 123"
# Require >= 2 digits to avoid matching "Chapter 1", "Part 2", etc.
_RE_TRAILING_PAGE = re.compile(r"[.\s]\s*\d{2,4}\s*$")
# Well-known structural sections (unnumbered)
_KNOWN_SECTIONS = {
    "abstract",
    "introduction",
    "preface",
    "foreword",
    "conclusion",
    "conclusions",
    "concluding remarks",
    "summary",
    "references",
    "bibliography",
    "index",
    "acknowledgments",
    "acknowledgements",
    "funding",
    "appendix",
    "glossary",
    "nomenclature",
    "notation",
}


def _toc_from_rules(raw_headers: list[dict], title: str) -> list[dict] | None:
    """Try to build TOC purely from rules. Returns list of toc entries or None.

    Strategy:
    1. Detect and skip a TOC area (headers with trailing page numbers).
    2. Filter noise: repeated paper title, author lines, metadata lines.
    3. Infer level from numbering (1 → l1, 1.2 → l2, 1.2.3 → l3).
    4. Keep well-known unnumbered sections as level 1.
    """
    if not raw_headers:
        return None

    # normalised title words for matching
    title_lower = title.lower().strip() if title else ""

    # --- pass 1: skip TOC/front-matter area ---
    # PDF books have a printed table-of-contents with trailing page numbers
    # ("1.2 Title ... 23"), followed by front-matter (preface, notation,
    # etc.) before the real body starts.  We find the last page-number
    # header in the first 10% of lines, then advance past any remaining
    # front-matter until we hit a real body-start marker.
    total_lines = raw_headers[-1]["line"] if raw_headers else 1
    toc_cutoff_line = max(total_lines * 0.10, 500)
    page_indices = [
        idx for idx, h in enumerate(raw_headers) if h["line"] <= toc_cutoff_line and _RE_TRAILING_PAGE.search(h["text"])
    ]
    if len(page_indices) >= 5:
        body_start = page_indices[-1] + 1
    else:
        body_start = 0

    # Advance past remaining front-matter noise until we hit a body-start
    # marker: "Chapter 1", numbered section "1" or "1.1", or known
    # front-matter sections (Preface, Foreword, Introduction, Notation).
    _FRONT_SECTIONS = {
        "preface",
        "foreword",
        "notation",
        "symbols",
        "acknowledgments",
        "acknowledgements",
        "introduction",
    }
    for idx in range(body_start, len(raw_headers)):
        h = raw_headers[idx]
        text = h["text"]
        text_lower = text.lower().strip()
        # "Chapter 1" or "Chapter N" or "第一章"
        if _RE_CHAPTER.match(text) or _RE_CHAPTER_ZH.match(text):
            body_start = idx
            break
        # Numbered section starting from "1" (top-level chapter)
        m = _RE_NUMBERED.match(text)
        if m and m.group(1).split(".")[0] == "1":
            body_start = idx
            break
        # Known front-matter sections that appear before Chapter 1
        if (
            text_lower.split(" to ")[0].strip().rstrip("s")
            in (
                "preface",
                "foreword",
                "notation",
                "symbol",
                "acknowledgment",
                "acknowledgement",
            )
            or text_lower.startswith("preface")
            or text_lower
            in (
                "摘要",
                "前言",
                "序言",
                "绪论",
            )
        ):
            body_start = idx
            break
    body_headers = raw_headers[body_start:]

    if not body_headers:
        body_headers = raw_headers  # fallback: no TOC area detected

    # --- pass 2: detect running headers (appear >= 3 times) ---
    from collections import Counter

    text_counts = Counter(h["text"].lower().strip() for h in body_headers)
    running_headers = {t for t, c in text_counts.items() if c >= 3}

    # --- pass 3: filter noise ---
    toc = []
    for h in body_headers:
        text = h["text"]
        text_lower = text.lower().strip()

        # skip running headers (repeated page headers from PDF)
        if text_lower in running_headers:
            continue

        # skip if it matches the paper/book title
        if title_lower and _similar_title(text_lower, title_lower):
            continue
        # skip common metadata noise
        if text_lower in (
            "contents",
            "table of contents",
            "acronyms",
            "abbreviations",
            "articleinfo",
            "affiliations",
            "目录",
            "插图目录",
            "表格目录",
        ):
            continue

        # --- infer level ---
        m_num = _RE_NUMBERED.match(text)
        m_chap = _RE_CHAPTER.match(text)
        m_chap_zh = _RE_CHAPTER_ZH.match(text)
        if m_chap:
            # "Chapter 3 Title" → level 1, strip "Chapter N" prefix for clean title
            clean = text[m_chap.end() :].strip()
            num = m_chap.group(1)
            final_title = f"{num} {clean}" if clean else f"Chapter {num}"
            toc.append({"line": h["line"], "level": 1, "title": final_title})
        elif m_chap_zh:
            # "第一章 绪论" → level 1, keep original text
            toc.append({"line": h["line"], "level": 1, "title": text})
        elif m_num:
            num_str = m_num.group(1)
            depth = num_str.count(".") + 1  # "1"→1, "1.2"→2, "1.2.3"→3
            level = min(depth, 3)
            # strip trailing page-number-like remnants (shouldn't exist in body, but be safe)
            clean_text = _RE_TRAILING_PAGE.sub("", text).strip().rstrip(".")
            toc.append({"line": h["line"], "level": level, "title": clean_text})
        elif (
            text_lower.split(",")[0].strip() in _KNOWN_SECTIONS
            or any(text_lower.startswith(s) for s in ("appendix",))
            or text
            in (
                "摘要",
                "前言",
                "绪论",
                "结论",
                "总结",
                "参考文献",
                "致谢",
                "附录",
            )
        ):
            toc.append({"line": h["line"], "level": 1, "title": text})
        # else: skip (unnumbered, unknown → likely noise)

    return toc if toc else None


def _similar_title(a: str, b: str) -> bool:
    """Check if two titles are similar enough to be considered duplicates."""
    # simple: one contains the other, or >80% word overlap
    if a == b or a in b or b in a:
        return True
    wa, wb = set(a.split()), set(b.split())
    if not wa or not wb:
        return False
    overlap = len(wa & wb) / max(len(wa), len(wb))
    return overlap > 0.8


def _primary_path(
    lines: list[str],
    headers: list[dict],
    config: Config,
    max_retries: int,
    inspect: bool,
) -> tuple[str | None, str | None]:
    header_list = "\n".join(f"Line {h['line']}: {'#' * h['level']} {h['text']}" for h in headers)
    prompt = (
        "Below are all section headers (with line numbers) from an academic paper markdown file.\n"
        "Identify the header that marks the START of the conclusion section "
        "(may be named 'Conclusion', 'Conclusions', 'Concluding Remarks', 'Summary', etc.).\n\n"
        f"{header_list}\n\n"
        'Return JSON only: {"line": <line_number>, "header": "<header_text>"}\n'
        'If no conclusion section exists, return: {"line": null, "header": null}'
    )

    # 1 initial attempt + max_retries retries; range(1, ...) so attempt number is 1-based
    for attempt in range(1, max_retries + 2):
        try:
            result = _parse_json(_call_llm(prompt, config))
            start_line = result.get("line")
            if not start_line:
                _log.debug("[Primary #%d] LLM found no conclusion", attempt)
                return None, None

            # Find end: next REAL section header after start_line
            # Skip running headers (no section number, short text)
            end_line = None
            for h in headers:
                if h["line"] > start_line and _is_real_section(h["text"]):
                    end_line = h["line"] - 1
                    break

            extracted = _slice_lines(lines, start_line, end_line)
            _log.debug(
                "[Primary #%d] extracted lines %d-%s, %d chars", attempt, start_line, end_line or "EOF", len(extracted)
            )

            cleaned, reason = _validate_and_clean(extracted, config)
            _log.debug("[Primary #%d] validate: %s %s", attempt, "PASS" if cleaned else "FAIL", reason)
            if cleaned:
                return cleaned, f"primary-attempt{attempt}"

        except Exception as e:
            _log.debug("[Primary #%d] exception: %s", attempt, e)

    return None, None


# ============================================================================
#  Fallback path
# ============================================================================


def _fallback_path(
    lines: list[str],
    config: Config,
    max_retries: int,
    inspect: bool,
) -> tuple[str | None, str | None]:
    n = len(lines)

    # Send first 100 + last 200 lines (conclusion is usually near the end)
    if n <= 300:
        sample = "\n".join(f"{i + 1}: {l}" for i, l in enumerate(lines))
    else:
        head = "\n".join(f"{i + 1}: {l}" for i, l in enumerate(lines[:100]))
        tail_start = max(100, n - 200)
        tail = "\n".join(f"{tail_start + i + 1}: {l}" for i, l in enumerate(lines[tail_start:]))
        sample = f"[Lines 1–100]\n{head}\n\n...[中间省略]...\n\n[Lines {tail_start + 1}–{n}]\n{tail}"

    prompt = (
        "Find the conclusion section in this academic paper (markdown format). "
        "Return the 1-indexed line number where the conclusion STARTS and where it ENDS "
        "(last line before References/Appendix/end of file).\n\n"
        f"{sample}\n\n"
        'Return JSON only: {"start_line": <N>, "end_line": <N>}\n'
        'If no conclusion exists, return: {"start_line": null, "end_line": null}'
    )

    # 1 initial attempt + max_retries retries; range(1, ...) so attempt number is 1-based
    for attempt in range(1, max_retries + 2):
        try:
            result = _parse_json(_call_llm(prompt, config))
            start_line = result.get("start_line")
            end_line = result.get("end_line")
            if not start_line:
                _log.debug("[Fallback #%d] LLM found no conclusion", attempt)
                return None, None

            extracted = _slice_lines(lines, start_line, end_line)
            _log.debug(
                "[Fallback #%d] extracted lines %d-%s, %d chars", attempt, start_line, end_line or "EOF", len(extracted)
            )

            cleaned, reason = _validate_and_clean(extracted, config)
            _log.debug("[Fallback #%d] validate: %s %s", attempt, "PASS" if cleaned else "FAIL", reason)
            if cleaned:
                return cleaned, f"fallback-attempt{attempt}"

        except Exception as e:
            _log.debug("[Fallback #%d] exception: %s", attempt, e)

    return None, None


# ============================================================================
#  LLM validation + cleaning
# ============================================================================


def _validate_and_clean(text: str, config: Config) -> tuple[str | None, str]:
    """校验并清理提取的结论文本。

    返回 (cleaned_text, reason)：
    - cleaned_text 为 None 表示文本不包含有效结论内容
    - cleaned_text 为清理后的纯结论文本（去除标题行、Acknowledgments 等）
    """
    if len(text.strip()) < 100:
        return None, "文本过短"

    prompt = (
        "The following text was extracted as the conclusion section of an academic paper. "
        "Your tasks:\n"
        "1. Check if it contains actual conclusion content (summary of findings, contributions, or future work).\n"
        "2. If yes, return a CLEANED version:\n"
        "   - Remove the section header line (e.g. '# 6. Conclusion', '# Concluding Remarks')\n"
        "   - Remove any in-text running headers (e.g. '# Author and others', '# Journal Name')\n"
        "   - Remove everything AFTER the conclusion ends: Acknowledgments, Funding statements, "
        "CRediT authorship statements, Declaration of interests/competing interest, "
        "Data availability, Author ORCIDs, Author contributions, conflict of interest, etc.\n"
        "   - Keep only the actual conclusion/summary paragraphs. Do NOT truncate mid-sentence.\n"
        "3. If it contains NO conclusion content at all, set conclusion to null.\n\n"
        f"{text}\n\n"
        'Return JSON only: {"conclusion": "<cleaned text or null>", "reason": "<one sentence>"}'
    )
    try:
        result = _parse_json(_call_llm(prompt, config, timeout=config.llm.timeout_clean))
        cleaned = result.get("conclusion")
        reason = result.get("reason") or ""
        if not cleaned or len(cleaned.strip()) < 50:
            return None, reason or "无有效结论内容"
        return cleaned.strip(), reason
    except Exception as e:
        return None, f"校验异常：{e}"


# ============================================================================
#  LLM + JSON utilities
# ============================================================================


def _call_llm(prompt: str, config: Config, timeout: int | None = None) -> str:
    from scholaraio.services.metrics import call_llm

    result = call_llm(prompt, config, timeout=timeout, purpose="loader")
    return result.content


def _parse_json(text: str) -> dict:
    text = text.strip()
    # Strip markdown code fences if present
    text = re.sub(r"^```\w*\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Fix unescaped backslashes (e.g. LaTeX: \alpha, \vec, \frac).
        # Only runs when initial parse fails. Valid JSON escapes are
        # preserved: \" \\ \/ \b \f \n \r \t \uXXXX
        fixed = re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", text)
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            # If escaping made things worse, raise with original text
            return json.loads(text)


def _slice_lines(lines: list[str], start: int, end: int | None) -> str:
    """1-indexed, inclusive on both ends."""
    s = max(0, start - 1)
    e = end if end is not None else len(lines)
    return "\n".join(lines[s:e]).strip()
