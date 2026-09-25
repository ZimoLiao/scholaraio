"""Atomic file replacement and cross-process locks for small local records."""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def file_lock(path: Path, *, timeout: float = 30.0, create_parent: bool = False) -> Iterator[None]:
    """Lock a persistent sidecar, not the inode that atomic writes replace.

    Store it beside the record's directory: Windows cannot rename a directory
    containing an open lock handle. Keep the sidecar after release so existing
    waiters and new callers cannot lock different inodes. All writers must use
    this advisory contract.
    """
    path = Path(path).resolve()
    if create_parent:
        path.parent.mkdir(parents=True, exist_ok=True)
    if not path.parent.is_dir():
        raise FileNotFoundError(f"Record directory no longer exists: {path.parent}")
    # Metadata transactions share one library lock: a path-derived per-record
    # identity changes during rename, while an ID-derived one cannot coordinate
    # initial creation or replacement of an ID. Hold this through registry commit.
    identity = "library-metadata" if path.name == "meta.json" else os.path.normcase(f"{path.parent.name}/{path.name}")
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    lock_path = path.parent.parent / f".scholaraio-{digest}.lock"
    with lock_path.open("a+b") as stream:
        if sys.platform == "win32":
            import msvcrt

            if stream.seek(0, os.SEEK_END) == 0:
                stream.write(b"\0")
                stream.flush()

            def acquire() -> None:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)

            def release() -> None:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            def acquire() -> None:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            def release() -> None:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

        deadline = time.monotonic() + timeout
        while True:
            try:
                acquire()
                break
            except (BlockingIOError, PermissionError):
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Timed out waiting for record lock: {path.name}") from None
                time.sleep(0.01)
        try:
            yield
        finally:
            release()


def atomic_write_text(path: Path, content: str) -> None:
    """Replace a UTF-8 file using a unique temporary file in the same directory."""
    path = Path(path)
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            temporary.chmod(path.stat().st_mode & 0o777)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
