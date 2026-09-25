"""Version-checked PDF recovery shared by the CLI and local WebUI.

Readers must be closed before resolving. Copies are retained without automatic
cleanup, including displaced inodes that a reader might still write later.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

from scholaraio.services.pdf_edit_mirror import recovery_identity

if TYPE_CHECKING:
    from scholaraio.services.pdf_edit_mirror import PdfEditMirrorReconciler, PdfTargetResolution
    from scholaraio.stores.pdf_edit_mirror import PdfEditMirrorRecord


TargetResolver = Callable[["PdfEditMirrorRecord"], "PdfTargetResolution"]


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
                "exportable": bool(identity[0]) and state.exists and not path.is_symlink(),
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


def _refresh_target(reconciler: PdfEditMirrorReconciler, sync_id: str, resolver: TargetResolver) -> None:
    record = reconciler.store.get(sync_id)
    if record is None or record.retired_at is not None:
        raise KeyError(sync_id)
    resolution = resolver(record)
    if resolution.ambiguous or resolution.target is None:
        raise PdfConflictChanged("Paper is missing or ambiguous; recovery cannot use its previous path.")
    target = resolution.target
    if target.paper_id != record.paper_id and not (record.identity and target.identity == record.identity):
        state = reconciler._inspect(target.canonical_path, target.library_root)
        if not record.base_hash or state.content_hash != record.base_hash:
            raise PdfConflictChanged("Paper identity changed; recovery cannot use a reused path.")
    reconciler.register(target, existing_record=record)


def inspect_conflict(reconciler: PdfEditMirrorReconciler, sync_id: str, *, resolver: TargetResolver) -> dict:
    with reconciler._entry_lock(sync_id, timeout_seconds=30):
        _refresh_target(reconciler, sync_id, resolver)
        return _snapshot(reconciler, sync_id)[0]


@contextmanager
def export_version(
    reconciler: PdfEditMirrorReconciler,
    sync_id: str,
    version: str,
    token: str,
    *,
    resolver: TargetResolver,
    preview: bool = False,
) -> Iterator[Path]:
    """Yield an owned, version-checked snapshot for the entire streaming lifetime."""
    reconciler.paths.state_root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="pdf-export-", dir=reconciler.paths.state_root) as directory:
        copy = Path(directory) / "snapshot.pdf"
        with reconciler._entry_lock(sync_id, timeout_seconds=30):
            _refresh_target(reconciler, sync_id, resolver)
            snapshot, paths = _snapshot(reconciler, sync_id)
            if snapshot["token"] != token:
                raise PdfConflictChanged("PDF versions changed; inspect them again.")
            if version not in paths:
                raise KeyError(version)
            selected = next(item for item in snapshot["versions"] if item["id"] == version)
            if not selected["exportable"] or (preview and not selected["valid"]):
                raise ValueError("This PDF version is unavailable or cannot be previewed.")
            if selected["valid"]:
                reconciler._atomic_copy(paths[version], copy, destination_root=copy.parent)
            else:
                with paths[version].open("rb") as src, copy.open("xb") as dst:
                    shutil.copyfileobj(src, dst)
            _refresh_target(reconciler, sync_id, resolver)
            if (
                recovery_identity(copy, copy.parent)[0] != selected["hash"]
                or _snapshot(reconciler, sync_id)[0]["token"] != token
            ):
                raise PdfConflictChanged("PDF changed during export; inspect it again.")
        yield copy


def resolve_conflict(
    reconciler: PdfEditMirrorReconciler, sync_id: str, *, token: str, version: str, resolver: TargetResolver
) -> dict:
    """Retain both sides, publish an explicitly selected version, reject stale input."""
    with reconciler._entry_lock(sync_id, timeout_seconds=30):
        _refresh_target(reconciler, sync_id, resolver)
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
                retained = archive / (item["id"] + ".pdf")
                reconciler._atomic_copy(paths[item["id"]], retained, destination_root=archive)
                if recovery_identity(retained, archive)[0] != item["hash"]:
                    raise PdfConflictChanged("PDF changed while retaining recovery copies.")
        expected = {key: reconciler._inspect(paths[key], paths[key].parent) for key in ("canonical", "mirror")}
        _refresh_target(reconciler, sync_id, resolver)
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
