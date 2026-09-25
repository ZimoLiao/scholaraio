"""Explicit conflict resolution must preserve versions and reject concurrent saves."""

from functools import partial

import pytest

from scholaraio.services.pdf_conflicts import PdfConflictChanged
from scholaraio.services.pdf_conflicts import export_version as export_service
from scholaraio.services.pdf_conflicts import inspect_conflict as inspect_service
from scholaraio.services.pdf_conflicts import resolve_conflict as resolve_service
from scholaraio.services.pdf_edit_mirror import PdfMirrorTarget, PdfTargetResolution
from tests.test_pdf_edit_mirror import _reconciler, _target, _write_pdf


def resolver(record):
    return PdfTargetResolution(
        target=PdfMirrorTarget(
            library_kind=record.library_kind,
            paper_id=record.paper_id,
            canonical_path=record.canonical_path,
            library_root=record.canonical_path.parent.parent,
            display_name=record.canonical_path.name,
            identity=record.identity,
        )
    )


inspect_conflict = partial(inspect_service, resolver=resolver)
resolve_conflict = partial(resolve_service, resolver=resolver)
export_version = partial(export_service, resolver=resolver)


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


def test_export_holds_immutable_snapshot_and_cleans_up(tmp_path):
    _, _, reconciler, record = conflict(tmp_path)
    snapshot = inspect_conflict(reconciler, record.sync_id)
    expected = record.mirror_path.read_bytes()
    with export_version(reconciler, record.sync_id, "mirror", snapshot["token"]) as copy:
        _write_pdf(record.mirror_path, b"later save", mtime_ns=9_000_000_000)
        assert copy.read_bytes() == expected
    assert not copy.exists()


def test_export_rejects_save_during_copy(tmp_path, monkeypatch):
    _, _, reconciler, record = conflict(tmp_path)
    snapshot = inspect_conflict(reconciler, record.sync_id)
    original = reconciler._atomic_copy

    def racing(source, destination, **kwargs):
        _write_pdf(source, b"racing save", mtime_ns=9_000_000_000)
        return original(source, destination, **kwargs)

    monkeypatch.setattr(reconciler, "_atomic_copy", racing)
    with pytest.raises(PdfConflictChanged), export_version(reconciler, record.sync_id, "mirror", snapshot["token"]):
        pytest.fail("Changed snapshot was exported")


def test_recovery_rebinds_renamed_paper_and_rejects_missing(tmp_path):
    import json

    from scholaraio.core.config import _build_config
    from scholaraio.services.library_view import resolve_pdf_edit_mirror_target

    cfg = _build_config({}, tmp_path)
    cfg.ensure_dirs()
    _, _, reconciler, record = conflict(tmp_path)
    directory = cfg.papers_dir / "original"
    record.canonical_path.parent.rename(directory)
    (directory / "meta.json").write_text(json.dumps({"id": record.paper_id, "title": "Paper"}))

    def current_resolver(current):
        return resolve_pdf_edit_mirror_target(cfg, "main", current.paper_id, record=current)

    snapshot = inspect_service(reconciler, record.sync_id, resolver=current_resolver)
    renamed = directory.with_name("renamed")
    directory.rename(renamed)
    with pytest.raises(PdfConflictChanged):
        resolve_service(
            reconciler, record.sync_id, token=snapshot["token"], version="mirror", resolver=current_resolver
        )
    snapshot = inspect_service(reconciler, record.sync_id, resolver=current_resolver)
    resolve_service(reconciler, record.sync_id, token=snapshot["token"], version="mirror", resolver=current_resolver)
    assert (renamed / "paper.pdf").read_bytes() == record.mirror_path.read_bytes()
    assert not directory.exists() and not record.canonical_path.exists()
    (renamed / "meta.json").unlink()
    with pytest.raises(PdfConflictChanged):
        inspect_service(reconciler, record.sync_id, resolver=current_resolver)


def test_damaged_version_can_be_exported_but_not_previewed(tmp_path):
    _, _, reconciler, record = conflict(tmp_path)
    damaged = b"partial annotation save"
    record.canonical_path.write_bytes(damaged)
    snapshot = inspect_conflict(reconciler, record.sync_id)
    with export_version(reconciler, record.sync_id, "canonical", snapshot["token"]) as copy:
        assert copy.read_bytes() == damaged
    with (
        pytest.raises(ValueError, match="cannot be previewed"),
        export_version(reconciler, record.sync_id, "canonical", snapshot["token"], preview=True),
    ):
        pytest.fail("Damaged PDF must not be previewed")


def test_recovery_rejects_ambiguous_or_reused_record(tmp_path):
    from dataclasses import replace

    _, _, reconciler, record = conflict(tmp_path)
    snapshot = inspect_conflict(reconciler, record.sync_id)
    for resolution in (
        PdfTargetResolution(target=None, ambiguous=True),
        PdfTargetResolution(
            target=replace(resolver(record).target, paper_id="different-paper", identity="doi:different-paper")
        ),
    ):

        def current_resolver(_record, result=resolution):
            return result

        with pytest.raises(PdfConflictChanged):
            resolve_service(
                reconciler, record.sync_id, token=snapshot["token"], version="mirror", resolver=current_resolver
            )
    assert reconciler.store.get(record.sync_id).paper_id == record.paper_id
    assert record.canonical_path.read_bytes() != record.mirror_path.read_bytes()
