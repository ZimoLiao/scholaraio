from __future__ import annotations

import io
import json
import shutil
import subprocess
import threading
from contextlib import contextmanager, nullcontext, suppress
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest

from scholaraio.core.config import _build_config


@contextmanager
def _running_library_server(cfg, *, host="127.0.0.1", native_target="host"):
    from scholaraio.interfaces.cli.gui import create_library_view_server
    from scholaraio.services.system_open import DefaultApplicationOpenCapability

    # Native-open route tests need a deterministic desktop-capable host even on
    # headless CI runners. System capability detection is covered separately.
    capability_patch = (
        patch(
            "scholaraio.services.system_open.default_application_open_capability",
            return_value=DefaultApplicationOpenCapability(True, native_target),
        )
        if native_target is not None
        else nullcontext()
    )
    with (
        patch.dict("os.environ", {"DISPLAY": ":pytest"}),
        capability_patch,
    ):
        server = create_library_view_server(cfg, host=host, port=0)
    bound_host, port = server.server_address[:2]
    connect_host = "127.0.0.1" if bound_host in {"0.0.0.0", "::"} else bound_host
    if ":" in connect_host and not connect_host.startswith("["):
        connect_host = f"[{connect_host}]"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://{connect_host}:{port}"
    finally:
        server.shutdown()
        server.server_close()


def _json_response(url: str) -> tuple[dict, object]:
    with urlopen(url, timeout=3) as response:
        return json.loads(response.read().decode("utf-8")), response.headers


def _post_json(
    url: str,
    payload: object,
    *,
    token: str = "",
    origin: str = "",
    content_type: str = "application/json",
):
    headers = {"Content-Type": content_type}
    if token:
        headers["X-ScholarAIO-CSRF"] = token
    if origin:
        headers["Origin"] = origin
    return Request(
        url,
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
    )


def _write_gui_action_fixtures(tmp_path: Path, *, main_pdf: bool = True):
    cfg = _build_config({}, tmp_path)
    main_dir = cfg.papers_dir / "Doe-2026-Action"
    main_dir.mkdir(parents=True)
    (main_dir / "meta.json").write_text(
        json.dumps(
            {
                "id": "action-paper",
                "title": "Action paper",
                "authors": ["Jane Doe"],
                "first_author_lastname": "Doe",
                "year": 2026,
                "journal": "Journal of Actions",
                "doi": "10.1000/action",
                "abstract": "Canonical abstract.",
                "paper_type": "journal-article",
            }
        ),
        encoding="utf-8",
    )
    if main_pdf:
        (main_dir / "Doe-2026-Action.pdf").write_bytes(b"%PDF-action")

    proceeding_dir = cfg.proceedings_dir / "Proc-2026-Actions"
    child_dir = proceeding_dir / "papers" / "Roe-2026-Proceeding"
    child_dir.mkdir(parents=True)
    (proceeding_dir / "meta.json").write_text(
        json.dumps({"id": "proc-actions", "title": "Proceedings of Actions", "year": 2026}),
        encoding="utf-8",
    )
    (child_dir / "meta.json").write_text(
        json.dumps(
            {
                "id": "proceeding-action-paper",
                "title": "Proceeding action paper",
                "authors": ["Pat Roe"],
                "first_author_lastname": "Roe",
                "year": 2026,
                "doi": "10.1000/proceeding-action",
                "paper_type": "conference-paper",
            }
        ),
        encoding="utf-8",
    )
    (child_dir / "Roe-2026-Proceeding.pdf").write_bytes(b"%PDF-proceeding")
    return cfg, main_dir, child_dir


def _run_library_app_vm(test_body: str, *, fetch_setup: str = "") -> dict:
    from scholaraio.interfaces.cli.gui import _static_dir

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for app.js behavior regression")
    rendering_js = (_static_dir() / "rendering.js").as_posix()
    app_js = (_static_dir() / "app.js").as_posix()
    script = r"""
const fs = require("fs");
const vm = require("vm");

let document;
function element(id) {
  const classes = new Set();
  const attributes = new Map();
  const listeners = new Map();
  const el = {
    id,
    dataset: {},
    value: "",
    checked: false,
    disabled: false,
    hidden: false,
    title: "",
    className: "",
    children: [],
    parentNode: null,
    style: {},
    classList: {
      add(name) { classes.add(name); },
      remove(name) { classes.delete(name); },
      contains(name) { return classes.has(name); },
      toggle(name, force) {
        const enabled = force === undefined ? !classes.has(name) : Boolean(force);
        if (enabled) classes.add(name);
        else classes.delete(name);
        return enabled;
      },
    },
    appendChild(child) { child.parentNode = this; this.children.push(child); return child; },
    append(...items) { items.forEach((item) => this.appendChild(item)); },
    remove() {
      if (!this.parentNode) return;
      this.parentNode.children = this.parentNode.children.filter((child) => child !== this);
      this.parentNode = null;
    },
    setAttribute(name, value) { attributes.set(name, String(value)); this[name] = String(value); },
    getAttribute(name) { return attributes.get(name) || null; },
    removeAttribute(name) { attributes.delete(name); delete this[name]; },
    addEventListener(name, handler) { listeners.set(name, handler); },
    dispatch(name, event = {}) { return listeners.get(name)?.(event); },
    focus() { document.activeElement = this; },
    select() { document.__selectedText = this.value; },
    click() { document.__clickedHref = this.href || ""; },
  };
  let content = "";
  Object.defineProperty(el, "textContent", {
    get() { return content; },
    set(value) { content = String(value ?? ""); if (content === "") el.children = []; },
  });
  return el;
}

const elements = new Map();
const tabs = ["main", "proceedings"].map((tab) => {
  const el = element(`tab-${tab}`);
  el.dataset.tab = tab;
  return el;
});
document = {
  body: element("body"),
  activeElement: null,
  __selectedText: "",
  __clickedHref: "",
  __execCopy: true,
  getElementById(id) {
    if (!elements.has(id)) elements.set(id, element(id));
    return elements.get(id);
  },
  createElement(tag) { return element(tag); },
  querySelectorAll(selector) {
    if (selector === ".tab") return tabs;
    return [];
  },
  addEventListener() {},
  execCommand(command) { return command === "copy" && this.__execCopy; },
};
const context = {
  URLSearchParams,
  document,
  elements,
  navigator: { clipboard: { writeText: async () => {} } },
  location: { origin: "http://127.0.0.1:8765" },
  URLSearchParams,
  setTimeout,
  clearTimeout,
  setInterval: () => 1,
  clearInterval: () => {},
  console,
};
context.window = context;
context.fetch = async (url) => {
  if (String(url).includes("/api/capabilities")) {
    return { ok: true, json: async () => ({
      csrf_token: "csrf-token",
      native_pdf_open: { enabled: true, reason: "" },
      search_modes: { main: ["metadata", "keyword", "semantic", "unified"], proceedings: ["metadata"] },
    }) };
  }
  if (String(url).includes("/detail")) return { ok: true, json: async () => ({}) };
  return { ok: true, json: async () => ({ papers: [], total: 0, issue_totals: {} }) };
};
__FETCH_SETUP__
const renderingCode = fs.readFileSync(__RENDERING_JS__, "utf8");
const code = fs.readFileSync(__APP_JS__, "utf8");
vm.runInNewContext(`${renderingCode}\n${code}
globalThis.__ready = (async () => {
  await new Promise((resolve) => setTimeout(resolve, 0));
__TEST_BODY__
})();`, context);
context.__ready.then((payload) => console.log(JSON.stringify(payload))).catch((err) => {
  console.error(err);
  process.exit(1);
});
"""
    script = script.replace("__RENDERING_JS__", json.dumps(rendering_js))
    script = script.replace("__APP_JS__", json.dumps(app_js))
    script = script.replace("__FETCH_SETUP__", fetch_setup)
    script = script.replace("__TEST_BODY__", test_body)
    result = subprocess.run([node, "-e", script], check=False, capture_output=True, text=True)
    if result.returncode:
        raise AssertionError(result.stderr or result.stdout)
    return json.loads(result.stdout)


def test_library_view_api_serves_live_json_and_rejects_writes(tmp_path):
    from scholaraio.interfaces.cli.gui import create_library_view_server

    cfg = _build_config({}, tmp_path)
    paper_dir = tmp_path / "data" / "libraries" / "papers" / "Doe-2026-Live"
    paper_dir.mkdir(parents=True)
    (paper_dir / "meta.json").write_text(
        json.dumps(
            {
                "id": "live-paper",
                "title": "Live paper",
                "authors": ["Jane Doe"],
                "year": 2026,
                "journal": "Live Journal",
                "doi": "10.1000/live",
                "abstract": "Live abstract.",
            }
        ),
        encoding="utf-8",
    )
    (paper_dir / "paper.md").write_text("# Live paper\n", encoding="utf-8")

    server = create_library_view_server(cfg, host="127.0.0.1", port=0)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(f"http://{host}:{port}/api/main/papers", timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
        assert payload["total"] == 1
        assert payload["papers"][0]["paper_id"] == "live-paper"

        new_dir = tmp_path / "data" / "libraries" / "papers" / "Roe-2026-New"
        new_dir.mkdir()
        (new_dir / "meta.json").write_text(
            json.dumps({"id": "new-paper", "title": "New paper", "authors": ["Pat Roe"], "year": 2026}),
            encoding="utf-8",
        )

        with urlopen(f"http://{host}:{port}/api/main/papers", timeout=3) as response:
            refreshed = json.loads(response.read().decode("utf-8"))
        assert {row["paper_id"] for row in refreshed["papers"]} == {"live-paper", "new-paper"}

        request = Request(f"http://{host}:{port}/api/main/papers", method="POST", data=b"{}")
        try:
            urlopen(request, timeout=3)
        except HTTPError as exc:
            assert exc.code == 405
            assert exc.headers["Allow"] == "GET, HEAD"
            assert "read-only" in exc.read().decode("utf-8")
        else:  # pragma: no cover - defensive assertion
            raise AssertionError("POST unexpectedly succeeded")
    finally:
        server.shutdown()
        server.server_close()


def test_library_view_server_serves_static_console_shell(tmp_path):
    from scholaraio.interfaces.cli.gui import create_library_view_server

    cfg = _build_config({}, tmp_path)
    server = create_library_view_server(cfg, host="127.0.0.1", port=0)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(f"http://{host}:{port}/", timeout=3) as response:
            html = response.read().decode("utf-8")
        assert "ScholarAIO Library" in html
        assert "Main Papers" in html
        assert "Proceedings" in html
        assert "pdf-frame" in html
        assert "Back to records" in html
        assert ">CLI<" not in html
        assert "https://" not in html
        assert "http://" not in html
        assert "tex-chtml.js" not in html
        assert "MathJax" not in html
        assert html.index("rendering.js") < html.index("app.js")
        assert "workflows.css" in html
    finally:
        server.shutdown()
        server.server_close()


def test_library_view_shell_uses_compact_records_and_pdf_controls(tmp_path):
    from scholaraio.interfaces.cli.gui import create_library_view_server

    cfg = _build_config({}, tmp_path)
    server = create_library_view_server(cfg, host="127.0.0.1", port=0)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(f"http://{host}:{port}/", timeout=3) as response:
            html = response.read().decode("utf-8")
        assert 'id="source-copy-button"' in html
        assert 'id="pdf-fullscreen-button"' in html
        assert 'id="detail-subtitle"' not in html
        assert html.index('id="toc-list"') < html.index('id="issue-list"')
    finally:
        server.shutdown()
        server.server_close()


def test_library_view_shell_omits_audit_chrome_and_keeps_pdf_actions_single_line(tmp_path):
    from scholaraio.interfaces.cli.gui import _static_dir, create_library_view_server

    cfg = _build_config({}, tmp_path)
    server = create_library_view_server(cfg, host="127.0.0.1", port=0)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(f"http://{host}:{port}/", timeout=3) as response:
            html = response.read().decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()

    for removed_text in ("Has audit issues", "Missing Markdown", ">Errors<", ">Warnings<"):
        assert removed_text not in html
    for removed_id in ("filter-issues", "filter-missing-md", "metric-errors", "metric-warnings"):
        assert f'id="{removed_id}"' not in html
    for removed_kicker in ("Source", "Discover", "Records", "Inspector"):
        assert f'<div class="monitor-kicker">{removed_kicker}</div>' not in html

    css = (_static_dir() / "workflows.css").read_text(encoding="utf-8")
    detail_actions = css.split(".detail-actions {", 1)[1].split("}", 1)[0]
    action_button = css.rsplit("\n.action-button {", 1)[1].split("}", 1)[0]
    assert "grid-template-columns:" in detail_actions
    assert "minmax(" in detail_actions
    assert "white-space: nowrap" in action_button


def test_library_view_shell_exposes_advanced_search_and_record_actions(tmp_path):
    cfg = _build_config({}, tmp_path)

    with (
        _running_library_server(cfg, native_target="windows") as (_server, base_url),
        urlopen(f"{base_url}/", timeout=3) as response,
    ):
        html = response.read().decode("utf-8")

    for control_id in (
        "search-mode",
        "search-input",
        "search-button",
        "title-filter",
        "author-filter",
        "year-from-filter",
        "year-to-filter",
        "journal-filter",
        "doi-filter",
        "type-filter",
        "clear-filters-button",
        "copy-bibtex-button",
        "preview-pdf-button",
        "native-pdf-button",
    ):
        assert f'id="{control_id}"' in html
    assert 'id="search-diagnostics"' in html
    assert 'aria-live="polite"' in html
    assert 'id="toast"' in html
    assert 'role="status"' in html
    assert 'id="pdf-frame"' in html
    assert "http://" not in html
    assert "https://" not in html


def test_library_view_app_combines_structured_filters_and_clears_them() -> None:
    payload = _run_library_app_vm(
        r"""
  state.tab = "main";
  state.rows.main = [{
    paper_id: "target-paper",
    dir_name: "Doe-2024-Target",
    title: "Turbulence closure for reacting flows",
    authors_text: "Jane Doe, Pat Roe",
    year: 2024,
    journal: "Journal of Fluid Mechanics",
    doi: "10.1000/target",
    paper_type: "journal-article",
    has_md: false,
    issue_counts: { warning: 1 },
  }];
  Object.assign(state.filters, {
    search: "closure",
    title: "reacting",
    author: "JANE DOE",
    yearFrom: "2020",
    yearTo: "2024",
    journal: "fluid mechanics",
    doi: "10.1000/tar",
    type: "journal-article",
    volume: "",
  });
  const allMatch = rowMatches(state.rows.main[0]);
  state.filters.yearFrom = "2025";
  const yearMiss = rowMatches(state.rows.main[0]);
  state.filters.yearFrom = "2020";
  state.filters.author = "someone else";
  const authorMiss = rowMatches(state.rows.main[0]);

  state.tab = "proceedings";
  const proceeding = {
    paper_id: "proceeding-paper",
    title: "Proceeding result",
    authors_text: "Jane Doe",
    year: 2024,
    journal: "",
    proceeding_title: "Proceedings of Fluid Actions",
    doi: "10.1000/tar",
    paper_type: "journal-article",
    has_md: false,
    issue_counts: { warning: 1 },
  };
  state.filters.author = "Jane Doe";
  state.filters.title = "Proceeding";
  state.filters.search = "result";
  state.filters.journal = "fluid actions";
  state.filters.volume = "Proceedings of Fluid Actions";
  const proceedingSourceMatch = rowMatches(proceeding);

  state.searchMode = "unified";
  state.ranked = { order: ["proceeding-paper"], byId: new Map(), diagnostics: {} };
  state.sortKey = "title";
  state.sortDir = "asc";
  for (const [id, value] of [
    ["search-input", "result"],
    ["title-filter", "Proceeding"],
    ["author-filter", "Jane Doe"],
    ["year-from-filter", "2020"],
    ["year-to-filter", "2024"],
    ["journal-filter", "fluid"],
    ["doi-filter", "10.1000"],
    ["type-filter", "journal-article"],
  ]) elements.get(id).value = value;
  clearAllFilters();

  return {
    allMatch,
    yearMiss,
    authorMiss,
    proceedingSourceMatch,
    filters: state.filters,
    searchMode: state.searchMode,
    ranked: state.ranked,
    sortKey: state.sortKey,
    sortDir: state.sortDir,
    controlValues: [
      elements.get("search-input").value,
      elements.get("title-filter").value,
      elements.get("author-filter").value,
      elements.get("year-from-filter").value,
      elements.get("year-to-filter").value,
      elements.get("journal-filter").value,
      elements.get("doi-filter").value,
      elements.get("type-filter").value,
    ],
  };
"""
    )

    assert payload["allMatch"] is True
    assert payload["yearMiss"] is False
    assert payload["authorMiss"] is False
    assert payload["proceedingSourceMatch"] is True
    assert all(value in {"", False} for value in payload["filters"].values())
    assert payload["searchMode"] == "metadata"
    assert payload["ranked"] is None
    assert payload["sortKey"] == "year"
    assert payload["sortDir"] == "desc"
    assert payload["controlValues"] == ["", "", "", "", "", "", "", ""]


def test_library_view_app_ranked_search_orders_results_and_ignores_stale_responses() -> None:
    payload = _run_library_app_vm(
        r"""
  state.tab = "main";
  state.rows.main = [
    { paper_id: "paper-a", title: "Alpha", authors_text: "A", year: 2024, paper_type: "article" },
    { paper_id: "paper-b", title: "Beta", authors_text: "B", year: 2025, paper_type: "article" },
  ];
  state.searchMode = "unified";
  els.searchMode.value = "unified";
  els.searchInput.value = "first query";
  state.filters.search = "first query";
  state.filters.title = "alpha";
  els.titleFilter.value = "alpha";
  const first = runRankedSearch();
  await Promise.resolve();

  els.searchInput.value = "second query";
  state.filters.search = "second query";
  state.filters.title = "";
  els.titleFilter.value = "";
  const second = runRankedSearch();
  await Promise.resolve();

  __searchResolvers[1]({
    mode: "unified",
    query: "second query",
    total: 2,
    results: [
      { paper_id: "paper-b", rank: 1, score: 0.0328, match: "both" },
      { paper_id: "paper-a", rank: 2, score: 0.0164, match: "keyword" },
    ],
    diagnostics: {
      status: "degraded",
      message: "Semantic search is unavailable; results use keyword retrieval only.",
      keyword: "available",
      semantic: "unavailable",
      actions: [{ command: "scholaraio embed", label: "Build semantic embeddings" }],
    },
  });
  await second;
  __searchResolvers[0]({
    mode: "unified",
    query: "first query",
    total: 1,
    results: [{ paper_id: "paper-a", rank: 1, score: 1, match: "both" }],
    diagnostics: { status: "ok", message: "stale", keyword: "available", semantic: "available", actions: [] },
  });
  await first;

  const ordered = filteredRows().map((row) => row.paper_id);
  const betaRank = rankingFor("paper-b");
  const diagnostics = els.searchDiagnostics.textContent;
  const diagnosticsKind = els.searchDiagnostics.dataset.kind;
  els.searchInput.value = "cancelled query";
  state.filters.search = "cancelled query";
  const cancelled = runRankedSearch();
  await Promise.resolve();
  switchTab("proceedings");
  const cancelledButtonLabel = els.searchButton.textContent;
  const cancelledButtonBusy = els.searchButton.getAttribute("aria-busy");
  __searchResolvers[2]({
    mode: "unified",
    query: "cancelled query",
    total: 1,
    results: [{ paper_id: "paper-a", rank: 1, score: 1, match: "both" }],
    diagnostics: { status: "ok", message: "cancelled", keyword: "available", semantic: "available", actions: [] },
  });
  await cancelled;
  await Promise.resolve();
  return {
    requests: __searchRequests,
    ordered,
    betaRank,
    diagnostics,
    diagnosticsKind,
    modeAfterProceedings: state.searchMode,
    proceedingsMessage: els.searchDiagnostics.textContent,
    cancelledButtonLabel,
    cancelledButtonBusy,
  };
""",
        fetch_setup=r"""
context.__searchRequests = [];
context.__searchResolvers = [];
context.fetch = async (url) => {
  const target = String(url);
  if (target.includes("/api/capabilities")) {
    return { ok: true, json: async () => ({
      csrf_token: "csrf-token",
      native_pdf_open: { enabled: true, reason: "" },
      search_modes: { main: ["metadata", "keyword", "semantic", "unified"], proceedings: ["metadata"] },
    }) };
  }
  if (target.includes("/api/main/search")) {
    context.__searchRequests.push(target);
    return new Promise((resolve) => context.__searchResolvers.push((payload) => resolve({
      ok: true,
      json: async () => payload,
    })));
  }
  if (target.includes("/detail")) return { ok: true, json: async () => ({}) };
  return { ok: true, json: async () => ({ papers: [], total: 0, issue_totals: {} }) };
};
""",
    )

    assert len(payload["requests"]) == 3
    assert "mode=unified" in payload["requests"][0]
    assert "q=first+query" in payload["requests"][0]
    assert "title=alpha" in payload["requests"][0]
    assert "q=second+query" in payload["requests"][1]
    assert payload["ordered"] == ["paper-b", "paper-a"]
    assert payload["betaRank"] == {"rank": 1, "score": 0.0328, "match": "both"}
    assert payload["diagnosticsKind"] == "degraded"
    assert "Semantic search is unavailable" in payload["diagnostics"]
    assert payload["modeAfterProceedings"] == "metadata"
    assert "Proceedings" in payload["proceedingsMessage"]
    assert payload["cancelledButtonLabel"] == "Search"
    assert payload["cancelledButtonBusy"] == "false"


def test_library_view_app_copies_bibtex_with_fallback_and_opens_native_pdf() -> None:
    payload = _run_library_app_vm(
        r"""
  state.tab = "main";
  state.selected.main = "action-paper";
  state.capabilities = {
    csrfToken: "csrf-token",
    nativePdfOpen: true,
    nativePdfReason: "",
    pdfDelivery: { mode: "native", target: "windows", label: "Open in default viewer", reason: "" },
  };
  const detail = {
    paper_id: "action-paper",
    dir_name: "Doe-2026-Action",
    title: "Action paper",
    has_pdf: true,
    pdf_url: "/api/main/pdf?id=action-paper",
    authors_text: "Jane Doe",
    issues: [],
    toc: [],
  };
  state.detail = detail;
  renderDetail(detail);
  navigator.clipboard.writeText = async () => { throw new Error("clipboard denied"); };
  await copySelectedBibtex();
  const copiedText = document.__selectedText;
  const copyFeedback = els.toast.textContent;
  await deliverSelectedPdf();
  const nativeFeedback = els.toast.textContent;
  const nativeRequest = __requests.find((request) => request.url.includes("/open-pdf"));

  renderDetail({ ...detail, has_pdf: false, pdf_url: "" });
  const noPdfDisabled = [els.previewPdfButton.disabled, els.nativePdfButton.disabled];
  state.capabilities.nativePdfOpen = false;
  state.capabilities.nativePdfReason = "Loopback only";
  state.capabilities.pdfDelivery = {
    mode: "download",
    target: "client",
    label: "Download PDF",
    reason: "Loopback only",
  };
  renderDetail(detail);
  await deliverSelectedPdf();

  return {
    copiedText,
    copyFeedback,
    nativeFeedback,
    nativeRequest,
    noPdfDisabled,
    nativeDisabled: els.nativePdfButton.disabled,
    nativeTitle: els.nativePdfButton.title,
    nativeLabel: els.nativePdfButton.textContent,
    downloadedHref: document.__clickedHref,
    temporaryNodes: document.body.children.length,
    copyButtonBusy: els.copyBibtexButton.disabled,
  };
""",
        fetch_setup=r"""
context.__requests = [];
context.fetch = async (url, options = {}) => {
  const target = String(url);
  context.__requests.push({ url: target, options });
  if (target.includes("/api/capabilities")) {
    return { ok: true, json: async () => ({
      csrf_token: "csrf-token",
      native_pdf_open: { enabled: true, reason: "" },
      search_modes: { main: ["metadata", "keyword", "semantic", "unified"], proceedings: ["metadata"] },
    }) };
  }
  if (target.includes("/bibtex")) {
    return { ok: true, json: async () => ({ paper_id: "action-paper", bibtex: "@article{Doe2026Action,\n}" }) };
  }
  if (target.includes("/open-pdf")) {
    return { ok: true, json: async () => ({ status: "opened", paper_id: "action-paper" }) };
  }
  if (target.includes("/detail")) return { ok: true, json: async () => ({}) };
  return { ok: true, json: async () => ({ papers: [], total: 0, issue_totals: {} }) };
};
""",
    )

    assert payload["copiedText"] == "@article{Doe2026Action,\n}"
    assert "BibTeX copied" in payload["copyFeedback"]
    assert "default viewer" in payload["nativeFeedback"]
    request = payload["nativeRequest"]
    assert request["options"]["method"] == "POST"
    assert request["options"]["headers"]["Content-Type"] == "application/json"
    assert request["options"]["headers"]["X-ScholarAIO-CSRF"] == "csrf-token"
    assert json.loads(request["options"]["body"]) == {"id": "action-paper"}
    assert payload["noPdfDisabled"] == [True, True]
    assert payload["nativeDisabled"] is False
    assert "Loopback only" in payload["nativeTitle"]
    assert payload["nativeLabel"] == "Download PDF"
    assert payload["downloadedHref"] == "/api/main/pdf?id=action-paper&download=1"
    assert payload["temporaryNodes"] == 0
    assert payload["copyButtonBusy"] is False


def test_library_view_shell_and_app_show_only_actionable_pdf_sync_states(tmp_path) -> None:
    from scholaraio.interfaces.cli.gui import _static_dir

    html = (_static_dir() / "index.html").read_text(encoding="utf-8")
    assert 'id="pdf-sync-status"' in html

    payload = _run_library_app_vm(
        r"""
  const detail = {
    paper_id: "sync-paper",
    title: "Sync paper",
    has_pdf: true,
    pdf_url: "/api/main/pdf?id=sync-paper",
    issues: [],
    toc: [],
  };
  renderDetail({ ...detail, pdf_sync: { state: "not_opened", retryable: false, message: "" } });
  const quietNotOpened = els.pdfSyncStatus.hidden;
  renderPdfSyncStatus({ state: "in_sync", retryable: false, message: "" });
  const quietInSync = els.pdfSyncStatus.hidden;
  renderPdfSyncStatus({ state: "sync_pending", retryable: true, message: "Waiting for the reader to finish saving" });
  const pending = {
    hidden: els.pdfSyncStatus.hidden,
    state: els.pdfSyncStatus.dataset.state,
    text: els.pdfSyncStatus.textContent,
  };
  renderPdfSyncStatus({ state: "sync_failed", retryable: false, message: "Disk is full" });
  const failed = {
    hidden: els.pdfSyncStatus.hidden,
    state: els.pdfSyncStatus.dataset.state,
    text: els.pdfSyncStatus.textContent,
  };
  return { quietNotOpened, quietInSync, pending, failed };
"""
    )

    assert payload["quietNotOpened"] is True
    assert payload["quietInSync"] is True
    assert payload["pending"] == {
        "hidden": False,
        "state": "sync_pending",
        "text": "Waiting for the reader to finish saving",
    }
    assert payload["failed"] == {"hidden": False, "state": "sync_failed", "text": "Disk is full"}


def test_library_view_app_refreshes_selected_pdf_sync_status_from_scoped_endpoint() -> None:
    payload = _run_library_app_vm(
        r"""
  state.tab = "main";
  state.selected.main = "sync-paper";
  state.capabilities = {
    csrfToken: "csrf-token",
    nativePdfOpen: true,
    nativePdfReason: "",
    pdfDelivery: {
      mode: "native",
      target: "windows",
      label: "Open in default viewer",
      reason: "",
      sync: "automatic",
    },
  };
  renderDetail({
    paper_id: "sync-paper",
    title: "Sync paper",
    has_pdf: true,
    pdf_url: "/api/main/pdf?id=sync-paper",
    pdf_sync: { state: "in_sync", retryable: false, message: "" },
    issues: [],
    toc: [],
  });
  await refreshPdfSyncStatus();
  const afterRefresh = {
    hidden: els.pdfSyncStatus.hidden,
    state: els.pdfSyncStatus.dataset.state,
    text: els.pdfSyncStatus.textContent,
  };
  state.selected.main = "different-paper";
  await refreshPdfSyncStatus();
  return { requests: __syncRequests, afterRefresh };
""",
        fetch_setup=r"""
context.__syncRequests = [];
const originalFetch = context.fetch;
context.fetch = async (url, options = {}) => {
  const target = String(url);
  if (target.includes("/pdf-sync")) {
    context.__syncRequests.push(target);
    return { ok: true, json: async () => ({
      state: "sync_pending",
      retryable: true,
      last_success_at: "",
      message: "Waiting for a stable PDF save",
    }) };
  }
  return originalFetch(url, options);
};
""",
    )

    assert payload["requests"] == ["/api/main/pdf-sync?id=sync-paper"]
    assert payload["afterRefresh"] == {
        "hidden": False,
        "state": "sync_pending",
        "text": "Waiting for a stable PDF save",
    }


def test_library_view_app_starts_sync_polling_when_capabilities_arrive_after_detail() -> None:
    payload = _run_library_app_vm(
        r"""
  state.tab = "main";
  state.selected.main = "late-capability-paper";
  renderDetail({
    paper_id: "late-capability-paper",
    title: "Late capability paper",
    has_pdf: true,
    pdf_url: "/api/main/pdf?id=late-capability-paper",
    pdf_sync: { state: "in_sync", retryable: false, message: "" },
    issues: [],
    toc: [],
  });
  const before = state.pdfSyncTimer;
  __resolveCapabilities({
    csrf_token: "csrf-token",
    native_pdf_open: { enabled: true, reason: "" },
    pdf_delivery: {
      mode: "native",
      target: "windows",
      label: "Open in default viewer",
      reason: "",
      sync: "automatic",
    },
  });
  await new Promise((resolve) => setTimeout(resolve, 0));
  return {
    before,
    after: state.pdfSyncTimer,
    sync: state.capabilities.pdfDelivery.sync,
    target: state.capabilities.pdfDelivery.target,
  };
""",
        fetch_setup=r"""
context.__capabilities = new Promise((resolve) => { context.__resolveCapabilities = resolve; });
context.fetch = async (url) => {
  const target = String(url);
  if (target.includes("/api/capabilities")) {
    return { ok: true, json: async () => context.__capabilities };
  }
  if (target.includes("/detail")) return { ok: true, json: async () => ({}) };
  return { ok: true, json: async () => ({ papers: [], total: 0, issue_totals: {} }) };
};
""",
    )

    assert payload == {"before": None, "after": 1, "sync": "automatic", "target": "windows"}


def test_library_view_app_falls_back_to_client_download_when_native_open_fails() -> None:
    payload = _run_library_app_vm(
        r"""
  state.tab = "main";
  state.capabilities = {
    csrfToken: "csrf-token",
    nativePdfOpen: true,
    nativePdfReason: "",
    pdfDelivery: { mode: "native", target: "windows", label: "Open in default viewer", reason: "" },
  };
  const detail = {
    paper_id: "fallback-paper",
    title: "Fallback paper",
    has_pdf: true,
    pdf_url: "/api/main/pdf?id=fallback-paper",
    issues: [],
    toc: [],
  };
  state.detail = detail;
  renderDetail(detail);
  await deliverSelectedPdf();
  return {
    downloadedHref: document.__clickedHref,
    message: els.toast.textContent,
    kind: els.toast.dataset.kind,
    busy: els.nativePdfButton.disabled,
    temporaryNodes: document.body.children.length,
  };
""",
        fetch_setup=r"""
context.fetch = async (url) => {
  const target = String(url);
  if (target.includes("/api/capabilities")) {
    return { ok: true, json: async () => ({
      csrf_token: "csrf-token",
      native_pdf_open: { enabled: true, reason: "" },
      pdf_delivery: { mode: "native", target: "windows", label: "Open in default viewer", reason: "" },
    }) };
  }
  if (target.includes("/open-pdf")) {
    return { ok: false, status: 500, statusText: "Failed", json: async () => ({ error: "Viewer failed" }) };
  }
  if (target.includes("/detail")) return { ok: true, json: async () => ({}) };
  return { ok: true, json: async () => ({ papers: [], total: 0, issue_totals: {} }) };
};
""",
    )

    assert payload["downloadedHref"] == "/api/main/pdf?id=fallback-paper&download=1"
    assert "downloaded" in payload["message"].lower()
    assert payload["kind"] == "warning"
    assert payload["busy"] is False
    assert payload["temporaryNodes"] == 0


def test_library_view_app_reports_clipboard_fallback_failure_without_leaking_textarea() -> None:
    payload = _run_library_app_vm(
        r"""
  state.tab = "main";
  state.selected.main = "action-paper";
  state.detail = { paper_id: "action-paper", title: "Action paper", has_pdf: false };
  renderDetail(state.detail);
  navigator.clipboard.writeText = async () => { throw new Error("denied"); };
  document.__execCopy = false;
  await copySelectedBibtex();
  return {
    message: els.toast.textContent,
    kind: els.toast.dataset.kind,
    temporaryNodes: document.body.children.length,
  };
""",
        fetch_setup=r"""
context.fetch = async (url) => {
  const target = String(url);
  if (target.includes("/api/capabilities")) {
    return { ok: true, json: async () => ({
      csrf_token: "csrf-token",
      native_pdf_open: { enabled: true, reason: "" },
    }) };
  }
  if (target.includes("/bibtex")) {
    return { ok: true, json: async () => ({ bibtex: "@article{Failure}" }) };
  }
  if (target.includes("/detail")) return { ok: true, json: async () => ({}) };
  return { ok: true, json: async () => ({ papers: [], total: 0, issue_totals: {} }) };
};
""",
    )

    assert "Could not copy BibTeX" in payload["message"]
    assert payload["kind"] == "error"
    assert payload["temporaryNodes"] == 0


def test_library_view_app_preserves_rows_for_unavailable_semantic_search() -> None:
    payload = _run_library_app_vm(
        r"""
  state.tab = "main";
  state.rows.main = [
    { paper_id: "paper-a", title: "Alpha", authors_text: "A", year: 2024, paper_type: "article" },
    { paper_id: "paper-b", title: "Beta", authors_text: "B", year: 2025, paper_type: "article" },
  ];
  state.ranked = { byId: new Map([["paper-a", { rank: 1, score: 1, match: "both" }]]) };
  state.sortKey = "relevance";
  state.sortDir = "asc";
  state.searchMode = "semantic";
  els.searchMode.value = "semantic";
  els.searchInput.value = "concept query";
  await runRankedSearch();
  return {
    visible: filteredRows().map((row) => row.paper_id),
    ranked: state.ranked,
    message: els.searchDiagnostics.textContent,
    kind: els.searchDiagnostics.dataset.kind,
  };
""",
        fetch_setup=r"""
context.fetch = async (url) => {
  const target = String(url);
  if (target.includes("/api/capabilities")) {
    return { ok: true, json: async () => ({
      csrf_token: "csrf-token",
      native_pdf_open: { enabled: true, reason: "" },
    }) };
  }
  if (target.includes("/api/main/search")) {
    return { ok: true, json: async () => ({
      mode: "semantic",
      query: "concept query",
      total: 0,
      results: [],
      diagnostics: {
        status: "unavailable",
        message: "Semantic search index or embedding provider is unavailable.",
        keyword: "not_used",
        semantic: "unavailable",
        actions: [{ command: "scholaraio embed", label: "Build semantic embeddings" }],
      },
    }) };
  }
  if (target.includes("/detail")) return { ok: true, json: async () => ({}) };
  return { ok: true, json: async () => ({ papers: [], total: 0, issue_totals: {} }) };
};
""",
    )

    assert payload["visible"] == ["paper-b", "paper-a"]
    assert payload["ranked"] is None
    assert payload["kind"] == "unavailable"
    assert "scholaraio embed" in payload["message"]


def test_library_view_app_reconciles_hidden_selection_after_metadata_filter() -> None:
    payload = _run_library_app_vm(
        r"""
  state.tab = "main";
  state.rows.main = [
    { paper_id: "paper-a", title: "Alpha", authors_text: "A", year: 2024, paper_type: "article" },
    { paper_id: "paper-b", title: "Beta", authors_text: "B", year: 2025, paper_type: "article" },
  ];
  state.selected.main = "paper-a";
  state.detail = { paper_id: "paper-a", title: "Alpha", issues: [], toc: [] };
  state.searchMode = "metadata";
  state.filters.title = "Beta";
  markRankedSearchDirty();
  await new Promise((resolve) => setTimeout(resolve, 0));
  return {
    selected: state.selected.main,
    detail: state.detail?.paper_id,
    visible: filteredRows().map((row) => row.paper_id),
  };
""",
        fetch_setup=r"""
context.fetch = async (url) => {
  const target = String(url);
  if (target.includes("/api/capabilities")) {
    return { ok: true, json: async () => ({
      csrf_token: "csrf-token",
      native_pdf_open: { enabled: true, reason: "" },
    }) };
  }
  if (target.includes("/api/main/detail") && target.includes("paper-b")) {
    return { ok: true, json: async () => ({ paper_id: "paper-b", title: "Beta", issues: [], toc: [] }) };
  }
  return { ok: true, json: async () => ({ papers: [], total: 0, issue_totals: {} }) };
};
""",
    )

    assert payload == {"selected": "paper-b", "detail": "paper-b", "visible": ["paper-b"]}


def test_library_view_app_keeps_record_action_busy_across_detail_refresh() -> None:
    payload = _run_library_app_vm(
        r"""
  state.tab = "main";
  const detail = {
    paper_id: "action-paper",
    title: "Action paper",
    has_pdf: true,
    pdf_url: "/api/main/pdf?id=action-paper",
    issues: [],
    toc: [],
  };
  state.detail = detail;
  renderDetail(detail);
  const copy = copySelectedBibtex();
  await Promise.resolve();
  renderDetail(detail);
  const duringRefresh = {
    disabled: els.copyBibtexButton.disabled,
    label: els.copyBibtexButton.textContent,
  };
  __resolveBibtex();
  await copy;
  return {
    duringRefresh,
    after: {
      disabled: els.copyBibtexButton.disabled,
      label: els.copyBibtexButton.textContent,
    },
  };
""",
        fetch_setup=r"""
context.__resolveBibtex = null;
context.fetch = async (url) => {
  const target = String(url);
  if (target.includes("/api/capabilities")) {
    return { ok: true, json: async () => ({
      csrf_token: "csrf-token",
      native_pdf_open: { enabled: true, reason: "" },
    }) };
  }
  if (target.includes("/bibtex")) {
    return new Promise((resolve) => {
      context.__resolveBibtex = () => resolve({
        ok: true,
        json: async () => ({ bibtex: "@article{Action}" }),
      });
    });
  }
  if (target.includes("/detail")) return { ok: true, json: async () => ({}) };
  return { ok: true, json: async () => ({ papers: [], total: 0, issue_totals: {} }) };
};
""",
    )

    assert payload["duringRefresh"] == {"disabled": True, "label": "Copying…"}
    assert payload["after"] == {"disabled": False, "label": "Copy BibTeX"}


def test_library_view_static_assets_live_inside_package() -> None:
    from scholaraio.interfaces.cli.gui import _static_dir

    static_dir = _static_dir()

    assert static_dir.is_dir()
    assert static_dir.parent == Path(__file__).resolve().parents[1] / "scholaraio" / "interfaces" / "cli"
    assert (static_dir / "index.html").is_file()
    assert (static_dir / "rendering.js").is_file()
    assert (static_dir / "app.js").is_file()
    assert (static_dir / "styles.css").is_file()
    assert (static_dir / "workflows.css").is_file()


def test_library_view_css_preserves_hidden_attribute_for_pdf_toolbar() -> None:
    from scholaraio.interfaces.cli.gui import _static_dir

    css = (_static_dir() / "styles.css").read_text(encoding="utf-8")

    assert "[hidden]" in css
    assert "display: none !important" in css


def test_library_view_css_covers_focus_reduced_motion_and_workflow_states() -> None:
    from scholaraio.interfaces.cli.gui import _static_dir

    css = (_static_dir() / "workflows.css").read_text(encoding="utf-8")

    assert ":focus-visible" in css
    assert "prefers-reduced-motion: reduce" in css
    assert '.search-diagnostics[data-kind="degraded"]' in css
    assert ".detail-actions" in css
    assert ".toast" in css
    assert ".clipboard-fallback" in css


def test_library_view_app_source_copy_fullscreen_and_compact_rows() -> None:
    from scholaraio.interfaces.cli.gui import _static_dir

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for app.js behavior regression")
    rendering_js = (_static_dir() / "rendering.js").as_posix()
    app_js = (_static_dir() / "app.js").as_posix()
    script = f"""
const fs = require("fs");
const vm = require("vm");

function element(id) {{
  const classes = new Set();
  return {{
    id,
    dataset: {{}},
    value: "",
    checked: false,
    disabled: false,
    hidden: false,
    textContent: "",
    className: "",
    children: [],
    classList: {{
      add(name) {{ classes.add(name); }},
      remove(name) {{ classes.delete(name); }},
      contains(name) {{ return classes.has(name); }},
      toggle(name, force) {{
        const enabled = force === undefined ? !classes.has(name) : Boolean(force);
        if (enabled) classes.add(name);
        else classes.delete(name);
        return enabled;
      }},
    }},
    appendChild(child) {{ this.children.push(child); return child; }},
    append(...items) {{ this.children.push(...items); }},
    removeAttribute(name) {{ delete this[name]; }},
    addEventListener() {{}},
  }};
}}

const elements = new Map();
const tabs = ["main", "proceedings"].map((tab) => {{
  const el = element(`tab-${{tab}}`);
  el.dataset.tab = tab;
  return el;
}});
const document = {{
  body: element("body"),
  getElementById(id) {{
    if (!elements.has(id)) elements.set(id, element(id));
    return elements.get(id);
  }},
  createElement(tag) {{
    return element(tag);
  }},
  querySelectorAll(selector) {{
    if (selector === ".tab") return tabs;
    return [];
  }},
  addEventListener() {{}},
}};
const context = {{
  URLSearchParams,
  document,
  navigator: {{ clipboard: {{ writeText: async (value) => {{ context.__copied = value; }} }} }},
  fetch: async () => ({{ ok: true, json: async () => ({{ papers: [], total: 0 }}) }}),
  setInterval: () => 1,
  clearInterval: () => {{}},
  console,
}};
const renderingCode = fs.readFileSync({json.dumps(rendering_js)}, "utf8");
const code = fs.readFileSync({json.dumps(app_js)}, "utf8");
vm.runInNewContext(`${{renderingCode}}\n${{code}}
(async () => {{
  state.payload.main = {{ root: "/tmp/scholaraio/data/libraries/papers", total: 1, issue_totals: {{}} }};
  renderMetrics();
  await copySourceRoot();
  openPdf({{ pdf_url: "/api/main/pdf?id=paper-1", title: "Paper title" }});
  setPdfFullscreen(true);
  const fullscreenOn = els.tablePanel.classList.contains("is-pdf-fullscreen");
  showRecords();
  const row = {{ paper_id: "paper-1", dir_name: "Doe-2026-Paper", title: "Paper title", has_md: true }};
  state.rows.main = [row];
  renderTable();
  globalThis.__result = {{
    copied: globalThis.__copied,
    sourceCopyLabel: els.sourceCopyButton.textContent,
    fullscreenOn,
    fullscreenAfterBack: els.tablePanel.classList.contains("is-pdf-fullscreen"),
    firstTitleChildren: els.tableBody.children[0].children[0].children[0].children.length,
    metadataLabels: (() => {{
      renderMetadata({{ paper_id: "paper-1", dir_name: "Doe-2026-Paper", title: "Paper title" }});
      return els.metadataGrid.children.filter((child, index) => index % 2 === 0).map((child) => child.textContent);
    }})(),
  }};
}})();
`, context);
setImmediate(() => console.log(JSON.stringify(context.__result)));
"""

    result = subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)

    payload = json.loads(result.stdout)
    assert payload["copied"] == "/tmp/scholaraio/data/libraries/papers"
    assert payload["sourceCopyLabel"] == "Copied"
    assert payload["fullscreenOn"] is True
    assert payload["fullscreenAfterBack"] is False
    assert payload["firstTitleChildren"] == 1
    assert "ID" not in payload["metadataLabels"]


def test_library_view_app_ignores_stale_refresh_and_detail_responses() -> None:
    from scholaraio.interfaces.cli.gui import _static_dir

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for app.js behavior regression")
    rendering_js = (_static_dir() / "rendering.js").as_posix()
    app_js = (_static_dir() / "app.js").as_posix()
    script = f"""
const fs = require("fs");
const vm = require("vm");

function element(id) {{
  const classes = new Set();
  return {{
    id,
    dataset: {{}},
    value: "",
    checked: false,
    disabled: false,
    hidden: false,
    textContent: "",
    title: "",
    className: "",
    children: [],
    classList: {{
      add(name) {{ classes.add(name); }},
      remove(name) {{ classes.delete(name); }},
      contains(name) {{ return classes.has(name); }},
      toggle(name, force) {{
        const enabled = force === undefined ? !classes.has(name) : Boolean(force);
        if (enabled) classes.add(name);
        else classes.delete(name);
        return enabled;
      }},
    }},
    appendChild(child) {{ this.children.push(child); return child; }},
    append(...items) {{ this.children.push(...items); }},
    removeAttribute(name) {{ delete this[name]; }},
    addEventListener() {{}},
  }};
}}

const elements = new Map();
const tabs = ["main", "proceedings"].map((tab) => {{
  const el = element(`tab-${{tab}}`);
  el.dataset.tab = tab;
  return el;
}});
const document = {{
  body: element("body"),
  getElementById(id) {{
    if (!elements.has(id)) elements.set(id, element(id));
    return elements.get(id);
  }},
  createElement(tag) {{
    return element(tag);
  }},
  querySelectorAll(selector) {{
    if (selector === ".tab") return tabs;
    return [];
  }},
  addEventListener() {{}},
}};
const pending = [];
const context = {{
  URLSearchParams,
  document,
  pending,
  navigator: {{ clipboard: {{ writeText: async () => {{}} }} }},
  controlled: false,
  fetch: async (url) => {{
    if (!context.controlled) return {{ ok: true, json: async () => ({{ papers: [], total: 0, issue_totals: {{}} }}) }};
    return new Promise((resolve) => pending.push({{ url, resolve }}));
  }},
  setTimeout,
  setInterval: () => 1,
  clearInterval: () => {{}},
  console,
}};
const renderingCode = fs.readFileSync({json.dumps(rendering_js)}, "utf8");
const code = fs.readFileSync({json.dumps(app_js)}, "utf8");
vm.runInNewContext(`${{renderingCode}}\n${{code}}
globalThis.__ready = (async () => {{
  controlled = true;
  state.tab = "main";
  state.rows = {{ main: [], proceedings: [] }};
  state.payload = {{ main: null, proceedings: null }};
  const staleRefresh = refreshActive({{ keepSelection: false }});
  state.tab = "proceedings";
  pending.shift().resolve({{ ok: true, json: async () => ({{
    root: "/main",
    total: 1,
    issue_totals: {{}},
    papers: [{{ paper_id: "main-paper", title: "Main paper", has_md: true }}],
  }}) }});
  await new Promise((resolve) => setTimeout(resolve, 0));
  if (pending.length) pending.shift().resolve({{ ok: true, json: async () => ({{ paper_id: "main-paper", title: "Wrong detail" }}) }});
  await staleRefresh;
  const refreshMainRows = state.rows.main.map((row) => row.paper_id);
  const refreshProceedingsRows = state.rows.proceedings.map((row) => row.paper_id);

  state.tab = "main";
  state.rows.main = [
    {{ paper_id: "first", title: "First", has_md: true }},
    {{ paper_id: "second", title: "Second", has_md: true }},
  ];
  state.selected.main = "";
  state.detail = null;
  const staleDetail = selectRow("first");
  await new Promise((resolve) => setTimeout(resolve, 0));
  state.selected.main = "second";
  pending.shift().resolve({{ ok: true, json: async () => ({{ paper_id: "first", title: "First detail" }}) }});
  await staleDetail;

  return {{
    refreshMainRows,
    refreshProceedingsRows,
    activeTab: state.tab,
    selected: state.selected.main,
    detailTitle: els.detailTitle.textContent,
    detail: state.detail,
  }};
}})();
`, context);
context.__ready.then((payload) => console.log(JSON.stringify(payload))).catch((err) => {{
  console.error(err);
  process.exit(1);
}});
"""

    result = subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)

    payload = json.loads(result.stdout)
    assert payload["refreshMainRows"] == ["main-paper"]
    assert payload["refreshProceedingsRows"] == []
    assert payload["activeTab"] == "main"
    assert payload["selected"] == "second"
    assert payload["detailTitle"] != "First detail"
    assert payload["detail"] is None


def test_library_view_app_detail_failure_fallback_has_no_commands() -> None:
    from scholaraio.interfaces.cli.gui import _static_dir

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for app.js behavior regression")
    rendering_js = (_static_dir() / "rendering.js").as_posix()
    app_js = (_static_dir() / "app.js").as_posix()
    script = f"""
const fs = require("fs");
const vm = require("vm");

function element(id) {{
  const classes = new Set();
  return {{
    id,
    dataset: {{}},
    value: "",
    checked: false,
    disabled: false,
    hidden: false,
    textContent: "",
    innerHTML: "",
    className: "",
    children: [],
    classList: {{
      add(name) {{ classes.add(name); }},
      remove(name) {{ classes.delete(name); }},
      contains(name) {{ return classes.has(name); }},
      toggle(name, force) {{
        const enabled = force === undefined ? !classes.has(name) : Boolean(force);
        if (enabled) classes.add(name);
        else classes.delete(name);
        return enabled;
      }},
    }},
    appendChild(child) {{ this.children.push(child); return child; }},
    append(...items) {{ this.children.push(...items); }},
    removeAttribute(name) {{ delete this[name]; }},
    addEventListener() {{}},
  }};
}}

const elements = new Map();
const tabs = ["main", "proceedings"].map((tab) => {{
  const el = element(`tab-${{tab}}`);
  el.dataset.tab = tab;
  return el;
}});
const document = {{
  body: element("body"),
  getElementById(id) {{
    if (!elements.has(id)) elements.set(id, element(id));
    return elements.get(id);
  }},
  createElement(tag) {{
    return element(tag);
  }},
  querySelectorAll(selector) {{
    if (selector === ".tab") return tabs;
    return [];
  }},
  addEventListener() {{}},
}};
const context = {{
  URLSearchParams,
  document,
  navigator: {{ clipboard: {{ writeText: async () => {{}} }} }},
  fetch: async () => ({{ ok: false, status: 500, statusText: "Boom" }}),
  setTimeout,
  setInterval: () => 1,
  clearInterval: () => {{}},
  console,
}};
const renderingCode = fs.readFileSync({json.dumps(rendering_js)}, "utf8");
const code = fs.readFileSync({json.dumps(app_js)}, "utf8");
vm.runInNewContext(`${{renderingCode}}\n${{code}}
globalThis.__ready = (async () => {{
  renderDetail = (detail) => {{ globalThis.__captured = detail; }};
  state.tab = "main";
  state.rows.main = [{{ paper_id: "broken", title: "Broken", has_md: true }}];
  await selectRow("broken");
  return globalThis.__captured;
}})();
`, context);
context.__ready.then((payload) => console.log(JSON.stringify(payload))).catch((err) => {{
  console.error(err);
  process.exit(1);
}});
"""

    result = subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)

    payload = json.loads(result.stdout)
    assert payload["title"] == "Detail unavailable"
    assert "commands" not in payload


def test_library_view_app_missing_markdown_status_is_not_clean() -> None:
    from scholaraio.interfaces.cli.gui import _static_dir

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for app.js behavior regression")
    rendering_js = (_static_dir() / "rendering.js").as_posix()
    app_js = (_static_dir() / "app.js").as_posix()
    script = f"""
const fs = require("fs");
const vm = require("vm");

function element(id) {{
  return {{
    id,
    dataset: {{}},
    value: "",
    checked: false,
    hidden: false,
    textContent: "",
    className: "",
    classList: {{ toggle() {{}}, add() {{}}, remove() {{}} }},
    appendChild() {{}},
    append() {{}},
    removeAttribute() {{}},
    addEventListener() {{}},
  }};
}}
const elements = new Map();
const document = {{
  getElementById(id) {{
    if (!elements.has(id)) elements.set(id, element(id));
    return elements.get(id);
  }},
  createElement(tag) {{
    return element(tag);
  }},
  querySelectorAll() {{
    return [];
  }},
  addEventListener() {{}},
}};
const context = {{
  URLSearchParams,
  document,
  navigator: {{ clipboard: {{ writeText: async () => {{}} }} }},
  fetch: async () => ({{ ok: true, json: async () => ({{ papers: [], total: 0, issue_totals: {{}} }}) }}),
  setInterval: () => 1,
  clearInterval: () => {{}},
  console,
}};
const renderingCode = fs.readFileSync({json.dumps(rendering_js)}, "utf8");
const code = fs.readFileSync({json.dumps(app_js)}, "utf8");
vm.runInNewContext(`${{renderingCode}}\n${{code}}
globalThis.__result = statusPills({{ has_md: false, issue_counts: {{}} }}).map((pill) => pill[0]);
`, context);
console.log(JSON.stringify(context.__result));
"""

    result = subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)

    assert json.loads(result.stdout) == ["No MD"]


def test_library_view_app_renders_markdown_and_math_in_detail_text() -> None:
    from scholaraio.interfaces.cli.gui import _static_dir

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for app.js behavior regression")
    rendering_js = (_static_dir() / "rendering.js").as_posix()
    app_js = (_static_dir() / "app.js").as_posix()
    abstract = json.dumps("Flow **energy** is $E_i = mc^2$. <script>alert(1)</script>")
    conclusion = json.dumps(r"Conclusion with $$\alpha + \beta$$.")
    script = f"""
const fs = require("fs");
const vm = require("vm");

function element(id) {{
  return {{
    id,
    dataset: {{}},
    value: "",
    checked: false,
    hidden: false,
    textContent: "",
    innerHTML: "",
    className: "",
    classList: {{ toggle() {{}}, add() {{}}, remove() {{}} }},
    children: [],
    appendChild(child) {{ this.children.push(child); return child; }},
    append(...items) {{ this.children.push(...items); }},
    removeAttribute() {{}},
    addEventListener() {{}},
  }};
}}
const elements = new Map();
const document = {{
  getElementById(id) {{
    if (!elements.has(id)) elements.set(id, element(id));
    return elements.get(id);
  }},
  createElement(tag) {{
    return element(tag);
  }},
  querySelectorAll() {{
    return [];
  }},
  addEventListener() {{}},
}};
const context = {{
  URLSearchParams,
  document,
  __abstract: {abstract},
  __conclusion: {conclusion},
  navigator: {{ clipboard: {{ writeText: async () => {{}} }} }},
  fetch: async () => ({{ ok: true, json: async () => ({{ papers: [], total: 0, issue_totals: {{}} }}) }}),
  setInterval: () => 1,
  clearInterval: () => {{}},
  console,
}};
const renderingCode = fs.readFileSync({json.dumps(rendering_js)}, "utf8");
const code = fs.readFileSync({json.dumps(app_js)}, "utf8");
vm.runInNewContext(`${{renderingCode}}\n${{code}}
renderDetail({{
  title: "Formula paper",
  abstract: globalThis.__abstract,
  l3_conclusion: globalThis.__conclusion
}});
globalThis.__result = {{
  abstractHtml: els.detailAbstract.innerHTML,
  conclusionHtml: els.detailConclusion.innerHTML,
}};
`, context);
setImmediate(() => console.log(JSON.stringify(context.__result)));
"""

    result = subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)

    payload = json.loads(result.stdout)
    assert "<strong>energy</strong>" in payload["abstractHtml"]
    assert '<span class="math math-inline"' in payload["abstractHtml"]
    assert "E<sub>i</sub> = mc<sup>2</sup>" in payload["abstractHtml"]
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in payload["abstractHtml"]
    assert '<span class="math math-display"' in payload["conclusionHtml"]
    assert "α + β" in payload["conclusionHtml"]


def test_library_view_app_treats_single_newlines_as_soft_breaks_in_detail_text() -> None:
    from scholaraio.interfaces.cli.gui import _static_dir

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for app.js behavior regression")
    rendering_js = (_static_dir() / "rendering.js").as_posix()
    app_js = (_static_dir() / "app.js").as_posix()
    abstract = json.dumps("We estimate\n$E_i = mc^2$\nfrom extracted features.")
    script = f"""
const fs = require("fs");
const vm = require("vm");

function element(id) {{
  return {{
    id,
    dataset: {{}},
    value: "",
    checked: false,
    hidden: false,
    textContent: "",
    innerHTML: "",
    className: "",
    classList: {{ toggle() {{}}, add() {{}}, remove() {{}} }},
    children: [],
    appendChild(child) {{ this.children.push(child); return child; }},
    append(...items) {{ this.children.push(...items); }},
    removeAttribute() {{}},
    addEventListener() {{}},
  }};
}}
const elements = new Map();
const document = {{
  getElementById(id) {{
    if (!elements.has(id)) elements.set(id, element(id));
    return elements.get(id);
  }},
  createElement(tag) {{
    return element(tag);
  }},
  querySelectorAll() {{
    return [];
  }},
  addEventListener() {{}},
}};
const context = {{
  URLSearchParams,
  document,
  __abstract: {abstract},
  navigator: {{ clipboard: {{ writeText: async () => {{}} }} }},
  fetch: async () => ({{ ok: true, json: async () => ({{ papers: [], total: 0, issue_totals: {{}} }}) }}),
  setInterval: () => 1,
  clearInterval: () => {{}},
  console,
}};
const renderingCode = fs.readFileSync({json.dumps(rendering_js)}, "utf8");
const code = fs.readFileSync({json.dumps(app_js)}, "utf8");
vm.runInNewContext(`${{renderingCode}}\n${{code}}
renderDetail({{
  title: "Wrapped formula paper",
  abstract: globalThis.__abstract,
  l3_conclusion: ""
}});
globalThis.__result = els.detailAbstract.innerHTML;
`, context);
console.log(JSON.stringify(context.__result));
"""

    result = subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)

    html = json.loads(result.stdout)
    assert "<br>" not in html
    assert "We estimate " in html
    assert '<span class="math math-inline"' in html
    assert "E<sub>i</sub> = mc<sup>2</sup>" in html
    assert " from extracted features." in html


def test_library_view_css_only_scrolls_display_math() -> None:
    from scholaraio.interfaces.cli.gui import _static_dir

    css = (_static_dir() / "styles.css").read_text(encoding="utf-8")

    assert ".math-display" in css
    assert "overflow-x: auto" in css
    assert ".math-inline {\n  display: inline;" in css
    assert "mjx-container" not in css


def test_library_view_tab_switch_resets_stale_type_filter() -> None:
    from scholaraio.interfaces.cli.gui import _static_dir

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for app.js behavior regression")
    rendering_js = (_static_dir() / "rendering.js").as_posix()
    app_js = (_static_dir() / "app.js").as_posix()
    script = f"""
const fs = require("fs");
const vm = require("vm");

function element(id) {{
  return {{
    id,
    dataset: {{}},
    value: "",
    checked: false,
    hidden: false,
    textContent: "",
    className: "",
    classList: {{ toggle() {{}} }},
    appendChild() {{}},
    append() {{}},
    removeAttribute() {{}},
    addEventListener() {{}},
  }};
}}

const elements = new Map();
const tabs = ["main", "proceedings"].map((tab) => {{
  const el = element(`tab-${{tab}}`);
  el.dataset.tab = tab;
  return el;
}});
const document = {{
  getElementById(id) {{
    if (!elements.has(id)) elements.set(id, element(id));
    return elements.get(id);
  }},
  createElement(tag) {{
    return element(tag);
  }},
  querySelectorAll(selector) {{
    if (selector === ".tab") return tabs;
    return [];
  }},
  addEventListener() {{}},
}};
const context = {{
  URLSearchParams,
  document,
  fetch: async () => ({{ ok: true, json: async () => ({{ papers: [], total: 0 }}) }}),
  setInterval: () => 1,
  clearInterval: () => {{}},
  console,
}};
const renderingCode = fs.readFileSync({json.dumps(rendering_js)}, "utf8");
const code = fs.readFileSync({json.dumps(app_js)}, "utf8");
vm.runInNewContext(`${{renderingCode}}\n${{code}}
state.filters.type = "journal-article";
els.typeFilter.value = "journal-article";
switchTab("proceedings");
globalThis.__result = {{ type: state.filters.type, select: els.typeFilter.value }};
`, context);
console.log(JSON.stringify(context.__result));
"""

    result = subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)

    assert json.loads(result.stdout) == {"type": "", "select": ""}


def test_library_view_capabilities_are_per_server_and_loopback_aware(tmp_path):
    from scholaraio.services.system_open import DefaultApplicationOpenCapability

    cfg = _build_config({}, tmp_path)

    def service_factory(*_args, **_kwargs):
        return SimpleNamespace(stop=Mock())

    with (
        patch(
            "scholaraio.services.system_open.default_application_open_capability",
            return_value=DefaultApplicationOpenCapability(True, "windows"),
        ),
        patch("scholaraio.services.pdf_edit_mirror.PdfEditMirrorService.for_wsl", side_effect=service_factory),
    ):
        with _running_library_server(cfg, native_target=None) as (_server, base_url):
            payload, _headers = _json_response(f"{base_url}/api/capabilities")
        with _running_library_server(cfg, native_target=None) as (_server, second_base_url):
            second, _headers = _json_response(f"{second_base_url}/api/capabilities")
        with _running_library_server(cfg, host="0.0.0.0", native_target=None) as (_server, wildcard_base_url):
            wildcard, _headers = _json_response(f"{wildcard_base_url}/api/capabilities")

    assert payload["csrf_token"]
    assert payload["csrf_token"] != second["csrf_token"]
    assert payload["native_pdf_open"] == {"enabled": True, "reason": ""}
    assert payload["pdf_delivery"] == {
        "mode": "native",
        "target": "windows",
        "label": "Open in default viewer",
        "reason": "",
        "sync": "automatic",
    }
    assert payload["search_modes"] == {
        "main": ["metadata", "keyword", "semantic", "unified"],
        "proceedings": ["metadata"],
    }

    assert wildcard["native_pdf_open"]["enabled"] is False
    assert "loopback" in wildcard["native_pdf_open"]["reason"].lower()
    assert wildcard["pdf_delivery"] == {
        "mode": "download",
        "target": "client",
        "label": "Download PDF",
        "reason": wildcard["native_pdf_open"]["reason"],
    }


def test_library_view_wsl_mirror_initialization_failure_falls_back_without_exposing_paths(tmp_path):
    import sqlite3

    from scholaraio.services.system_open import DefaultApplicationOpenCapability

    cfg = _build_config({}, tmp_path)
    with (
        patch(
            "scholaraio.services.system_open.default_application_open_capability",
            return_value=DefaultApplicationOpenCapability(True, "windows"),
        ),
        patch(
            "scholaraio.services.pdf_edit_mirror.PdfEditMirrorService.for_wsl",
            side_effect=sqlite3.OperationalError("cannot open /secret/sync.db"),
        ),
        patch("scholaraio.interfaces.cli.gui._ui"),
        _running_library_server(cfg, native_target=None) as (_server, base_url),
    ):
        payload, _headers = _json_response(f"{base_url}/api/capabilities")

    assert payload["native_pdf_open"] == {
        "enabled": False,
        "reason": "WSL PDF edit mirror could not be initialized.",
    }
    assert payload["pdf_delivery"]["mode"] == "download"
    assert "/secret" not in repr(payload)


def test_library_view_capabilities_download_when_host_launcher_is_unavailable(tmp_path):
    from scholaraio.services.system_open import DefaultApplicationOpenCapability

    cfg = _build_config({}, tmp_path)
    reason = "Required desktop launcher `xdg-open` was not found"
    with (
        patch(
            "scholaraio.services.system_open.default_application_open_capability",
            return_value=DefaultApplicationOpenCapability(False, None, reason),
        ),
        _running_library_server(cfg, native_target=None) as (_server, base_url),
    ):
        payload, _headers = _json_response(f"{base_url}/api/capabilities")

    assert payload["native_pdf_open"] == {"enabled": False, "reason": reason}
    assert payload["pdf_delivery"] == {
        "mode": "download",
        "target": "client",
        "label": "Download PDF",
        "reason": reason,
    }


def test_library_view_bibtex_endpoints_use_canonical_metadata(tmp_path):
    cfg, _main_dir, _child_dir = _write_gui_action_fixtures(tmp_path)

    with _running_library_server(cfg) as (_server, base_url):
        main, _headers = _json_response(f"{base_url}/api/main/bibtex?id=action-paper")
        proceedings, _headers = _json_response(f"{base_url}/api/proceedings/bibtex?id=proceeding-action-paper")

    assert main["paper_id"] == "action-paper"
    assert main["bibtex"].startswith("@article{")
    assert "author = {Jane Doe}" in main["bibtex"]
    assert "abstract = {{Canonical abstract.}}" in main["bibtex"]
    assert proceedings["paper_id"] == "proceeding-action-paper"
    assert proceedings["bibtex"].startswith("@inproceedings{")
    assert "booktitle = {Proceedings of Actions}" in proceedings["bibtex"]


def test_library_view_ranked_search_endpoint_parses_structured_filters(tmp_path, monkeypatch):
    cfg, _main_dir, _child_dir = _write_gui_action_fixtures(tmp_path)
    captured: dict[str, object] = {}

    def fake_search(cfg_arg, *, query, mode, filters, limit):
        captured.update(cfg=cfg_arg, query=query, mode=mode, filters=filters, limit=limit)
        return {
            "mode": mode,
            "query": query,
            "total": 1,
            "results": [
                {
                    "paper_id": "action-paper",
                    "rank": 1,
                    "score": 0.03,
                    "match": "both",
                }
            ],
            "diagnostics": {
                "status": "ok",
                "message": "Both legs active.",
                "keyword": "available",
                "semantic": "available",
                "actions": [],
            },
        }

    monkeypatch.setattr("scholaraio.services.library_search.search_main_library", fake_search)
    query = urlencode(
        {
            "mode": "unified",
            "q": "reacting flow",
            "title": "Action",
            "author": "Doe",
            "year_from": "2020",
            "year_to": "2026",
            "journal": "Actions",
            "paper_type": "journal-article",
            "doi": "10.1000/action",
            "limit": "75",
        }
    )

    with _running_library_server(cfg) as (_server, base_url):
        payload, _headers = _json_response(f"{base_url}/api/main/search?{query}")

    assert payload["results"][0]["paper_id"] == "action-paper"
    assert captured["cfg"] is cfg
    assert captured["query"] == "reacting flow"
    assert captured["mode"] == "unified"
    assert captured["limit"] == 75
    filters = captured["filters"]
    assert filters.title == "Action"
    assert filters.author == "Doe"
    assert filters.year_from == 2020
    assert filters.year_to == 2026
    assert filters.journal == "Actions"
    assert filters.paper_type == "journal-article"
    assert filters.doi == "10.1000/action"


@pytest.mark.parametrize(
    ("query", "code"),
    [
        ({"mode": "metadata", "q": "test"}, "invalid_search_mode"),
        ({"mode": "keyword", "q": "test", "year_from": "not-a-year"}, "invalid_year"),
        ({"mode": "keyword", "q": "test", "limit": "many"}, "invalid_search_limit"),
    ],
)
def test_library_view_ranked_search_rejects_invalid_requests(tmp_path, query, code):
    cfg = _build_config({}, tmp_path)

    with _running_library_server(cfg) as (_server, base_url):
        with pytest.raises(HTTPError) as caught:
            urlopen(f"{base_url}/api/main/search?{urlencode(query)}", timeout=3)
        payload = json.loads(caught.value.read().decode("utf-8"))

    assert caught.value.code == HTTPStatus.BAD_REQUEST
    assert payload["code"] == code


def test_library_view_responses_include_browser_security_headers(tmp_path):
    cfg = _build_config({}, tmp_path)
    required = {
        "Content-Security-Policy": "default-src 'self'",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "X-Frame-Options": "DENY",
    }

    with _running_library_server(cfg) as (_server, base_url):
        for path in ("/", "/api/health"):
            with urlopen(f"{base_url}{path}", timeout=3) as response:
                response.read()
                for name, expected in required.items():
                    assert expected in response.headers[name]
            assert "Access-Control-Allow-Origin" not in response.headers


def test_library_view_native_open_uses_canonical_pdf_path(tmp_path):
    cfg, main_dir, _child_dir = _write_gui_action_fixtures(tmp_path)

    with (
        patch("scholaraio.services.system_open.open_with_default_application") as open_default,
        _running_library_server(cfg) as (_server, base_url),
    ):
        capabilities, _headers = _json_response(f"{base_url}/api/capabilities")
        request = _post_json(
            f"{base_url}/api/main/open-pdf",
            {"id": "action-paper"},
            token=capabilities["csrf_token"],
            origin=base_url,
        )
        with urlopen(request, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))

    assert payload == {"status": "opened", "paper_id": "action-paper"}
    open_default.assert_called_once_with((main_dir / "Doe-2026-Action.pdf").resolve())


def test_library_view_native_open_supports_proceedings_child_pdf(tmp_path):
    cfg, _main_dir, child_dir = _write_gui_action_fixtures(tmp_path)

    with (
        patch("scholaraio.services.system_open.open_with_default_application") as open_default,
        _running_library_server(cfg) as (_server, base_url),
    ):
        capabilities, _headers = _json_response(f"{base_url}/api/capabilities")
        request = _post_json(
            f"{base_url}/api/proceedings/open-pdf",
            {"id": "proceeding-action-paper"},
            token=capabilities["csrf_token"],
            origin=base_url,
        )
        with urlopen(request, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))

    assert payload == {"status": "opened", "paper_id": "proceeding-action-paper"}
    open_default.assert_called_once_with((child_dir / "Roe-2026-Proceeding.pdf").resolve())


def test_library_view_wsl_native_open_reuses_stable_edit_mirror_and_exposes_status(tmp_path):
    from scholaraio.services.pdf_edit_mirror import PdfOpenPreparation
    from scholaraio.services.system_open import DefaultApplicationOpenCapability

    cfg, _main_dir, _child_dir = _write_gui_action_fixtures(tmp_path)
    mirror = tmp_path / "windows-local-app-data" / "ScholarAIO" / "editable-pdfs" / "main" / "sync" / "Action.pdf"
    mirror.parent.mkdir(parents=True)
    mirror.write_bytes(b"%PDF-mirror")
    sync_status = {
        "state": "in_sync",
        "retryable": False,
        "last_success_at": "2026-07-14T12:00:00+00:00",
        "message": "",
    }
    service = SimpleNamespace(
        prepare_for_open=lambda _target: PdfOpenPreparation(mirror, True, sync_status),
        status=lambda _source, _paper_id: dict(sync_status),
        stop=Mock(),
    )

    with (
        patch(
            "scholaraio.services.system_open.default_application_open_capability",
            return_value=DefaultApplicationOpenCapability(True, "windows"),
        ),
        patch("scholaraio.services.pdf_edit_mirror.PdfEditMirrorService.for_wsl", return_value=service),
        patch("scholaraio.services.system_open.open_wsl_windows_file") as open_windows,
        _running_library_server(cfg, native_target="windows") as (_server, base_url),
    ):
        capabilities, _headers = _json_response(f"{base_url}/api/capabilities")
        detail, _headers = _json_response(f"{base_url}/api/main/detail?id=action-paper")
        status, _headers = _json_response(f"{base_url}/api/main/pdf-sync?id=action-paper")
        for _index in range(2):
            request = _post_json(
                f"{base_url}/api/main/open-pdf",
                {"id": "action-paper"},
                token=capabilities["csrf_token"],
                origin=base_url,
            )
            with urlopen(request, timeout=3) as response:
                assert json.loads(response.read().decode("utf-8")) == {
                    "status": "opened",
                    "paper_id": "action-paper",
                }

    assert capabilities["pdf_delivery"]["target"] == "windows"
    assert capabilities["pdf_delivery"]["sync"] == "automatic"
    assert detail["pdf_sync"] == sync_status
    assert status == sync_status
    assert open_windows.call_args_list == [call(mirror), call(mirror)]
    service.stop.assert_called_once_with()


def test_library_view_wsl_refuses_unvalidated_mirror_so_client_can_download_canonical(tmp_path):
    from scholaraio.services.pdf_edit_mirror import PdfOpenPreparation
    from scholaraio.services.system_open import DefaultApplicationOpenCapability

    cfg, _main_dir, _child_dir = _write_gui_action_fixtures(tmp_path)
    mirror = tmp_path / "managed" / "unsafe.pdf"
    pending = {
        "state": "sync_pending",
        "retryable": True,
        "last_success_at": "",
        "message": "PDF candidate has no end-of-file marker",
    }
    service = SimpleNamespace(
        prepare_for_open=lambda _target: PdfOpenPreparation(mirror, False, pending),
        status=lambda _source, _paper_id: dict(pending),
        stop=Mock(),
    )

    with (
        patch(
            "scholaraio.services.system_open.default_application_open_capability",
            return_value=DefaultApplicationOpenCapability(True, "windows"),
        ),
        patch("scholaraio.services.pdf_edit_mirror.PdfEditMirrorService.for_wsl", return_value=service),
        patch("scholaraio.services.system_open.open_wsl_windows_file") as open_windows,
        _running_library_server(cfg, native_target="windows") as (_server, base_url),
    ):
        capabilities, _headers = _json_response(f"{base_url}/api/capabilities")
        request = _post_json(
            f"{base_url}/api/main/open-pdf",
            {"id": "action-paper"},
            token=capabilities["csrf_token"],
            origin=base_url,
        )
        with pytest.raises(HTTPError) as caught:
            urlopen(request, timeout=3)
        payload = json.loads(caught.value.read().decode("utf-8"))

    assert caught.value.code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert payload["code"] == "native_open_failed"
    assert "end-of-file" in payload["error"]
    open_windows.assert_not_called()


def test_library_view_pdf_sync_status_validates_paper_id_without_exposing_paths(tmp_path):
    cfg, _main_dir, _child_dir = _write_gui_action_fixtures(tmp_path)

    with _running_library_server(cfg) as (_server, base_url):
        status, _headers = _json_response(f"{base_url}/api/main/pdf-sync?id=action-paper")
        with pytest.raises(HTTPError) as caught:
            urlopen(f"{base_url}/api/main/pdf-sync?id=missing-paper", timeout=3)

    assert status == {
        "state": "not_opened",
        "retryable": False,
        "last_success_at": "",
        "message": "",
    }
    assert "/" not in repr(status)
    assert caught.value.code == HTTPStatus.NOT_FOUND


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE"])
def test_library_view_native_open_rejects_non_post_methods(tmp_path, method):
    cfg, _main_dir, _child_dir = _write_gui_action_fixtures(tmp_path)

    with _running_library_server(cfg) as (_server, base_url):
        request = Request(
            f"{base_url}/api/main/open-pdf",
            method=method,
            data=b"{}",
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(HTTPError) as caught:
            urlopen(request, timeout=3)

    assert caught.value.code == HTTPStatus.METHOD_NOT_ALLOWED


@pytest.mark.parametrize(
    ("path", "method", "allowed"),
    [
        ("/api/main/open-pdf", "GET", "POST"),
        ("/api/health", "OPTIONS", "GET, HEAD"),
    ],
)
def test_library_view_method_errors_keep_contract_and_security_headers(tmp_path, path, method, allowed):
    cfg, _main_dir, _child_dir = _write_gui_action_fixtures(tmp_path)

    with _running_library_server(cfg) as (_server, base_url):
        request = Request(f"{base_url}{path}", method=method)
        with pytest.raises(HTTPError) as caught:
            urlopen(request, timeout=3)

    assert caught.value.code == HTTPStatus.METHOD_NOT_ALLOWED
    assert caught.value.headers["Allow"] == allowed
    assert "default-src 'self'" in caught.value.headers["Content-Security-Policy"]
    assert caught.value.headers["X-Content-Type-Options"] == "nosniff"
    assert "Access-Control-Allow-Origin" not in caught.value.headers


def test_library_view_unknown_methods_still_receive_secure_json_errors(tmp_path):
    cfg = _build_config({}, tmp_path)

    with _running_library_server(cfg) as (_server, base_url):
        request = Request(f"{base_url}/api/health", method="PROPFIND")
        with pytest.raises(HTTPError) as caught:
            urlopen(request, timeout=3)
        payload = json.loads(caught.value.read().decode("utf-8"))

    assert caught.value.code == HTTPStatus.NOT_IMPLEMENTED
    assert payload["code"] == "http_error"
    assert "default-src 'self'" in caught.value.headers["Content-Security-Policy"]
    assert caught.value.headers["X-Content-Type-Options"] == "nosniff"


@pytest.mark.parametrize(
    ("token_kind", "origin_kind"),
    [
        ("missing", "valid"),
        ("wrong", "valid"),
        ("valid", "missing"),
        ("valid", "cross-origin"),
    ],
)
def test_library_view_native_open_rejects_csrf_and_cross_origin(
    tmp_path,
    token_kind,
    origin_kind,
):
    cfg, _main_dir, _child_dir = _write_gui_action_fixtures(tmp_path)

    with (
        patch("scholaraio.services.system_open.open_with_default_application") as open_default,
        _running_library_server(cfg) as (_server, base_url),
    ):
        capabilities, _headers = _json_response(f"{base_url}/api/capabilities")
        token = capabilities["csrf_token"] if token_kind == "valid" else ""
        if token_kind == "wrong":
            token = "wrong-token"
        origin = base_url if origin_kind == "valid" else ""
        if origin_kind == "cross-origin":
            origin = "https://attacker.example"
        request = _post_json(
            f"{base_url}/api/main/open-pdf",
            {"id": "action-paper"},
            token=token,
            origin=origin,
        )
        with pytest.raises(HTTPError) as caught:
            urlopen(request, timeout=3)
        payload = json.loads(caught.value.read().decode("utf-8"))

    assert caught.value.code == HTTPStatus.FORBIDDEN
    assert payload["code"] in {"csrf_rejected", "origin_rejected"}
    open_default.assert_not_called()


def test_library_view_native_open_is_disabled_for_non_loopback_bind(tmp_path):
    cfg, _main_dir, _child_dir = _write_gui_action_fixtures(tmp_path)

    with (
        patch("scholaraio.services.system_open.open_with_default_application") as open_default,
        _running_library_server(cfg, host="0.0.0.0") as (_server, base_url),
    ):
        capabilities, _headers = _json_response(f"{base_url}/api/capabilities")
        request = _post_json(
            f"{base_url}/api/main/open-pdf",
            {"id": "action-paper"},
            token=capabilities["csrf_token"],
            origin=base_url,
        )
        with pytest.raises(HTTPError) as caught:
            urlopen(request, timeout=3)
        payload = json.loads(caught.value.read().decode("utf-8"))

    assert caught.value.code == HTTPStatus.FORBIDDEN
    assert payload["code"] == "native_open_disabled"
    open_default.assert_not_called()


@pytest.mark.parametrize(
    ("payload", "content_type", "expected_status", "expected_code"),
    [
        (
            {"id": "action-paper", "path": "/etc/passwd"},
            "application/json",
            HTTPStatus.BAD_REQUEST,
            "invalid_request_body",
        ),
        (
            {"id": "action-paper"},
            "text/plain",
            HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
            "unsupported_media_type",
        ),
    ],
)
def test_library_view_native_open_validates_request_schema(
    tmp_path,
    payload,
    content_type,
    expected_status,
    expected_code,
):
    cfg, _main_dir, _child_dir = _write_gui_action_fixtures(tmp_path)

    with (
        patch("scholaraio.services.system_open.open_with_default_application") as open_default,
        _running_library_server(cfg) as (_server, base_url),
    ):
        capabilities, _headers = _json_response(f"{base_url}/api/capabilities")
        request = _post_json(
            f"{base_url}/api/main/open-pdf",
            payload,
            token=capabilities["csrf_token"],
            origin=base_url,
            content_type=content_type,
        )
        with pytest.raises(HTTPError) as caught:
            urlopen(request, timeout=3)
        response_payload = json.loads(caught.value.read().decode("utf-8"))

    assert caught.value.code == expected_status
    assert response_payload["code"] == expected_code
    open_default.assert_not_called()


def test_library_view_native_open_rejects_oversized_json(tmp_path):
    cfg, _main_dir, _child_dir = _write_gui_action_fixtures(tmp_path)

    with _running_library_server(cfg) as (_server, base_url):
        capabilities, _headers = _json_response(f"{base_url}/api/capabilities")
        request = Request(
            f"{base_url}/api/main/open-pdf",
            method="POST",
            data=b"{" + b"x" * (70 * 1024) + b"}",
            headers={
                "Content-Type": "application/json",
                "X-ScholarAIO-CSRF": capabilities["csrf_token"],
                "Origin": base_url,
            },
        )
        with pytest.raises(HTTPError) as caught:
            urlopen(request, timeout=3)
        payload = json.loads(caught.value.read().decode("utf-8"))

    assert caught.value.code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
    assert payload["code"] == "request_too_large"


@pytest.mark.parametrize(
    ("paper_id", "with_pdf", "expected_status", "expected_code"),
    [
        ("missing-paper", True, HTTPStatus.NOT_FOUND, "paper_not_found"),
        ("action-paper", False, HTTPStatus.NOT_FOUND, "pdf_not_found"),
    ],
)
def test_library_view_native_open_reports_missing_records_and_pdfs(
    tmp_path,
    paper_id,
    with_pdf,
    expected_status,
    expected_code,
):
    cfg, _main_dir, _child_dir = _write_gui_action_fixtures(tmp_path, main_pdf=with_pdf)

    with (
        patch("scholaraio.services.system_open.open_with_default_application") as open_default,
        _running_library_server(cfg) as (_server, base_url),
    ):
        capabilities, _headers = _json_response(f"{base_url}/api/capabilities")
        request = _post_json(
            f"{base_url}/api/main/open-pdf",
            {"id": paper_id},
            token=capabilities["csrf_token"],
            origin=base_url,
        )
        with pytest.raises(HTTPError) as caught:
            urlopen(request, timeout=3)
        payload = json.loads(caught.value.read().decode("utf-8"))

    assert caught.value.code == expected_status
    assert payload["code"] == expected_code
    open_default.assert_not_called()


def test_library_view_native_open_reports_controlled_launcher_failure(tmp_path):
    from scholaraio.services.system_open import DefaultApplicationOpenError

    cfg, _main_dir, _child_dir = _write_gui_action_fixtures(tmp_path)

    with (
        patch(
            "scholaraio.services.system_open.open_with_default_application",
            side_effect=DefaultApplicationOpenError("desktop unavailable"),
        ),
        _running_library_server(cfg) as (_server, base_url),
    ):
        capabilities, _headers = _json_response(f"{base_url}/api/capabilities")
        request = _post_json(
            f"{base_url}/api/main/open-pdf",
            {"id": "action-paper"},
            token=capabilities["csrf_token"],
            origin=base_url,
        )
        with pytest.raises(HTTPError) as caught:
            urlopen(request, timeout=3)
        payload = json.loads(caught.value.read().decode("utf-8"))

    assert caught.value.code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert payload["code"] == "native_open_failed"
    assert "desktop unavailable" in payload["error"]


def test_library_view_server_serves_main_pdf_inline(tmp_path):
    from scholaraio.interfaces.cli.gui import create_library_view_server

    cfg = _build_config({}, tmp_path)
    paper_dir = tmp_path / "data" / "libraries" / "papers" / "Doe-2026-PDF"
    paper_dir.mkdir(parents=True)
    (paper_dir / "meta.json").write_text(
        json.dumps({"id": "pdf-paper", "title": "PDF paper", "authors": ["Jane Doe"], "year": 2026}),
        encoding="utf-8",
    )
    (paper_dir / "Doe-2026-PDF.pdf").write_bytes(b"%PDF-inline")

    server = create_library_view_server(cfg, host="127.0.0.1", port=0)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(f"http://{host}:{port}/api/main/pdf?id=pdf-paper", timeout=3) as response:
            body = response.read()
            content_type = response.headers["Content-Type"]
            disposition = response.headers["Content-Disposition"]
        assert body == b"%PDF-inline"
        assert content_type == "application/pdf"
        assert "inline" in disposition
        assert "Doe-2026-PDF.pdf" in disposition
    finally:
        server.shutdown()
        server.server_close()


def test_library_view_server_downloads_main_pdf_as_attachment(tmp_path):
    from scholaraio.interfaces.cli.gui import create_library_view_server

    cfg = _build_config({}, tmp_path)
    paper_dir = tmp_path / "data" / "libraries" / "papers" / "Doe-2026-Download"
    paper_dir.mkdir(parents=True)
    (paper_dir / "meta.json").write_text(
        json.dumps({"id": "download-paper", "title": "Download paper", "authors": ["Jane Doe"], "year": 2026}),
        encoding="utf-8",
    )
    (paper_dir / "Doe-2026-Download.pdf").write_bytes(b"%PDF-download")

    server = create_library_view_server(cfg, host="127.0.0.1", port=0)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(f"http://{host}:{port}/api/main/pdf?id=download-paper&download=1", timeout=3) as response:
            body = response.read()
            headers = response.headers
    finally:
        server.shutdown()
        server.server_close()

    assert body == b"%PDF-download"
    assert headers["Content-Type"] == "application/pdf"
    assert headers["Content-Disposition"].startswith("attachment;")
    assert "Doe-2026-Download.pdf" in headers["Content-Disposition"]
    assert headers["X-Frame-Options"] == "SAMEORIGIN"


def test_library_view_inline_pdf_security_headers_allow_same_origin_frame(tmp_path):
    cfg, _main_dir, _child_dir = _write_gui_action_fixtures(tmp_path)

    with (
        _running_library_server(cfg) as (_server, base_url),
        urlopen(f"{base_url}/api/main/pdf?id=action-paper", timeout=3) as response,
    ):
        response.read()
        headers = response.headers

    assert headers["X-Frame-Options"] == "SAMEORIGIN"
    assert "frame-ancestors 'self'" in headers["Content-Security-Policy"]


def test_library_view_server_serves_non_ascii_pdf_filename(tmp_path):
    from scholaraio.interfaces.cli.gui import create_library_view_server

    cfg = _build_config({}, tmp_path)
    paper_dir = tmp_path / "data" / "libraries" / "papers" / "王-2026-中文论文"
    paper_dir.mkdir(parents=True)
    (paper_dir / "meta.json").write_text(
        json.dumps({"id": "cn-pdf", "title": "中文论文", "authors": ["王"], "year": 2026}, ensure_ascii=False),
        encoding="utf-8",
    )
    (paper_dir / "王-2026-中文论文.pdf").write_bytes(b"%PDF-cn")

    server = create_library_view_server(cfg, host="127.0.0.1", port=0)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(f"http://{host}:{port}/api/main/pdf?id=cn-pdf", timeout=3) as response:
            body = response.read()
            disposition = response.headers["Content-Disposition"]
        assert body == b"%PDF-cn"
        assert 'filename="paper.pdf"' in disposition
        assert "filename*=UTF-8''%E7%8E%8B-2026-%E4%B8%AD%E6%96%87%E8%AE%BA%E6%96%87.pdf" in disposition
    finally:
        server.shutdown()
        server.server_close()


def test_library_view_pdf_errors_do_not_send_ok_before_file_check():
    from scholaraio.interfaces.cli.gui import LibraryViewRequestHandler

    class MissingPdf:
        name = "missing.pdf"

        def stat(self):
            raise FileNotFoundError("missing")

        def open(self, _mode):
            raise AssertionError("open should not run after failed stat")

    class UnreadablePdf:
        name = "locked.pdf"

        def stat(self):
            return SimpleNamespace(st_size=1)

        def open(self, _mode):
            raise PermissionError("locked")

    for pdf_path, expected_status in [
        (MissingPdf(), HTTPStatus.NOT_FOUND),
        (UnreadablePdf(), HTTPStatus.INTERNAL_SERVER_ERROR),
    ]:
        handler = LibraryViewRequestHandler.__new__(LibraryViewRequestHandler)
        statuses: list[HTTPStatus] = []
        handler.command = "GET"
        handler.wfile = io.BytesIO()
        handler.send_response = statuses.append
        handler.send_header = lambda *_args, **_kwargs: None
        handler.end_headers = lambda: None

        def record_error(status, _message, headers=None, *, statuses=statuses):
            statuses.append(status)

        handler._send_error_json = record_error

        with suppress(FileNotFoundError, PermissionError):
            handler._send_pdf(pdf_path)  # type: ignore[arg-type]

        assert HTTPStatus.OK not in statuses
        assert statuses == [expected_status]


def test_pdf_content_disposition_uses_ascii_fallback_and_strips_line_breaks():
    from scholaraio.interfaces.cli.gui import _pdf_content_disposition

    disposition = _pdf_content_disposition('坏\r\nName".pdf')

    assert "\r" not in disposition
    assert "\n" not in disposition
    assert 'filename="paper.pdf"' in disposition
    assert "filename*=UTF-8''%E5%9D%8F__Name_.pdf" in disposition


def test_library_view_rejected_write_methods_close_connection():
    from scholaraio.interfaces.cli.gui import LibraryViewRequestHandler

    handler = LibraryViewRequestHandler.__new__(LibraryViewRequestHandler)
    captured: dict[str, object] = {}
    handler.close_connection = False
    handler.headers = {"Content-Length": "7"}
    handler.rfile = io.BytesIO(b"payload")
    handler._send_error_json = lambda status, message, headers=None: captured.update(
        {"status": status, "message": message, "headers": headers or {}}
    )

    handler.do_POST()

    assert handler.close_connection is True
    assert captured["status"] == HTTPStatus.METHOD_NOT_ALLOWED
    assert captured["headers"] == {"Allow": "GET, HEAD", "Connection": "close"}


def test_browser_url_uses_loopback_for_wildcard_bind_hosts():
    from scholaraio.interfaces.cli.gui import _browser_url

    assert _browser_url("0.0.0.0", 8765) == "http://127.0.0.1:8765"
    assert _browser_url("::", 8765) == "http://127.0.0.1:8765"
    assert _browser_url("", 8765) == "http://127.0.0.1:8765"
    assert _browser_url("127.0.0.1", 8765) == "http://127.0.0.1:8765"
    assert _browser_url("::1", 8765) == "http://[::1]:8765"


def test_library_view_server_head_pdf_does_not_read_body(tmp_path):
    from scholaraio.interfaces.cli.gui import create_library_view_server

    cfg = _build_config({}, tmp_path)
    paper_dir = tmp_path / "data" / "libraries" / "papers" / "Doe-2026-Head-PDF"
    paper_dir.mkdir(parents=True)
    (paper_dir / "meta.json").write_text(
        json.dumps({"id": "head-pdf", "title": "Head PDF", "authors": ["Jane Doe"], "year": 2026}),
        encoding="utf-8",
    )
    (paper_dir / "Doe-2026-Head-PDF.pdf").write_bytes(b"%PDF-head")

    server = create_library_view_server(cfg, host="127.0.0.1", port=0)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with patch.object(Path, "read_bytes", side_effect=AssertionError("PDF body should not be buffered")):
            request = Request(f"http://{host}:{port}/api/main/pdf?id=head-pdf", method="HEAD")
            with urlopen(request, timeout=3) as response:
                body = response.read()
                content_type = response.headers["Content-Type"]
                length = response.headers["Content-Length"]
        assert body == b""
        assert content_type == "application/pdf"
        assert length == str(len(b"%PDF-head"))
    finally:
        server.shutdown()
        server.server_close()


def test_cmd_gui_delegates_to_read_only_server(monkeypatch, tmp_path):
    from scholaraio.interfaces.cli.gui import cmd_gui

    seen = {}

    def fake_serve(cfg, *, host, port, open_browser):
        seen["cfg"] = cfg
        seen["host"] = host
        seen["port"] = port
        seen["open_browser"] = open_browser

    monkeypatch.setattr("scholaraio.interfaces.cli.gui.serve_library_view", fake_serve)
    cfg = _build_config({}, tmp_path)

    cmd_gui(SimpleNamespace(host="127.0.0.1", port=18888, no_open=True), cfg)

    assert seen == {"cfg": cfg, "host": "127.0.0.1", "port": 18888, "open_browser": False}


def test_pdf_range_head_and_conditional_delivery(tmp_path):
    cfg, _main_dir, _child_dir = _write_gui_action_fixtures(tmp_path)
    with _running_library_server(cfg) as (_server, base):
        url = base + "/api/main/pdf?id=action-paper"
        with urlopen(url) as response:
            full = response.read()
            etag = response.headers["ETag"]
        for requested, expected in [("bytes=0-4", full[:5]), ("bytes=5-", full[5:]), ("bytes=-3", full[-3:])]:
            with urlopen(Request(url, headers={"Range": requested})) as response:
                assert response.status == 206
                assert response.read() == expected
                assert response.headers["Accept-Ranges"] == "bytes"
                assert response.headers["Content-Range"].endswith(f"/{len(full)}")
        with urlopen(Request(url, method="HEAD", headers={"Range": "bytes=0-4"})) as response:
            assert response.status == 200
            assert int(response.headers["Content-Length"]) == len(full)
            assert response.read() == b""
        for requested in ("bytes=999999-", "bytes=-0", "bytes=8-2"):
            with pytest.raises(HTTPError) as exc:
                urlopen(Request(url, headers={"Range": requested}))
            assert exc.value.code == 416
            assert exc.value.headers["Content-Range"] == f"bytes */{len(full)}"
        with pytest.raises(HTTPError) as exc:
            urlopen(Request(url, headers={"If-None-Match": etag}))
        assert exc.value.code == 304
        assert exc.value.headers["X-Frame-Options"] == "SAMEORIGIN"
        with urlopen(Request(url, headers={"Range": "bytes=0-4", "If-Range": '"outdated"'})) as response:
            assert response.status == 200
            assert response.read() == full
        pdf = cfg.papers_dir / "Doe-2026-Action" / "Doe-2026-Action.pdf"
        pdf.write_bytes(full + b"changed")
        with urlopen(Request(url, headers={"If-None-Match": etag})) as response:
            assert response.status == 200
            assert response.headers["ETag"] != etag


def test_library_conditional_request_changes_after_metadata_edit(tmp_path):
    cfg, _main_dir, _child_dir = _write_gui_action_fixtures(tmp_path)
    from scholaraio.services.library_view import build_main_library_view
    from scholaraio.stores.papers import update_meta

    build_main_library_view(cfg)  # Complete the audit before comparing versions.
    with _running_library_server(cfg) as (_server, base):
        url = base + "/api/main/papers"
        _payload, headers = _json_response(url)
        with pytest.raises(HTTPError) as exc:
            urlopen(Request(url, headers={"If-None-Match": headers["ETag"]}))
        assert exc.value.code == 304
        update_meta(cfg.papers_dir / "Doe-2026-Action", title="Changed")
        with urlopen(Request(url, headers={"If-None-Match": headers["ETag"]})) as response:
            assert response.status == 200
            assert json.loads(response.read())["papers"][0]["title"] == "Changed"


def test_native_pdf_conflict_returns_409_without_launch(tmp_path):
    from scholaraio.services.pdf_edit_mirror import PdfOpenPreparation

    cfg, _main_dir, _child_dir = _write_gui_action_fixtures(tmp_path)
    conflict = {"state": "conflict", "retryable": False, "message": "Both PDFs changed"}
    service = SimpleNamespace(
        prepare_for_open=lambda _: PdfOpenPreparation(tmp_path / "mirror.pdf", False, conflict),
        status=lambda *_: conflict,
        stop=Mock(),
    )
    with (
        patch("scholaraio.services.pdf_edit_mirror.PdfEditMirrorService.for_wsl", return_value=service),
        patch("scholaraio.services.system_open.open_wsl_windows_file") as launch,
        _running_library_server(cfg, native_target="windows") as (_server, base),
    ):
        capabilities, _headers = _json_response(base + "/api/capabilities")
        with pytest.raises(HTTPError) as exc:
            urlopen(
                _post_json(
                    base + "/api/main/open-pdf", {"id": "action-paper"}, token=capabilities["csrf_token"], origin=base
                )
            )
        assert exc.value.code == 409
        assert json.loads(exc.value.read())["code"] == "pdf_sync_conflict"
        launch.assert_not_called()


def test_browser_does_not_download_a_pdf_after_sync_conflict():
    result = _run_library_app_vm(
        """
state.capabilities.nativePdfOpen = true;
state.capabilities.pdfDelivery = { mode: "native", target: "windows" };
state.detail = { paper_id: "paper", has_pdf: true, pdf_url: "/api/main/pdf?id=paper" };
fetch = async () => ({ ok: false, status: 409, json: async () => ({ error: "Both PDFs changed", code: "pdf_sync_conflict" }) });
await deliverSelectedPdf();
return { href: document.__clickedHref, message: els.toast.textContent, busy: state.actionBusy.nativePdf };
"""
    )
    assert result["href"] == ""
    assert "Both PDFs changed" in result["message"]
    assert result["busy"] is False


def test_browser_reuses_304_list_payload():
    result = _run_library_app_vm(
        """
let calls = 0;
let conditionalHeader = "";
fetch = async (_url, options) => {
  calls++;
  if (calls === 1) return { ok: true, status: 200, headers: { get: () => '"version"' }, json: async () => ({ papers: [{ paper_id: "a" }] }) };
  conditionalHeader = options.headers["If-None-Match"];
  return { ok: false, status: 304, json: async () => { throw new Error("304 has no body"); } };
};
const first = await fetchJson("/conditional-test", { conditional: true });
const second = await fetchJson("/conditional-test", { conditional: true });
return { identical: first === second, conditionalHeader };
"""
    )
    assert result == {"identical": True, "conditionalHeader": '"version"'}


def test_browser_does_not_duplicate_delivery_when_native_open_times_out():
    result = _run_library_app_vm(
        """
state.capabilities.nativePdfOpen = true;
state.capabilities.pdfDelivery = { mode: "native", target: "windows" };
state.detail = { paper_id: "paper", has_pdf: true, pdf_url: "/api/main/pdf?id=paper" };
fetch = async () => { const error = new Error("deadline"); error.name = "TimeoutError"; throw error; };
await deliverSelectedPdf();
return { href: document.__clickedHref, message: els.toast.textContent, busy: state.actionBusy.nativePdf };
"""
    )
    assert result["href"] == ""
    assert "Check the default viewer" in result["message"]
    assert result["busy"] is False


def test_paged_library_rejects_bad_queries_and_uses_stable_revision(tmp_path):
    cfg, _main, _child = _write_gui_action_fixtures(tmp_path)
    with _running_library_server(cfg) as (_server, base):
        page, headers = _json_response(base + "/api/main/papers?limit=1")
        assert page["total"] == 1 and page["matched"] == 1
        assert len(page["papers"]) == 1
        assert page["revision"]
        assert headers["ETag"]
        for query in ("limit=1000", "limit=1&sort=unsafe", "limit=1&ids=%7B%7D"):
            with pytest.raises(HTTPError) as error:
                urlopen(base + "/api/main/papers?" + query)
            assert error.value.code == 400


def test_pdf_recovery_requires_csrf_and_matching_versions(tmp_path):
    from tests.test_pdf_conflicts import conflict

    cfg = _build_config({"paths": {"papers_dir": str(tmp_path / "library")}}, tmp_path)
    store, paths, reconciler, record = conflict(tmp_path)
    (record.canonical_path.parent / "meta.json").write_text(json.dumps({"id": record.paper_id, "title": "Paper"}))
    service = SimpleNamespace(store=store, paths=paths, reconciler=reconciler)
    with _running_library_server(cfg) as (server, base):
        server.RequestHandlerClass.pdf_edit_mirror_service = service
        snapshot, _headers = _json_response(base + "/api/main/pdf-recovery?id=paper-id")
        body = {"id": "paper-id", "token": snapshot["token"], "version": "mirror", "readers_closed": True}
        with pytest.raises(HTTPError) as error:
            urlopen(_post_json(base + "/api/main/resolve-pdf", body, origin=base))
        assert error.value.code == 403
        token = server.RequestHandlerClass.csrf_token
        body["token"] = "stale"
        with pytest.raises(HTTPError) as error:
            urlopen(_post_json(base + "/api/main/resolve-pdf", body, origin=base, token=token))
        assert error.value.code == 409
        body["token"] = snapshot["token"]
        with urlopen(_post_json(base + "/api/main/resolve-pdf", body, origin=base, token=token)) as response:
            assert json.load(response)["status"]["state"] == "in_sync"
        assert record.canonical_path.read_bytes() == record.mirror_path.read_bytes()


def test_pdf_recovery_downloads_damaged_snapshot_without_preview(tmp_path):
    from urllib.parse import urlencode

    from tests.test_pdf_conflicts import conflict

    cfg = _build_config({"paths": {"papers_dir": str(tmp_path / "library")}}, tmp_path)
    store, paths, reconciler, record = conflict(tmp_path)
    (record.canonical_path.parent / "meta.json").write_text(json.dumps({"id": record.paper_id, "title": "Paper"}))
    damaged = b"partial viewer save"
    record.canonical_path.write_bytes(damaged)
    with _running_library_server(cfg) as (server, base):
        server.RequestHandlerClass.pdf_edit_mirror_service = SimpleNamespace(
            store=store, paths=paths, reconciler=reconciler
        )
        snapshot, _ = _json_response(base + "/api/main/pdf-recovery?id=paper-id")
        query = urlencode({"id": record.paper_id, "version": "canonical", "token": snapshot["token"]})
        endpoint = base + "/api/main/pdf-recovery?" + query
        with urlopen(endpoint + "&download=1") as response:
            assert response.read() == damaged
            assert "attachment" in response.headers["Content-Disposition"]
        with pytest.raises(HTTPError) as error:
            urlopen(endpoint)
        assert error.value.code == 400
        record.canonical_path.write_bytes(b"new save")
        with pytest.raises(HTTPError) as error:
            urlopen(endpoint + "&download=1")
        assert error.value.code == 409


def test_paged_proceedings_supports_conditional_response(tmp_path):
    cfg, _main, _child = _write_gui_action_fixtures(tmp_path)
    with _running_library_server(cfg) as (_server, base):
        url = base + "/api/proceedings/papers?limit=100"
        page, headers = _json_response(url)
        assert page["total"] == page["matched"] == 1
        assert len(page["papers"]) == 1
        with pytest.raises(HTTPError) as error:
            urlopen(Request(url, headers={"If-None-Match": headers["ETag"]}))
        assert error.value.code == 304


def test_recovery_inspection_cannot_reopen_after_switching_tabs():
    result = _run_library_app_vm(
        """
state.tab = "main";
state.selected.main = "paper";
document.getElementById("pdf-recovery-panel").hidden = true;
refreshActive = async () => {};
let complete;
fetch = () => new Promise(resolve => { complete = resolve; });
const pending = inspectPdfRecovery();
switchTab("proceedings");
switchTab("main");
complete({ ok: true, status: 200, json: async () => ({ token: "old", versions: [] }) });
await pending;
return { recovery: state.recovery, hidden: document.getElementById("pdf-recovery-panel").hidden };
"""
    )
    assert result == {"recovery": None, "hidden": True}


def test_recovered_scan_clears_its_error_without_erasing_search_diagnostics():
    result = _run_library_app_vm(
        """
state.tab = "main";
setSearchDiagnostics("degraded", "Semantic index needs updating");
state.payload.main = { refresh_error: "Library refresh failed" };
renderMetrics();
const error = document.getElementById("library-refresh-error");
const before = { message: error.textContent, hidden: error.hidden };
state.payload.main = { refresh_error: "" };
renderMetrics();
return { before, cleared: error.hidden && error.textContent === "", search: els.searchDiagnostics.textContent };
"""
    )
    assert result == {
        "before": {"message": "Library refresh failed", "hidden": False},
        "cleared": True,
        "search": "Semantic index needs updating",
    }


def test_editing_filters_reenables_search_while_old_request_is_pending():
    result = _run_library_app_vm(
        """
state.searchMode = "semantic";
els.searchMode.value = "semantic";
els.searchInput.value = "query";
let complete;
fetch = () => new Promise(resolve => { complete = resolve; });
const pending = runRankedSearch();
const wasBusy = state.searchBusy;
els.titleFilter.value = "changed";
syncFiltersFromControls();
markRankedSearchDirty();
const enabledBeforeCompletion = !state.searchBusy && !els.searchButton.disabled;
complete({ ok: true, status: 200, json: async () => ({ results: [], diagnostics: { message: "stale" } }) });
await pending;
return { wasBusy, enabledBeforeCompletion, enabledAfter: !state.searchBusy && !els.searchButton.disabled, label: els.searchButton.textContent, message: els.searchDiagnostics.textContent };
"""
    )
    assert result["wasBusy"] is True
    assert result["enabledBeforeCompletion"] is True
    assert result["enabledAfter"] is True
    assert result["label"] == "Search"
    assert "Filters changed" in result["message"]
