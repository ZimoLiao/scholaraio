"""WSL-to-Windows PDF edit mirror synchronization."""

from __future__ import annotations

import errno
import hashlib
import importlib
import logging
import os
import re
import stat
import tempfile
import threading
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scholaraio.stores.pdf_edit_mirror import PdfEditMirrorRecord, PdfEditMirrorStore

_TRAILING_PDF_WINDOW_BYTES = 64 * 1024
_SYNC_FAILURE_THRESHOLD = 5
DeepValidator = Callable[[Path], tuple[bool, str] | None]
_LOG = logging.getLogger(__name__)


class _DestinationChanged(OSError):
    """An external writer changed the destination during synchronization."""


@dataclass(frozen=True)
class PdfValidationResult:
    """Validated content and metadata captured from one stable PDF file."""

    valid: bool
    exists: bool
    message: str = ""
    content_hash: str = ""
    size: int = 0
    mtime_ns: int = 0
    inode: int = 0
    deep_checked: bool = False


@dataclass(frozen=True)
class PdfMirrorTarget:
    """A server-resolved library record eligible for synchronization."""

    library_kind: str
    paper_id: str
    canonical_path: Path
    library_root: Path
    display_name: str
    identity: str = ""


@dataclass(frozen=True)
class PdfReconcileResult:
    """One reconciliation attempt without filesystem paths."""

    state: str
    direction: str = ""
    retryable: bool = False
    message: str = ""
    bytes_copied: int = 0


@dataclass(frozen=True)
class PdfOpenPreparation:
    """A safe launch decision for the WebUI native-open route."""

    mirror_path: Path
    launchable: bool
    status: dict[str, object]


@dataclass(frozen=True)
class PdfTargetResolution:
    """Background resolution result, including ambiguous rename detection."""

    target: PdfMirrorTarget | None
    ambiguous: bool = False


@dataclass(frozen=True)
class PdfEditMirrorPaths:
    """Managed roots and deterministic paths for editable PDF mirrors."""

    mirror_root: Path
    state_root: Path

    @staticmethod
    def sanitize_display_name(display_name: str) -> str:
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", Path(display_name).name).strip(" .")
        stem = Path(name or "paper.pdf").stem[:120].strip(" .") or "paper"
        return f"{stem}.pdf"

    def mirror_path(self, *, library_kind: str, sync_id: str, display_name: str) -> Path:
        if library_kind not in {"main", "proceedings"}:
            raise ValueError(f"Unsupported library kind: {library_kind}")
        return (
            Path(self.mirror_root).expanduser() / library_kind / sync_id / self.sanitize_display_name(display_name)
        ).resolve()

    def backup_path(self, sync_id: str) -> Path:
        return (Path(self.state_root).expanduser() / "backups" / f"{sync_id}.pdf").resolve()

    def lock_path(self, sync_id: str) -> Path:
        return (Path(self.state_root).expanduser() / "locks" / f"{sync_id}.lock").resolve()


def _path_within(path: Path, root: Path) -> bool:
    absolute = Path(os.path.abspath(path))
    resolved_root = Path(root).expanduser().resolve()
    try:
        absolute.parent.resolve().relative_to(resolved_root)
    except (OSError, ValueError):
        return False
    return True


def _optional_deep_validate(path: Path) -> tuple[bool, str] | None:
    pdf_module: Any = None
    for module_name in ("pymupdf", "fitz"):
        try:
            pdf_module = importlib.import_module(module_name)
            break
        except ImportError:
            continue
    if pdf_module is not None:
        try:
            with pdf_module.open(path) as document:
                if len(document) <= 0:
                    return False, "PDF has no readable pages"
        except Exception:
            return False, "PDF deep structure check failed"
        return True, ""

    try:
        import pikepdf
    except ImportError:
        return None
    try:
        with pikepdf.open(path) as document:
            if len(document.pages) <= 0:
                return False, "PDF has no readable pages"
    except Exception:
        return False, "PDF deep structure check failed"
    return True, ""


def validate_pdf_candidate(
    path: Path,
    *,
    expected_root: Path,
    deep_validator: DeepValidator | None = _optional_deep_validate,
) -> PdfValidationResult:
    """Validate and hash a regular, stable PDF below an expected managed root."""
    candidate = Path(path).expanduser()
    if not _path_within(candidate, expected_root):
        return PdfValidationResult(False, candidate.exists(), "PDF candidate is outside its managed root")
    try:
        if candidate.is_symlink():
            return PdfValidationResult(False, True, "PDF candidate must not be a symbolic link")
        before = candidate.stat(follow_symlinks=False)
    except FileNotFoundError:
        return PdfValidationResult(False, False, "PDF candidate is missing")
    except OSError:
        return PdfValidationResult(False, candidate.exists(), "PDF candidate cannot be inspected")
    if not stat.S_ISREG(before.st_mode):
        return PdfValidationResult(False, True, "PDF candidate is not a regular file")
    if before.st_size <= 0:
        return PdfValidationResult(
            False,
            True,
            "PDF candidate is empty",
            content_hash=hashlib.sha256(b"").hexdigest(),
            size=0,
            mtime_ns=before.st_mtime_ns,
            inode=before.st_ino,
        )

    digest = hashlib.sha256()
    try:
        with candidate.open("rb") as stream:
            header = stream.read(5)
            digest.update(header)
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
            stream.seek(max(0, before.st_size - _TRAILING_PDF_WINDOW_BYTES))
            tail = stream.read()
        after = candidate.stat(follow_symlinks=False)
    except OSError:
        return PdfValidationResult(False, True, "PDF candidate could not be read consistently")

    before_signature = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    after_signature = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if before_signature != after_signature:
        return PdfValidationResult(False, True, "PDF candidate changed while it was being read")
    if header != b"%PDF-":
        return PdfValidationResult(
            False,
            True,
            "PDF candidate has an invalid header",
            content_hash=digest.hexdigest(),
            size=after.st_size,
            mtime_ns=after.st_mtime_ns,
            inode=after.st_ino,
        )
    if b"%%EOF" not in tail:
        return PdfValidationResult(
            False,
            True,
            "PDF candidate has no end-of-file marker",
            content_hash=digest.hexdigest(),
            size=after.st_size,
            mtime_ns=after.st_mtime_ns,
            inode=after.st_ino,
        )

    deep_checked = False
    if deep_validator is not None:
        deep_result = deep_validator(candidate)
        if deep_result is not None:
            deep_checked = True
            deep_ok, deep_message = deep_result
            if not deep_ok:
                return PdfValidationResult(
                    False,
                    True,
                    deep_message or "PDF deep structure check failed",
                    deep_checked=True,
                    content_hash=digest.hexdigest(),
                    size=after.st_size,
                    mtime_ns=after.st_mtime_ns,
                    inode=after.st_ino,
                )
    return PdfValidationResult(
        True,
        True,
        content_hash=digest.hexdigest(),
        size=after.st_size,
        mtime_ns=after.st_mtime_ns,
        inode=after.st_ino,
        deep_checked=deep_checked,
    )


def recovery_identity(path: Path, root: Path) -> tuple[str, int, int, int]:
    """Hash stable retained bytes, including a damaged PDF, without following links."""
    if not _path_within(path, root) or path.is_symlink():
        raise OSError("Recovery file is outside its managed root or is a symbolic link")
    before = path.stat()
    if not stat.S_ISREG(before.st_mode):
        raise OSError("Recovery candidate is not a regular file")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
        after = os.fstat(stream.fileno())

    def signature(value: os.stat_result) -> tuple[int, int, int, int]:
        return (value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)

    if signature(before) != signature(after) or signature(before) != signature(path.stat()):
        raise OSError("Recovery candidate changed while reading")
    return digest.hexdigest(), after.st_size, after.st_mtime_ns, after.st_ino


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_log_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._:@+-]", "_", str(value or ""))[:96] or "unknown"


class PdfEditMirrorReconciler:
    """Validate complete PDFs and atomically converge canonical and mirror copies."""

    def __init__(
        self,
        *,
        store: PdfEditMirrorStore,
        paths: PdfEditMirrorPaths,
        deep_validator: DeepValidator | None = _optional_deep_validate,
    ):
        self.store = store
        self.paths = paths
        self.deep_validator = deep_validator
        self._library_roots: dict[str, Path] = {}
        self._thread_locks: dict[str, threading.Lock] = {}
        self._thread_locks_guard = threading.Lock()

    def register(
        self,
        target: PdfMirrorTarget,
        *,
        existing_record: PdfEditMirrorRecord | None = None,
    ) -> PdfEditMirrorRecord:
        if target.library_kind not in {"main", "proceedings"}:
            raise ValueError(f"Unsupported library kind: {target.library_kind}")
        if not _path_within(target.canonical_path, target.library_root):
            raise ValueError("Canonical PDF is outside its configured library root")
        existing = existing_record or self.store.get_by_paper(target.library_kind, target.paper_id)
        if existing is None and target.identity:
            identity_matches = self.store.list_by_identity(target.library_kind, target.identity)
            if len(identity_matches) == 1:
                existing = identity_matches[0]
        if existing is not None and existing.library_kind != target.library_kind:
            raise ValueError("Cannot rebind a PDF mirror across library kinds")
        if existing is not None and (
            existing.paper_id != target.paper_id or existing.canonical_path != target.canonical_path.resolve()
        ):
            existing = self.store.update(
                existing.sync_id,
                paper_id=target.paper_id,
                canonical_path=target.canonical_path,
                identity=target.identity or existing.identity,
                retired_at=None,
            )
        sync_id = existing.sync_id if existing is not None else str(uuid.uuid4())
        mirror_path = (
            existing.mirror_path
            if existing is not None
            else self.paths.mirror_path(
                library_kind=target.library_kind,
                sync_id=sync_id,
                display_name=target.display_name,
            )
        )
        record = self.store.get_or_create(
            library_kind=target.library_kind,
            paper_id=target.paper_id,
            canonical_path=target.canonical_path,
            mirror_path=mirror_path,
            identity=target.identity,
            sync_id=sync_id,
        )
        self._library_roots[record.sync_id] = Path(target.library_root).expanduser().resolve()
        return record

    @contextmanager
    def _entry_lock(self, sync_id: str, *, timeout_seconds: float):
        with self._thread_locks_guard:
            thread_lock = self._thread_locks.setdefault(sync_id, threading.Lock())
        timeout = max(0.0, timeout_seconds)
        started = time.monotonic()
        if not thread_lock.acquire(timeout=timeout):
            raise TimeoutError("PDF synchronization thread lock timed out")
        try:
            lock_path = self.paths.lock_path(sync_id)
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            with lock_path.open("a+b") as lock_file:
                try:
                    fcntl_module: Any = importlib.import_module("fcntl")
                except ImportError:  # pragma: no cover - service runs under Linux/WSL
                    fcntl_module = None
                if fcntl_module is not None:
                    deadline = time.monotonic() + max(0.0, timeout - (time.monotonic() - started))
                    while True:
                        try:
                            fcntl_module.flock(
                                lock_file.fileno(),
                                fcntl_module.LOCK_EX | fcntl_module.LOCK_NB,
                            )
                            break
                        except BlockingIOError as exc:
                            if time.monotonic() >= deadline:
                                raise TimeoutError("PDF synchronization lock timed out") from exc
                            time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
                try:
                    yield
                finally:
                    if fcntl_module is not None:
                        fcntl_module.flock(lock_file.fileno(), fcntl_module.LOCK_UN)
        finally:
            thread_lock.release()

    def _inspect(self, path: Path, root: Path) -> PdfValidationResult:
        return validate_pdf_candidate(
            path,
            expected_root=root,
            deep_validator=self.deep_validator,
        )

    def _atomic_copy(
        self,
        source: Path,
        destination: Path,
        *,
        destination_root: Path,
        expected_destination: PdfValidationResult | None = None,
    ) -> int:
        if not _path_within(destination, destination_root):
            raise OSError("PDF destination is outside its managed root")
        source_state = source.stat(follow_symlinks=False)
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
        )
        temporary = Path(temporary_name)
        try:
            copied_hash = hashlib.sha256()
            with os.fdopen(descriptor, "wb") as destination_stream, source.open("rb") as source_stream:
                while chunk := source_stream.read(1024 * 1024):
                    copied_hash.update(chunk)
                    destination_stream.write(chunk)
                destination_stream.flush()
                os.fsync(destination_stream.fileno())
            source_after = source.stat(follow_symlinks=False)
            before_signature = (
                source_state.st_dev,
                source_state.st_ino,
                source_state.st_size,
                source_state.st_mtime_ns,
            )
            after_signature = (
                source_after.st_dev,
                source_after.st_ino,
                source_after.st_size,
                source_after.st_mtime_ns,
            )
            if before_signature != after_signature:
                raise OSError("PDF source changed during atomic copy")
            os.utime(temporary, ns=(source_state.st_atime_ns, source_state.st_mtime_ns))
            validation = self._inspect(temporary, destination_root)
            if not validation.valid:
                raise OSError(validation.message)
            if validation.content_hash != copied_hash.hexdigest():
                raise OSError("PDF copy hash did not match the source stream")
            if expected_destination is None:
                os.replace(temporary, destination)
            else:
                self._publish_pdf(temporary, destination, destination_root, expected_destination)
            try:
                directory_fd = os.open(destination.parent, os.O_RDONLY)
            except OSError:
                directory_fd = None
            if directory_fd is not None:
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            return validation.size
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def _publish_pdf(self, temporary: Path, destination: Path, root: Path, expected: PdfValidationResult) -> None:
        """Publish without destroying a concurrent save or an open writer's inode.

        There is no portable filesystem compare-and-swap against an external PDF
        reader. Move the old inode into retained recovery storage, validate that
        generation, then link the prepared file only if the name is still absent.
        Never remove the retained inode: a reader may still hold it open.
        """
        if self._inspect(destination, root) != expected:
            raise _DestinationChanged()
        retained = None
        try:
            if expected.exists:
                recovery_dir = destination.parent / ".scholaraio-pdf-recovery" / destination.name
                recovery_dir.mkdir(parents=True, exist_ok=True)
                original_hash, original_size, original_mtime = expected.content_hash, expected.size, expected.mtime_ns
                if not original_hash:
                    # Invalid PDFs still need a baseline for detecting writes
                    # through old handles after recovery from the other side.
                    original_stat = destination.stat()
                    digest = hashlib.sha256()
                    with destination.open("rb") as stream:
                        while chunk := stream.read(1024 * 1024):
                            digest.update(chunk)
                    original_hash = digest.hexdigest()
                    original_size, original_mtime = original_stat.st_size, original_stat.st_mtime_ns
                retained = recovery_dir / (f"{original_hash}_{original_size}_{original_mtime}_{uuid.uuid4()}.pdf")
                try:
                    destination.rename(retained)
                except FileNotFoundError as exc:
                    raise _DestinationChanged() from exc
                if self._inspect(retained, root) != expected:
                    raise _DestinationChanged()
            try:
                os.link(temporary, destination)
            except FileExistsError as exc:
                raise _DestinationChanged() from exc
            if retained is not None and self._inspect(retained, root) != expected:
                raise _DestinationChanged()
        except OSError:
            if retained is not None and retained.exists():
                # Restore the displaced file only if a reader has not already
                # created a new file at this name. Both versions stay recoverable.
                try:
                    os.link(retained, destination)
                except OSError:
                    pass
            raise

    def recovery_changed(self, record: PdfEditMirrorRecord) -> bool:
        """Detect saves through handles still referencing a displaced inode."""
        acknowledged = self.store.recovery_acknowledgements(record.sync_id)
        for active in (record.canonical_path, record.mirror_path):
            recovery_dir = active.parent / ".scholaraio-pdf-recovery" / active.name
            for path in recovery_dir.glob("*.pdf"):
                if str(path) in acknowledged:
                    baseline = acknowledged[str(path)]
                    try:
                        current = path.stat()
                        if (current.st_size, current.st_mtime_ns, current.st_ino) != baseline[1:]:
                            if recovery_identity(path, active.parent)[0] != baseline[0]:
                                return True
                    except OSError:
                        return True
                    continue
                fields = path.stem.split("_")
                if len(fields) != 4:
                    return True
                content_hash, size, mtime, _identifier = fields
                try:
                    state = path.stat()
                    if (state.st_size, state.st_mtime_ns) == (int(size), int(mtime)):
                        continue
                except (OSError, ValueError):
                    return True
                if self._inspect(path, active.parent).content_hash != content_hash:
                    return True
        return False

    def _set_pending(self, record: PdfEditMirrorRecord, message: str) -> PdfReconcileResult:
        failure_count = record.failure_count + 1
        state = "sync_failed" if failure_count >= _SYNC_FAILURE_THRESHOLD else "sync_pending"
        self.store.update(
            record.sync_id,
            state=state,
            retryable=True,
            message=message,
            failure_count=failure_count,
        )
        return PdfReconcileResult(state, retryable=True, message=message)

    def _persist_success(
        self,
        record: PdfEditMirrorRecord,
        *,
        canonical: PdfValidationResult,
        mirror: PdfValidationResult,
        direction: str,
        bytes_copied: int,
    ) -> PdfReconcileResult:
        # All success paths, including backup restoration, must check old reader
        # handles immediately before advancing the common base hash.
        if self.recovery_changed(record):
            raise _DestinationChanged()
        self.store.update(
            record.sync_id,
            base_hash=canonical.content_hash,
            canonical_hash=canonical.content_hash,
            canonical_size=canonical.size,
            canonical_mtime_ns=canonical.mtime_ns,
            canonical_inode=canonical.inode,
            mirror_hash=mirror.content_hash,
            mirror_size=mirror.size,
            mirror_mtime_ns=mirror.mtime_ns,
            mirror_inode=mirror.inode,
            state="in_sync",
            retryable=False,
            message="",
            last_success_at=_now_iso(),
            last_direction=direction,
            failure_count=0,
            next_retry_at=0.0,
        )
        return PdfReconcileResult("in_sync", direction=direction, bytes_copied=bytes_copied)

    def _copy_winner(
        self,
        record: PdfEditMirrorRecord,
        *,
        source: Path,
        destination: Path,
        destination_state: PdfValidationResult,
        destination_root: Path,
        direction: str,
        library_root: Path,
    ) -> PdfReconcileResult:
        if destination_state.valid:
            backup = self.paths.backup_path(record.sync_id)
            self._atomic_copy(destination, backup, destination_root=self.paths.state_root)
        bytes_copied = self._atomic_copy(
            source, destination, destination_root=destination_root, expected_destination=destination_state
        )
        canonical = self._inspect(record.canonical_path, library_root)
        mirror = self._inspect(record.mirror_path, self.paths.mirror_root)
        if not canonical.valid or not mirror.valid or canonical.content_hash != mirror.content_hash:
            return self._set_pending(record, "Copied PDF could not be verified on both sides")
        return self._persist_success(
            record,
            canonical=canonical,
            mirror=mirror,
            direction=direction,
            bytes_copied=bytes_copied,
        )

    def _restore_backup(
        self,
        record: PdfEditMirrorRecord,
        *,
        library_root: Path,
        backup: PdfValidationResult,
        canonical: PdfValidationResult,
        mirror: PdfValidationResult,
    ) -> PdfReconcileResult:
        backup_path = self.paths.backup_path(record.sync_id)
        copied = self._atomic_copy(
            backup_path,
            record.canonical_path,
            destination_root=library_root,
            expected_destination=canonical,
        )
        copied += self._atomic_copy(
            backup_path,
            record.mirror_path,
            destination_root=self.paths.mirror_root,
            expected_destination=mirror,
        )
        canonical = self._inspect(record.canonical_path, library_root)
        mirror = self._inspect(record.mirror_path, self.paths.mirror_root)
        if (
            not canonical.valid
            or not mirror.valid
            or canonical.content_hash != backup.content_hash
            or mirror.content_hash != backup.content_hash
        ):
            return self._set_pending(record, "Backup recovery could not be verified")
        return self._persist_success(
            record,
            canonical=canonical,
            mirror=mirror,
            direction="backup_restore",
            bytes_copied=copied,
        )

    @staticmethod
    def _safe_error(exc: BaseException) -> str:
        if isinstance(exc, PermissionError):
            category = "permission was denied"
        elif isinstance(exc, TimeoutError):
            category = "another synchronization worker held the entry lock too long"
        elif isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
            category = "the destination has insufficient free space"
        elif isinstance(exc, OSError):
            category = "an I/O operation failed"
        else:
            category = "an internal synchronization operation failed"
        return f"PDF synchronization could not complete because {category}"

    def reconcile(
        self,
        sync_id: str,
        *,
        record_exists: bool,
        lock_timeout_seconds: float = 30.0,
    ) -> PdfReconcileResult:
        started = time.monotonic()
        try:
            with self._entry_lock(sync_id, timeout_seconds=lock_timeout_seconds):
                result = self._reconcile_locked(sync_id, record_exists=record_exists)
        except _DestinationChanged:
            message = (
                "A PDF changed during synchronization. Preserve both PDFs and the adjacent "
                ".scholaraio-pdf-recovery files before reconciling the copies."
            )
            self.store.update(sync_id, state="conflict", retryable=False, message=message, next_retry_at=0.0)
            result = PdfReconcileResult("conflict", retryable=False, message=message)
        except (OSError, RuntimeError) as exc:
            record = self.store.get(sync_id)
            if record is None:
                raise KeyError(sync_id) from exc
            result = self._set_pending(record, self._safe_error(exc))
        persisted = self.store.get(sync_id)
        _LOG.info(
            "pdf-edit-mirror paper=%s source=%s direction=%s state=%s bytes=%d duration_ms=%d",
            _safe_log_id(persisted.paper_id) if persisted is not None else "unknown",
            persisted.library_kind if persisted is not None else "unknown",
            result.direction or "none",
            result.state,
            result.bytes_copied,
            int((time.monotonic() - started) * 1000),
        )
        return result

    def _reconcile_locked(self, sync_id: str, *, record_exists: bool) -> PdfReconcileResult:
        record = self.store.get(sync_id)
        if record is None:
            raise KeyError(sync_id)
        library_root = self._library_roots.get(sync_id)
        if library_root is None:
            library_root = record.canonical_path.parent
        if not record_exists:
            return self._set_pending(record, "Library record is no longer available")
        if self.recovery_changed(record):
            raise _DestinationChanged()

        canonical = self._inspect(record.canonical_path, library_root)
        mirror = self._inspect(record.mirror_path, self.paths.mirror_root)
        if mirror.exists and not mirror.valid and canonical.valid:
            return self._set_pending(record, mirror.message)
        if canonical.exists and not canonical.valid and mirror.valid:
            return self._copy_winner(
                record,
                source=record.mirror_path,
                destination=record.canonical_path,
                destination_state=canonical,
                destination_root=library_root,
                direction="mirror_to_canonical",
                library_root=library_root,
            )
        if not canonical.valid and not mirror.valid:
            backup = self._inspect(self.paths.backup_path(record.sync_id), self.paths.state_root)
            if backup.valid:
                return self._restore_backup(
                    record, library_root=library_root, backup=backup, canonical=canonical, mirror=mirror
                )
            return self._set_pending(record, canonical.message if canonical.exists else mirror.message)
        if canonical.valid and not mirror.exists:
            return self._copy_winner(
                record,
                source=record.canonical_path,
                destination=record.mirror_path,
                destination_state=mirror,
                destination_root=self.paths.mirror_root,
                direction="canonical_to_mirror",
                library_root=library_root,
            )
        if mirror.valid and not canonical.exists:
            return self._copy_winner(
                record,
                source=record.mirror_path,
                destination=record.canonical_path,
                destination_state=canonical,
                destination_root=library_root,
                direction="mirror_to_canonical",
                library_root=library_root,
            )
        if not canonical.valid or not mirror.valid:  # pragma: no cover - exhaustive guard
            return self._set_pending(record, "PDF validation failed")
        if canonical.content_hash == mirror.content_hash:
            return self._persist_success(
                record,
                canonical=canonical,
                mirror=mirror,
                direction="none",
                bytes_copied=0,
            )

        canonical_changed = canonical.content_hash != record.base_hash
        mirror_changed = mirror.content_hash != record.base_hash
        if canonical_changed and not mirror_changed:
            winner = "canonical"
        elif mirror_changed and not canonical_changed:
            winner = "mirror"
        else:
            message = (
                "Both PDFs changed. Synchronization is paused; preserve and reconcile both copies before reopening."
            )
            self.store.update(
                record.sync_id,
                state="conflict",
                retryable=False,
                message=message,
                canonical_hash=canonical.content_hash,
                canonical_size=canonical.size,
                canonical_mtime_ns=canonical.mtime_ns,
                canonical_inode=canonical.inode,
                mirror_hash=mirror.content_hash,
                mirror_size=mirror.size,
                mirror_mtime_ns=mirror.mtime_ns,
                mirror_inode=mirror.inode,
                next_retry_at=0.0,
            )
            return PdfReconcileResult("conflict", retryable=False, message=message)

        if winner == "canonical":
            return self._copy_winner(
                record,
                source=record.canonical_path,
                destination=record.mirror_path,
                destination_state=mirror,
                destination_root=self.paths.mirror_root,
                direction="canonical_to_mirror",
                library_root=library_root,
            )
        return self._copy_winner(
            record,
            source=record.mirror_path,
            destination=record.canonical_path,
            destination_state=canonical,
            destination_root=library_root,
            direction="mirror_to_canonical",
            library_root=library_root,
        )


class PdfEditMirrorService:
    """Lifecycle, settling, retry, retirement, and launch coordination."""

    def __init__(
        self,
        *,
        store: PdfEditMirrorStore,
        paths: PdfEditMirrorPaths,
        resolver: Callable[[PdfEditMirrorRecord], PdfMirrorTarget | PdfTargetResolution | None] | None,
        deep_validator: DeepValidator | None = _optional_deep_validate,
        poll_interval: float = 1.0,
        settle_interval: float = 1.0,
        stable_observations: int = 2,
        retry_max_seconds: float = 60.0,
        resolution_audit_interval: float = 60.0,
        retirement_grace_seconds: float = 7 * 24 * 60 * 60,
        wall_clock: Callable[[], float] = time.time,
        monotonic_clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        auto_start: bool = True,
    ):
        self.store = store
        self.paths = paths
        self.resolver = resolver
        self.poll_interval = max(0.01, float(poll_interval))
        self.settle_interval = max(0.0, float(settle_interval))
        self.stable_observations = max(1, int(stable_observations))
        self.retry_max_seconds = max(1.0, float(retry_max_seconds))
        self.resolution_audit_interval = max(self.poll_interval, float(resolution_audit_interval))
        self.retirement_grace_seconds = max(0.0, float(retirement_grace_seconds))
        self.wall_clock = wall_clock
        self.monotonic_clock = monotonic_clock
        self.sleep = sleep
        self.reconciler = PdfEditMirrorReconciler(store=store, paths=paths, deep_validator=deep_validator)
        self._observations: dict[str, tuple[tuple[object, ...], int]] = {}
        self._next_resolution_audit: dict[str, float] = {}
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        if auto_start:
            self.start()

    @classmethod
    def for_wsl(
        cls,
        cfg,
        *,
        resolver: Callable[[PdfEditMirrorRecord], PdfMirrorTarget | PdfTargetResolution | None],
        auto_start: bool = True,
    ) -> PdfEditMirrorService:
        from scholaraio.services.system_open import cleanup_legacy_wsl_pdf_copies, wsl_windows_local_app_data

        state_root = cfg.pdf_edit_mirror_state_dir
        cleanup_legacy_wsl_pdf_copies()
        paths = PdfEditMirrorPaths(
            mirror_root=wsl_windows_local_app_data() / "ScholarAIO" / "editable-pdfs",
            state_root=state_root,
        )
        return cls(
            store=PdfEditMirrorStore(state_root / "sync.db"),
            paths=paths,
            resolver=resolver,
            auto_start=auto_start,
        )

    @staticmethod
    def _signature(path: Path) -> tuple[object, ...]:
        try:
            value = path.stat(follow_symlinks=False)
        except FileNotFoundError:
            return (False, 0, 0, 0)
        except OSError:
            return ("error", 0, 0, 0)
        return (True, value.st_size, value.st_mtime_ns, value.st_ino)

    @staticmethod
    def _stored_signatures(record: PdfEditMirrorRecord) -> tuple[tuple[object, ...], tuple[object, ...]]:
        return (
            (bool(record.canonical_hash), record.canonical_size, record.canonical_mtime_ns, record.canonical_inode),
            (bool(record.mirror_hash), record.mirror_size, record.mirror_mtime_ns, record.mirror_inode),
        )

    def _current_signatures(self, record: PdfEditMirrorRecord) -> tuple[tuple[object, ...], tuple[object, ...]]:
        return self._signature(record.canonical_path), self._signature(record.mirror_path)

    def _changed(self, record: PdfEditMirrorRecord) -> bool:
        return self._current_signatures(record) != self._stored_signatures(record) or self.reconciler.recovery_changed(
            record
        )

    def _wait_until_settled(self, record: PdfEditMirrorRecord, budget_seconds: float) -> bool:
        if not record.base_hash or not self._changed(record):
            return True
        if budget_seconds <= 0:
            return True
        deadline = self.monotonic_clock() + budget_seconds
        previous: tuple[tuple[object, ...], tuple[object, ...]] | None = None
        stable = 0
        while True:
            current = self._current_signatures(record)
            stable = stable + 1 if current == previous else 1
            if stable >= self.stable_observations:
                return True
            remaining = deadline - self.monotonic_clock()
            if remaining <= 0:
                return False
            previous = current
            self.sleep(min(self.settle_interval, remaining))

    def _known_good_launchable(self, record: PdfEditMirrorRecord) -> bool:
        if not record.base_hash:
            return False
        library_root = self.reconciler._library_roots.get(record.sync_id, record.canonical_path.parent)
        canonical = self.reconciler._inspect(record.canonical_path, library_root)
        mirror = self.reconciler._inspect(record.mirror_path, self.paths.mirror_root)
        return (
            canonical.valid
            and mirror.valid
            and canonical.content_hash == record.base_hash
            and mirror.content_hash == record.base_hash
        )

    def prepare_for_open(self, target: PdfMirrorTarget, *, budget_seconds: float = 30.0) -> PdfOpenPreparation:
        started = self.monotonic_clock()
        record = self.reconciler.register(target)
        if record.state == "in_sync" and record.base_hash and not self._changed(record):
            return PdfOpenPreparation(
                mirror_path=record.mirror_path,
                launchable=True,
                status=self.store.public_status(record),
            )
        if record.state == "conflict" and not self._changed(record):
            return PdfOpenPreparation(record.mirror_path, False, self.store.public_status(record))
        if not self._wait_until_settled(record, budget_seconds):
            record = self.store.update(
                record.sync_id,
                state="sync_pending",
                retryable=True,
                message="PDF change is still being saved; synchronization will retry",
            )
        else:
            remaining = max(0.0, budget_seconds - (self.monotonic_clock() - started))
            self.reconciler.reconcile(
                record.sync_id,
                record_exists=True,
                lock_timeout_seconds=remaining,
            )
            record = self.store.get(record.sync_id) or record
        launchable = record.state == "in_sync" or (record.state != "conflict" and self._known_good_launchable(record))
        return PdfOpenPreparation(
            mirror_path=record.mirror_path,
            launchable=launchable,
            status=self.store.public_status(record),
        )

    def status(self, library_kind: str, paper_id: str) -> dict[str, object]:
        return self.store.public_status(self.store.get_by_paper(library_kind, paper_id))

    @staticmethod
    def _normalize_resolution(
        value: PdfMirrorTarget | PdfTargetResolution | None,
    ) -> PdfTargetResolution:
        if isinstance(value, PdfTargetResolution):
            return value
        return PdfTargetResolution(target=value)

    def _record_retry(self, record: PdfEditMirrorRecord) -> None:
        refreshed = self.store.get(record.sync_id)
        if refreshed is None or refreshed.state == "in_sync":
            return
        delay = min(2 ** max(0, refreshed.failure_count - 1), self.retry_max_seconds)
        self.store.update(refreshed.sync_id, next_retry_at=self.wall_clock() + delay)

    def _cleanup_retired(self) -> None:
        cutoff = self.wall_clock() - self.retirement_grace_seconds
        for record in self.store.list_retired_before(cutoff):
            cleanup_failed = False
            for path in (
                record.mirror_path,
                self.paths.backup_path(record.sync_id),
                self.paths.lock_path(record.sync_id),
            ):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
                except OSError:
                    cleanup_failed = True
            if cleanup_failed:
                continue
            try:
                record.mirror_path.parent.rmdir()
            except OSError:
                pass
            self.store.delete(record.sync_id)

    def poll_once(self) -> None:
        self._cleanup_retired()
        if self.resolver is None:
            return
        now = self.wall_clock()
        for current in self.store.list_active():
            signatures = self._current_signatures(current)
            signature_changed = signatures != self._stored_signatures(current) or self.reconciler.recovery_changed(
                current
            )
            retry_due = current.next_retry_at <= now
            audit_due = self._next_resolution_audit.get(current.sync_id, 0.0) <= now
            needs_reconcile = signature_changed or current.state not in {"in_sync", "conflict"}
            if not (signature_changed or audit_due or (needs_reconcile and retry_due)):
                continue
            resolution = self._normalize_resolution(self.resolver(current))
            self._next_resolution_audit[current.sync_id] = now + self.resolution_audit_interval
            if resolution.ambiguous:
                self.store.update(
                    current.sync_id,
                    state="sync_pending",
                    retryable=True,
                    message="PDF library record rename is ambiguous; synchronization is paused",
                )
                continue
            if resolution.target is None:
                self.store.mark_retired(current.sync_id, retired_at=now)
                self._next_resolution_audit.pop(current.sync_id, None)
                continue
            current = self.reconciler.register(resolution.target, existing_record=current)
            if current.next_retry_at > now:
                continue
            signatures = self._current_signatures(current)
            changed = self._changed(current) or current.state not in {"in_sync", "conflict"}
            if not changed:
                self._observations.pop(current.sync_id, None)
                continue
            previous, count = self._observations.get(current.sync_id, ((), 0))
            count = count + 1 if signatures == previous else 1
            self._observations[current.sync_id] = (signatures, count)
            if count < self.stable_observations:
                continue
            result = self.reconciler.reconcile(current.sync_id, record_exists=True)
            self._observations.pop(current.sync_id, None)
            if result.retryable:
                self._record_retry(current)

    def _run(self) -> None:
        while not self._stop_event.wait(self.poll_interval):
            try:
                self.poll_once()
            except Exception:
                _LOG.exception("PDF edit mirror monitor iteration failed")

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="scholaraio-pdf-edit-mirror", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(35.0, self.poll_interval * 2))
        if thread is not None and thread.is_alive():
            _LOG.warning("PDF edit mirror monitor did not stop before the shutdown timeout")
            return
        self._thread = None
