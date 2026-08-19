"""Tests for resolving Zotero PDF attachments, including linked-file base directories."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from scholaraio.providers.zotero import _base_attachment_path, _find_local_pdf

PDF_BYTES = b"%PDF-1.4\n% scholar aio test pdf\n%%EOF\n"


@pytest.fixture(autouse=True)
def _clear_base_path_cache():
    """``_base_attachment_path`` is memoized; keep cases independent."""
    _base_attachment_path.cache_clear()
    yield
    _base_attachment_path.cache_clear()


def _attachment_db(path: str) -> sqlite3.Connection:
    """In-memory Zotero-shaped DB with one PDF attachment on item 1."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE items (itemID INTEGER PRIMARY KEY, key TEXT);
        CREATE TABLE itemAttachments (
            itemID INTEGER, parentItemID INTEGER, contentType TEXT, path TEXT
        );
        INSERT INTO items VALUES (2, 'ATTACHKEY');
        """
    )
    conn.execute(
        "INSERT INTO itemAttachments VALUES (2, 1, 'application/pdf', ?)",
        (path,),
    )
    return conn


def _write_prefs(home: Path, base_dir: Path) -> None:
    profile = home / "Library" / "Application Support" / "Zotero" / "Profiles" / "abc123.default"
    profile.mkdir(parents=True)
    (profile / "prefs.js").write_text(
        'user_pref("extensions.zotero.autoSync", true);\n'
        f'user_pref("extensions.zotero.baseAttachmentPath", "{base_dir}");\n',
        encoding="utf-8",
    )


def test_base_attachment_path_reads_prefs_js(tmp_path: Path):
    home = tmp_path / "home"
    base = tmp_path / "linked-pdfs"
    base.mkdir()
    _write_prefs(home, base)

    assert _base_attachment_path(home) == base


def test_base_attachment_path_is_none_without_profile(tmp_path: Path):
    assert _base_attachment_path(tmp_path / "empty-home") is None


def test_base_attachment_path_is_none_when_base_dir_is_missing(tmp_path: Path):
    home = tmp_path / "home"
    _write_prefs(home, tmp_path / "was-deleted")

    assert _base_attachment_path(home) is None


def test_find_local_pdf_resolves_attachments_prefix(tmp_path: Path, monkeypatch):
    """Zotero stores linked files as ``attachments:<relative>``; resolve via the base dir."""
    home = tmp_path / "home"
    base = tmp_path / "linked-pdfs"
    (base / "2024").mkdir(parents=True)
    pdf = base / "2024" / "paper.pdf"
    pdf.write_bytes(PDF_BYTES)
    _write_prefs(home, base)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    conn = _attachment_db("attachments:2024/paper.pdf")

    assert _find_local_pdf(conn, 1, tmp_path / "storage") == pdf


def test_find_local_pdf_skips_attachments_prefix_when_file_is_absent(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    base = tmp_path / "linked-pdfs"
    base.mkdir()
    _write_prefs(home, base)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    conn = _attachment_db("attachments:missing.pdf")

    assert _find_local_pdf(conn, 1, tmp_path / "storage") is None


def test_find_local_pdf_still_resolves_storage_prefix(tmp_path: Path):
    storage = tmp_path / "storage"
    (storage / "ATTACHKEY").mkdir(parents=True)
    pdf = storage / "ATTACHKEY" / "paper.pdf"
    pdf.write_bytes(PDF_BYTES)

    conn = _attachment_db("storage:paper.pdf")

    assert _find_local_pdf(conn, 1, storage) == pdf


def test_find_local_pdf_still_resolves_absolute_path(tmp_path: Path):
    pdf = tmp_path / "elsewhere" / "paper.pdf"
    pdf.parent.mkdir()
    pdf.write_bytes(PDF_BYTES)

    conn = _attachment_db(str(pdf))

    assert _find_local_pdf(conn, 1, tmp_path / "storage") == pdf
