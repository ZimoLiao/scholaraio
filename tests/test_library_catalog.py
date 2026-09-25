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
