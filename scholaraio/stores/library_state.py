"""File identities for rebuildable library projections.

No database owns paper metadata. A manifest detects external edits; application
writes also touch the collection directory to invalidate the short scan cache.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path

Signature = tuple[int, int, int, int]
Manifest = dict[str, tuple[tuple[str, Signature], ...]]
_CACHE: dict[Path, tuple[float, tuple[int, int], Manifest]] = {}
_LOCK = threading.Lock()
_GENERATION = 0


def notify_metadata_write(path: Path) -> None:
    """Signal application writes without introducing another authoritative store."""
    global _GENERATION
    with _LOCK:
        _GENERATION += 1
        _CACHE.clear()
    try:
        os.utime(path.parent.parent, None)
    except OSError:
        logging.getLogger(__name__).warning("Metadata saved; collection timestamp notification failed: %s", path)


def library_stamp(root: Path) -> tuple[int, int]:
    """Combine filesystem notification with reliable in-process invalidation."""
    with _LOCK:
        generation = _GENERATION
    return (root.stat().st_mtime_ns if root.is_dir() else 0, generation)


def library_manifest(root: Path, *, force: bool = False) -> Manifest:
    """Scan record identities at most every five seconds unless explicitly forced.

    Inspect immediate paper directories and proceedings child directories only;
    extracted image trees are irrelevant to metadata/list projections.
    """
    root = root.resolve()
    stamp = library_stamp(root)
    now = time.monotonic()
    with _LOCK:
        cached = _CACHE.get(root)
        if not force and cached and cached[0] > now and cached[1] == stamp:
            return cached[2]
    result: Manifest = {}

    def scan_record(directory: Path) -> None:
        entries: list[tuple[str, Signature]] = []
        with os.scandir(directory) as files:
            for entry in files:
                if entry.name not in {"meta.json", "paper.md"} and not entry.name.lower().endswith(".pdf"):
                    continue
                try:
                    stat = entry.stat()
                except FileNotFoundError:
                    continue
                entries.append((entry.name, (stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)))
        if entries:
            result[str(directory.relative_to(root))] = tuple(sorted(entries))

    with os.scandir(root) as entries:
        for entry in entries:
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            directory = Path(entry.path)
            try:
                scan_record(directory)
                children = directory / "papers"
                if children.is_dir():
                    with os.scandir(children) as papers:
                        for paper in papers:
                            if paper.is_dir():
                                scan_record(Path(paper.path))
            except FileNotFoundError:
                continue  # concurrent rename: next scan observes the new name
    with _LOCK:
        if len(_CACHE) >= 16:
            _CACHE.clear()
        _CACHE[root] = (now + 5.0, stamp, result)
    return result


def keyword_manifest_digest(manifest: Manifest) -> str:
    """Fingerprint only inputs consumed by the metadata keyword projection.

    PDF bytes and Markdown contents are separate resources. Only the Markdown
    path/existence is stored in this index; full-text indexing has its own flow.
    """
    projected = {
        path: [
            (name, signature if name == "meta.json" else True)
            for name, signature in entries
            if name in {"meta.json", "paper.md"}
        ]
        for path, entries in manifest.items()
        if any(name == "meta.json" for name, _signature in entries)
    }
    return hashlib.sha256(json.dumps(projected, sort_keys=True).encode()).hexdigest()


_RECORDS: dict[Path, tuple[Manifest, dict[str, dict]]] = {}
_RECORD_LOCK = threading.Lock()


def library_records(root: Path) -> dict[str, dict]:
    """Read-only metadata snapshot for ranked retrieval; parse changed records only."""
    from scholaraio.stores.papers import read_meta

    root = root.resolve()
    manifest = library_manifest(root) if root.is_dir() else {}
    with _RECORD_LOCK:
        old, records = _RECORDS.get(root, ({}, {}))
        current = {path: meta for path, meta in records.items() if path in manifest}
        for path, signature in manifest.items():
            if old.get(path) == signature:
                continue
            try:
                current[path] = read_meta(root / path)
            except (ValueError, OSError):
                current.pop(path, None)
        if len(_RECORDS) >= 8 and root not in _RECORDS:
            _RECORDS.clear()
        _RECORDS[root] = (manifest, current)
        return current
