"""Version-checked PDF recovery shared by the CLI and local WebUI.

Readers must be closed before resolving. Copies are retained without automatic
cleanup, including displaced inodes that a reader might still write later.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from scholaraio.services.pdf_edit_mirror import recovery_identity

if TYPE_CHECKING:
    from scholaraio.services.pdf_edit_mirror import PdfEditMirrorReconciler
    from scholaraio.stores.pdf_edit_mirror import PdfEditMirrorRecord


class PdfConflictChanged(ValueError):
    """The user's inspected versions are no longer the current versions."""


def _paths(record: PdfEditMirrorRecord) -> dict[str, Path]:
    result = {"canonical": record.canonical_path, "mirror": record.mirror_path}
    for active in (record.canonical_path, record.mirror_path):
        for path in sorted((active.parent / ".scholaraio-pdf-recovery" / active.name).glob("*.pdf")):
            result["recovery-" + hashlib.sha256(str(path).encode()).hexdigest()[:24]] = path
    return result


def _snapshot(reconciler: PdfEditMirrorReconciler, sync_id: str) -> tuple[dict, dict[str, Path]]:
    record = reconciler.store.get(sync_id)
    if record is None or record.retired_at is not None:
        raise KeyError(sync_id)
    paths = _paths(record)
    versions = []
    for key, path in paths.items():
        root = record.canonical_path.parent if key == "canonical" else reconciler.paths.mirror_root
        if key.startswith("recovery-"):
            root = (
                record.canonical_path.parent
                if path.is_relative_to(record.canonical_path.parent)
                else reconciler.paths.mirror_root
            )
        state = reconciler._inspect(path, root)
        identity = (state.content_hash, state.size, state.mtime_ns, state.inode)
        if state.exists and not path.is_symlink() and path.is_file():
            identity = recovery_identity(path, root)
        versions.append(
            {
                "id": key,
                "filename": path.name,
                "exists": state.exists,
                "valid": state.valid,
                "hash": identity[0],
                "size": identity[1],
                "mtime_ns": identity[2],
                "inode": identity[3],
                "message": state.message,
            }
        )
    token = hashlib.sha256(
        json.dumps([record.canonical_path.as_posix(), record.mirror_path.as_posix(), versions], sort_keys=True).encode()
    ).hexdigest()
    return {"sync_id": sync_id, "state": record.state, "token": token, "versions": versions}, paths


def inspect_conflict(reconciler: PdfEditMirrorReconciler, sync_id: str) -> dict:
    with reconciler._entry_lock(sync_id, timeout_seconds=30):
        return _snapshot(reconciler, sync_id)[0]


def version_path(reconciler: PdfEditMirrorReconciler, sync_id: str, version: str, token: str) -> Path:
    """Resolve an opaque version selector, never a caller-provided filesystem path."""
    with reconciler._entry_lock(sync_id, timeout_seconds=30):
        snapshot, paths = _snapshot(reconciler, sync_id)
        if snapshot["token"] != token:
            raise PdfConflictChanged("PDF versions changed; inspect them again.")
        if version not in paths:
            raise KeyError(version)
        selected = next(item for item in snapshot["versions"] if item["id"] == version)
        if not selected["valid"]:
            raise ValueError("This PDF version cannot be previewed or selected.")
        return paths[version]


def resolve_conflict(reconciler: PdfEditMirrorReconciler, sync_id: str, *, token: str, version: str) -> dict:
    """Retain both sides, publish an explicitly selected version, reject stale input."""
    with reconciler._entry_lock(sync_id, timeout_seconds=30):
        snapshot, paths = _snapshot(reconciler, sync_id)
        if token != snapshot["token"]:
            raise PdfConflictChanged("PDF versions changed; inspect them again.")
        chosen = next((item for item in snapshot["versions"] if item["id"] == version), None)
        if chosen is None or not chosen["valid"]:
            raise ValueError("Select a valid PDF version.")
        record = reconciler.store.get(sync_id)
        assert record is not None
        archive = reconciler.paths.state_root / "resolutions" / sync_id / uuid.uuid4().hex
        archive.mkdir(parents=True)
        # Archive every valid candidate before changing either active file.
        for item in snapshot["versions"]:
            if item["valid"]:
                reconciler._atomic_copy(paths[item["id"]], archive / (item["id"] + ".pdf"), destination_root=archive)
        expected = {key: reconciler._inspect(paths[key], paths[key].parent) for key in ("canonical", "mirror")}
        if _snapshot(reconciler, sync_id)[0]["token"] != token:
            raise PdfConflictChanged("A PDF was saved while recovery copies were being retained.")
        selected = archive / (version + ".pdf")
        try:
            for key in ("canonical", "mirror"):
                reconciler._atomic_copy(
                    selected, paths[key], destination_root=paths[key].parent, expected_destination=expected[key]
                )
            # Compare old recovery versions against what the user reviewed. New
            # retained files must still match their publication-time digest.
            original = {
                str(paths[item["id"]]): item["hash"]
                for item in snapshot["versions"]
                if item["id"].startswith("recovery-")
            }
            acknowledgements = {}
            for key, path in _paths(record).items():
                if not key.startswith("recovery-"):
                    continue
                baseline = original.get(str(path), path.stem.split("_")[0])
                actual = recovery_identity(path, path.parent)
                if actual[0] != baseline:
                    raise PdfConflictChanged("A retained PDF changed during recovery; all versions were preserved.")
                acknowledgements[str(path)] = actual
            canonical = reconciler._inspect(record.canonical_path, record.canonical_path.parent)
            mirror = reconciler._inspect(record.mirror_path, reconciler.paths.mirror_root)
            if (
                not canonical.valid
                or not mirror.valid
                or canonical.content_hash != chosen["hash"]
                or mirror.content_hash != chosen["hash"]
            ):
                raise PdfConflictChanged("An active PDF changed during recovery.")
            reconciler.store.acknowledge_recovery(sync_id, acknowledgements)
            reconciler._persist_success(
                record, canonical=canonical, mirror=mirror, direction="user_resolution", bytes_copied=chosen["size"] * 2
            )
        except (OSError, PdfConflictChanged) as exc:
            reconciler.store.update(
                sync_id, state="conflict", retryable=False, message="PDF changed during recovery; copies retained."
            )
            raise PdfConflictChanged("PDF changed during recovery; copies retained.") from exc
        return {
            "status": reconciler.store.public_status(reconciler.store.get(sync_id)),
            "retained_directory": str(archive),
        }
