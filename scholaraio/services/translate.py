"""
translate.py — 论文 Markdown 自动翻译
======================================

将非目标语言的论文 Markdown 翻译为目标语言（默认中文），
保留 LaTeX 公式、代码块、图片引用和 Markdown 格式。

翻译结果保存为 ``paper_{lang}.md``（如 ``paper_zh.md``），
原文 ``paper.md`` 保持不变。

单篇翻译会按 ``config.translate.concurrency`` 并发请求多个分块，
将中间结果持久化到临时工作目录，并按原顺序推进最终输出。
当启用 portable 导出时，还会额外生成
``config.translation_bundle_root/<paper-dir>/`` 可移植包；
默认位于 ``workspace/_system/translation-bundles/<paper-dir>/``。

用法：
    from scholaraio.services.translate import translate_paper, batch_translate
    translate_paper(paper_dir, config)
    batch_translate(papers_dir, config)
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import time
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

import requests

if TYPE_CHECKING:
    from scholaraio.core.config import Config

_log = logging.getLogger(__name__)

# Strict pattern for language codes — prevents path traversal via lang parameter
_LANG_CODE_RE = re.compile(r"^[a-z]{2,5}$")

# Language name mapping for prompts
_LANG_NAMES = {
    "zh": "中文",
    "en": "English",
    "ja": "日本語",
    "ko": "한국어",
    "de": "Deutsch",
    "fr": "Français",
    "es": "Español",
}

# ============================================================================
#  Language detection (lightweight heuristic, no extra dependency)
# ============================================================================

# CJK Unicode ranges
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
_HANGUL_RE = re.compile(r"[\uac00-\ud7af]")
_KANA_RE = re.compile(r"[\u3040-\u309f\u30a0-\u30ff]")
_LATIN_WORD_RE = re.compile(r"[a-zA-ZÀ-ÿ]+")
_LATIN_STOPWORDS: dict[str, set[str]] = {
    "en": {"the", "and", "of", "to", "in", "for", "with", "is", "that", "this"},
    "de": {"der", "die", "das", "und", "ist", "mit", "eine", "ein", "den", "von"},
    "fr": {"le", "la", "les", "de", "des", "et", "une", "un", "dans", "pour"},
    "es": {"el", "la", "los", "las", "de", "del", "y", "una", "un", "para"},
}


def detect_language(text: str) -> str:
    """Detect the primary language of text using character-class heuristics.

    Args:
        text: Input text (first ~2000 chars are examined).

    Returns:
        ISO 639-1 code: ``"zh"``, ``"ja"``, ``"ko"``, ``"en"``, ``"de"``,
        ``"fr"``, or ``"es"``. Falls back to ``"en"`` when uncertain.
    """
    sample = text[:2000]
    # Strip code blocks and LaTeX to avoid false positives
    sample = re.sub(r"```[\s\S]*?```", "", sample)
    sample = re.sub(r"\$\$[\s\S]*?\$\$", "", sample)
    sample = re.sub(r"\$[^$]+\$", "", sample)

    cjk_count = len(_CJK_RE.findall(sample))
    hangul_count = len(_HANGUL_RE.findall(sample))
    kana_count = len(_KANA_RE.findall(sample))

    total_alpha = sum(1 for c in sample if c.isalpha())
    if total_alpha == 0:
        return "en"

    # Japanese: kana alone (hiragana/katakana-heavy text with few kanji)
    if kana_count / total_alpha > 0.1:
        return "ja"
    if cjk_count / total_alpha > 0.15:
        # Mixed CJK+kana → Japanese; pure CJK → Chinese
        if kana_count > cjk_count * 0.1:
            return "ja"
        return "zh"
    if hangul_count / total_alpha > 0.15:
        return "ko"

    # Lightweight Latin-script detection for same-language skip logic.
    # This is intentionally conservative; if scores tie or are weak,
    # default to English rather than making a brittle claim.
    words = [w.lower() for w in _LATIN_WORD_RE.findall(sample)]
    if words:
        scores = {lang: sum(1 for w in words if w in stopwords) for lang, stopwords in _LATIN_STOPWORDS.items()}
        best_lang, best_score = max(scores.items(), key=lambda item: item[1])
        if best_score >= 2:
            top_tied = sum(1 for score in scores.values() if score == best_score)
            if top_tied == 1:
                return best_lang
    return "en"


# ============================================================================
#  Chunking (preserve markdown structure)
# ============================================================================

# Combined pattern for protected blocks (code fences, display/inline math, images).
# Order matters: display math ($$...$$) must be matched before inline math ($...$)
# to avoid consuming the opening $$ as two inline $ tokens.
_PROTECTED_RE = re.compile(
    r"(```[\s\S]*?```|\$\$[\s\S]*?\$\$|(?<!\$)\$(?!\$)(?:[^$\\]|\\.)+\$(?!\$)|!\[.*?\]\(.*?\))",
    re.MULTILINE,
)

_PLACEHOLDER_FMT = "\x00PROTECTED_{}\x00"
_PLACEHOLDER_RE = re.compile(r"\x00PROTECTED_(\d+)\x00")


def _hard_split(text: str, chunk_size: int) -> list[str]:
    """Split an oversized text block into pieces targeting chunk_size.

    Tries sentence boundaries first (``". "``), falls back to hard cut.
    Avoids cutting through ``\\x00PROTECTED_N\\x00`` placeholder tokens.
    A piece may exceed chunk_size only if a single placeholder token is
    longer than chunk_size (unavoidable).
    """
    if len(text) <= chunk_size:
        return [text]
    parts: list[str] = []
    while len(text) > chunk_size:
        cut = text.rfind(". ", 0, chunk_size)
        if cut == -1 or cut < chunk_size // 4:
            cut = chunk_size  # hard cut
        else:
            cut += 2  # include ". "
        # Ensure we don't split inside a placeholder token
        orig_cut = cut
        cut = _adjust_for_placeholder(text, cut)
        # If placeholder adjustment pushed cut beyond chunk_size, split
        # *before* the placeholder instead (unless that gives us nothing).
        if cut > orig_cut and cut > chunk_size:
            before_placeholder = text.rfind("\x00PROTECTED_", 0, orig_cut)
            if before_placeholder > 0:
                cut = before_placeholder
        parts.append(text[:cut])
        text = text[cut:]
    if text:
        parts.append(text)
    return parts


def _adjust_for_placeholder(text: str, cut: int) -> int:
    """Move cut point outside any placeholder span it would bisect."""
    # Find the last placeholder start before cut
    last_start = text.rfind("\x00PROTECTED_", 0, cut)
    if last_start == -1:
        return cut
    # Find the closing NUL of that placeholder
    end = text.find("\x00", last_start + 1)
    if end == -1:
        return cut
    end += 1  # include the closing NUL
    if cut < end:
        # cut falls inside the placeholder — move past it
        return end
    return cut


def _split_into_chunks(text: str, chunk_size: int) -> list[str]:
    """Split markdown text into translatable chunks respecting structure.

    Protected blocks (code fences, display math ``$$...$$``, inline math
    ``$...$``, and images) are replaced with placeholders before splitting
    to prevent them from being broken across chunks. After splitting,
    placeholders are restored.

    Args:
        text: Full markdown text.
        chunk_size: Target maximum chunk size in characters.

    Returns:
        List of text chunks.
    """
    # Mask protected blocks with placeholders
    protected: list[str] = []

    def _mask(m: re.Match) -> str:
        idx = len(protected)
        protected.append(m.group(0))
        return _PLACEHOLDER_FMT.format(idx)

    masked = _PROTECTED_RE.sub(_mask, text)

    # Split on paragraph boundaries (filter empty strings from leading/trailing blanks)
    paragraphs = [p for p in re.split(r"\n{2,}", masked) if p.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para)
        # Oversized paragraph: flush current, then hard-split the paragraph
        if para_len > chunk_size:
            if current:
                chunks.append("\n\n".join(current))
                current = []
                current_len = 0
            # Split on sentence boundaries or hard-cut
            for frag in _hard_split(para, chunk_size):
                chunks.append(frag)
            continue
        if current_len + para_len > chunk_size and current:
            chunks.append("\n\n".join(current))
            current = []
            current_len = 0
        current.append(para)
        current_len += para_len + 2  # +2 for \n\n

    if current:
        chunks.append("\n\n".join(current))

    # Restore protected blocks in each chunk; warn if restoration inflates beyond limit
    def _restore(chunk: str) -> str:
        return _PLACEHOLDER_RE.sub(lambda m: protected[int(m.group(1))], chunk)

    restored = [_restore(c) for c in chunks]
    for i, c in enumerate(restored):
        if len(c) > chunk_size * 2:
            _log.warning(
                "chunk %d/%d restored to %d chars (limit %d) due to large protected blocks",
                i + 1,
                len(restored),
                len(c),
                chunk_size,
            )
    return restored


# ============================================================================
#  Translation via LLM
# ============================================================================

_TRANSLATE_PROMPT_HEADER = """\
翻译以下学术论文段落至{target_lang}。

重要事项：
- 保留所有 markdown 格式（#, **, ``, [links]、表格等）
- 保留 LaTeX 公式（$...$, $$...$$）不翻译
- 保留代码块（```...```）不翻译
- 保留图片引用（![...](...)）不翻译
- 保留作者姓名和引用格式（如 [Smith et al., 2023]）"""

_TRANSLATE_PROMPT_FOOTER = """\
- 只返回翻译文本，不要任何解释

原文：
{text}"""

# Terminology annotation rules per target language
_TERMINOLOGY_RULES: dict[str, str] = {
    "zh": "- 对于专业术语，在首次出现时用「英文 (中文翻译)」格式",
    "ja": "- 専門用語は初出時に「英語 (日本語訳)」の形式で記載すること",
    "ko": "- 전문 용어는 처음 등장할 때 「영어 (한국어 번역)」 형식을 사용",
}


def _build_translate_prompt(text: str, target_lang: str, lang_name: str) -> str:
    """Build the translation prompt with language-appropriate terminology rule."""
    header = _TRANSLATE_PROMPT_HEADER.format(target_lang=lang_name)
    rule = _TERMINOLOGY_RULES.get(target_lang)
    parts = [header]
    if rule:
        parts.append(rule)
    parts.append(_TRANSLATE_PROMPT_FOOTER.format(text=text))
    return "\n".join(parts)


def _translate_chunk(text: str, target_lang: str, config: Config, timeout: int | None = None) -> str:
    """Translate a single chunk via LLM.

    Args:
        text: Text chunk to translate.
        target_lang: Target language code.
        config: Global config for LLM access.
        timeout: Optional timeout override.

    Returns:
        Translated text.
    """
    from scholaraio.services.metrics import call_llm

    lang_name = _LANG_NAMES.get(target_lang, target_lang)
    prompt = _build_translate_prompt(text, target_lang, lang_name)
    result = call_llm(
        prompt,
        config,
        json_mode=False,
        timeout=timeout or config.llm.timeout_clean,
        purpose="translate",
    )
    return result.content.strip()


# ============================================================================
#  Public API
# ============================================================================


# Skip reason constants for TranslateResult
SKIP_NO_MD = "no_paper_md"
SKIP_ALREADY_EXISTS = "already_exists"
SKIP_EMPTY = "empty_source"
SKIP_SAME_LANG = "same_language"
SKIP_ALL_CHUNKS_FAILED = "all_chunks_failed"

CHUNK_STATUS_PENDING = "pending"
CHUNK_STATUS_SUCCESS = "success"
CHUNK_STATUS_FAILED = "failed"
DEFAULT_TRANSLATE_MAX_ATTEMPTS = 5
DEFAULT_TRANSLATE_BACKOFF_BASE = 1.0
DEFAULT_TRANSLATE_SPLIT_TIMEOUT_ATTEMPTS = 2


def validate_lang(lang: str) -> str:
    """Validate, normalize, and return a safe language code.

    Normalizes to lowercase and strips whitespace before validation,
    so config values like ``"ZH"`` or ``" zh "`` are accepted.

    Raises:
        ValueError: If ``lang`` is not a string, or doesn't match the
            ``[a-z]{2,5}`` pattern (ISO 639-1/3) after normalization.
    """
    if not isinstance(lang, str):
        raise ValueError(f"invalid language code type: {type(lang).__name__} (expected string)")
    lang = lang.lower().strip()
    if not _LANG_CODE_RE.match(lang):
        raise ValueError(f"invalid language code: {lang!r} (expected 2-5 lowercase letters)")
    return lang


@dataclass
class TranslateResult:
    """Thread-safe result from :func:`translate_paper`.

    Attributes:
        path: Path to the translated file, or ``None`` if skipped/failed.
        portable_path: Path to the optional portable bundle markdown, or ``None``.
        skip_reason: Why the translation was skipped (one of ``SKIP_*`` constants),
            or empty string if translated successfully.
        partial: ``True`` when translation was interrupted after some chunks were
            written, so the output is resumable but incomplete.
    """

    path: Path | None = None
    portable_path: Path | None = None
    skip_reason: str = ""
    partial: bool = False
    completed_chunks: int = 0
    total_chunks: int = 0

    @property
    def ok(self) -> bool:
        return self.path is not None and not self.partial


def _translation_workdir(paper_dir: Path, lang: str) -> Path:
    return paper_dir / f".translate_{lang}"


def _source_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_json_atomic(path: Path, payload: dict) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _write_translated_output(out_path: Path, translated_chunks: list[str]) -> None:
    out_path.write_text("\n\n".join(translated_chunks), encoding="utf-8")


def _translation_state_path(workdir: Path) -> Path:
    return workdir / "state.json"


def _translation_chunks_path(workdir: Path) -> Path:
    return workdir / "chunks.json"


def _translation_parts_dir(workdir: Path) -> Path:
    return workdir / "parts"


def _translation_part_path(workdir: Path, index: int) -> Path:
    return _translation_parts_dir(workdir) / f"{index + 1:06d}.md"


def _load_translation_state(state_path: Path) -> dict | None:
    if not state_path.exists():
        return None
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _build_chunk_digests(chunks: list[str]) -> list[str]:
    return [hashlib.sha256(chunk.encode("utf-8")).hexdigest() for chunk in chunks]


def _write_chunk_part(part_path: Path, text: str) -> None:
    part_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = part_path.with_suffix(".md.tmp")
    tmp_path.write_text(text, encoding="utf-8")
    tmp_path.replace(part_path)


def _build_translation_state(
    workdir: Path,
    *,
    lang: str,
    source_digest: str,
    chunk_size: int,
    chunk_digests: list[str],
) -> dict:
    _translation_parts_dir(workdir).mkdir(parents=True, exist_ok=True)
    chunks_meta = []
    for idx in range(len(chunk_digests)):
        chunks_meta.append(
            {
                "index": idx,
                "status": CHUNK_STATUS_PENDING,
                "attempts": 0,
                "error": "",
                "part": f"parts/{idx + 1:06d}.md",
            }
        )
    return {
        "target_lang": lang,
        "source_digest": source_digest,
        "chunk_size": chunk_size,
        "total_chunks": len(chunk_digests),
        "chunk_digests": chunk_digests,
        "chunks": chunks_meta,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }


def _write_translation_workspace_files(workdir: Path, state: dict, chunks: list[str]) -> None:
    chunk_digests = state["chunk_digests"]
    _write_json_atomic(
        _translation_chunks_path(workdir),
        {
            "target_lang": state["target_lang"],
            "source_digest": state["source_digest"],
            "chunk_size": state["chunk_size"],
            "total_chunks": state["total_chunks"],
            "chunks": [
                {
                    "index": idx,
                    "chars": len(chunk),
                    "digest": chunk_digests[idx],
                }
                for idx, chunk in enumerate(chunks)
            ],
        },
    )
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _write_json_atomic(_translation_state_path(workdir), state)


def _load_or_init_translation_workspace(
    paper_dir: Path,
    *,
    lang: str,
    force: bool,
    out_path: Path,
    source_digest: str,
    chunk_size: int,
    chunks: list[str],
) -> dict:
    workdir = _translation_workdir(paper_dir, lang)
    if force:
        shutil.rmtree(workdir, ignore_errors=True)
        out_path.unlink(missing_ok=True)

    chunk_digests = _build_chunk_digests(chunks)
    state = _load_translation_state(_translation_state_path(workdir))
    is_valid = (
        isinstance(state, dict)
        and state.get("target_lang") == lang
        and state.get("source_digest") == source_digest
        and state.get("chunk_size") == chunk_size
        and state.get("total_chunks") == len(chunks)
        and state.get("chunk_digests") == chunk_digests
        and isinstance(state.get("chunks"), list)
        and len(state["chunks"]) == len(chunks)
    )
    if is_valid:
        return cast(dict, state)

    shutil.rmtree(workdir, ignore_errors=True)
    workdir.mkdir(parents=True, exist_ok=True)
    state = _build_translation_state(
        workdir,
        lang=lang,
        source_digest=source_digest,
        chunk_size=chunk_size,
        chunk_digests=chunk_digests,
    )
    _write_translation_workspace_files(workdir, state, chunks)
    return state


def _load_success_prefix(workdir: Path, state: dict) -> list[str]:
    translated_chunks: list[str] = []
    for idx, entry in enumerate(state.get("chunks", [])):
        if entry.get("status") != CHUNK_STATUS_SUCCESS:
            break
        part_path = _translation_part_path(workdir, idx)
        if not part_path.exists():
            break
        translated_chunks.append(part_path.read_text(encoding="utf-8"))
    return translated_chunks


def _persist_prefix_output(out_path: Path, translated_chunks: list[str]) -> None:
    if translated_chunks:
        _write_translated_output(out_path, translated_chunks)
    else:
        out_path.unlink(missing_ok=True)


def _count_successful_chunks(state: dict) -> int:
    return sum(1 for entry in state.get("chunks", []) if entry.get("status") == CHUNK_STATUS_SUCCESS)


def _is_timeout_like_translate_error(exc: Exception) -> bool:
    return isinstance(exc, (TimeoutError, requests.Timeout))


def _subdivide_chunk_for_retry(text: str, chunk_size: int) -> list[str]:
    target_size = max(1, min(chunk_size, max(1, len(text) // 2)))
    if target_size >= len(text):
        return [text]
    queue = [text]
    result: list[str] = []
    while queue:
        current = queue.pop(0)
        if len(current) <= target_size:
            result.append(current)
            continue
        subchunks = _split_into_chunks(current, target_size)
        if len(subchunks) <= 1 or subchunks == [current]:
            subchunks = _hard_split(current, target_size)
        if len(subchunks) <= 1 or subchunks == [current]:
            result.append(current)
            continue
        queue = subchunks + queue
    return result


def _translate_chunk_with_retry(
    text: str,
    target_lang: str,
    config: Config,
    *,
    timeout: int | None = None,
    max_attempts: int = DEFAULT_TRANSLATE_MAX_ATTEMPTS,
    backoff_base: float = DEFAULT_TRANSLATE_BACKOFF_BASE,
) -> tuple[str, int]:
    attempts = 0
    while True:
        attempts += 1
        try:
            if timeout is None:
                return _translate_chunk(text, target_lang, config), attempts
            return _translate_chunk(text, target_lang, config, timeout=timeout), attempts
        except Exception:
            if attempts >= max_attempts:
                raise
            time.sleep(backoff_base * (2 ** (attempts - 1)))


def _translate_chunk_resilient(
    text: str,
    target_lang: str,
    config: Config,
    *,
    chunk_size: int,
    timeout: int | None = None,
    max_attempts: int = DEFAULT_TRANSLATE_MAX_ATTEMPTS,
    backoff_base: float = DEFAULT_TRANSLATE_BACKOFF_BASE,
) -> tuple[str, int]:
    subchunks = _subdivide_chunk_for_retry(text, chunk_size)
    split_retry_budget = (
        min(max_attempts, DEFAULT_TRANSLATE_SPLIT_TIMEOUT_ATTEMPTS) if len(subchunks) > 1 else max_attempts
    )
    try:
        return _translate_chunk_with_retry(
            text,
            target_lang,
            config,
            timeout=timeout,
            max_attempts=split_retry_budget,
            backoff_base=backoff_base,
        )
    except Exception as exc:
        if not _is_timeout_like_translate_error(exc):
            raise
        if len(subchunks) <= 1:
            raise
        _log.warning(
            "translate chunk timed out after retries (%d chars); retrying as %d subchunks",
            len(text),
            len(subchunks),
        )
        translated_parts: list[str] = []
        total_attempts = split_retry_budget
        for subchunk in subchunks:
            translated, used_attempts = _translate_chunk_resilient(
                subchunk,
                target_lang,
                config,
                chunk_size=max(1, min(chunk_size, len(subchunk))),
                timeout=timeout,
                max_attempts=max_attempts,
                backoff_base=backoff_base,
            )
            translated_parts.append(translated)
            total_attempts += used_attempts
        return "\n\n".join(translated_parts), total_attempts


def _portable_bundle_dir(config: Config, paper_dir: Path) -> Path:
    """Return the portable bundle directory for a paper."""
    translation_bundle_root = getattr(config, "translation_bundle_root", None)
    if translation_bundle_root is not None:
        return Path(translation_bundle_root) / paper_dir.name
    workspace_dir = getattr(config, "workspace_dir", None)
    if workspace_dir is None:
        workspace_dir = paper_dir.parent.parent / "workspace"
    return Path(workspace_dir) / "_system" / "translation-bundles" / paper_dir.name


def _write_portable_translation_bundle(config: Config, paper_dir: Path, out_path: Path) -> Path:
    """Create a portable translation bundle under ``config.translation_bundle_root/<paper>/``.

    The translated markdown is copied to
    ``config.translation_bundle_root/<paper>/<paper_{lang}.md>`` and any sibling
    ``images/`` directory is copied alongside it so relative image links remain
    valid when the bundle is moved elsewhere.
    """
    bundle_dir = _portable_bundle_dir(config, paper_dir)
    bundle_dir.mkdir(parents=True, exist_ok=True)

    portable_path = bundle_dir / out_path.name
    shutil.copy2(out_path, portable_path)

    src_images = paper_dir / "images"
    if src_images.is_dir():
        dst_images = bundle_dir / "images"
        for src in src_images.rglob("*"):
            rel = src.relative_to(src_images)
            dst = dst_images / rel
            if src.is_dir():
                dst.mkdir(parents=True, exist_ok=True)
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)

    return portable_path


def translate_paper(
    paper_dir: Path,
    config: Config,
    *,
    target_lang: str | None = None,
    force: bool = False,
    portable: bool = False,
    chunk_workers: int | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> TranslateResult:
    """Translate a paper's markdown to the target language.

    The translation is saved as ``paper_{lang}.md`` in the same directory.
    Original ``paper.md`` is preserved.

    Args:
        paper_dir: Paper directory containing ``paper.md``.
        config: Global config.
        target_lang: Target language code, defaults to ``config.translate.target_lang``.
        force: Re-translate even if translation file already exists.

    Returns:
        :class:`TranslateResult` with ``path`` (or ``None``) and ``skip_reason``.
    """

    def report(message: str) -> None:
        if progress_callback is not None:
            progress_callback(message)

    lang = validate_lang(target_lang or config.translate.target_lang)
    md_path = paper_dir / "paper.md"
    out_path = paper_dir / f"paper_{lang}.md"
    workdir = _translation_workdir(paper_dir, lang)

    if not md_path.exists():
        _log.debug("no paper.md in %s, skipping", paper_dir.name)
        return TranslateResult(skip_reason=SKIP_NO_MD)

    text = md_path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        return TranslateResult(skip_reason=SKIP_EMPTY)

    # Detect source language — skip if already target
    src_lang = detect_language(text)
    if src_lang == lang:
        _log.debug("paper already in target language (%s), skipping", lang)
        return TranslateResult(skip_reason=SKIP_SAME_LANG)

    # Chunk and translate
    chunk_size = config.translate.chunk_size
    chunks = _split_into_chunks(text, chunk_size)
    total_chunks = len(chunks)
    source_digest = _source_digest(text)
    _log.debug("translating %s: %d chunks, target=%s", paper_dir.name, len(chunks), lang)

    if not force and not workdir.exists() and out_path.exists():
        _log.debug("translation already exists: %s", out_path.name)
        portable_path = _write_portable_translation_bundle(config, paper_dir, out_path) if portable else None
        if portable_path is not None:
            return TranslateResult(
                path=out_path,
                portable_path=portable_path,
                completed_chunks=total_chunks,
                total_chunks=total_chunks,
            )
        return TranslateResult(skip_reason=SKIP_ALREADY_EXISTS)

    state = _load_or_init_translation_workspace(
        paper_dir,
        lang=lang,
        force=force,
        out_path=out_path,
        source_digest=source_digest,
        chunk_size=chunk_size,
        chunks=chunks,
    )
    translated_chunks = _load_success_prefix(workdir, state)
    start_idx = len(translated_chunks)
    _persist_prefix_output(out_path, translated_chunks)

    if start_idx > 0 and start_idx < total_chunks:
        report(f"Resuming translation: completed {start_idx}/{total_chunks} chunks")
    elif start_idx == 0:
        report(f"Starting translation: {total_chunks} chunks")

    all_success = start_idx == total_chunks and total_chunks > 0
    if all_success:
        _record_translation_meta(paper_dir, lang, src_lang, config, partial=False)
        portable_path = _write_portable_translation_bundle(config, paper_dir, out_path) if portable else None
        shutil.rmtree(workdir, ignore_errors=True)
        report(f"Translation completed: {total_chunks}/{total_chunks} chunks")
        return TranslateResult(
            path=out_path,
            portable_path=portable_path,
            completed_chunks=total_chunks,
            total_chunks=total_chunks,
        )

    worker_budget = chunk_workers if chunk_workers is not None else getattr(config.translate, "concurrency", 1)
    workers = max(1, int(worker_budget or 1))
    pending_indices = [idx for idx, entry in enumerate(state["chunks"]) if entry.get("status") != CHUNK_STATUS_SUCCESS]
    prev_prefix = start_idx
    prev_completed = _count_successful_chunks(state)

    if pending_indices:
        with ThreadPoolExecutor(max_workers=min(workers, len(pending_indices))) as pool:
            in_flight = {
                pool.submit(
                    _translate_chunk_resilient,
                    chunks[idx],
                    lang,
                    config,
                    chunk_size=chunk_size,
                ): idx
                for idx in pending_indices
            }
            while in_flight:
                done, _ = wait(in_flight, return_when=FIRST_COMPLETED)
                for fut in done:
                    idx = in_flight.pop(fut)
                    entry = state["chunks"][idx]
                    try:
                        translated, used_attempts = fut.result()
                        _write_chunk_part(_translation_part_path(workdir, idx), translated)
                        entry["status"] = CHUNK_STATUS_SUCCESS
                        entry["attempts"] = int(entry.get("attempts", 0) or 0) + used_attempts
                        entry["error"] = ""
                        _log.debug("  chunk %d/%d done (%d chars)", idx + 1, len(chunks), len(translated))
                    except Exception as e:
                        entry["status"] = CHUNK_STATUS_FAILED
                        entry["attempts"] = int(entry.get("attempts", 0) or 0) + DEFAULT_TRANSLATE_MAX_ATTEMPTS
                        entry["error"] = str(e)
                        _log.error("  chunk %d/%d failed after retries: %s", idx + 1, len(chunks), e)
                    _write_translation_workspace_files(workdir, state, chunks)

                translated_chunks = _load_success_prefix(workdir, state)
                prefix_count = len(translated_chunks)
                completed_count = _count_successful_chunks(state)
                if prefix_count != prev_prefix:
                    _persist_prefix_output(out_path, translated_chunks)
                    report(f"Translation progress: {prefix_count}/{total_chunks}")
                    if completed_count > prefix_count:
                        report(
                            f"Translation progress: completed {completed_count}/{total_chunks} chunks "
                            f"(prefix {prefix_count}/{total_chunks})"
                        )
                    prev_prefix = prefix_count
                elif completed_count != prev_completed:
                    report(
                        f"Translation progress: completed {completed_count}/{total_chunks} chunks "
                        f"(prefix {prefix_count}/{total_chunks})"
                    )
                prev_completed = completed_count

    translated_chunks = _load_success_prefix(workdir, state)
    prefix_count = len(translated_chunks)
    _persist_prefix_output(out_path, translated_chunks)

    if prefix_count == total_chunks:
        _record_translation_meta(paper_dir, lang, src_lang, config, partial=False)
        portable_path = _write_portable_translation_bundle(config, paper_dir, out_path) if portable else None
        shutil.rmtree(workdir, ignore_errors=True)
        report(f"Translation completed: {total_chunks}/{total_chunks} chunks")
        return TranslateResult(
            path=out_path,
            portable_path=portable_path,
            completed_chunks=total_chunks,
            total_chunks=total_chunks,
        )

    if prefix_count > 0:
        next_failed = prefix_count + 1
        report(f"Translation interrupted at chunk {next_failed}/{total_chunks}; rerun later to resume")
        return TranslateResult(
            path=out_path,
            partial=True,
            completed_chunks=prefix_count,
            total_chunks=total_chunks,
        )

    _log.error("%s: all %d chunks failed; not writing output", paper_dir.name, len(chunks))
    return TranslateResult(skip_reason=SKIP_ALL_CHUNKS_FAILED, total_chunks=total_chunks)


def batch_translate(
    papers_dir: Path,
    config: Config,
    *,
    target_lang: str | None = None,
    force: bool = False,
    portable: bool = False,
    paper_ids: set[str] | None = None,
) -> dict[str, int]:
    """Batch translate all papers in the library.

    Args:
        papers_dir: Papers directory.
        config: Global config.
        target_lang: Target language code.
        force: Re-translate existing translations.
        paper_ids: Optional set of paper UUIDs to limit translation scope.

    Returns:
        Stats dict with ``translated``, ``skipped``, ``failed`` counts.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from scholaraio.stores.papers import iter_paper_dirs, read_meta

    lang = target_lang or config.translate.target_lang
    workers = max(1, int(getattr(config.translate, "concurrency", 1) or 1))
    stats = {"translated": 0, "skipped": 0, "failed": 0}

    dirs = list(iter_paper_dirs(papers_dir))
    if paper_ids:
        filtered = []
        for d in dirs:
            try:
                meta = read_meta(d)
                if meta.get("id") in paper_ids:
                    filtered.append(d)
            except Exception as e:
                _log.debug("failed to read meta for %s: %s", d.name, e)
        dirs = filtered

    paper_workers = min(workers, len(dirs)) if dirs else 1
    chunk_workers = max(1, workers // paper_workers) if paper_workers else 1

    def _do_one(pdir: Path) -> str:
        try:
            tr = translate_paper(
                pdir,
                config,
                target_lang=lang,
                force=force,
                portable=portable,
                chunk_workers=chunk_workers,
            )
            if tr.ok:
                return "translated"
            if tr.partial or tr.skip_reason == SKIP_ALL_CHUNKS_FAILED:
                return "failed"
            return "skipped"
        except Exception as e:
            _log.error("translation failed for %s: %s", pdir.name, e)
            return "failed"

    if paper_workers > 1 and len(dirs) > 1:
        with ThreadPoolExecutor(max_workers=paper_workers) as pool:
            futures = {pool.submit(_do_one, d): d for d in dirs}
            for fut in as_completed(futures):
                status = fut.result()
                stats[status] = stats.get(status, 0) + 1
    else:
        for pdir in dirs:
            status = _do_one(pdir)
            stats[status] = stats.get(status, 0) + 1

    return stats


def _record_translation_meta(
    paper_dir: Path,
    target_lang: str,
    src_lang: str,
    config: Config,
    *,
    partial: bool = False,
) -> None:
    """Record translation info in meta.json."""
    from scholaraio.stores.papers import modify_meta

    try:
        entry: dict[str, object] = {
            "file": f"paper_{target_lang}.md",
            "source_lang": src_lang,
            "translated_at": datetime.now().isoformat(timespec="seconds"),
            "model": config.llm.model,
        }
        if partial:
            entry["status"] = "partial"

        def record(current):
            current.setdefault("translations", {})[target_lang] = entry

        modify_meta(paper_dir, record)
    except Exception as e:
        _log.debug("failed to record translation meta: %s", e)
