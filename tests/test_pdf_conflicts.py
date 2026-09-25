"""Explicit conflict resolution must preserve versions and reject concurrent saves."""

import pytest

from scholaraio.services.pdf_conflicts import PdfConflictChanged, inspect_conflict, resolve_conflict
from tests.test_pdf_edit_mirror import _reconciler, _target, _write_pdf


def conflict(tmp_path):
    store, paths, reconciler = _reconciler(tmp_path)
    canonical = tmp_path / "library" / "paper" / "paper.pdf"
    _write_pdf(canonical, b"base", mtime_ns=1_000_000_000)
    record = reconciler.register(_target(tmp_path, canonical))
    reconciler.reconcile(record.sync_id, record_exists=True)
    _write_pdf(canonical, b"canonical edit", mtime_ns=2_000_000_000)
    _write_pdf(record.mirror_path, b"mirror edit", mtime_ns=3_000_000_000)
    assert reconciler.reconcile(record.sync_id, record_exists=True).state == "conflict"
    return store, paths, reconciler, record


def test_resolution_retains_both_and_rejects_stale_decisions(tmp_path):
    _store, paths, reconciler, record = conflict(tmp_path)
    snapshot = inspect_conflict(reconciler, record.sync_id)
    original = [record.canonical_path.read_bytes(), record.mirror_path.read_bytes()]
    result = resolve_conflict(reconciler, record.sync_id, token=snapshot["token"], version="mirror")
    assert result["status"]["state"] == "in_sync"
    assert record.canonical_path.read_bytes() == original[1] == record.mirror_path.read_bytes()
    retained = [p.read_bytes() for p in (paths.state_root / "resolutions").rglob("*.pdf")]
    assert all(data in retained for data in original)
    with pytest.raises(PdfConflictChanged):
        resolve_conflict(reconciler, record.sync_id, token=snapshot["token"], version="canonical")


def test_saved_after_inspection_is_not_overwritten(tmp_path):
    _store, _paths, reconciler, record = conflict(tmp_path)
    snapshot = inspect_conflict(reconciler, record.sync_id)
    saved = _write_pdf(record.canonical_path, b"late save", mtime_ns=4_000_000_000)
    with pytest.raises(PdfConflictChanged):
        resolve_conflict(reconciler, record.sync_id, token=snapshot["token"], version="mirror")
    assert record.canonical_path.read_bytes() == saved


def test_save_to_old_handle_after_resolution_reopens_conflict(tmp_path):
    _store, _paths, reconciler, record = conflict(tmp_path)
    snapshot = inspect_conflict(reconciler, record.sync_id)
    with record.canonical_path.open("r+b") as reader:
        resolve_conflict(reconciler, record.sync_id, token=snapshot["token"], version="mirror")
        reader.seek(0)
        reader.write(b"%PDF-1.4\n% Saved by old reader\n%%EOF\n")
        reader.truncate()
        reader.flush()
    assert reconciler.reconcile(record.sync_id, record_exists=True).state == "conflict"


def test_save_during_publication_preserves_new_bytes(tmp_path, monkeypatch):
    _store, _paths, reconciler, record = conflict(tmp_path)
    snapshot = inspect_conflict(reconciler, record.sync_id)
    publish = reconciler._publish_pdf
    saved = None

    def racing(temporary, destination, root, expected):
        nonlocal saved
        saved = _write_pdf(destination, b"save during resolve", mtime_ns=5_000_000_000)
        return publish(temporary, destination, root, expected)

    monkeypatch.setattr(reconciler, "_publish_pdf", racing)
    with pytest.raises(PdfConflictChanged):
        resolve_conflict(reconciler, record.sync_id, token=snapshot["token"], version="mirror")
    assert record.canonical_path.read_bytes() == saved


def test_resolution_can_preserve_a_damaged_copy(tmp_path):
    _store, _paths, reconciler, record = conflict(tmp_path)
    damaged = b"partial damaged reader save"
    record.canonical_path.write_bytes(damaged)
    snapshot = inspect_conflict(reconciler, record.sync_id)
    result = resolve_conflict(reconciler, record.sync_id, token=snapshot["token"], version="mirror")
    assert result["status"]["state"] == "in_sync"
    recovery = record.canonical_path.parent / ".scholaraio-pdf-recovery"
    assert damaged in [path.read_bytes() for path in recovery.rglob("*.pdf") if path.is_file()]
