"""Behavior regressions for background refresh without disrupting reading."""

import shutil
import subprocess

import pytest

from scholaraio.interfaces.cli.gui import _static_dir


def test_background_refresh_preserves_reading_and_does_not_overlap():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for app.js behavior regression")
    script = r"""
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const elements = new Map();
let titleWrites = 0;
const document = {
  visibilityState: "visible",
  getElementById(id) {
    if (!elements.has(id)) {
      let content = "";
      elements.set(id, {
        get textContent() { return content; },
        set textContent(value) { content = value; if (id === "detail-title") titleWrites++; },
        classList: { toggle() {} },
      });
    }
    return elements.get(id);
  },
};
let selection = "";
let calls = [];
let handler;
const context = {
  document,
  getSelection: () => ({ toString: () => selection }),
  ScholarAIORendering: { text: String, formatDate: String, renderMarkdown() {} },
  fetch: async (url) => {
    calls.push(url);
    return { ok: true, json: async () => handler(url) };
  },
  assert,
  setSelection: (value) => { selection = value; },
  setHandler: (value) => { handler = value; },
  getCalls: () => calls,
  clearCalls: () => { calls = []; },
  titleWrites: () => titleWrites,
};
let code = fs.readFileSync(process.argv[1], "utf8");
code = code.slice(0, code.lastIndexOf("\nbindEvents();"));
vm.runInNewContext(code + `
let tableRenders = 0;
renderTable = () => { tableRenders++; };
renderFilters = () => {};
renderMetrics = () => {};
renderMetadata = () => {};
renderIssues = () => {};
renderToc = () => {};
renderDetailActions = () => {};
renderPdfSyncStatus = () => {};
schedulePdfSyncPolling = () => {};
const row = { paper_id: "a", title: "Original title" };
const detail = { ...row, abstract: "Abstract", pdf_sync: { state: "in_sync" } };
state.rows.main = [row];
state.selected.main = "a";
renderDetail(detail);
globalThis.done = (async () => {
  const initialWrites = titleWrites();
  renderDetail(JSON.parse(JSON.stringify(detail)));
  renderDetail({ ...detail, pdf_sync: { state: "sync_pending" } });
  assert.equal(titleWrites(), initialWrites, "unchanged content and sync updates must preserve text nodes");

  setHandler(url => url.includes("/papers") ? { papers: [row] } : detail);
  await refreshActive({ background: true });
  assert.equal(tableRenders, 0, "unchanged rows must not be rebuilt");
  assert.equal(titleWrites(), initialWrites);

  for (const mode of ["selection", "pointer", "hidden", "pdf"]) {
    clearCalls();
    setSelection(mode === "selection" ? "Original" : "");
    state.selectingText = mode === "pointer";
    document.visibilityState = mode === "hidden" ? "hidden" : "visible";
    state.pdf = mode === "pdf" ? { url: "/pdf" } : null;
    await refreshActive({ background: true });
    assert.equal(getCalls().length, 0, mode + " must suspend polling");
  }
  state.pdf = null;
  document.visibilityState = "visible";
  state.selectingText = false;

  let release;
  clearCalls();
  setHandler(() => new Promise(resolve => { release = resolve; }));
  const pending = refreshActive({ background: true });
  await Promise.resolve(); await Promise.resolve();
  await refreshActive({ background: true });
  assert.equal(getCalls().length, 1, "slow polls must not overlap");
  setSelection("Original");
  release({ papers: [{ ...row, title: "Updated title" }] });
  await pending;
  assert.equal(state.rows.main[0].title, "Original title", "selection started during fetch must defer update");
  assert.equal(state.refreshInFlight.main, 0);

  setSelection("");
  clearCalls();
  setHandler(url => url.includes("/papers") ? { papers: [row] } :
    new Promise(resolve => { release = resolve; }));
  const pendingDetail = refreshActive({ background: true });
  while (!getCalls().some(url => url.includes("/detail"))) await Promise.resolve();
  await Promise.resolve(); await Promise.resolve();
  setSelection("Original");
  release({ ...detail, title: "Updated title" });
  await pendingDetail;
  assert.equal(els.detailTitle.textContent, "Original title", "in-flight detail must preserve new selection");

  setSelection("");
  setHandler(url => url.includes("/papers") ? { papers: [row] } : { ...detail, title: "Updated title" });
  await refreshActive({ background: true });
  assert.equal(els.detailTitle.textContent, "Updated title", "updates must resume after selection clears");

  setHandler(() => { throw new Error("offline"); });
  await refreshActive({ background: true });
  assert.equal(state.refreshInFlight.main, 0, "errors must release polling guard");
})();
`, context);
context.done.catch(error => { console.error(error); process.exitCode = 1; });
"""
    result = subprocess.run(
        [node, "-e", script, str(_static_dir() / "app.js")],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
