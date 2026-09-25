"""Real metadata pagination and projection invalidation contracts."""

import json

import pytest

from scholaraio.core.config import _build_config
from scholaraio.services.library_catalog import LibraryCatalog
from scholaraio.stores.papers import update_meta


def test_page_filters_full_library_and_reuses_unchanged_records(tmp_path, monkeypatch):
    cfg = _build_config({}, tmp_path)
    cfg.ensure_dirs()
    for i in range(205):
        directory = cfg.papers_dir / str(i)
        directory.mkdir()
        (directory / "meta.json").write_text(
            json.dumps({"id": str(i), "title": f"Paper {i:03}", "authors": ["测试"], "year": 2000 + i % 20})
        )
    monkeypatch.setattr("scholaraio.services.library_view._background_issue_map", lambda *_: {})
    catalog = LibraryCatalog(cfg, "main")
    first = catalog.page({"limit": "100", "sort": "title", "direction": "asc"})
    assert first["total"] == 205
    assert len(first["papers"]) == 100
    monkeypatch.setattr("scholaraio.services.library_view._background_issue_map", lambda *_: {})
    # Auditing is a separate revision; freeze it while checking metadata reuse.
    catalog.audit_revision = str(catalog.page({"limit": "1"})["audit"].get("completed_at", ""))
    original = __import__("scholaraio.services.library_catalog", fromlist=["read_meta"]).read_meta
    calls = []

    def counted(path):
        calls.append(path)
        return original(path)

    monkeypatch.setattr("scholaraio.services.library_catalog.read_meta", counted)
    second = catalog.page({"limit": "100", "offset": "100", "sort": "title", "direction": "asc"})
    assert len(second["papers"]) == 100
    assert not ({r["paper_id"] for r in first["papers"]} & {r["paper_id"] for r in second["papers"]})
    assert calls == []
    update_meta(cfg.papers_dir / "204", title="Special result")
    result = catalog.page({"limit": "100", "q": "Special", "author": "测试"})
    assert result["matched"] == 1 and result["papers"][0]["paper_id"] == "204"
    assert calls == [cfg.papers_dir / "204"]
    (cfg.papers_dir / "204" / "meta.json").write_text(json.dumps({"id": "204", "title": "External"}))
    assert catalog.page({"limit": "100", "q": "External", "refresh": "1"})["matched"] == 1
    catalog.close()


@pytest.mark.parametrize(
    "params", [{"limit": "201"}, {"offset": "-1"}, {"sort": "DROP TABLE"}, {"year_from": "abc"}, {"ids": "{}"}]
)
def test_bad_page_query_is_rejected(tmp_path, params):
    cfg = _build_config({}, tmp_path)
    catalog = LibraryCatalog(cfg, "main")
    with pytest.raises(ValueError):
        catalog.page(params)
    catalog.close()


def test_background_scan_does_not_block_paging(tmp_path, monkeypatch):
    import threading

    cfg = _build_config({}, tmp_path)
    cfg.ensure_dirs()
    monkeypatch.setattr("scholaraio.services.library_view._background_issue_map", lambda *_: {})
    catalog = LibraryCatalog(cfg, "main", background=False)
    catalog.page({"limit": "100"})
    entered, release = threading.Event(), threading.Event()
    from scholaraio.services import library_catalog

    original = library_catalog.library_manifest

    def blocked(root, *, force=False):
        if force:
            entered.set()
            assert release.wait(5)
        return original(root, force=force)

    monkeypatch.setattr(library_catalog, "library_manifest", blocked)
    worker = threading.Thread(target=catalog._scan_loop)
    catalog.worker = worker
    worker.start()
    try:
        assert entered.wait(8)
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor() as executor:
            future = executor.submit(catalog.page, {"limit": "100"})
            try:
                assert future.result(timeout=1)["total"] == 0
            finally:
                release.set()
                catalog.stop.set()
    finally:
        release.set()
        worker.join()
        catalog.close()


def test_failed_timestamp_notification_keeps_committed_metadata_visible(tmp_path, monkeypatch):
    from scholaraio.stores import library_state

    cfg = _build_config({}, tmp_path)
    cfg.ensure_dirs()
    directory = cfg.papers_dir / "one"
    directory.mkdir()
    (directory / "meta.json").write_text(json.dumps({"id": "one", "title": "Before"}))
    monkeypatch.setattr("scholaraio.services.library_view._background_issue_map", lambda *_: {})
    catalog = LibraryCatalog(cfg, "main", background=False)
    try:
        assert catalog.page({})["papers"][0]["title"] == "Before"

        def denied(*args, **kwargs):
            raise PermissionError("collection cannot be touched")

        monkeypatch.setattr(library_state.os, "utime", denied)
        update_meta(directory, title="After")
        assert catalog.page({"q": "After"})["matched"] == 1
    finally:
        catalog.close()


def test_content_and_identical_audit_refresh_preserve_page(tmp_path, monkeypatch):
    from scholaraio.services import library_view

    cfg = _build_config({}, tmp_path)
    cfg.ensure_dirs()
    for i in range(101):
        directory = cfg.papers_dir / str(i)
        directory.mkdir()
        (directory / "meta.json").write_text(json.dumps({"id": str(i), "title": "Paper"}))
        (directory / "paper.pdf").write_bytes(b"old")
    monkeypatch.setattr(library_view, "_background_issue_map", lambda *_: {})
    catalog = LibraryCatalog(cfg, "main", background=False)
    try:
        first = catalog.page({"offset": "100"})

        def unexpected_read(_directory):
            pytest.fail("Unchanged row inputs must not reparse metadata")

        monkeypatch.setattr("scholaraio.services.library_catalog.read_meta", unexpected_read)
        (cfg.papers_dir / "0" / "paper.pdf").write_bytes(b"annotation save")
        monkeypatch.setattr(library_view, "main_audit_status", lambda *_: {"completed_at": "new audit"})
        after = catalog.page({"offset": "100", "revision": first["revision"], "refresh": "1"})
        assert after["revision"] == first["revision"]
        assert after["offset"] == 100
    finally:
        catalog.close()


def test_malformed_metadata_field_does_not_break_whole_catalog(tmp_path, monkeypatch):
    cfg = _build_config({}, tmp_path)
    cfg.ensure_dirs()
    for name, title in [("good", "Good"), ("bad", ["not", "text"])]:
        directory = cfg.papers_dir / name
        directory.mkdir()
        (directory / "meta.json").write_text(json.dumps({"id": name, "title": title, "doi": {"invalid": True}}))
    monkeypatch.setattr("scholaraio.services.library_view._background_issue_map", lambda *_: {})
    catalog = LibraryCatalog(cfg, "main", background=False)
    try:
        page = catalog.page({})
        assert page["total"] == 2
        bad = next(row for row in page["papers"] if row["paper_id"] == "bad")
        assert any(issue["code"] == "invalid_metadata_type" for issue in bad["issues"])
    finally:
        catalog.close()


@pytest.mark.parametrize("field", ["year", "citation_count"])
@pytest.mark.parametrize("value", [10**100, float("inf"), float("nan"), float("-inf")])
def test_out_of_range_integer_is_a_row_warning(tmp_path, monkeypatch, field, value):
    cfg = _build_config({}, tmp_path)
    cfg.ensure_dirs()
    for name, extra in [("good", {}), ("bad", {field: value})]:
        directory = cfg.papers_dir / name
        directory.mkdir()
        (directory / "meta.json").write_text(json.dumps({"id": name, "title": name, **extra}))
    monkeypatch.setattr("scholaraio.services.library_view._background_issue_map", lambda *_: {})
    catalog = LibraryCatalog(cfg, "main", background=False)
    try:
        page = catalog.page({})
        assert page["total"] == 2
        bad = next(row for row in page["papers"] if row["paper_id"] == "bad")
        assert bad[field] == 0
        assert any(issue["rule"] == "invalid_metadata_number" for issue in bad["issues"])
    finally:
        catalog.close()


def test_removing_proceedings_volume_metadata_removes_projected_children(tmp_path):
    cfg = _build_config({}, tmp_path)
    volume = cfg.proceedings_dir / "volume"
    child = volume / "papers" / "child"
    child.mkdir(parents=True)
    (volume / "meta.json").write_text(json.dumps({"id": "volume", "title": "Original volume"}))
    (child / "meta.json").write_text(json.dumps({"id": "child", "title": "Child paper"}))
    catalog = LibraryCatalog(cfg, "proceedings", background=False)
    try:
        first = catalog.page({})
        assert first["total"] == 1
        (volume / "meta.json").unlink()
        page = catalog.page({"refresh": "1"})
        assert page["total"] == 0
        assert page["revision"] != first["revision"]
        (volume / "meta.json").write_text(json.dumps({"id": "volume", "title": "Restored volume"}))
        restored = catalog.page({"refresh": "1"})
        assert restored["total"] == 1
        assert restored["papers"][0]["proceeding_title"] == "Restored volume"
    finally:
        catalog.close()


def test_nonfinite_provider_citations_do_not_discard_valid_count(tmp_path, monkeypatch):
    cfg = _build_config({}, tmp_path)
    directory = cfg.papers_dir / "one"
    directory.mkdir(parents=True)
    (directory / "meta.json").write_text(
        json.dumps({"id": "one", "title": "One", "citation_count": {"bad": float("inf"), "good": 12}})
    )
    monkeypatch.setattr("scholaraio.services.library_view._background_issue_map", lambda *_: {})
    catalog = LibraryCatalog(cfg, "main", background=False)
    try:
        row = catalog.page({})["papers"][0]
        assert row["citation_count"] == 12
        assert row["issues"][0]["rule"] == "invalid_metadata_number"
    finally:
        catalog.close()


@pytest.mark.parametrize("location", ["volume", "child"])
@pytest.mark.parametrize("invalid", [[], "not an object", None])
def test_proceedings_non_object_metadata_is_a_row_issue(tmp_path, location, invalid):
    cfg = _build_config({}, tmp_path)
    volume = cfg.proceedings_dir / "volume"
    child = volume / "papers" / "child"
    child.mkdir(parents=True)
    (volume / "meta.json").write_text(json.dumps({"id": "volume", "title": "Volume"}))
    (child / "meta.json").write_text(json.dumps({"id": "child", "title": "Child"}))
    directory = volume if location == "volume" else child
    (directory / "meta.json").write_text(json.dumps(invalid))
    catalog = LibraryCatalog(cfg, "proceedings", background=False)
    try:
        page = catalog.page({})
        assert page["total"] == 1
        assert page["papers"][0]["issues"]
    finally:
        catalog.close()
