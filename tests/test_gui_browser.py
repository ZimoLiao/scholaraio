"""Opt-in real-browser checks: SCHOLARAIO_BROWSER_TESTS=1 pytest -m browser."""

import os
import threading
from unittest.mock import patch

import pytest

from scholaraio.core.config import _build_config
from scholaraio.interfaces.cli.gui import create_library_view_server
from scholaraio.services.system_open import DefaultApplicationOpenCapability
from scholaraio.stores.papers import update_meta, write_meta


@pytest.mark.browser
@pytest.mark.skipif(os.environ.get("SCHOLARAIO_BROWSER_TESTS") != "1", reason="opt-in Chromium integration")
def test_real_browser_preserves_dragged_selection_and_resumes_updates(tmp_path):
    from playwright.sync_api import expect, sync_playwright

    cfg = _build_config({}, tmp_path)
    paper = cfg.papers_dir / "Doe-2026-Paper"
    paper.mkdir(parents=True)
    write_meta(
        paper,
        {
            "id": "paper",
            "title": "Selection should survive automatic refresh",
            "year": 2026,
            "authors": ["Jane Doe"],
            "abstract": "Readable abstract.",
        },
    )
    (paper / "paper.md").write_text("# Selection should survive automatic refresh\n")
    with patch(
        "scholaraio.services.system_open.default_application_open_capability",
        return_value=DefaultApplicationOpenCapability(False, None, "browser test"),
    ):
        server = create_library_view_server(cfg, port=0)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=playwright.chromium.executable_path)
            context = browser.new_context(permissions=["clipboard-read", "clipboard-write"])
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{server.server_port}")
            title = page.locator("#detail-title")
            expect(title).to_have_text("Selection should survive automatic refresh")
            box = title.bounding_box()
            assert box is not None
            page.mouse.move(box["x"] + 2, box["y"] + 10)
            page.mouse.down()
            page.mouse.move(box["x"] + 75, box["y"] + 10, steps=10)
            page.mouse.up()
            selected = page.evaluate("getSelection().toString()")
            assert selected
            update_meta(paper, title="Changed while reading")
            # Cross two real poll intervals; the selected DOM must stay intact.
            page.wait_for_timeout(4800)
            assert page.evaluate("getSelection().toString()") == selected
            expect(title).to_have_text("Selection should survive automatic refresh")
            page.keyboard.press("Control+c")
            assert page.evaluate("navigator.clipboard.readText()") == selected
            page.evaluate("getSelection().removeAllRanges()")
            expect(title).to_have_text("Changed while reading", timeout=7000)
            # An unchanged refresh must retain the exact title text node too.
            page.evaluate("globalThis.savedTitleNode = document.querySelector('#detail-title').firstChild")
            with page.expect_response(lambda response: "/api/main/detail" in response.url):
                page.locator("#refresh-button").click()
            assert page.evaluate("savedTitleNode === document.querySelector('#detail-title').firstChild")
            assert errors == []
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


@pytest.mark.browser
@pytest.mark.skipif(os.environ.get("SCHOLARAIO_BROWSER_TESTS") != "1", reason="opt-in Chromium integration")
def test_real_browser_pages_and_filters_across_the_library(tmp_path):
    from playwright.sync_api import expect, sync_playwright

    cfg = _build_config({}, tmp_path)
    for i in range(205):
        paper = cfg.papers_dir / str(i)
        paper.mkdir(parents=True)
        write_meta(paper, {"id": str(i), "title": f"Paper {i:03}", "authors": ["Jane Doe"], "year": 2026})
    proceeding = cfg.proceedings_dir / "volume"
    child = proceeding / "papers" / "child"
    child.mkdir(parents=True)
    write_meta(proceeding, {"id": "volume", "title": "Test Proceedings"})
    write_meta(child, {"id": "child", "title": "Proceedings test paper", "year": 2026})
    with patch(
        "scholaraio.services.system_open.default_application_open_capability",
        return_value=DefaultApplicationOpenCapability(False, None, "browser test"),
    ):
        server = create_library_view_server(cfg, port=0)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{server.server_port}")
            expect(page.locator("#table-count")).to_have_text("1–100 / 205")
            expect(page.locator("#paper-table-body tr")).to_have_count(100)
            page.locator("#page-next").click()
            expect(page.locator("#table-count")).to_have_text("101–200 / 205")
            page.locator("#title-filter").fill("Paper 204")
            expect(page.locator("#table-count")).to_have_text("1–1 / 1")
            expect(page.locator("#detail-title")).to_have_text("Paper 204")
            page.locator("#clear-filters-button").click()
            page.locator("#tab-proceedings").click()
            expect(page.locator("#table-count")).to_have_text("1–1 / 1")
            expect(page.locator("#detail-title")).to_have_text("Proceedings test paper")
            assert errors == []
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


@pytest.mark.browser
@pytest.mark.skipif(os.environ.get("SCHOLARAIO_BROWSER_TESTS") != "1", reason="opt-in Chromium integration")
def test_real_browser_resolves_inspected_pdf_versions(tmp_path):
    from types import SimpleNamespace

    from playwright.sync_api import expect, sync_playwright

    from tests.test_pdf_conflicts import conflict

    store, paths, reconciler, record = conflict(tmp_path)
    cfg = _build_config({"paths": {"papers_dir": str(tmp_path / "library")}}, tmp_path)
    write_meta(record.canonical_path.parent, {"id": "paper-id", "title": "Conflicting annotations", "year": 2026})
    with patch(
        "scholaraio.services.system_open.default_application_open_capability",
        return_value=DefaultApplicationOpenCapability(True, "host", "browser test"),
    ):
        server = create_library_view_server(cfg, port=0)
    server.RequestHandlerClass.pdf_edit_mirror_service = SimpleNamespace(
        store=store,
        paths=paths,
        reconciler=reconciler,
        status=lambda source, paper_id: store.public_status(store.get_by_paper(source, paper_id)),
    )
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{server.server_port}")
            page.locator("#pdf-recovery-button").click()
            expect(page.locator("#pdf-recovery-panel")).to_be_visible()
            mirror = page.locator("#pdf-recovery-versions > div").filter(has_text="Windows viewer copy:")
            mirror.get_by_role("button").click()
            expect(page.locator("#pdf-recovery-message")).to_contain_text("Close all PDF readers")
            page.locator("#pdf-readers-closed").check()
            mirror.get_by_role("button").click()
            expect(page.locator("#pdf-recovery-panel")).to_be_hidden()
            assert record.canonical_path.read_bytes() == record.mirror_path.read_bytes()
            assert store.get(record.sync_id).state == "in_sync"
            assert errors == []
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
