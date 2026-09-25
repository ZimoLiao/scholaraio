from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest

from scholaraio.services.pdf_edit_mirror import (
    PdfEditMirrorPaths,
    PdfEditMirrorReconciler,
    PdfEditMirrorService,
    PdfMirrorTarget,
    PdfTargetResolution,
    validate_pdf_candidate,
)
from scholaraio.stores.pdf_edit_mirror import PdfEditMirrorStore


def _write_pdf(path: Path, marker: bytes, *, mtime_ns: int) -> bytes:
    content = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n% " + marker + b"\n%%EOF\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    os.utime(path, ns=(mtime_ns, mtime_ns))
    return content


def _reconciler(tmp_path):
    paths = PdfEditMirrorPaths(
        mirror_root=tmp_path / "windows" / "ScholarAIO" / "editable-pdfs",
        state_root=tmp_path / "state" / "pdf-edit-mirror",
    )
    store = PdfEditMirrorStore(paths.state_root / "sync.db")
    return store, paths, PdfEditMirrorReconciler(store=store, paths=paths, deep_validator=lambda _path: None)


def _target(tmp_path, canonical: Path) -> PdfMirrorTarget:
    return PdfMirrorTarget(
        library_kind="main",
        paper_id="paper-id",
        canonical_path=canonical,
        library_root=tmp_path / "library",
        display_name="Readable Paper.pdf",
        identity="doi:10.1000/example",
    )


def test_paths_allocate_stable_human_readable_mirror_names(tmp_path):
    paths = PdfEditMirrorPaths(
        mirror_root=tmp_path / "windows-local-app-data" / "ScholarAIO" / "editable-pdfs",
        state_root=tmp_path / "data" / "state" / "pdf-edit-mirror",
    )

    mirror = paths.mirror_path(
        library_kind="main",
        sync_id="a2ac1020-4607-47dd-955d-02ab0efcd68d",
        display_name="Estrada: A <Distributional> Approach?.pdf",
    )

    assert mirror == (
        tmp_path
        / "windows-local-app-data"
        / "ScholarAIO"
        / "editable-pdfs"
        / "main"
        / "a2ac1020-4607-47dd-955d-02ab0efcd68d"
        / "Estrada_ A _Distributional_ Approach_.pdf"
    )
    assert mirror.name.endswith(".pdf")
    assert not mirror.name.startswith("a2ac1020")


def test_store_reuses_mapping_after_restart_and_rebinds_canonical_path(tmp_path):
    database = tmp_path / "data" / "state" / "pdf-edit-mirror" / "sync.db"
    first = PdfEditMirrorStore(database)
    record = first.get_or_create(
        library_kind="main",
        paper_id="estrada-2002",
        canonical_path=tmp_path / "papers" / "old" / "Estrada.pdf",
        mirror_path=tmp_path / "mirror" / "Estrada.pdf",
        identity="doi:10.1007/978-0-8176-8130-2",
    )

    reopened = PdfEditMirrorStore(database)
    rebound = reopened.get_or_create(
        library_kind="main",
        paper_id="estrada-2002",
        canonical_path=tmp_path / "papers" / "renamed" / "Estrada.pdf",
        mirror_path=tmp_path / "ignored-new-mirror" / "Estrada.pdf",
        identity="doi:10.1007/978-0-8176-8130-2",
    )

    assert rebound.sync_id == record.sync_id
    assert rebound.mirror_path == record.mirror_path
    assert rebound.canonical_path == (tmp_path / "papers" / "renamed" / "Estrada.pdf").resolve()
    assert reopened.list_active() == [rebound]


def test_store_keeps_main_and_proceedings_mappings_separate(tmp_path):
    store = PdfEditMirrorStore(tmp_path / "sync.db")

    main = store.get_or_create(
        library_kind="main",
        paper_id="shared-id",
        canonical_path=tmp_path / "main.pdf",
        mirror_path=tmp_path / "main-mirror.pdf",
    )
    proceedings = store.get_or_create(
        library_kind="proceedings",
        paper_id="shared-id",
        canonical_path=tmp_path / "proceedings.pdf",
        mirror_path=tmp_path / "proceedings-mirror.pdf",
    )

    assert main.sync_id != proceedings.sync_id
    assert store.get_by_paper("main", "shared-id") == main
    assert store.get_by_paper("proceedings", "shared-id") == proceedings


def test_store_status_does_not_expose_paths(tmp_path):
    store = PdfEditMirrorStore(tmp_path / "sync.db")
    record = store.get_or_create(
        library_kind="main",
        paper_id="paper-id",
        canonical_path=Path("/secret/library/paper.pdf"),
        mirror_path=Path("/secret/windows/paper.pdf"),
    )

    payload = store.public_status(record)

    assert payload == {
        "state": "not_opened",
        "retryable": False,
        "last_success_at": "",
        "message": "",
    }
    assert "/secret" not in repr(payload)


@pytest.mark.parametrize(
    ("content", "expected_error"),
    [
        (b"", "empty"),
        (b"not a pdf\n%%EOF\n", "header"),
        (b"%PDF-1.4\ntruncated", "end-of-file"),
    ],
)
def test_dependency_free_validation_rejects_malformed_candidates(tmp_path, content, expected_error):
    candidate = tmp_path / "library" / "candidate.pdf"
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(content)

    result = validate_pdf_candidate(candidate, expected_root=tmp_path / "library", deep_validator=lambda _path: None)

    assert result.valid is False
    assert expected_error in result.message


def test_dependency_free_validation_accepts_pdf_and_records_no_deep_check(tmp_path):
    candidate = tmp_path / "library" / "candidate.pdf"
    _write_pdf(candidate, b"valid", mtime_ns=1_000_000_000)

    result = validate_pdf_candidate(candidate, expected_root=tmp_path / "library", deep_validator=lambda _path: None)

    assert result.valid is True
    assert result.deep_checked is False
    assert len(result.content_hash) == 64


def test_available_deep_validator_can_reject_structurally_unreadable_pdf(tmp_path):
    candidate = tmp_path / "library" / "candidate.pdf"
    _write_pdf(candidate, b"valid-envelope", mtime_ns=1_000_000_000)

    result = validate_pdf_candidate(
        candidate,
        expected_root=tmp_path / "library",
        deep_validator=lambda _path: (False, "PDF deep structure check failed"),
    )

    assert result.valid is False
    assert result.deep_checked is True
    assert result.message == "PDF deep structure check failed"


def test_validation_rejects_symlink_even_when_target_is_valid_pdf(tmp_path):
    outside = tmp_path / "outside.pdf"
    _write_pdf(outside, b"outside", mtime_ns=1_000_000_000)
    link = tmp_path / "library" / "linked.pdf"
    link.parent.mkdir(parents=True)
    link.symlink_to(outside)

    result = validate_pdf_candidate(link, expected_root=tmp_path / "library", deep_validator=lambda _path: None)

    assert result.valid is False
    assert "symbolic link" in result.message


def test_first_reconcile_copies_canonical_to_stable_mirror(tmp_path):
    store, paths, reconciler = _reconciler(tmp_path)
    canonical = tmp_path / "library" / "paper" / "paper.pdf"
    expected = _write_pdf(canonical, b"canonical", mtime_ns=2_000_000_000)
    record = reconciler.register(_target(tmp_path, canonical))

    result = reconciler.reconcile(record.sync_id, record_exists=True)
    persisted = store.get(record.sync_id)

    assert result.state == "in_sync"
    assert result.direction == "canonical_to_mirror"
    assert persisted is not None
    assert persisted.mirror_path == paths.mirror_path(
        library_kind="main", sync_id=record.sync_id, display_name="Readable Paper.pdf"
    )
    assert persisted.mirror_path.read_bytes() == expected
    assert persisted.mirror_path.stat().st_mtime_ns == canonical.stat().st_mtime_ns
    assert persisted.base_hash == persisted.canonical_hash == persisted.mirror_hash


def test_mirror_only_change_is_written_back_to_canonical(tmp_path):
    store, _paths, reconciler = _reconciler(tmp_path)
    canonical = tmp_path / "library" / "paper" / "paper.pdf"
    _write_pdf(canonical, b"base", mtime_ns=2_000_000_000)
    record = reconciler.register(_target(tmp_path, canonical))
    reconciler.reconcile(record.sync_id, record_exists=True)
    record = store.get(record.sync_id)
    assert record is not None
    edited = _write_pdf(record.mirror_path, b"annotated", mtime_ns=3_000_000_000)

    result = reconciler.reconcile(record.sync_id, record_exists=True)

    assert result.direction == "mirror_to_canonical"
    assert canonical.read_bytes() == edited
    assert canonical.stat().st_mtime_ns == 3_000_000_000


def test_canonical_only_change_refreshes_mirror(tmp_path):
    store, _paths, reconciler = _reconciler(tmp_path)
    canonical = tmp_path / "library" / "paper" / "paper.pdf"
    _write_pdf(canonical, b"base", mtime_ns=2_000_000_000)
    record = reconciler.register(_target(tmp_path, canonical))
    reconciler.reconcile(record.sync_id, record_exists=True)
    refreshed = _write_pdf(canonical, b"refetched", mtime_ns=4_000_000_000)

    result = reconciler.reconcile(record.sync_id, record_exists=True)
    record = store.get(record.sync_id)

    assert result.direction == "canonical_to_mirror"
    assert record is not None
    assert record.mirror_path.read_bytes() == refreshed


@pytest.mark.parametrize(
    "canonical_mtime,mirror_mtime",
    [(5_000_000_000, 4_000_000_000), (4_000_000_000, 5_000_000_000), (5_000_000_000, 5_000_000_000)],
)
def test_both_changed_preserves_both_files_as_conflict(tmp_path, canonical_mtime, mirror_mtime):
    store, paths, reconciler = _reconciler(tmp_path)
    canonical = tmp_path / "library" / "paper" / "paper.pdf"
    _write_pdf(canonical, b"base", mtime_ns=2_000_000_000)
    record = reconciler.register(_target(tmp_path, canonical))
    reconciler.reconcile(record.sync_id, record_exists=True)
    record = store.get(record.sync_id)
    library_edit = _write_pdf(canonical, b"canonical-new", mtime_ns=canonical_mtime)
    viewer_edit = _write_pdf(record.mirror_path, b"mirror-new", mtime_ns=mirror_mtime)

    result = reconciler.reconcile(record.sync_id, record_exists=True)

    assert result.state == "conflict"
    assert result.retryable is False
    assert canonical.read_bytes() == library_edit
    assert record.mirror_path.read_bytes() == viewer_edit
    service = PdfEditMirrorService(
        store=store, paths=paths, resolver=None, auto_start=False, deep_validator=lambda _: None
    )
    assert service.prepare_for_open(_target(tmp_path, canonical)).launchable is False
    assert store.get(record.sync_id).state == "conflict"
    # A deliberate external reconciliation (same bytes on both sides) clears it.
    record.mirror_path.write_bytes(library_edit)
    result = reconciler.reconcile(record.sync_id, record_exists=True)
    assert result.state == "in_sync"


def test_invalid_mirror_never_replaces_valid_canonical(tmp_path):
    store, _paths, reconciler = _reconciler(tmp_path)
    canonical = tmp_path / "library" / "paper" / "paper.pdf"
    original = _write_pdf(canonical, b"base", mtime_ns=2_000_000_000)
    record = reconciler.register(_target(tmp_path, canonical))
    reconciler.reconcile(record.sync_id, record_exists=True)
    record = store.get(record.sync_id)
    assert record is not None
    record.mirror_path.write_bytes(b"%PDF-1.4\npartial save")

    result = reconciler.reconcile(record.sync_id, record_exists=True)

    assert result.state == "sync_pending"
    assert result.retryable is True
    assert canonical.read_bytes() == original
    assert "end-of-file" in result.message


def test_repeated_failures_promote_pending_status_to_sync_failed(tmp_path):
    store, _paths, reconciler = _reconciler(tmp_path)
    canonical = tmp_path / "library" / "paper" / "paper.pdf"
    _write_pdf(canonical, b"base", mtime_ns=2_000_000_000)
    record = reconciler.register(_target(tmp_path, canonical))
    reconciler.reconcile(record.sync_id, record_exists=True)
    record = store.get(record.sync_id)
    assert record is not None
    record.mirror_path.write_bytes(b"%PDF-1.4\npartial")

    results = [reconciler.reconcile(record.sync_id, record_exists=True) for _attempt in range(5)]

    assert [result.state for result in results[:4]] == ["sync_pending"] * 4
    assert results[-1].state == "sync_failed"
    assert results[-1].retryable is True


def test_copy_failure_preserves_both_files_and_sanitizes_diagnostic(tmp_path, monkeypatch):
    _store, _paths, reconciler = _reconciler(tmp_path)
    canonical = tmp_path / "library" / "paper" / "paper.pdf"
    original = _write_pdf(canonical, b"base", mtime_ns=2_000_000_000)
    record = reconciler.register(_target(tmp_path, canonical))

    def fail_copy(*_args, **_kwargs):
        raise PermissionError(13, "permission denied", "/secret/library/paper.pdf")

    monkeypatch.setattr(reconciler, "_atomic_copy", fail_copy)
    result = reconciler.reconcile(record.sync_id, record_exists=True)

    assert result.state == "sync_pending"
    assert result.retryable is True
    assert "/secret" not in result.message
    assert canonical.read_bytes() == original
    assert record.mirror_path.exists() is False


def test_atomic_replacement_rotates_one_generation_backup(tmp_path):
    store, paths, reconciler = _reconciler(tmp_path)
    canonical = tmp_path / "library" / "paper" / "paper.pdf"
    base = _write_pdf(canonical, b"base", mtime_ns=2_000_000_000)
    record = reconciler.register(_target(tmp_path, canonical))
    reconciler.reconcile(record.sync_id, record_exists=True)
    record = store.get(record.sync_id)
    assert record is not None
    first_edit = _write_pdf(record.mirror_path, b"first-edit", mtime_ns=3_000_000_000)

    reconciler.reconcile(record.sync_id, record_exists=True)
    backup = paths.backup_path(record.sync_id)
    assert backup.read_bytes() == base

    second_edit = _write_pdf(record.mirror_path, b"second-edit", mtime_ns=4_000_000_000)
    reconciler.reconcile(record.sync_id, record_exists=True)

    assert canonical.read_bytes() == second_edit
    assert backup.read_bytes() == first_edit
    assert list(backup.parent.glob(f"{record.sync_id}*")) == [backup]


def test_deleted_mirror_and_deleted_canonical_are_recovered(tmp_path):
    store, _paths, reconciler = _reconciler(tmp_path)
    canonical = tmp_path / "library" / "paper" / "paper.pdf"
    content = _write_pdf(canonical, b"base", mtime_ns=2_000_000_000)
    record = reconciler.register(_target(tmp_path, canonical))
    reconciler.reconcile(record.sync_id, record_exists=True)
    record = store.get(record.sync_id)
    assert record is not None

    record.mirror_path.unlink()
    assert reconciler.reconcile(record.sync_id, record_exists=True).direction == "canonical_to_mirror"
    assert record.mirror_path.read_bytes() == content

    canonical.unlink()
    assert reconciler.reconcile(record.sync_id, record_exists=True).direction == "mirror_to_canonical"
    assert canonical.read_bytes() == content


def test_last_backup_recovers_when_both_active_files_are_missing(tmp_path):
    store, paths, reconciler = _reconciler(tmp_path)
    canonical = tmp_path / "library" / "paper" / "paper.pdf"
    _write_pdf(canonical, b"base", mtime_ns=2_000_000_000)
    record = reconciler.register(_target(tmp_path, canonical))
    reconciler.reconcile(record.sync_id, record_exists=True)
    record = store.get(record.sync_id)
    assert record is not None
    recovered = _write_pdf(record.mirror_path, b"annotated", mtime_ns=3_000_000_000)
    reconciler.reconcile(record.sync_id, record_exists=True)
    assert paths.backup_path(record.sync_id).exists()
    canonical.unlink()
    record.mirror_path.unlink()

    result = reconciler.reconcile(record.sync_id, record_exists=True)

    assert result.direction == "backup_restore"
    assert canonical.exists()
    assert record.mirror_path.exists()
    assert canonical.read_bytes() == record.mirror_path.read_bytes()
    assert canonical.read_bytes() != recovered


def test_backup_restore_does_not_report_in_sync_if_reader_changes_mirror_during_verification(tmp_path, monkeypatch):
    store, paths, reconciler = _reconciler(tmp_path)
    canonical = tmp_path / "library" / "paper" / "paper.pdf"
    _write_pdf(canonical, b"base", mtime_ns=2_000_000_000)
    record = reconciler.register(_target(tmp_path, canonical))
    reconciler.reconcile(record.sync_id, record_exists=True)
    record = store.get(record.sync_id)
    assert record is not None
    _write_pdf(record.mirror_path, b"annotated", mtime_ns=3_000_000_000)
    reconciler.reconcile(record.sync_id, record_exists=True)
    canonical.unlink()
    record.mirror_path.unlink()
    original_copy = reconciler._atomic_copy

    def copy_with_reader_race(source, destination, *, destination_root, **kwargs):
        copied = original_copy(source, destination, destination_root=destination_root, **kwargs)
        if destination == record.mirror_path:
            _write_pdf(destination, b"reader-race", mtime_ns=4_000_000_000)
        return copied

    monkeypatch.setattr(reconciler, "_atomic_copy", copy_with_reader_race)

    result = reconciler.reconcile(record.sync_id, record_exists=True)

    assert result.state == "sync_pending"
    assert canonical.read_bytes() != record.mirror_path.read_bytes()
    assert paths.backup_path(record.sync_id).exists()


def test_monitor_waits_for_two_stable_observations_and_detects_atomic_rename(tmp_path):
    store, paths, _reconciler_instance = _reconciler(tmp_path)
    canonical = tmp_path / "library" / "paper" / "paper.pdf"
    _write_pdf(canonical, b"AAAA", mtime_ns=2_000_000_000)
    target = _target(tmp_path, canonical)
    service = PdfEditMirrorService(
        store=store,
        paths=paths,
        resolver=lambda _record: target,
        deep_validator=lambda _path: None,
        stable_observations=2,
        poll_interval=0.01,
        auto_start=False,
    )
    prepared = service.prepare_for_open(target)
    original_record = store.get_by_paper("main", "paper-id")
    assert original_record is not None
    original_mirror_inode = original_record.mirror_path.stat().st_ino
    replacement = original_record.mirror_path.with_suffix(".replacement.pdf")
    _write_pdf(replacement, b"BBBB", mtime_ns=original_record.mirror_path.stat().st_mtime_ns)
    os.replace(replacement, original_record.mirror_path)

    service.poll_once()
    assert b"AAAA" in canonical.read_bytes()
    service.poll_once()

    updated = store.get(original_record.sync_id)
    assert prepared.launchable is True
    assert b"BBBB" in canonical.read_bytes()
    assert updated is not None
    assert updated.mirror_inode != original_mirror_inode
    assert updated.state == "in_sync"


def test_service_restart_reconciles_edits_saved_while_webui_was_stopped(tmp_path):
    store, paths, _reconciler_instance = _reconciler(tmp_path)
    canonical = tmp_path / "library" / "paper" / "paper.pdf"
    _write_pdf(canonical, b"base", mtime_ns=2_000_000_000)
    target = _target(tmp_path, canonical)
    first = PdfEditMirrorService(
        store=store,
        paths=paths,
        resolver=lambda _record: target,
        deep_validator=lambda _path: None,
        auto_start=False,
    )
    prepared = first.prepare_for_open(target)
    first.stop()
    edited = _write_pdf(prepared.mirror_path, b"offline-annotation", mtime_ns=4_000_000_000)

    restarted = PdfEditMirrorService(
        store=PdfEditMirrorStore(store.db_path),
        paths=paths,
        resolver=lambda _record: target,
        deep_validator=lambda _path: None,
        stable_observations=2,
        auto_start=False,
    )
    restarted.poll_once()
    restarted.poll_once()

    assert canonical.read_bytes() == edited
    assert restarted.status("main", "paper-id")["state"] == "in_sync"


def test_monitor_rebinds_renamed_record_without_changing_sync_id_or_mirror(tmp_path):
    store, paths, _reconciler_instance = _reconciler(tmp_path)
    old_canonical = tmp_path / "library" / "old" / "paper.pdf"
    _write_pdf(old_canonical, b"base", mtime_ns=2_000_000_000)
    old_target = _target(tmp_path, old_canonical)
    new_canonical = tmp_path / "library" / "renamed" / "renamed.pdf"
    _write_pdf(new_canonical, b"base", mtime_ns=2_000_000_000)
    new_target = PdfMirrorTarget(
        library_kind="main",
        paper_id="renamed-paper-id",
        canonical_path=new_canonical,
        library_root=tmp_path / "library",
        display_name="Renamed Paper.pdf",
        identity=old_target.identity,
    )
    service = PdfEditMirrorService(
        store=store,
        paths=paths,
        resolver=lambda _record: new_target,
        deep_validator=lambda _path: None,
        stable_observations=1,
        auto_start=False,
    )
    prepared = service.prepare_for_open(old_target)
    original = store.get_by_paper("main", "paper-id")
    assert original is not None

    service.poll_once()

    rebound = store.get_by_paper("main", "renamed-paper-id")
    assert store.get_by_paper("main", "paper-id") is None
    assert rebound is not None
    assert rebound.sync_id == original.sync_id
    assert rebound.mirror_path == prepared.mirror_path
    assert rebound.canonical_path == new_canonical.resolve()


def test_direct_open_after_identity_preserving_rename_reuses_existing_mirror(tmp_path):
    store, _paths, reconciler = _reconciler(tmp_path)
    old_canonical = tmp_path / "library" / "old" / "paper.pdf"
    _write_pdf(old_canonical, b"base", mtime_ns=2_000_000_000)
    old_target = _target(tmp_path, old_canonical)
    original = reconciler.register(old_target)
    reconciler.reconcile(original.sync_id, record_exists=True)
    new_canonical = tmp_path / "library" / "renamed" / "renamed.pdf"
    _write_pdf(new_canonical, b"base", mtime_ns=2_000_000_000)
    old_canonical.unlink()
    new_target = PdfMirrorTarget(
        library_kind="main",
        paper_id="renamed-paper-id",
        canonical_path=new_canonical,
        library_root=tmp_path / "library",
        display_name="Renamed Paper.pdf",
        identity=old_target.identity,
    )

    rebound = reconciler.register(new_target)

    assert rebound.sync_id == original.sync_id
    assert rebound.mirror_path == original.mirror_path
    assert store.get_by_paper("main", "paper-id") is None
    assert store.get_by_paper("main", "renamed-paper-id") is not None


def test_two_reconcilers_are_idempotent_under_concurrent_writeback(tmp_path):
    paths = PdfEditMirrorPaths(
        mirror_root=tmp_path / "windows" / "ScholarAIO" / "editable-pdfs",
        state_root=tmp_path / "state" / "pdf-edit-mirror",
    )
    database = paths.state_root / "sync.db"
    first = PdfEditMirrorReconciler(store=PdfEditMirrorStore(database), paths=paths, deep_validator=lambda _path: None)
    second = PdfEditMirrorReconciler(store=PdfEditMirrorStore(database), paths=paths, deep_validator=lambda _path: None)
    canonical = tmp_path / "library" / "paper" / "paper.pdf"
    _write_pdf(canonical, b"base", mtime_ns=2_000_000_000)
    target = _target(tmp_path, canonical)
    record = first.register(target)
    first.reconcile(record.sync_id, record_exists=True)
    second.register(target)
    record = first.store.get(record.sync_id)
    assert record is not None
    edited = _write_pdf(record.mirror_path, b"concurrent-edit", mtime_ns=3_000_000_000)
    barrier = threading.Barrier(3)
    results = []

    def reconcile(worker):
        barrier.wait(timeout=3)
        results.append(worker.reconcile(record.sync_id, record_exists=True))

    threads = [threading.Thread(target=reconcile, args=(worker,)) for worker in (first, second)]
    for thread in threads:
        thread.start()
    barrier.wait(timeout=3)
    for thread in threads:
        thread.join(timeout=3)

    assert all(not thread.is_alive() for thread in threads)
    assert [result.state for result in results] == ["in_sync", "in_sync"]
    assert canonical.read_bytes() == edited
    persisted = first.store.get(record.sync_id)
    assert persisted is not None
    assert persisted.base_hash == persisted.canonical_hash == persisted.mirror_hash


def test_lock_contention_returns_retryable_status_with_bounded_wait(tmp_path):
    import fcntl

    _store, paths, reconciler = _reconciler(tmp_path)
    canonical = tmp_path / "library" / "paper" / "paper.pdf"
    _write_pdf(canonical, b"base", mtime_ns=2_000_000_000)
    record = reconciler.register(_target(tmp_path, canonical))
    lock_path = paths.lock_path(record.sync_id)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    with lock_path.open("a+b") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = reconciler.reconcile(record.sync_id, record_exists=True, lock_timeout_seconds=0)

    assert result.state == "sync_pending"
    assert result.retryable is True
    assert "held the entry lock" in result.message
    assert record.mirror_path.exists() is False


def test_in_process_lock_contention_obeys_the_same_bounded_wait(tmp_path):
    _store, _paths, reconciler = _reconciler(tmp_path)
    canonical = tmp_path / "library" / "paper" / "paper.pdf"
    _write_pdf(canonical, b"base", mtime_ns=2_000_000_000)
    record = reconciler.register(_target(tmp_path, canonical))
    held = threading.Lock()
    held.acquire()
    reconciler._thread_locks[record.sync_id] = held

    started = time.monotonic()
    result = reconciler.reconcile(record.sync_id, record_exists=True, lock_timeout_seconds=0)

    assert time.monotonic() - started < 0.5
    assert result.state == "sync_pending"
    assert result.retryable is True
    held.release()


def test_unvalidated_divergent_mirror_is_not_launchable(tmp_path):
    store, paths, _reconciler_instance = _reconciler(tmp_path)
    canonical = tmp_path / "library" / "paper" / "paper.pdf"
    _write_pdf(canonical, b"base", mtime_ns=2_000_000_000)
    target = _target(tmp_path, canonical)
    service = PdfEditMirrorService(
        store=store,
        paths=paths,
        resolver=lambda _record: target,
        deep_validator=lambda _path: None,
        settle_interval=0,
        auto_start=False,
    )
    first = service.prepare_for_open(target)
    first.mirror_path.write_bytes(b"%PDF-1.4\npartial")

    unsafe = service.prepare_for_open(target, budget_seconds=0)

    assert unsafe.launchable is False
    assert unsafe.status["state"] == "sync_pending"
    assert "end-of-file" in unsafe.status["message"]


def test_monitor_uses_bounded_retry_backoff_then_recovers(tmp_path):
    now = [1_000.0]
    store, paths, _reconciler_instance = _reconciler(tmp_path)
    canonical = tmp_path / "library" / "paper" / "paper.pdf"
    _write_pdf(canonical, b"base", mtime_ns=2_000_000_000)
    target = _target(tmp_path, canonical)
    service = PdfEditMirrorService(
        store=store,
        paths=paths,
        resolver=lambda _record: target,
        deep_validator=lambda _path: None,
        wall_clock=lambda: now[0],
        stable_observations=1,
        retry_max_seconds=60,
        auto_start=False,
    )
    prepared = service.prepare_for_open(target)
    prepared.mirror_path.write_bytes(b"%PDF-1.4\npartial")

    service.poll_once()
    pending = store.get_by_paper("main", "paper-id")
    assert pending is not None
    assert pending.next_retry_at == 1_001.0
    assert pending.failure_count == 1
    service.poll_once()
    unchanged = store.get(pending.sync_id)
    assert unchanged is not None
    assert unchanged.failure_count == 1

    now[0] = 1_001.0
    edited = _write_pdf(prepared.mirror_path, b"recovered", mtime_ns=4_000_000_000)
    service.poll_once()

    recovered = store.get(pending.sync_id)
    assert canonical.read_bytes() == edited
    assert recovered is not None
    assert recovered.state == "in_sync"
    assert recovered.next_retry_at == 0


def test_ambiguous_rebind_stays_pending_without_writing(tmp_path):
    store, paths, _reconciler_instance = _reconciler(tmp_path)
    canonical = tmp_path / "library" / "paper" / "paper.pdf"
    _write_pdf(canonical, b"base", mtime_ns=2_000_000_000)
    target = _target(tmp_path, canonical)
    service = PdfEditMirrorService(
        store=store,
        paths=paths,
        resolver=lambda _record: PdfTargetResolution(target=None, ambiguous=True),
        deep_validator=lambda _path: None,
        auto_start=False,
    )
    prepared = service.prepare_for_open(target)
    canonical.unlink()

    service.poll_once()
    record = store.get_by_paper("main", "paper-id")

    assert record is not None
    assert record.retired_at is None
    assert record.state == "sync_pending"
    assert canonical.exists() is False
    assert prepared.mirror_path.exists()


def test_intentional_record_removal_retires_then_cleans_managed_state(tmp_path):
    now = [1_000.0]
    store, paths, _reconciler_instance = _reconciler(tmp_path)
    canonical = tmp_path / "library" / "paper" / "paper.pdf"
    _write_pdf(canonical, b"base", mtime_ns=2_000_000_000)
    target = _target(tmp_path, canonical)
    service = PdfEditMirrorService(
        store=store,
        paths=paths,
        resolver=lambda _record: None,
        deep_validator=lambda _path: None,
        wall_clock=lambda: now[0],
        retirement_grace_seconds=7 * 24 * 60 * 60,
        auto_start=False,
    )
    prepared = service.prepare_for_open(target)
    canonical.unlink()

    service.poll_once()
    retired = store.get_by_paper("main", "paper-id")
    assert retired is not None
    assert retired.retired_at == now[0]
    assert canonical.exists() is False
    assert prepared.mirror_path.exists()

    now[0] += 8 * 24 * 60 * 60
    service.poll_once()

    assert store.get_by_paper("main", "paper-id") is None
    assert prepared.mirror_path.exists() is False
    assert paths.backup_path(retired.sync_id).exists() is False


def test_repeated_open_reuses_unchanged_verified_mirror_without_rehashing(tmp_path, monkeypatch):
    store, paths, _reconciler_instance = _reconciler(tmp_path)
    canonical = tmp_path / "library" / "paper" / "paper.pdf"
    _write_pdf(canonical, b"base", mtime_ns=2_000_000_000)
    target = _target(tmp_path, canonical)
    service = PdfEditMirrorService(
        store=store,
        paths=paths,
        resolver=lambda _record: target,
        deep_validator=lambda _path: None,
        auto_start=False,
    )
    first = service.prepare_for_open(target)
    monkeypatch.setattr(
        service.reconciler,
        "reconcile",
        lambda *_args, **_kwargs: pytest.fail("unchanged PDFs should not be rehashed"),
    )

    repeated = service.prepare_for_open(target)

    assert first.launchable is True
    assert repeated.launchable is True
    assert repeated.mirror_path == first.mirror_path


def test_retired_cleanup_failure_keeps_record_for_a_later_retry(tmp_path, monkeypatch):
    now = [1_000.0]
    store, paths, _reconciler_instance = _reconciler(tmp_path)
    canonical = tmp_path / "library" / "paper" / "paper.pdf"
    _write_pdf(canonical, b"base", mtime_ns=2_000_000_000)
    target = _target(tmp_path, canonical)
    service = PdfEditMirrorService(
        store=store,
        paths=paths,
        resolver=lambda _record: None,
        deep_validator=lambda _path: None,
        wall_clock=lambda: now[0],
        retirement_grace_seconds=0,
        auto_start=False,
    )
    prepared = service.prepare_for_open(target)
    record = store.get_by_paper("main", "paper-id")
    assert record is not None
    canonical.unlink()
    store.mark_retired(record.sync_id, retired_at=now[0] - 1)
    original_unlink = Path.unlink

    def fail_mirror_once(path, *args, **kwargs):
        if path == prepared.mirror_path:
            raise PermissionError("reader still holds the mirror")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_mirror_once)
    service.poll_once()

    assert store.get(record.sync_id) is not None
    assert prepared.mirror_path.exists()

    monkeypatch.setattr(Path, "unlink", original_unlink)
    service.poll_once()

    assert store.get(record.sync_id) is None
    assert prepared.mirror_path.exists() is False


def test_monitor_avoids_full_record_resolution_between_periodic_audits(tmp_path):
    now = [1_000.0]
    store, paths, _reconciler_instance = _reconciler(tmp_path)
    canonical = tmp_path / "library" / "paper" / "paper.pdf"
    _write_pdf(canonical, b"base", mtime_ns=2_000_000_000)
    target = _target(tmp_path, canonical)
    resolutions = []

    def resolve(record):
        resolutions.append(record.sync_id)
        return target

    service = PdfEditMirrorService(
        store=store,
        paths=paths,
        resolver=resolve,
        deep_validator=lambda _path: None,
        wall_clock=lambda: now[0],
        resolution_audit_interval=60,
        auto_start=False,
    )
    prepared = service.prepare_for_open(target)

    service.poll_once()
    service.poll_once()
    assert len(resolutions) == 1

    now[0] += 1
    _write_pdf(prepared.mirror_path, b"changed", mtime_ns=4_000_000_000)
    service.poll_once()

    assert len(resolutions) == 2


def test_stop_keeps_reference_to_a_monitor_that_outlives_shutdown_timeout(tmp_path):
    store, paths, _reconciler_instance = _reconciler(tmp_path)
    service = PdfEditMirrorService(
        store=store,
        paths=paths,
        resolver=None,
        deep_validator=lambda _path: None,
        auto_start=False,
    )

    class StuckThread:
        def __init__(self):
            self.join_timeout = None

        def is_alive(self):
            return True

        def join(self, timeout):
            self.join_timeout = timeout

    thread = StuckThread()
    service._thread = thread

    service.stop()
    service.start()

    assert service._thread is thread
    assert thread.join_timeout == 35.0


@pytest.mark.parametrize("direction", ["canonical", "mirror"])
def test_destination_save_after_backup_is_preserved(tmp_path, monkeypatch, direction):
    store, paths, reconciler = _reconciler(tmp_path)
    canonical = tmp_path / "library" / "paper" / "paper.pdf"
    _write_pdf(canonical, b"base", mtime_ns=2_000_000_000)
    record = reconciler.register(_target(tmp_path, canonical))
    assert reconciler.reconcile(record.sync_id, record_exists=True).state == "in_sync"
    source = canonical if direction == "canonical" else record.mirror_path
    destination = record.mirror_path if direction == "canonical" else canonical
    source_bytes = _write_pdf(source, b"source-edit", mtime_ns=3_000_000_000)
    original = reconciler._atomic_copy
    saved = []

    def save_after_backup(src, dst, **kwargs):
        copied = original(src, dst, **kwargs)
        if dst == paths.backup_path(record.sync_id):
            saved.append(_write_pdf(destination, b"late-edit", mtime_ns=4_000_000_000))
        return copied

    monkeypatch.setattr(reconciler, "_atomic_copy", save_after_backup)
    result = reconciler.reconcile(record.sync_id, record_exists=True)
    assert result.state == "conflict"
    assert not result.retryable
    assert destination.read_bytes() == saved[0]
    assert source.read_bytes() == source_bytes
    assert store.get(record.sync_id).state == "conflict"


@pytest.mark.parametrize("timing", ["before_move", "before_link", "open_handle"])
def test_destination_publication_preserves_late_saves(tmp_path, monkeypatch, timing):
    _store, _paths, reconciler = _reconciler(tmp_path)
    canonical = tmp_path / "library" / "paper" / "paper.pdf"
    _write_pdf(canonical, b"base", mtime_ns=2_000_000_000)
    record = reconciler.register(_target(tmp_path, canonical))
    assert reconciler.reconcile(record.sync_id, record_exists=True).state == "in_sync"
    _write_pdf(canonical, b"source-edit", mtime_ns=3_000_000_000)
    destination = record.mirror_path
    late = b"%PDF-1.4\nlate reader save\n%%EOF\n"
    rename = Path.rename
    link = os.link
    handle = destination.open("r+b") if timing == "open_handle" else None

    def racing_rename(path, target):
        if path == destination and timing == "before_move":
            path.write_bytes(late)
        return rename(path, target)

    def racing_link(src, dst, **kwargs):
        if dst == destination and Path(src).suffix == ".tmp":
            if timing == "before_link":
                destination.write_bytes(late)
            elif handle is not None:
                handle.seek(0)
                handle.write(late)
                handle.truncate()
                handle.flush()
                os.fsync(handle.fileno())
        return link(src, dst, **kwargs)

    monkeypatch.setattr(Path, "rename", racing_rename)
    monkeypatch.setattr(os, "link", racing_link)
    try:
        result = reconciler.reconcile(record.sync_id, record_exists=True)
    finally:
        if handle is not None:
            handle.close()
    assert result.state == "conflict"
    preserved = [destination, *destination.parent.glob(".scholaraio-pdf-recovery/**/*.pdf")]
    assert any(p.is_file() and p.read_bytes() == late for p in preserved)


def test_old_open_handle_save_after_success_is_detected_on_next_reconcile(tmp_path):
    _store, _paths, reconciler = _reconciler(tmp_path)
    canonical = tmp_path / "library" / "paper" / "paper.pdf"
    _write_pdf(canonical, b"base", mtime_ns=2_000_000_000)
    record = reconciler.register(_target(tmp_path, canonical))
    assert reconciler.reconcile(record.sync_id, record_exists=True).state == "in_sync"
    late = b"%PDF-1.4\nsaved through old handle\n%%EOF\n"
    with record.mirror_path.open("r+b") as handle:
        _write_pdf(canonical, b"source-edit", mtime_ns=3_000_000_000)
        assert reconciler.reconcile(record.sync_id, record_exists=True).state == "in_sync"
        handle.seek(0)
        handle.write(late)
        handle.truncate()
        handle.flush()
        os.fsync(handle.fileno())
    assert reconciler.reconcile(record.sync_id, record_exists=True).state == "conflict"
    retained = list(record.mirror_path.parent.glob(".scholaraio-pdf-recovery/**/*.pdf"))
    assert any(p.is_file() and p.read_bytes() == late for p in retained)


def test_backup_restore_detects_late_save_through_displaced_handle(tmp_path, monkeypatch):
    store, paths, reconciler = _reconciler(tmp_path)
    canonical = tmp_path / "library" / "paper" / "paper.pdf"
    _write_pdf(canonical, b"base", mtime_ns=2_000_000_000)
    record = reconciler.register(_target(tmp_path, canonical))
    assert reconciler.reconcile(record.sync_id, record_exists=True).state == "in_sync"
    _write_pdf(record.mirror_path, b"edit", mtime_ns=3_000_000_000)
    assert reconciler.reconcile(record.sync_id, record_exists=True).state == "in_sync"
    assert paths.backup_path(record.sync_id).exists()
    canonical.write_bytes(b"partial canonical save")
    record.mirror_path.write_bytes(b"partial mirror save")
    original = reconciler._atomic_copy
    late = b"%PDF-1.4\nlate completed save\n%%EOF\n"
    with canonical.open("r+b") as handle:

        def copy_then_finish_save(source, destination, **kwargs):
            copied = original(source, destination, **kwargs)
            if destination == canonical:
                handle.seek(0)
                handle.write(late)
                handle.truncate()
                handle.flush()
                os.fsync(handle.fileno())
            return copied

        monkeypatch.setattr(reconciler, "_atomic_copy", copy_then_finish_save)
        result = reconciler.reconcile(record.sync_id, record_exists=True)
    assert result.state == "conflict"
    assert store.get(record.sync_id).state == "conflict"
    retained = canonical.parent.glob(".scholaraio-pdf-recovery/**/*.pdf")
    assert any(p.is_file() and p.read_bytes() == late for p in retained)
