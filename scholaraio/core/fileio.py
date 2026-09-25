"""Atomic file replacement and cross-process locks for small local records."""

from __future__ import annotations

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

    Keep the sidecar after release: unlinking it lets existing waiters and new
    callers lock different inodes. All writers must use this advisory contract.
    """
    path = Path(path).resolve()
    if create_parent:
        path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.lock")
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
