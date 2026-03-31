"""
vectors.py — 向量嵌入与语义检索
==================================

使用 Qwen3-Embedding-0.6B（本地 ModelScope 缓存）生成论文向量。
嵌入文本 = title + abstract，存入 index.db 的 paper_vectors 表。

用法：
    from scholaraio.vectors import build_vectors, vsearch
    build_vectors(papers_dir, db_path)
    results = vsearch("turbulent drag reduction", db_path, top_k=5)
"""

from __future__ import annotations

import hashlib
import importlib
import json
import logging
import os
import re
import sqlite3
import struct
import time
from pathlib import Path
from typing import TYPE_CHECKING

_log = logging.getLogger(__name__)
_CHUNK_TITLE_FULL = "全文"
_CHUNK_TITLE_UNTITLED = "未命名章节"
_CHUNK_TITLE_PREFACE = "前言"
_CHUNK_SENTENCE_SEARCH_WINDOW = 8
_CHUNK_MAX_LINES = 120

if TYPE_CHECKING:
    import faiss

    from scholaraio.config import Config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_vectors (
    paper_id     TEXT PRIMARY KEY,
    embedding    BLOB NOT NULL,
    content_hash TEXT NOT NULL DEFAULT ''
);
"""

_MIGRATE_HASH = "ALTER TABLE paper_vectors ADD COLUMN content_hash TEXT NOT NULL DEFAULT ''"


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Create paper_vectors table and migrate schema if needed."""
    conn.execute(_SCHEMA)
    # Migrate: add content_hash column if missing
    cols = {row[1] for row in conn.execute("PRAGMA table_info(paper_vectors)")}
    if "content_hash" not in cols:
        conn.execute(_MIGRATE_HASH)


def _content_hash(title: str, abstract: str) -> str:
    """Compute a short hash of the embedding source text."""
    text = f"{title}\n\n{abstract}"
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:12]


# ============================================================================
#  Embedding
# ============================================================================

_model_cache: dict = {}  # key: (model_path, device) → SentenceTransformer


def _load_model(cfg: Config | None = None):
    """Load SentenceTransformer, using module-level cache to avoid reloading."""
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    SentenceTransformer = importlib.import_module("sentence_transformers").SentenceTransformer

    # Resolve config
    if cfg is not None:
        model_name = cfg.embed.model
        cache_dir = os.path.expanduser(cfg.embed.cache_dir)
        device_cfg = cfg.embed.device
        source = cfg.embed.source
    else:
        model_name = "Qwen/Qwen3-Embedding-0.6B"
        cache_dir = os.path.expanduser("~/.cache/modelscope/hub/models")
        device_cfg = "auto"
        source = "modelscope"

    # Resolve device
    if device_cfg == "auto":
        try:
            import torch

            device = "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            device = "cpu"
    else:
        device = device_cfg

    cache_key = (model_name, cache_dir, device)
    if cache_key in _model_cache:
        return _model_cache[cache_key]

    # Try to find or download the model
    local_path = _resolve_model_path(model_name, cache_dir, source)
    if local_path:
        model = SentenceTransformer(local_path, device=device)
    else:
        # HuggingFace fallback: SentenceTransformer handles download internally
        _log.info("[embed] downloading model %s from HuggingFace", model_name)
        model = SentenceTransformer(model_name, device=device)

    _model_cache[cache_key] = model
    return model


def _resolve_model_path(model_name: str, cache_dir: str, source: str) -> str | None:
    """Find local model path or download via ModelScope.

    Args:
        model_name: Model ID (e.g. ``"Qwen/Qwen3-Embedding-0.6B"``).
        cache_dir: Local cache directory.
        source: ``"modelscope"`` or ``"huggingface"``.

    Returns:
        Local folder path if found or downloaded, ``None`` to fall back
        to HuggingFace (SentenceTransformer handles download internally).
    """
    if source != "modelscope":
        return None

    try:
        from modelscope import snapshot_download
    except ImportError:
        return None

    # Check if already cached locally
    try:
        local_path = snapshot_download(model_name, cache_dir=cache_dir, local_files_only=True)
        return local_path
    except Exception as e:
        _log.debug("model not cached locally: %s", e)

    # Download
    try:
        _log.info("[embed] downloading model %s from ModelScope", model_name)
        return snapshot_download(model_name, cache_dir=cache_dir)
    except Exception as e:
        _log.warning("[embed] ModelScope download failed: %s, falling back to HuggingFace", e)
    return None


# ============================================================================
#  GPU profiling & adaptive batching
# ============================================================================

_GPU_PROFILE_FILE = Path("~/.cache/scholaraio/gpu_profile.json").expanduser()


def _profile_cache_key(model_name: str, gpu_name: str) -> str:
    return f"{model_name}::{gpu_name}"


def _run_profile(model, cfg: Config | None = None) -> dict:
    """Profile GPU memory per sample at various sequence lengths.

    Generates dummy texts at several token counts, encodes one at a time,
    and records peak GPU memory.  Results are cached to disk so this only
    runs once per model + GPU combination.

    Returns:
        ``{"gpu_total_bytes": int, "per_sample": {token_len: bytes, ...},
           "model_name": str, "gpu_name": str, "profiled_at": str}``
    """
    import torch

    if not torch.cuda.is_available():
        return {}

    device = next(model.parameters() if hasattr(model, "parameters") else model[0].parameters()).device
    if device.type != "cuda":
        return {}

    gpu_props = torch.cuda.get_device_properties(device)
    gpu_name = gpu_props.name
    gpu_total = gpu_props.total_memory

    # Use model's tokenizer to craft texts of exact token lengths
    tokenizer = model.tokenizer

    per_sample: dict[int, int] = {}
    filler = "turbulence flow particle dynamics simulation "

    # Measure baseline: model weights already on GPU
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats(device)
    tiny = filler[:20]
    model.encode([tiny], normalize_embeddings=True, batch_size=1)
    baseline = torch.cuda.memory_allocated(device)

    model_name = cfg.embed.model if cfg is not None else "Qwen/Qwen3-Embedding-0.6B"

    _log.info(
        "[gpu-profile] Profiling GPU memory for %s on %s (baseline=%.0f MB, total=%.0f MB) ...",
        model_name,
        gpu_name,
        baseline / 1024**2,
        gpu_total / 1024**2,
    )

    # Probe from 64 tokens, doubling each time, until OOM
    tgt_tokens = 64
    max_tokens = getattr(model, "max_seq_length", 32768) or 32768
    while tgt_tokens <= max_tokens:
        raw = filler * (tgt_tokens // 4 + 10)
        ids = tokenizer.encode(raw)[:tgt_tokens]
        text = tokenizer.decode(ids, skip_special_tokens=True)

        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats(device)

        try:
            model.encode([text], normalize_embeddings=True, batch_size=1)
            peak = torch.cuda.max_memory_allocated(device)
            incremental = peak - baseline
            per_sample[tgt_tokens] = incremental
            _log.info(
                "[gpu-profile]   tokens=%5d  incremental=%6.0f MB  (peak=%.0f MB)",
                tgt_tokens,
                incremental / 1024**2,
                peak / 1024**2,
            )
        except torch.cuda.OutOfMemoryError:
            _log.info("[gpu-profile]   tokens=%5d  OOM — max single-sample capacity found", tgt_tokens)
            torch.cuda.empty_cache()
            break

        tgt_tokens *= 2

    return {
        "gpu_total_bytes": gpu_total,
        "baseline_bytes": baseline,
        "gpu_name": gpu_name,
        "model_name": model_name,
        "per_sample": {str(k): v for k, v in per_sample.items()},
        "profiled_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def _load_or_create_profile(model, cfg: Config | None = None) -> dict:
    """Load cached GPU profile or run profiling."""
    import torch

    if not torch.cuda.is_available():
        return {}

    device = next(model.parameters() if hasattr(model, "parameters") else model[0].parameters()).device
    if device.type != "cuda":
        return {}

    gpu_name = torch.cuda.get_device_properties(device).name
    model_name = cfg.embed.model if cfg is not None else "Qwen/Qwen3-Embedding-0.6B"
    cache_key = _profile_cache_key(model_name, gpu_name)

    # Try loading from disk
    if _GPU_PROFILE_FILE.exists():
        try:
            all_profiles = json.loads(_GPU_PROFILE_FILE.read_text("utf-8"))
            if cache_key in all_profiles:
                _log.debug("[gpu-profile] loaded cached profile for %s", cache_key)
                return all_profiles[cache_key]
        except Exception:
            pass

    # Run profiling
    profile = _run_profile(model, cfg)
    if not profile:
        return {}

    # Save to disk
    _GPU_PROFILE_FILE.parent.mkdir(parents=True, exist_ok=True)
    all_profiles = {}
    if _GPU_PROFILE_FILE.exists():
        try:
            all_profiles = json.loads(_GPU_PROFILE_FILE.read_text("utf-8"))
        except Exception:
            pass
    all_profiles[cache_key] = profile
    _GPU_PROFILE_FILE.write_text(json.dumps(all_profiles, indent=2, ensure_ascii=False) + "\n", "utf-8")
    _log.info("[gpu-profile] saved profile to %s", _GPU_PROFILE_FILE)
    return profile


def _estimate_mem_per_sample(est_tokens: int, profile: dict) -> int:
    """Interpolate/extrapolate memory per sample from profile data.

    For sequence lengths beyond the profiled range, extrapolates using
    quadratic scaling (attention is O(n²)).
    """
    per_sample = profile.get("per_sample", {})
    if not per_sample:
        return 0

    # Convert keys to int, sort
    points = sorted((int(k), v) for k, v in per_sample.items())

    if est_tokens <= points[0][0]:
        return points[0][1]

    # Linear interpolation within profiled range
    for i in range(len(points) - 1):
        t0, m0 = points[i]
        t1, m1 = points[i + 1]
        if t0 <= est_tokens <= t1:
            frac = (est_tokens - t0) / (t1 - t0)
            return int(m0 + frac * (m1 - m0))

    # Extrapolate beyond max profiled point with quadratic scaling
    t_max, m_max = points[-1]
    ratio = est_tokens / t_max
    return int(m_max * ratio * ratio)


def _compute_batch_size(est_tokens: int, profile: dict, safety_factor: float = 0.85) -> int:
    """Compute optimal batch_size for texts of a given token length.

    Uses incremental memory per sample (peak minus baseline) from the
    profile, so model weight memory is excluded from the calculation.
    """
    if not profile or not profile.get("per_sample"):
        return 8  # conservative default

    gpu_total = profile["gpu_total_bytes"]
    baseline = profile.get("baseline_bytes", 0)
    mem_per_sample = _estimate_mem_per_sample(est_tokens, profile)

    if mem_per_sample <= 0:
        return 8

    # Available = total GPU memory * safety - baseline (model weights etc.)
    available = gpu_total * safety_factor - baseline
    if available <= 0:
        return 1

    bs = int(available / mem_per_sample)
    return max(1, min(bs, 128))


def _embed_text(text: str, cfg: Config | None = None) -> list[float]:
    model = _load_model(cfg)
    vec = model.encode([text], prompt_name="query", normalize_embeddings=True)
    return vec[0].tolist()


def _embed_batch(texts: list[str], cfg: Config | None = None) -> list[list[float]]:
    """Embed texts with adaptive GPU batch sizing.

    Sorts texts by estimated token count, groups them into buckets of
    similar length, and computes an optimal batch_size per bucket based
    on a one-time GPU memory profile.  Falls back to halving the batch
    (and ultimately CPU) on OOM.
    """

    model = _load_model(cfg)
    profile = _load_or_create_profile(model, cfg)

    if not profile:
        # CPU path or profiling unavailable — use conservative fixed batch
        vecs = model.encode(texts, normalize_embeddings=True, batch_size=8, show_progress_bar=len(texts) > 100)
        return vecs.tolist()

    # Estimate token count per text (~3.5 chars per token for mixed text)
    tokenizer = model.tokenizer
    # Fast estimation: use tokenizer on a sample, calibrate ratio
    est_tokens = []
    for t in texts:
        # Approximate: tokenizer.encode is fast enough for length estimation
        est_tokens.append(len(tokenizer.encode(t)))

    # Build indexed list and sort by token count
    indexed = sorted(enumerate(texts), key=lambda x: est_tokens[x[0]])

    # Group into buckets by similar token length
    # Bucket boundaries: powers of 2 from 64 to model max
    boundaries = [64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384]
    buckets: dict[int, list[int]] = {}  # boundary -> list of original indices

    for orig_idx, _text in indexed:
        tlen = est_tokens[orig_idx]
        # Find the smallest boundary >= tlen
        bucket_key = boundaries[-1]
        for b in boundaries:
            if tlen <= b:
                bucket_key = b
                break
        buckets.setdefault(bucket_key, []).append(orig_idx)

    # Encode each bucket with adaptive batch_size
    import torch

    results = [None] * len(texts)
    total_done = 0
    show_progress = len(texts) > 100

    for bucket_key in sorted(buckets.keys()):
        indices = buckets[bucket_key]
        bucket_texts = [texts[i] for i in indices]
        bs = _compute_batch_size(bucket_key, profile)

        _log.debug("[embed] bucket tokens<=%d: %d texts, batch_size=%d", bucket_key, len(bucket_texts), bs)

        # Encode with OOM retry
        encoded = None
        while encoded is None:
            try:
                encoded = model.encode(bucket_texts, normalize_embeddings=True, batch_size=bs)
            except torch.cuda.OutOfMemoryError:
                torch.cuda.empty_cache()
                if bs > 1:
                    bs = max(1, bs // 2)
                    _log.warning("[embed] OOM, retrying with batch_size=%d", bs)
                else:
                    _log.warning("[embed] OOM at batch_size=1, falling back to CPU")
                    model_cpu = model.to("cpu")
                    encoded = model_cpu.encode(bucket_texts, normalize_embeddings=True, batch_size=1)
                    model.to("cuda")

        for idx, vec in zip(indices, encoded):
            results[idx] = vec.tolist() if hasattr(vec, "tolist") else list(vec)
        total_done += len(indices)

    return results


class QwenEmbedder:
    """BERTopic-compatible embedder wrapping Qwen3 via ``_embed_batch``.

    BERTopic's KeyBERTInspired representation model requires an embedding
    backend that exposes ``embed_documents`` and ``embed_words`` methods.
    This class provides that interface.

    Args:
        cfg: Optional Config (or None) forwarded to ``_embed_batch``.
    """

    def __init__(self, cfg: Config | None = None):
        self._cfg = cfg

    def embed_documents(self, documents, verbose=False):
        import numpy as np

        return np.array(_embed_batch(documents, self._cfg), dtype="float32")

    def embed_words(self, words, verbose=False):
        return self.embed_documents(words, verbose)


def _pack(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _unpack(blob: bytes) -> list[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


def _faiss_paths(db_path: Path, *, prefix: str = "faiss") -> tuple[Path, Path]:
    """Return (faiss_index_path, faiss_ids_path) next to the db file."""
    parent = db_path.parent
    return parent / f"{prefix}.index", parent / f"{prefix}_ids.json"


def _invalidate_faiss(db_path: Path, *, prefix: str = "faiss") -> None:
    """Delete cached FAISS index files so next search rebuilds them."""
    for p in _faiss_paths(db_path, prefix=prefix):
        p.unlink(missing_ok=True)


def _append_faiss_files(
    index_path: Path,
    ids_path: Path,
    new_ids: list[str],
    new_vecs: list[list[float]],
) -> None:
    """Append new vectors to a FAISS index at explicit file paths.

    If the cached index does not exist yet, does nothing (it will be built on
    next search).  If any new IDs overlap with existing ones, the cached index
    is deleted so it gets rebuilt.

    Args:
        index_path: Path to ``faiss.index`` file.
        ids_path: Path to ``faiss_ids.json`` file.
        new_ids: New paper IDs.
        new_vecs: Corresponding embedding vectors (already normalised).
    """
    import faiss
    import numpy as np

    if not index_path.exists() or not ids_path.exists():
        return

    try:
        index = faiss.read_index(str(index_path))
        paper_ids = json.loads(ids_path.read_text("utf-8"))
    except Exception as e:
        _log.debug("failed to load FAISS cache, rebuilding: %s", e)
        index_path.unlink(missing_ok=True)
        ids_path.unlink(missing_ok=True)
        return

    if set(new_ids) & set(paper_ids):
        index_path.unlink(missing_ok=True)
        ids_path.unlink(missing_ok=True)
        return

    arr = np.array(new_vecs, dtype="float32")
    faiss.normalize_L2(arr)
    index.add(arr)
    paper_ids.extend(new_ids)

    faiss.write_index(index, str(index_path))
    ids_path.write_text(json.dumps(paper_ids, ensure_ascii=False) + "\n", encoding="utf-8")


def _append_faiss(db_path: Path, new_ids: list[str], new_vecs: list[list[float]]) -> None:
    """Append new vectors to existing FAISS index, or invalidate if not possible.

    Args:
        db_path: SQLite 数据库路径。
        new_ids: 新增论文 ID 列表。
        new_vecs: 对应的向量列表（已归一化）。
    """
    idx_p, ids_p = _faiss_paths(db_path)
    _append_faiss_files(idx_p, ids_p, new_ids, new_vecs)


# ============================================================================
#  Build
# ============================================================================


def build_vectors(papers_dir: Path, db_path: Path, rebuild: bool = False, cfg: Config | None = None) -> int:
    """为论文生成语义嵌入向量并写入 ``paper_vectors`` 表。

    嵌入文本 = ``title`` + ``abstract`` 拼接。
    使用 Sentence Transformer 模型（默认 Qwen3-Embedding-0.6B）。

    Args:
        papers_dir: 已入库论文目录，扫描其中的 ``*.json``。
        db_path: SQLite 数据库路径，不存在时自动创建。
        rebuild: 为 ``True`` 时清空旧向量后重建。
        cfg: 可选的 :class:`~scholaraio.config.Config`，用于读取模型/设备配置。

    Returns:
        本次新写入的向量数量。
    """
    conn = sqlite3.connect(db_path)
    try:
        _ensure_schema(conn)

        if rebuild:
            conn.execute("DELETE FROM paper_vectors")

        # Build lookup of existing hashes for incremental check
        existing_hashes: dict[str, str] = {}
        if not rebuild:
            for row in conn.execute("SELECT paper_id, content_hash FROM paper_vectors").fetchall():
                existing_hashes[row[0]] = row[1]

        # Collect papers to embed
        from scholaraio.papers import iter_paper_dirs, read_meta

        to_embed: list[tuple[str, str, str]] = []  # (paper_id, text, hash)
        for pdir in iter_paper_dirs(papers_dir):
            try:
                meta = read_meta(pdir)
            except (ValueError, FileNotFoundError) as e:
                _log.debug("failed to read meta.json in %s: %s", pdir.name, e)
                continue
            paper_id = meta.get("id") or pdir.name

            title = (meta.get("title") or "").strip()
            abstract = (meta.get("abstract") or "").strip()
            if not title and not abstract:
                continue

            h = _content_hash(title, abstract)
            if not rebuild and existing_hashes.get(paper_id) == h:
                continue  # content unchanged, skip

            if not abstract:
                _log.debug("no abstract, embedding title only: %s", paper_id)

            parts = [p for p in [title, abstract] if p]
            text = "\n\n".join(parts)
            to_embed.append((paper_id, text, h))

        if not to_embed:
            return 0

        _log.info("embedding %d papers", len(to_embed))
        texts = [t for _, t, _ in to_embed]
        vecs = _embed_batch(texts, cfg)

        new_ids = []
        new_vecs_raw = []
        updated_ids = set()
        for (paper_id, _, h), vec in zip(to_embed, vecs):
            is_update = paper_id in existing_hashes
            conn.execute(
                "INSERT OR REPLACE INTO paper_vectors (paper_id, embedding, content_hash) VALUES (?, ?, ?)",
                (paper_id, _pack(vec), h),
            )
            new_ids.append(paper_id)
            new_vecs_raw.append(vec)
            if is_update:
                updated_ids.add(paper_id)

        conn.commit()
    finally:
        conn.close()

    if to_embed:
        if updated_ids:
            # Content changed for existing papers — must rebuild FAISS
            _invalidate_faiss(db_path)
        else:
            # Pure additions — try incremental append
            _append_faiss(db_path, new_ids, new_vecs_raw)

    return len(to_embed)


# ============================================================================
#  Chunk Build
# ============================================================================


def _chunk_content_hash(paper_id: str, section_title: str, start_line: int, end_line: int, text: str) -> str:
    payload = f"{paper_id}\n{section_title}\n{start_line}\n{end_line}\n{text}"
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


def _heading_sections(lines: list[str]) -> list[tuple[str, int, int]]:
    """Fallback section split from markdown headings, line numbers are 1-based."""
    heading_pat = re.compile(r"^\s*#{1,6}\s+(.+?)\s*$")
    headers: list[tuple[int, str]] = []
    for i, line in enumerate(lines, start=1):
        m = heading_pat.match(line)
        if m:
            headers.append((i, m.group(1).strip()))

    if not headers:
        return [(_CHUNK_TITLE_FULL, 1, len(lines))]

    sections: list[tuple[str, int, int]] = []
    for idx, (line_no, title) in enumerate(headers):
        end_line = headers[idx + 1][0] - 1 if idx + 1 < len(headers) else len(lines)
        if end_line >= line_no:
            sections.append((title or _CHUNK_TITLE_UNTITLED, line_no, end_line))
    return sections


def _toc_sections(meta: dict, lines: list[str]) -> list[tuple[str, int, int]]:
    """Split sections by meta['toc'] when available, line numbers are 1-based."""
    toc = meta.get("toc")
    if not isinstance(toc, list):
        return []

    entries: list[tuple[int, str]] = []
    for item in toc:
        if not isinstance(item, dict):
            continue
        line_no = item.get("line")
        title = str(item.get("title") or "").strip()
        if not isinstance(line_no, int) or line_no < 1 or line_no > len(lines):
            continue
        if not title:
            title = _CHUNK_TITLE_UNTITLED
        entries.append((line_no, title))

    if not entries:
        return []

    entries = sorted(set(entries), key=lambda x: x[0])
    sections: list[tuple[str, int, int]] = []
    if entries[0][0] > 1:
        sections.append((_CHUNK_TITLE_PREFACE, 1, entries[0][0] - 1))
    for idx, (line_no, title) in enumerate(entries):
        end_line = entries[idx + 1][0] - 1 if idx + 1 < len(entries) else len(lines)
        if end_line >= line_no:
            sections.append((title, line_no, end_line))
    return sections


def _best_split_line(slice_lines: list[str], start_idx: int, end_idx: int) -> int:
    """Find a preferred split line near the end; indices are 0-based and inclusive."""
    tail_start = max(start_idx, end_idx - _CHUNK_SENTENCE_SEARCH_WINDOW)
    sentence_pat = re.compile(r"[。！？.!?][\s\"'”’）)]*$")
    for i in range(end_idx, tail_start - 1, -1):
        text = slice_lines[i].strip()
        if sentence_pat.search(text):
            return i
    for i in range(end_idx, tail_start - 1, -1):
        if not slice_lines[i].strip():
            return i
    return end_idx


def _split_large_section(
    lines: list[str],
    section_title: str,
    start_line: int,
    end_line: int,
    *,
    max_lines: int = _CHUNK_MAX_LINES,
) -> list[tuple[str, int, int, str]]:
    """Split section into chunk windows; uses sentence-boundary fallback."""
    slice_lines = lines[start_line - 1 : end_line]
    if not slice_lines:
        return []

    chunks: list[tuple[str, int, int, str]] = []
    i = 0
    while i < len(slice_lines):
        j = min(i + max_lines - 1, len(slice_lines) - 1)
        if j < len(slice_lines) - 1:
            j = _best_split_line(slice_lines, i, j)
        c_start = start_line + i
        c_end = start_line + j
        text = "\n".join(slice_lines[i : j + 1]).strip()
        if text:
            chunks.append((section_title, c_start, c_end, text))
        i = j + 1
    return chunks


def _iter_chunks(meta: dict, md_text: str) -> list[tuple[str, int, int, str]]:
    lines = md_text.splitlines()
    if not lines:
        return []

    sections = _toc_sections(meta, lines)
    if not sections:
        sections = _heading_sections(lines)

    chunks: list[tuple[str, int, int, str]] = []
    for section_title, start_line, end_line in sections:
        chunks.extend(_split_large_section(lines, section_title, start_line, end_line))
    return chunks


def _build_chunk_faiss_index(db_path: Path) -> tuple[faiss.Index, list[str]]:
    """Build/load FAISS for chunk_vectors table."""
    idx_p, ids_p = _faiss_paths(db_path, prefix="chunk_faiss")
    return _build_faiss_from_db(
        db_path,
        idx_p,
        ids_p,
        empty_msg="段落向量索引为空，请先运行 `scholaraio index --chunks`",
        table_name="chunk_vectors",
        id_column="chunk_id",
    )


def build_chunk_vectors(papers_dir: Path, db_path: Path, rebuild: bool = False, cfg: Config | None = None) -> int:
    """Build paragraph/section chunk vectors in ``chunk_vectors`` table."""
    from scholaraio.papers import iter_paper_dirs, read_meta

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chunk_vectors (
                chunk_id       TEXT PRIMARY KEY,
                paper_id       TEXT NOT NULL,
                section_title  TEXT,
                start_line     INTEGER NOT NULL,
                end_line       INTEGER NOT NULL,
                content_hash   TEXT NOT NULL,
                embedding      BLOB NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chunk_vectors_paper_id ON chunk_vectors(paper_id)")
        if rebuild:
            conn.execute("DELETE FROM chunk_vectors")

        existing_hashes: dict[str, str] = {}
        if not rebuild:
            for row in conn.execute("SELECT chunk_id, content_hash FROM chunk_vectors").fetchall():
                existing_hashes[row[0]] = row[1]

        to_embed: list[tuple[str, str, str, int, int, str, str]] = []
        paper_chunk_ids: dict[str, list[str]] = {}
        for pdir in iter_paper_dirs(papers_dir):
            try:
                meta = read_meta(pdir)
            except (ValueError, FileNotFoundError) as e:
                _log.debug("failed to read meta.json in %s: %s", pdir.name, e)
                continue
            paper_id = meta.get("id") or pdir.name
            md_path = pdir / "paper.md"
            if not md_path.exists():
                continue

            chunks = _iter_chunks(meta, md_path.read_text(encoding="utf-8", errors="replace"))
            new_chunk_ids: list[str] = []
            for seq, (section_title, start_line, end_line, text) in enumerate(chunks, start=1):
                chunk_id = f"{paper_id}:{seq}"
                new_chunk_ids.append(chunk_id)
                h = _chunk_content_hash(paper_id, section_title, start_line, end_line, text)
                if not rebuild and existing_hashes.get(chunk_id) == h:
                    continue
                to_embed.append((chunk_id, paper_id, section_title, start_line, end_line, h, text))
            paper_chunk_ids[paper_id] = new_chunk_ids

        if not to_embed:
            stale_removed = False
            if not rebuild:
                for paper_id, expected_ids in paper_chunk_ids.items():
                    existing_ids = [
                        r[0] for r in conn.execute("SELECT chunk_id FROM chunk_vectors WHERE paper_id = ?", (paper_id,)).fetchall()
                    ]
                    stale_ids = set(existing_ids) - set(expected_ids)
                    if stale_ids:
                        conn.executemany("DELETE FROM chunk_vectors WHERE chunk_id = ?", [(cid,) for cid in stale_ids])
                        stale_removed = True
                if stale_removed:
                    conn.commit()
            if stale_removed:
                _invalidate_faiss(db_path, prefix="chunk_faiss")
            return 0

        texts = [row[6] for row in to_embed]
        vecs = _embed_batch(texts, cfg)

        updated = False
        new_ids: list[str] = []
        new_vecs_raw: list[list[float]] = []
        touched_papers = {row[1] for row in to_embed}
        for (chunk_id, paper_id, section_title, start_line, end_line, h, _), vec in zip(to_embed, vecs):
            if chunk_id in existing_hashes:
                updated = True
            conn.execute(
                """INSERT OR REPLACE INTO chunk_vectors
                   (chunk_id, paper_id, section_title, start_line, end_line, content_hash, embedding)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (chunk_id, paper_id, section_title, start_line, end_line, h, _pack(vec)),
            )
            new_ids.append(chunk_id)
            new_vecs_raw.append(vec)

        # Remove stale chunks for touched papers
        for paper_id in touched_papers:
            existing_ids = [r[0] for r in conn.execute("SELECT chunk_id FROM chunk_vectors WHERE paper_id = ?", (paper_id,)).fetchall()]
            stale_ids = set(existing_ids) - set(paper_chunk_ids.get(paper_id, []))
            if stale_ids:
                updated = True
                conn.executemany("DELETE FROM chunk_vectors WHERE chunk_id = ?", [(cid,) for cid in stale_ids])

        conn.commit()
    finally:
        conn.close()

    if updated:
        _invalidate_faiss(db_path, prefix="chunk_faiss")
    else:
        try:
            _append_faiss_files(
                *_faiss_paths(db_path, prefix="chunk_faiss"),
                new_ids,
                new_vecs_raw,
            )
        except ImportError:
            _log.debug("faiss is unavailable, skip incremental chunk FAISS append")
    return len(to_embed)


def chunk_search(
    query: str,
    db_path: Path,
    top_k: int = 10,
    cfg: Config | None = None,
    *,
    aggregate: bool = False,
) -> list[dict]:
    """Search chunk-level semantic vectors."""
    if not db_path.exists():
        raise FileNotFoundError(f"索引文件不存在：{db_path}\n请先运行 `scholaraio index`")

    conn = sqlite3.connect(db_path)
    try:
        has_vectors = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='chunk_vectors'"
        ).fetchone()
        if not has_vectors:
            raise FileNotFoundError("段落向量索引不存在，请先运行 `scholaraio index --chunks`")
    finally:
        conn.close()

    index, chunk_ids = _build_chunk_faiss_index(db_path)
    hits = _vsearch_faiss(query, index, chunk_ids, top_k * 5 if aggregate else top_k, cfg=cfg)

    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        meta_rows = conn.execute(
            """
            SELECT chunk_id, paper_id, section_title, start_line, end_line
            FROM chunk_vectors
            """
        ).fetchall()
        meta_map = {r["chunk_id"]: dict(r) for r in meta_rows}
        paper_meta: dict[str, dict] = {}
        has_fts = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='papers'").fetchone()
        if has_fts:
            for row in conn.execute("SELECT paper_id, title, authors, year, journal, citation_count FROM papers").fetchall():
                paper_meta[row["paper_id"]] = dict(row)
        dir_map: dict[str, str] = {}
        has_reg = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='papers_registry'").fetchone()
        if has_reg:
            for row in conn.execute("SELECT id, dir_name FROM papers_registry").fetchall():
                dir_map[row["id"]] = row["dir_name"]
    finally:
        conn.close()

    results: list[dict] = []
    for chunk_id, score in hits:
        m = meta_map.get(chunk_id)
        if not m:
            continue
        pmeta = paper_meta.get(m["paper_id"], {})
        results.append(
            {
                "chunk_id": chunk_id,
                "paper_id": m["paper_id"],
                "dir_name": dir_map.get(m["paper_id"], ""),
                "title": pmeta.get("title") or m["paper_id"],
                "authors": pmeta.get("authors") or "",
                "year": pmeta.get("year") or "",
                "journal": pmeta.get("journal") or "",
                "citation_count": pmeta.get("citation_count") or "",
                "section_title": m["section_title"] or "",
                "start_line": int(m["start_line"]),
                "end_line": int(m["end_line"]),
                "score": float(score),
            }
        )

    if not aggregate:
        return results[:top_k]

    best_by_paper: dict[str, dict] = {}
    for r in results:
        pid = r["paper_id"]
        prev = best_by_paper.get(pid)
        if prev is None or r["score"] > prev["score"]:
            best_by_paper[pid] = r
    aggregated = sorted(best_by_paper.values(), key=lambda x: x["score"], reverse=True)
    return aggregated[:top_k]


# ============================================================================
#  Search
# ============================================================================


def _build_faiss_from_db(
    db_path: Path,
    index_path: Path,
    ids_path: Path,
    *,
    empty_msg: str = "向量索引为空，请先运行 `scholaraio embed`",
    table_name: str = "paper_vectors",
    id_column: str = "paper_id",
) -> tuple[faiss.Index, list[str]]:
    """Build or load a FAISS IndexFlatIP from a paper_vectors table.

    Generic implementation that works with any SQLite DB containing a
    ``paper_vectors`` table (main library or explore silo).

    Args:
        db_path: SQLite database with vector table.
        index_path: Path to cached ``faiss.index`` file.
        ids_path: Path to cached ``faiss_ids.json`` file.
        empty_msg: Error message when no vectors found.
        table_name: Vector table name.
        id_column: ID column name corresponding to each embedding row.

    Returns:
        ``(faiss_index, paper_ids)`` tuple.

    Raises:
        FileNotFoundError: No vectors in the database.
    """
    import faiss
    import numpy as np

    if index_path.exists() and ids_path.exists():
        index = faiss.read_index(str(index_path))
        paper_ids = json.loads(ids_path.read_text("utf-8"))
        return index, paper_ids

    allowed_table_cols = {
        "paper_vectors": {"paper_id"},
        "chunk_vectors": {"chunk_id"},
    }
    if table_name not in allowed_table_cols or id_column not in allowed_table_cols[table_name]:
        raise ValueError(f"unsupported vector table/column: {table_name}.{id_column}")

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(f"SELECT {id_column}, embedding FROM {table_name}").fetchall()
    finally:
        conn.close()

    if not rows:
        raise FileNotFoundError(empty_msg)

    # Validate blob dimensions: use first row to determine dim, skip corrupted rows
    expected_blob_len = len(rows[0][1])
    dim = expected_blob_len // 4
    if expected_blob_len == 0 or expected_blob_len % 4 != 0:
        raise ValueError(f"First embedding blob has invalid length: {expected_blob_len}")

    valid_rows = []
    for r in rows:
        if len(r[1]) != expected_blob_len:
            _log.warning("Skipping paper %s: blob length %d != expected %d", r[0], len(r[1]), expected_blob_len)
            continue
        valid_rows.append(r)

    if not valid_rows:
        raise FileNotFoundError("No valid embedding rows after dimension check")

    paper_ids = [r[0] for r in valid_rows]
    vecs = np.array(
        [list(struct.unpack(f"{dim}f", r[1])) for r in valid_rows],
        dtype="float32",
    )
    faiss.normalize_L2(vecs)

    index = faiss.IndexFlatIP(dim)
    index.add(vecs)

    faiss.write_index(index, str(index_path))
    ids_path.write_text(json.dumps(paper_ids, ensure_ascii=False) + "\n", encoding="utf-8")
    return index, paper_ids


def _build_faiss_index(db_path: Path) -> tuple[faiss.Index, list[str]]:
    """Build or load a FAISS IndexFlatIP for the main library."""
    idx_p, ids_p = _faiss_paths(db_path)
    return _build_faiss_from_db(db_path, idx_p, ids_p)


def _vsearch_faiss(
    query: str,
    index: faiss.Index,
    paper_ids: list[str],
    top_k: int,
    cfg: Config | None = None,
) -> list[tuple[str, float]]:
    """Run a FAISS similarity search, returning ``(paper_id, score)`` pairs.

    Args:
        query: Natural-language query text.
        index: FAISS ``IndexFlatIP`` instance.
        paper_ids: Paper ID list aligned with the index.
        top_k: Number of results to return.
        cfg: Optional config for embedding model.

    Returns:
        List of ``(paper_id, score)`` sorted by descending similarity.
    """
    import faiss
    import numpy as np

    q_vec = np.array([_embed_text(query, cfg)], dtype="float32")
    faiss.normalize_L2(q_vec)

    fetch_k = min(top_k, index.ntotal)
    scores, indices = index.search(q_vec, fetch_k)

    results = []
    for score, idx in zip(scores[0], indices[0]):
        if idx < 0:
            continue
        results.append((paper_ids[idx], float(score)))
    return results


def vsearch(
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
    """语义向量检索，使用 FAISS 加速余弦相似度搜索。

    将查询文本编码为向量，通过 FAISS IndexFlatIP 检索最相似的论文。
    FAISS 索引在首次查询时自动构建并缓存到磁盘，向量变更后自动失效重建。

    Args:
        query: 自然语言查询文本。
        db_path: SQLite 数据库路径（需包含 ``paper_vectors`` 表）。
        top_k: 最多返回条数，为 ``None`` 时从 ``cfg.embed.top_k`` 读取。
        cfg: 可选的 :class:`~scholaraio.config.Config`，用于加载嵌入模型。
        year: 年份过滤（``"2023"`` / ``"2020-2024"`` / ``"2020-"``）。
        journal: 期刊名过滤（LIKE 模糊匹配）。
        paper_type: 论文类型过滤（如 ``"review"``、``"journal-article"``）。
        paper_ids: 论文 UUID 白名单，仅返回集合内的结果。

    Returns:
        论文字典列表，按 ``score`` 降序排列。每项包含
        ``paper_id``, ``title``, ``authors``, ``year``, ``journal``, ``score``。

    Raises:
        FileNotFoundError: 索引文件或 ``paper_vectors`` 表不存在。
    """
    import faiss
    import numpy as np

    if top_k is None:
        top_k = cfg.embed.top_k if cfg is not None else 10

    if not db_path.exists():
        raise FileNotFoundError(f"索引文件不存在：{db_path}\n请先运行 `scholaraio index`")

    conn = sqlite3.connect(db_path)
    try:
        has_vectors = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='paper_vectors'"
        ).fetchone()
        if not has_vectors:
            raise FileNotFoundError("向量索引不存在，请先运行 `scholaraio embed`")
    finally:
        conn.close()

    index, faiss_ids = _build_faiss_index(db_path)

    q_vec = np.array([_embed_text(query, cfg)], dtype="float32")
    faiss.normalize_L2(q_vec)

    # Fetch more candidates when post-filtering is needed
    fetch_k = top_k * 5 if (year or journal or paper_type or paper_ids) else top_k
    fetch_k = min(fetch_k, index.ntotal)
    scores, indices = index.search(q_vec, fetch_k)

    # Load metadata from FTS5 table
    conn = sqlite3.connect(db_path)
    try:
        has_fts = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='papers'").fetchone()
        meta_map: dict[str, dict] = {}
        if has_fts:
            conn.row_factory = sqlite3.Row
            for row in conn.execute(
                "SELECT paper_id, title, authors, year, journal, citation_count, paper_type FROM papers"
            ).fetchall():
                meta_map[row["paper_id"]] = dict(row)
        # Load dir_name mapping
        dir_map: dict[str, str] = {}
        has_reg = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='papers_registry'"
        ).fetchone()
        if has_reg:
            for row in conn.execute("SELECT id, dir_name FROM papers_registry").fetchall():
                dir_map[row[0]] = row[1]
    finally:
        conn.close()

    results = []
    for score, idx in zip(scores[0], indices[0]):
        if idx < 0:
            continue
        pid = faiss_ids[idx]
        meta = meta_map.get(pid, {})
        results.append(
            {
                "paper_id": pid,
                "dir_name": dir_map.get(pid, ""),
                "title": meta.get("title") or pid,
                "authors": meta.get("authors") or "",
                "year": meta.get("year") or "",
                "journal": meta.get("journal") or "",
                "citation_count": meta.get("citation_count") or "",
                "paper_type": meta.get("paper_type") or "",
                "score": float(score),
            }
        )

    if paper_ids is not None:
        results = [r for r in results if r["paper_id"] in paper_ids]
    if year or journal or paper_type:
        results = _post_filter(results, year=year, journal=journal, paper_type=paper_type)

    return results[:top_k]


def _safe_year(r: dict) -> int | None:
    """Extract year as int, return None if missing or invalid."""
    val = r.get("year", "")
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _post_filter(
    results: list[dict],
    *,
    year: str | None = None,
    journal: str | None = None,
    paper_type: str | None = None,
) -> list[dict]:
    """对向量检索结果做年份/期刊/类型过滤。"""
    from scholaraio.papers import parse_year_range

    filtered = results
    if year:
        start_i, end_i = parse_year_range(year)
        if start_i is not None and end_i is not None:
            filtered = [r for r in filtered if _safe_year(r) is not None and start_i <= _safe_year(r) <= end_i]
        elif start_i is not None:
            filtered = [r for r in filtered if _safe_year(r) is not None and _safe_year(r) >= start_i]
        elif end_i is not None:
            filtered = [r for r in filtered if _safe_year(r) is not None and _safe_year(r) <= end_i]
    if journal:
        j_lower = journal.lower()
        filtered = [r for r in filtered if j_lower in str(r.get("journal", "")).lower()]
    if paper_type:
        t_lower = paper_type.lower()
        filtered = [r for r in filtered if t_lower in str(r.get("paper_type", "")).lower()]
    return filtered
