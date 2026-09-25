"""
workspace.py — 工作区论文子集管理
===================================

每个工作区是 ``workspace/<name>/`` 目录，论文索引固定为：

- current: ``refs/papers.json``

legacy root-level ``papers.json`` is no longer a runtime format. It may only be
read by explicit migration helpers that rewrite old workspaces into the current
layout.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import yaml

from scholaraio.core.fileio import atomic_write_text, file_lock

_log = logging.getLogger(__name__)


# ============================================================================
#  Internal helpers
# ============================================================================


def _papers_json(ws_dir: Path) -> Path:
    return ws_dir / "papers.json"


def _refs_papers_json(ws_dir: Path) -> Path:
    return ws_dir / "refs" / "papers.json"


def _workspace_yaml(ws_dir: Path) -> Path:
    return ws_dir / "workspace.yaml"


def _paper_index_path(ws_dir: Path) -> Path:
    return _refs_papers_json(ws_dir)


def _normalize_optional_text(value: object, field: str, source: Path) -> str | None:
    if not isinstance(value, str):
        raise RuntimeError(f"workspace.yaml 字段 {field} 必须是字符串: {source}")
    normalized = value.strip()
    return normalized or None


def _normalize_string_list(value: object, field: str, source: Path) -> list[str]:
    if not isinstance(value, list):
        raise RuntimeError(f"workspace.yaml 字段 {field} 必须是字符串列表: {source}")
    items: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise RuntimeError(f"workspace.yaml 字段 {field} 必须是字符串列表: {source}")
        normalized = item.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        items.append(normalized)
    return items


def _is_safe_logical_mount_id(value: str) -> bool:
    if not value:
        return False
    if value != value.strip():
        return False
    if value in {".", ".."}:
        return False
    if value.startswith(("/", "\\")):
        return False
    if "/" in value or "\\" in value:
        return False
    if ":" in value:
        return False
    return ".." not in value


def _normalize_mount_ids(value: object, field: str, source: Path) -> list[str]:
    items = _normalize_string_list(value, field, source)
    for item in items:
        if not _is_safe_logical_mount_id(item):
            raise RuntimeError(f"workspace.yaml 字段 {field} 必须是逻辑共享存储标识，不能是物理路径: {source}")
    return items


def _normalize_outputs_default_dir(value: object, source: Path) -> str | None:
    normalized = _normalize_optional_text(value, "outputs.default_dir", source)
    if normalized is None:
        return None
    if normalized.startswith(("/", "\\")):
        raise RuntimeError(f"workspace.yaml 字段 outputs.default_dir 必须是工作区内相对路径: {source}")
    if "\\" in normalized or ":" in normalized:
        raise RuntimeError(f"workspace.yaml 字段 outputs.default_dir 必须是工作区内相对路径: {source}")
    parts = PurePosixPath(normalized).parts
    if any(part == ".." for part in parts):
        raise RuntimeError(f"workspace.yaml 字段 outputs.default_dir 不能逃逸工作区根目录: {source}")
    return normalized


def _normalize_manifest_v1(raw: dict, source: Path) -> dict:
    normalized = dict(raw)

    for field in ("name", "description"):
        if field not in raw:
            continue
        value = _normalize_optional_text(raw[field], field, source)
        if value is None:
            normalized.pop(field, None)
        else:
            normalized[field] = value

    if "tags" in raw:
        tags = _normalize_string_list(raw["tags"], "tags", source)
        if tags:
            normalized["tags"] = tags
        else:
            normalized.pop("tags", None)

    if "mounts" in raw:
        mounts = raw["mounts"]
        if not isinstance(mounts, dict):
            raise RuntimeError(f"workspace.yaml 字段 mounts 必须是 mapping: {source}")
        normalized_mounts = dict(mounts)
        for bucket in ("explore", "toolref"):
            if bucket not in mounts:
                continue
            values = _normalize_mount_ids(mounts[bucket], f"mounts.{bucket}", source)
            if values:
                normalized_mounts[bucket] = values
            else:
                normalized_mounts.pop(bucket, None)
        if normalized_mounts:
            normalized["mounts"] = normalized_mounts
        else:
            normalized.pop("mounts", None)

    if "outputs" in raw:
        outputs = raw["outputs"]
        if not isinstance(outputs, dict):
            raise RuntimeError(f"workspace.yaml 字段 outputs 必须是 mapping: {source}")
        normalized_outputs = dict(outputs)
        if "default_dir" in outputs:
            default_dir = _normalize_outputs_default_dir(outputs["default_dir"], source)
            if default_dir is None:
                normalized_outputs.pop("default_dir", None)
            else:
                normalized_outputs["default_dir"] = default_dir
        if normalized_outputs:
            normalized["outputs"] = normalized_outputs
        else:
            normalized.pop("outputs", None)

    return normalized


def has_paper_index(ws_dir: Path) -> bool:
    return _paper_index_path(ws_dir).exists()


def has_legacy_paper_index(ws_dir: Path) -> bool:
    return _papers_json(ws_dir).exists()


def read_manifest(ws_dir: Path) -> dict | None:
    """Read and validate ``workspace.yaml`` when present.

    Returns normalized schema-v1 metadata. Newer schema versions are returned
    as opaque mappings without normalization so callers do not accidentally
    rewrite unsupported formats.
    """
    manifest_path = _workspace_yaml(ws_dir)
    if not manifest_path.exists():
        return None
    try:
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise RuntimeError(f"workspace.yaml 格式损坏，操作中止: {manifest_path}") from e
    if not isinstance(raw, dict):
        raise RuntimeError(
            f"workspace.yaml 格式异常（期望 mapping，实际 {type(raw).__name__ if raw is not None else 'NoneType'}）: {manifest_path}"
        )
    if "schema_version" not in raw:
        raise RuntimeError(f"workspace.yaml 缺少 schema_version: {manifest_path}")
    schema_version = raw["schema_version"]
    if type(schema_version) is not int:
        raise RuntimeError(f"workspace.yaml 字段 schema_version 必须是整数: {manifest_path}")
    if schema_version != 1:
        return dict(raw)
    return _normalize_manifest_v1(raw, manifest_path)


def _normalize_entry(entry: object) -> dict | None:
    if isinstance(entry, dict) and "id" in entry:
        return entry
    if isinstance(entry, str):
        # Older workspaces could store a bare list of visible paper refs.
        return {"id": entry, "dir_name": entry}
    return None


def _load_entries_from_path(index_path: Path) -> list[dict]:
    try:
        raw = json.loads(index_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise RuntimeError(f"workspace index 格式损坏，操作中止: {index_path}") from e
    if not isinstance(raw, list):
        raise RuntimeError(f"workspace index 格式异常（期望 list，实际 {type(raw).__name__}）: {index_path}")
    valid = [normalized for entry in raw if (normalized := _normalize_entry(entry)) is not None]
    if len(valid) < len(raw):
        _log.warning("workspace index 中有 %d 条缺少 id 的记录已跳过 (%s)", len(raw) - len(valid), index_path)
    return valid


def migrate_paper_index_layout(ws_dir: Path) -> dict[str, object]:
    """Rewrite a legacy root ``papers.json`` into ``refs/papers.json``.

    Returns a small status payload describing whether migration work happened.
    """
    legacy = _papers_json(ws_dir)
    current = _paper_index_path(ws_dir)
    result: dict[str, object] = {
        "workspace": ws_dir.name,
        "legacy_path": str(legacy),
        "current_path": str(current),
        "status": "noop",
        "entry_count": 0,
        "cleanup_candidates": [],
    }
    if current.exists() and legacy.exists():
        legacy_entries = _load_entries_from_path(legacy)
        current_entries = _load_entries_from_path(current)
        if legacy_entries != current_entries:
            raise RuntimeError(f"workspace legacy/current index mismatch，需要人工处理: {ws_dir}")
        result["status"] = "already_migrated"
        result["entry_count"] = len(current_entries)
        result["cleanup_candidates"] = [str(legacy)]
        return result
    if current.exists():
        result["status"] = "current_only"
        result["entry_count"] = len(_load_entries_from_path(current))
        return result
    if not legacy.exists():
        current.parent.mkdir(parents=True, exist_ok=True)
        current.write_text("[]\n", encoding="utf-8")
        result["status"] = "initialized_empty"
        return result

    entries = _load_entries_from_path(legacy)
    current.parent.mkdir(parents=True, exist_ok=True)
    current.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    result["status"] = "migrated"
    result["entry_count"] = len(entries)
    result["cleanup_candidates"] = [str(legacy)]
    return result


def migrate_workspace_index_layouts(ws_root: Path) -> list[dict[str, object]]:
    """Migrate all named workspaces under *ws_root* to ``refs/papers.json``."""
    if not ws_root.is_dir():
        return []
    reports: list[dict[str, object]] = []
    for child in sorted(ws_root.iterdir()):
        if not child.is_dir():
            continue
        if child.name == "_system":
            continue
        reports.append(migrate_paper_index_layout(child))
    return reports


def _read(ws_dir: Path) -> list[dict]:
    pj = _paper_index_path(ws_dir)
    if not pj.exists():
        return []
    return _load_entries_from_path(pj)


def _write(ws_dir: Path, entries: list[dict]) -> None:
    pj = _paper_index_path(ws_dir)
    pj.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(pj, json.dumps(entries, indent=2, ensure_ascii=False) + "\n")


# ============================================================================
#  Public API
# ============================================================================


def create(ws_dir: Path) -> Path:
    """创建工作区目录并初始化空论文索引。

    Args:
        ws_dir: 工作区目录路径。

    Returns:
        论文索引文件路径。
    """
    ws_dir.mkdir(parents=True, exist_ok=True)
    pj = _paper_index_path(ws_dir)
    with file_lock(_paper_index_path(ws_dir), create_parent=True):
        if not pj.exists():
            _write(ws_dir, [])
        return pj


def add(
    ws_dir: Path,
    paper_refs: list[str],
    db_path: Path,
    *,
    resolved: list[dict] | None = None,
) -> list[dict]:
    """添加论文到工作区。

    通过 UUID、目录名或 DOI 解析论文，去重后追加到 ``refs/papers.json``。

    当调用方已持有解析好的论文信息时，可通过 *resolved* 参数直接传入，
    跳过逐个 ``lookup_paper()`` 查询（避免 O(N) 次 DB 连接开销）。

    Args:
        ws_dir: 工作区目录路径。
        paper_refs: 论文引用列表（UUID / 目录名 / DOI）。
            当 *resolved* 不为 ``None`` 时本参数被忽略。
        db_path: index.db 路径，用于 lookup_paper。
        resolved: 预解析的论文列表，每个元素须含 ``"id"`` 和
            ``"dir_name"`` 键。提供时跳过 lookup_paper 查询。

    Returns:
        新增条目列表。
    """
    with file_lock(_paper_index_path(ws_dir), create_parent=True):
        entries = _read(ws_dir)
        existing_ids = {e["id"] for e in entries}
        added: list[dict] = []
        now = datetime.now(timezone.utc).isoformat()

        if resolved is not None:
            required_keys = {"id", "dir_name"}
            for idx, rec in enumerate(resolved):
                if not isinstance(rec, dict):
                    raise ValueError(
                        f"resolved[{idx}] must be a dict with keys {sorted(required_keys)}, got {type(rec).__name__!s}"
                    )
                missing = required_keys.difference(rec.keys())
                if missing:
                    raise ValueError(f"resolved[{idx}] is missing required keys {sorted(missing)}: {rec!r}")
                uid = rec["id"]
                if uid in existing_ids:
                    continue
                entry = {"id": uid, "dir_name": rec["dir_name"], "added_at": now}
                entries.append(entry)
                existing_ids.add(uid)
                added.append(entry)
        else:
            from scholaraio.services.index import lookup_paper

            for ref in paper_refs:
                record = lookup_paper(db_path, ref)
                if record is None:
                    _log.warning("无法解析论文引用: %s", ref)
                    continue
                uid = record["id"]
                if uid in existing_ids:
                    _log.debug("已存在，跳过: %s", ref)
                    continue
                entry = {"id": uid, "dir_name": record["dir_name"], "added_at": now}
                entries.append(entry)
                existing_ids.add(uid)
                added.append(entry)

        if added:
            _write(ws_dir, entries)
        return added


def remove(ws_dir: Path, paper_refs: list[str], db_path: Path) -> list[dict]:
    """从工作区移除论文。

    Args:
        ws_dir: 工作区目录路径。
        paper_refs: 论文引用列表（UUID / 目录名 / DOI）。
        db_path: index.db 路径。

    Returns:
        被移除的条目列表。
    """
    from scholaraio.services.index import lookup_paper

    with file_lock(_paper_index_path(ws_dir), create_parent=True):
        entries = _read(ws_dir)
        remove_ids: set[str] = set()
        remove_dir_names: set[str] = set()
        entry_ids = {e["id"] for e in entries}
        entry_dir_names = {e.get("dir_name") for e in entries}
        for ref in paper_refs:
            try:
                record = lookup_paper(db_path, ref)
            except sqlite3.Error as exc:
                _log.warning("lookup_paper 失败，回退到工作区可见标识: %s", exc)
                record = None
            if record:
                remove_ids.add(record["id"])
            else:
                # Fall back to exact workspace-visible identifiers when the index is stale
                # or unavailable, so users can still remove items they see in `ws show`.
                if ref in entry_ids:
                    remove_ids.add(ref)
                elif ref in entry_dir_names:
                    remove_dir_names.add(ref)

        removed = [e for e in entries if e["id"] in remove_ids or e.get("dir_name") in remove_dir_names]
        if removed:
            entries = [e for e in entries if e["id"] not in remove_ids and e.get("dir_name") not in remove_dir_names]
            _write(ws_dir, entries)
        return removed


def list_workspaces(ws_root: Path) -> list[str]:
    """列出所有含工作区论文索引的工作区。

    Args:
        ws_root: workspace/ 根目录。

    Returns:
        工作区名称列表（排序）。
    """
    if not ws_root.is_dir():
        return []
    return sorted(d.name for d in ws_root.iterdir() if d.is_dir() and has_paper_index(d))


def validate_workspace_name(name: str) -> bool:
    """Return True if *name* is a safe workspace identifier.

    Rejects empty names, ``.``/``..`` names, leading/trailing whitespace,
    absolute paths, path separators, Windows drive-like names (``:``),
    and any name containing ``..`` to prevent path traversal outside
    ``workspace/``.

    Args:
        name: Candidate workspace name from user input.

    Returns:
        ``True`` when the name is safe for path construction.
    """
    if not name:
        return False
    normalized = name.strip()
    if not normalized:
        return False
    # Reject names with leading/trailing whitespace to avoid ambiguity.
    if normalized != name:
        return False
    if normalized in {".", ".."}:
        return False
    import os

    if os.path.isabs(normalized):
        return False
    # Reject Windows drive-like paths (e.g., C:foo).
    if ":" in normalized:
        return False
    if "/" in normalized or "\\" in normalized:
        return False
    return ".." not in normalized


def show(ws_dir: Path, db_path: Path) -> list[dict]:
    """查看工作区论文列表，刷新过期的 dir_name。

    Args:
        ws_dir: 工作区目录路径。
        db_path: index.db 路径。

    Returns:
        论文条目列表（含最新 dir_name）。
    """
    from scholaraio.services.index import lookup_paper

    entries = _read(ws_dir)
    changed = False
    for e in entries:
        record = lookup_paper(db_path, e["id"])
        if record and record["dir_name"] != e.get("dir_name"):
            e["dir_name"] = record["dir_name"]
            changed = True
    if changed:
        _write(ws_dir, entries)
    return entries


def read_paper_ids(ws_dir: Path) -> set[str]:
    """返回工作区中所有论文的 UUID 集合。

    Args:
        ws_dir: 工作区目录路径。

    Returns:
        UUID 字符串集合，用于搜索过滤。
    """
    return {e["id"] for e in _read(ws_dir)}


def rename(ws_root: Path, old_name: str, new_name: str) -> Path:
    """重命名工作区。

    Args:
        ws_root: workspace/ 根目录。
        old_name: 当前工作区名称。
        new_name: 新工作区名称。

    Returns:
        重命名后的工作区目录路径。

    Raises:
        ValueError: 工作区名称非法（路径穿越/绝对路径等）。
        FileNotFoundError: 源工作区不存在。
        FileExistsError: 目标工作区已存在。
    """
    if not validate_workspace_name(old_name):
        raise ValueError(f"非法工作区名称: {old_name}")
    if not validate_workspace_name(new_name):
        raise ValueError(f"非法工作区名称: {new_name}")
    old_dir = ws_root / old_name
    new_dir = ws_root / new_name
    if not old_dir.exists():
        raise FileNotFoundError(f"工作区不存在: {old_name}")
    if not old_dir.is_dir():
        raise ValueError(f"不是有效工作区目录: {old_name}")
    if not has_paper_index(old_dir):
        raise ValueError(f"缺少工作区论文索引（refs/papers.json），无法重命名工作区: {old_name}")
    if new_dir.exists():
        raise FileExistsError(f"目标工作区已存在: {new_name}")
    old_dir.rename(new_dir)
    return new_dir


def read_dir_names(ws_dir: Path, db_path: Path) -> set[str]:
    """返回工作区中所有论文的当前目录名集合。

    从 papers_registry 查找最新 dir_name（处理 rename 后的情况）。

    Args:
        ws_dir: 工作区目录路径。
        db_path: index.db 路径。

    Returns:
        目录名字符串集合，用于导出过滤。
    """
    from scholaraio.services.index import lookup_paper

    names: set[str] = set()
    for e in _read(ws_dir):
        record = lookup_paper(db_path, e["id"])
        if record:
            names.add(record["dir_name"])
        elif e.get("dir_name"):
            names.add(e["dir_name"])
    return names


def paper_count(ws_dir: Path) -> int:
    """返回工作区索引中的论文条目数。"""
    return len(_read(ws_dir))
