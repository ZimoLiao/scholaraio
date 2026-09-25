"""Persistent synchronization records for WSL PDF edit mirrors."""

from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PdfEditMirrorRecord:
    """One durable canonical-PDF to Windows-mirror mapping."""

    sync_id: str
    library_kind: str
    paper_id: str
    canonical_path: Path
    mirror_path: Path
    identity: str = ""
    base_hash: str = ""
    canonical_hash: str = ""
    canonical_size: int = 0
    canonical_mtime_ns: int = 0
    canonical_inode: int = 0
    mirror_hash: str = ""
    mirror_size: int = 0
    mirror_mtime_ns: int = 0
    mirror_inode: int = 0
    state: str = "not_opened"
    retryable: bool = False
    message: str = ""
    last_success_at: str = ""
    last_direction: str = ""
    failure_count: int = 0
    next_retry_at: float = 0.0
    retired_at: float | None = None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS pdf_recovery_ack (
    sync_id TEXT NOT NULL, path TEXT NOT NULL, content_hash TEXT NOT NULL,
    size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL, inode INTEGER NOT NULL,
    PRIMARY KEY (sync_id, path)
);
CREATE TABLE IF NOT EXISTS pdf_edit_mirrors (
    sync_id TEXT PRIMARY KEY,
    library_kind TEXT NOT NULL,
    paper_id TEXT NOT NULL,
    canonical_path TEXT NOT NULL,
    mirror_path TEXT NOT NULL,
    identity TEXT NOT NULL DEFAULT '',
    base_hash TEXT NOT NULL DEFAULT '',
    canonical_hash TEXT NOT NULL DEFAULT '',
    canonical_size INTEGER NOT NULL DEFAULT 0,
    canonical_mtime_ns INTEGER NOT NULL DEFAULT 0,
    canonical_inode INTEGER NOT NULL DEFAULT 0,
    mirror_hash TEXT NOT NULL DEFAULT '',
    mirror_size INTEGER NOT NULL DEFAULT 0,
    mirror_mtime_ns INTEGER NOT NULL DEFAULT 0,
    mirror_inode INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL DEFAULT 'not_opened',
    retryable INTEGER NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT '',
    last_success_at TEXT NOT NULL DEFAULT '',
    last_direction TEXT NOT NULL DEFAULT '',
    failure_count INTEGER NOT NULL DEFAULT 0,
    next_retry_at REAL NOT NULL DEFAULT 0,
    retired_at REAL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE (library_kind, paper_id)
);
CREATE INDEX IF NOT EXISTS idx_pdf_edit_mirrors_identity
    ON pdf_edit_mirrors (library_kind, identity);
CREATE INDEX IF NOT EXISTS idx_pdf_edit_mirrors_retired
    ON pdf_edit_mirrors (retired_at);
"""


class PdfEditMirrorStore:
    """Small SQLite store with one connection per operation."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path).expanduser().resolve()
        self._schema_lock = threading.Lock()
        self._ensure_schema()

    def _connect(self, *, configure_journal: bool = False) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        if configure_journal:
            connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _ensure_schema(self) -> None:
        with self._schema_lock:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect(configure_journal=True) as connection:
                connection.executescript(_SCHEMA)

    @staticmethod
    def _record(row: sqlite3.Row | None) -> PdfEditMirrorRecord | None:
        if row is None:
            return None
        return PdfEditMirrorRecord(
            sync_id=row["sync_id"],
            library_kind=row["library_kind"],
            paper_id=row["paper_id"],
            canonical_path=Path(row["canonical_path"]),
            mirror_path=Path(row["mirror_path"]),
            identity=row["identity"],
            base_hash=row["base_hash"],
            canonical_hash=row["canonical_hash"],
            canonical_size=int(row["canonical_size"]),
            canonical_mtime_ns=int(row["canonical_mtime_ns"]),
            canonical_inode=int(row["canonical_inode"]),
            mirror_hash=row["mirror_hash"],
            mirror_size=int(row["mirror_size"]),
            mirror_mtime_ns=int(row["mirror_mtime_ns"]),
            mirror_inode=int(row["mirror_inode"]),
            state=row["state"],
            retryable=bool(row["retryable"]),
            message=row["message"],
            last_success_at=row["last_success_at"],
            last_direction=row["last_direction"],
            failure_count=int(row["failure_count"]),
            next_retry_at=float(row["next_retry_at"]),
            retired_at=float(row["retired_at"]) if row["retired_at"] is not None else None,
        )

    def recovery_acknowledgements(self, sync_id: str) -> dict[str, tuple[str, int, int, int]]:
        with self._connect() as connection:
            return {
                row[0]: (row[1], row[2], row[3], row[4])
                for row in connection.execute(
                    "SELECT path, content_hash, size, mtime_ns, inode FROM pdf_recovery_ack WHERE sync_id=?", (sync_id,)
                )
            }

    def acknowledge_recovery(self, sync_id: str, versions: dict[str, tuple[str, int, int, int]]) -> None:
        with self._connect() as connection:
            connection.executemany(
                "INSERT OR REPLACE INTO pdf_recovery_ack VALUES (?, ?, ?, ?, ?, ?)",
                [(sync_id, path, *identity) for path, identity in versions.items()],
            )

    def get_or_create(
        self,
        *,
        library_kind: str,
        paper_id: str,
        canonical_path: Path,
        mirror_path: Path,
        identity: str = "",
        sync_id: str | None = None,
    ) -> PdfEditMirrorRecord:
        """Return the stable mapping, updating only its resolvable identity."""
        if library_kind not in {"main", "proceedings"}:
            raise ValueError(f"Unsupported library kind: {library_kind}")
        canonical = str(Path(canonical_path).expanduser().resolve())
        mirror = str(Path(mirror_path).expanduser().resolve())
        now = time.time()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM pdf_edit_mirrors WHERE library_kind = ? AND paper_id = ?",
                (library_kind, paper_id),
            ).fetchone()
            if row is None:
                sync_id = sync_id or str(uuid.uuid4())
                connection.execute(
                    """
                    INSERT INTO pdf_edit_mirrors (
                        sync_id, library_kind, paper_id, canonical_path, mirror_path,
                        identity, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (sync_id, library_kind, paper_id, canonical, mirror, identity, now, now),
                )
            else:
                sync_id = row["sync_id"]
                connection.execute(
                    """
                    UPDATE pdf_edit_mirrors
                    SET canonical_path = ?, identity = ?, retired_at = NULL, updated_at = ?
                    WHERE sync_id = ?
                    """,
                    (canonical, identity or row["identity"], now, sync_id),
                )
            updated = connection.execute("SELECT * FROM pdf_edit_mirrors WHERE sync_id = ?", (sync_id,)).fetchone()
        record = self._record(updated)
        if record is None:  # pragma: no cover - SQLite invariant
            raise RuntimeError("PDF edit mirror mapping was not persisted")
        return record

    def update(self, sync_id: str, **values: object) -> PdfEditMirrorRecord:
        """Atomically update synchronization state for one mapping."""
        allowed = {
            "paper_id",
            "canonical_path",
            "identity",
            "base_hash",
            "canonical_hash",
            "canonical_size",
            "canonical_mtime_ns",
            "canonical_inode",
            "mirror_hash",
            "mirror_size",
            "mirror_mtime_ns",
            "mirror_inode",
            "state",
            "retryable",
            "message",
            "last_success_at",
            "last_direction",
            "failure_count",
            "next_retry_at",
            "retired_at",
        }
        unknown = set(values) - allowed
        if unknown:
            raise ValueError(f"Unsupported PDF edit mirror field(s): {', '.join(sorted(unknown))}")
        if not values:
            record = self.get(sync_id)
            if record is None:
                raise KeyError(sync_id)
            return record
        normalized: dict[str, object] = {}
        for key, value in values.items():
            if key == "canonical_path" and value is not None:
                value = str(Path(str(value)).expanduser().resolve())
            elif key == "retryable":
                value = int(bool(value))
            normalized[key] = value
        normalized["updated_at"] = time.time()
        assignments = ", ".join(f"{key} = ?" for key in normalized)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                f"UPDATE pdf_edit_mirrors SET {assignments} WHERE sync_id = ?",
                (*normalized.values(), sync_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(sync_id)
            row = connection.execute("SELECT * FROM pdf_edit_mirrors WHERE sync_id = ?", (sync_id,)).fetchone()
        record = self._record(row)
        if record is None:  # pragma: no cover - SQLite invariant
            raise KeyError(sync_id)
        return record

    def get(self, sync_id: str) -> PdfEditMirrorRecord | None:
        with self._connect() as connection:
            return self._record(
                connection.execute("SELECT * FROM pdf_edit_mirrors WHERE sync_id = ?", (sync_id,)).fetchone()
            )

    def get_by_paper(self, library_kind: str, paper_id: str) -> PdfEditMirrorRecord | None:
        with self._connect() as connection:
            return self._record(
                connection.execute(
                    "SELECT * FROM pdf_edit_mirrors WHERE library_kind = ? AND paper_id = ?",
                    (library_kind, paper_id),
                ).fetchone()
            )

    def list_by_identity(self, library_kind: str, identity: str) -> list[PdfEditMirrorRecord]:
        if not identity:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM pdf_edit_mirrors
                WHERE library_kind = ? AND identity = ?
                ORDER BY updated_at DESC
                """,
                (library_kind, identity),
            ).fetchall()
        return [record for row in rows if (record := self._record(row)) is not None]

    def list_active(self) -> list[PdfEditMirrorRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM pdf_edit_mirrors WHERE retired_at IS NULL ORDER BY library_kind, paper_id"
            ).fetchall()
        return [record for row in rows if (record := self._record(row)) is not None]

    def mark_retired(self, sync_id: str, *, retired_at: float) -> PdfEditMirrorRecord:
        return self.update(
            sync_id,
            retired_at=retired_at,
            state="sync_failed",
            retryable=False,
            message="Library record was removed; managed mirror is awaiting cleanup",
        )

    def list_retired_before(self, cutoff: float) -> list[PdfEditMirrorRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM pdf_edit_mirrors WHERE retired_at IS NOT NULL AND retired_at <= ? ORDER BY retired_at",
                (cutoff,),
            ).fetchall()
        return [record for row in rows if (record := self._record(row)) is not None]

    def delete(self, sync_id: str) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM pdf_recovery_ack WHERE sync_id = ?", (sync_id,))
            connection.execute("DELETE FROM pdf_edit_mirrors WHERE sync_id = ?", (sync_id,))

    @staticmethod
    def public_status(record: PdfEditMirrorRecord | None) -> dict[str, object]:
        if record is None or record.retired_at is not None:
            return {
                "state": "not_opened",
                "retryable": False,
                "last_success_at": "",
                "message": "",
            }
        return {
            "state": record.state,
            "retryable": record.retryable,
            "last_success_at": record.last_success_at,
            "message": record.message,
        }
