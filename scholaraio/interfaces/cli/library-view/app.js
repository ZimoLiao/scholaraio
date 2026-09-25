const POLL_MS = 2200;
const PDF_SYNC_POLL_MS = 5000;
const responseCache = new Map();

const state = {
  tab: "main",
  pageOffset: 0,
  filterTimer: null,
  recovery: null,
  recoveryRequestSeq: 0,
  rows: { main: [], proceedings: [] },
  payload: { main: null, proceedings: null },
  detail: null,
  selected: { main: "", proceedings: "" },
  sortKey: "year",
  sortDir: "desc",
  searchMode: "metadata",
  ranked: null,
  searchRequestSeq: 0,
  searchBusy: false,
  actionBusy: { bibtex: false, nativePdf: false },
  capabilities: {
    csrfToken: "",
    nativePdfOpen: false,
    nativePdfReason: "Checking local capabilities…",
    pdfDelivery: {
      mode: "download",
      target: "client",
      label: "Download PDF",
      reason: "Checking local capabilities…",
    },
  },
  pdf: null,
  pdfFullscreen: false,
  detailRequestSeq: 0,
  refreshRequestSeq: { main: 0, proceedings: 0 },
  refreshInFlight: { main: 0, proceedings: 0 },
  selectingText: false,
  filters: {
    search: "",
    title: "",
    author: "",
    yearFrom: "",
    yearTo: "",
    journal: "",
    doi: "",
    type: "",
    volume: "",
  },
  pollTimer: null,
  pdfSyncTimer: null,
  pdfSyncKey: "",
  pdfSyncRequestSeq: 0,
};

const els = {
  connectionDot: document.getElementById("connection-dot"),
  connectionLabel: document.getElementById("connection-label"),
  updatedAt: document.getElementById("updated-at"),
  sourceTitle: document.getElementById("source-title"),
  sourceRoot: document.getElementById("source-root"),
  sourceCopyButton: document.getElementById("source-copy-button"),
  metricTotal: document.getElementById("metric-total"),
  tableCount: document.getElementById("table-count"),
  recordsToolbarTitle: document.getElementById("records-toolbar-title"),
  tablePanel: document.getElementById("table-panel"),
  recordsView: document.getElementById("records-view"),
  pdfToolbarTitle: document.getElementById("pdf-toolbar-title"),
  pdfBackButton: document.getElementById("pdf-back-button"),
  pdfFullscreenButton: document.getElementById("pdf-fullscreen-button"),
  pdfTitle: document.getElementById("pdf-title"),
  pdfViewer: document.getElementById("pdf-viewer"),
  pdfFrame: document.getElementById("pdf-frame"),
  tableBody: document.getElementById("paper-table-body"),
  emptyState: document.getElementById("empty-state"),
  searchInput: document.getElementById("search-input"),
  searchMode: document.getElementById("search-mode"),
  searchButton: document.getElementById("search-button"),
  searchDiagnostics: document.getElementById("search-diagnostics"),
  clearFiltersButton: document.getElementById("clear-filters-button"),
  activeFilterCount: document.getElementById("active-filter-count"),
  titleFilter: document.getElementById("title-filter"),
  authorFilter: document.getElementById("author-filter"),
  yearFromFilter: document.getElementById("year-from-filter"),
  yearToFilter: document.getElementById("year-to-filter"),
  journalFilter: document.getElementById("journal-filter"),
  doiFilter: document.getElementById("doi-filter"),
  typeFilter: document.getElementById("type-filter"),
  volumeFilter: document.getElementById("volume-filter"),
  volumeFilterLabel: document.getElementById("volume-filter-label"),
  refreshButton: document.getElementById("refresh-button"),
  detailTitle: document.getElementById("detail-title"),
  detailActions: document.getElementById("detail-actions"),
  copyBibtexButton: document.getElementById("copy-bibtex-button"),
  previewPdfButton: document.getElementById("preview-pdf-button"),
  nativePdfButton: document.getElementById("native-pdf-button"),
  pdfSyncStatus: document.getElementById("pdf-sync-status"),
  metadataGrid: document.getElementById("metadata-grid"),
  issueList: document.getElementById("issue-list"),
  detailAbstract: document.getElementById("detail-abstract"),
  detailConclusion: document.getElementById("detail-conclusion"),
  tocList: document.getElementById("toc-list"),
  toast: document.getElementById("toast"),
};
const { formatDate, renderMarkdown, text } = globalThis.ScholarAIORendering;

function setConnection(kind, label) {
  els.connectionDot.classList.toggle("live", kind === "live");
  els.connectionDot.classList.toggle("error", kind === "error");
  els.connectionLabel.textContent = label;
}

async function fetchJson(url, options = {}) {
  const { conditional = false, ...requestOptions } = options;
  const cached = conditional ? responseCache.get(url) : null;
  const headers = { ...requestOptions.headers };
  if (cached?.etag) headers["If-None-Match"] = cached.etag;
  const response = await fetch(url, {
    cache: "no-store", signal: globalThis.AbortSignal?.timeout?.(60000), ...requestOptions, headers,
  });
  if (response.status === 304 && cached) return cached.payload;
  if (!response.ok) {
    let message = `${response.status || ""} ${response.statusText || "Request failed"}`.trim();
    let code = "";
    try {
      const payload = await response.json();
      if (payload?.error) message = payload.error;
      code = payload?.code || "";
    } catch (_err) {
      // Keep the HTTP fallback when an error body is not JSON.
    }
    const error = new Error(message);
    error.code = code;
    throw error;
  }
  const payload = await response.json();
  if (conditional) responseCache.set(url, { etag: response.headers?.get?.("ETag"), payload });
  return payload;
}

async function loadCapabilities() {
  try {
    const payload = await fetchJson("/api/capabilities");
    const nativePdfOpen = Boolean(payload?.native_pdf_open?.enabled);
    const nativePdfReason = String(payload?.native_pdf_open?.reason || "");
    const advertisedDelivery = payload?.pdf_delivery;
    const deliveryMode = advertisedDelivery?.mode === "native" && nativePdfOpen ? "native" : "download";
    state.capabilities = {
      csrfToken: String(payload?.csrf_token || ""),
      nativePdfOpen,
      nativePdfReason,
      pdfDelivery: {
        mode: deliveryMode,
        target: String(advertisedDelivery?.target || (deliveryMode === "native" ? "host" : "client")),
        label: String(
          advertisedDelivery?.label || (deliveryMode === "native" ? "Open in default viewer" : "Download PDF"),
        ),
        reason: String(advertisedDelivery?.reason || nativePdfReason),
        sync: String(advertisedDelivery?.sync || ""),
      },
    };
  } catch (_err) {
    const reason = "Native PDF launch capability could not be verified.";
    state.capabilities = {
      csrfToken: "",
      nativePdfOpen: false,
      nativePdfReason: reason,
      pdfDelivery: { mode: "download", target: "client", label: "Download PDF", reason, sync: "" },
    };
  }
  if (state.detail) {
    renderDetailActions(state.detail);
    schedulePdfSyncPolling(state.detail);
  }
}

function activePayload() {
  return state.payload[state.tab];
}

function activeRows() {
  return state.rows[state.tab] || [];
}

function issueTotal(row) {
  const counts = row.issue_counts || {};
  return Number(counts.error || 0) + Number(counts.warning || 0) + Number(counts.info || 0);
}

function includesFold(value, query) {
  return String(value ?? "").toLocaleLowerCase().includes(String(query ?? "").toLocaleLowerCase());
}

function rowMatches(row) {
  const q = state.filters.search.trim();
  if (q && state.searchMode === "metadata") {
    const haystack = [
      row.title,
      row.authors_text,
      row.journal,
      row.doi,
      row.paper_id,
      row.dir_name,
      row.proceeding_title,
    ].join(" ");
    if (!includesFold(haystack, q)) return false;
  }
  if (state.filters.title && !includesFold(row.title, state.filters.title)) return false;
  if (state.filters.author && !includesFold(row.authors_text, state.filters.author)) return false;
  if (state.filters.journal) {
    const source = [row.journal, row.proceeding_title].filter(Boolean).join(" ");
    if (!includesFold(source, state.filters.journal)) return false;
  }
  if (state.filters.doi && !includesFold(row.doi, state.filters.doi)) return false;
  const year = Number(row.year);
  const yearFrom = Number(state.filters.yearFrom);
  const yearTo = Number(state.filters.yearTo);
  if (state.filters.yearFrom && (!Number.isFinite(year) || year < yearFrom)) return false;
  if (state.filters.yearTo && (!Number.isFinite(year) || year > yearTo)) return false;
  if (state.filters.type && row.paper_type !== state.filters.type) return false;
  if (state.filters.volume && row.proceeding_title !== state.filters.volume) return false;
  return true;
}

function compareRows(a, b) {
  if (state.sortKey === "relevance") {
    const aRank = rankingFor(a.paper_id)?.rank ?? Number.MAX_SAFE_INTEGER;
    const bRank = rankingFor(b.paper_id)?.rank ?? Number.MAX_SAFE_INTEGER;
    return aRank - bRank;
  }
  const av = a[state.sortKey] ?? "";
  const bv = b[state.sortKey] ?? "";
  const an = Number(av);
  const bn = Number(bv);
  let result;
  if (Number.isFinite(an) && Number.isFinite(bn)) result = an - bn;
  else result = String(av).localeCompare(String(bv));
  return state.sortDir === "asc" ? result : -result;
}

function filteredRows() {
  if (activePayload()?.matched !== undefined) return activeRows();
  let rows = activeRows().filter(rowMatches);
  if (state.ranked) {
    rows = rows.filter((row) => state.ranked.byId.has(row.paper_id));
  }
  return rows.sort(compareRows);
}

function rankingFor(paperId) {
  return state.ranked?.byId?.get(paperId) || null;
}

function syncFiltersFromControls() {
  state.filters.search = els.searchInput.value.trim();
  state.filters.title = els.titleFilter.value.trim();
  state.filters.author = els.authorFilter.value.trim();
  state.filters.yearFrom = els.yearFromFilter.value.trim();
  state.filters.yearTo = els.yearToFilter.value.trim();
  state.filters.journal = els.journalFilter.value.trim();
  state.filters.doi = els.doiFilter.value.trim();
  state.filters.type = els.typeFilter.value;
  state.filters.volume = els.volumeFilter.value;
}

function activeFilterTotal() {
  return [
    state.filters.search,
    state.filters.title,
    state.filters.author,
    state.filters.yearFrom,
    state.filters.yearTo,
    state.filters.journal,
    state.filters.doi,
    state.filters.type,
    state.filters.volume,
  ].filter(Boolean).length;
}

function renderActiveFilterCount() {
  const total = activeFilterTotal();
  els.activeFilterCount.textContent = total ? `${total} active filter${total === 1 ? "" : "s"}` : "No active filters";
}

function validateYearRange() {
  const fields = [
    ["Year from", state.filters.yearFrom],
    ["Year to", state.filters.yearTo],
  ];
  for (const [label, value] of fields) {
    if (value && (!/^\d{4}$/.test(value) || Number(value) < 1000)) return `${label} must be a four-digit year.`;
  }
  if (state.filters.yearFrom && state.filters.yearTo && Number(state.filters.yearFrom) > Number(state.filters.yearTo)) {
    return "Year to must not be before year from.";
  }
  return "";
}

function buildOptions(select, values, emptyLabel) {
  const current = select.value;
  select.textContent = "";
  const empty = document.createElement("option");
  empty.value = "";
  empty.textContent = emptyLabel;
  select.appendChild(empty);
  for (const value of values) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.appendChild(option);
  }
  select.value = values.includes(current) ? current : "";
  return select.value;
}

function setSearchDiagnostics(kind, message, actions = []) {
  const commands = (actions || []).map((action) => action.command).filter(Boolean);
  els.searchDiagnostics.dataset.kind = kind;
  els.searchDiagnostics.textContent = [message, ...commands].filter(Boolean).join(" • ");
}

function updateSearchModeUi() {
  const proceedings = state.tab === "proceedings";
  if (proceedings && state.searchMode !== "metadata") {
    state.searchMode = "metadata";
    state.ranked = null;
  }
  els.searchMode.value = state.searchMode;
  els.searchMode.disabled = proceedings;
  els.searchMode.title = proceedings ? "Ranked search is not available for proceedings yet." : "";
  els.searchButton.disabled = state.searchBusy || state.searchMode === "metadata" || proceedings;
  els.searchButton.hidden = state.searchMode === "metadata";
  els.searchButton.setAttribute?.("aria-busy", state.searchBusy ? "true" : "false");
  els.searchButton.textContent = state.searchBusy ? "Searching…" : "Search";
  els.searchInput.placeholder =
    state.searchMode === "metadata" ? "Search library metadata" : `Enter a ${state.searchMode} search query`;
  if (proceedings) {
    setSearchDiagnostics("info", "Proceedings currently supports Metadata search and structured filters.");
  } else if (state.searchMode === "metadata") {
    setSearchDiagnostics("info", "Metadata filters apply across the whole library.");
  }
}

function renderFilters() {
  const rows = activeRows();
  const types = activePayload()?.types || [...new Set(rows.map((row) => row.paper_type).filter(Boolean))].sort();
  const volumes = activePayload()?.volumes || [...new Set(rows.map((row) => row.proceeding_title).filter(Boolean))].sort();
  state.filters.type = buildOptions(els.typeFilter, types, "All types");
  state.filters.volume = buildOptions(els.volumeFilter, volumes, "All volumes");
  const isProceedings = state.tab === "proceedings";
  els.volumeFilter.hidden = !isProceedings;
  els.volumeFilterLabel.hidden = !isProceedings;
  updateSearchModeUi();
  renderActiveFilterCount();
}

function renderMetrics() {
  const payload = activePayload();
  const refreshError = document.getElementById("library-refresh-error");
  refreshError.textContent = payload?.refresh_error || "";
  refreshError.hidden = !payload?.refresh_error;
  const root = payload?.root || "";
  els.sourceTitle.textContent = state.tab === "main" ? "Main Papers" : "Proceedings";
  els.sourceRoot.textContent = root || "--";
  els.sourceRoot.title = root;
  els.sourceCopyButton.disabled = !root;
  if (els.sourceCopyButton.textContent !== "Copied") els.sourceCopyButton.textContent = "Copy";
  els.metricTotal.textContent = String(payload?.total ?? "--");
  const audit = payload?.audit;
  els.updatedAt.textContent = audit?.state === "running" ? "Checking metadata quality…" : formatDate(payload?.generated_at);
  els.updatedAt.title = audit?.state === "failed" ? "Metadata quality check failed; it will retry automatically." :
    audit?.completed_at ? `Metadata quality checked: ${formatDate(audit.completed_at)}` : "";
}

function rankedSearchUrl() {
  const params = new URLSearchParams({
    mode: state.searchMode,
    q: state.filters.search,
  });
  const fields = [
    ["title", state.filters.title],
    ["author", state.filters.author],
    ["year_from", state.filters.yearFrom],
    ["year_to", state.filters.yearTo],
    ["journal", state.filters.journal],
    ["paper_type", state.filters.type],
    ["doi", state.filters.doi],
  ];
  for (const [name, value] of fields) {
    if (value) params.set(name, value);
  }
  params.set("limit", "200");
  return `/api/main/search?${params.toString()}`;
}

function setSearchButtonBusy(busy) {
  state.searchBusy = Boolean(busy);
  els.searchButton.disabled = Boolean(busy) || state.searchMode === "metadata" || state.tab === "proceedings";
  els.searchButton.setAttribute?.("aria-busy", busy ? "true" : "false");
  els.searchButton.textContent = busy ? "Searching…" : "Search";
}

async function runRankedSearch() {
  syncFiltersFromControls();
  renderActiveFilterCount();
  if (state.tab !== "main") {
    state.searchMode = "metadata";
    state.ranked = null;
    updateSearchModeUi();
    renderTableAndReconcileSelection();
    return;
  }
  if (state.searchMode === "metadata") {
    state.ranked = null;
    setSearchDiagnostics("info", "Metadata filters apply across the whole library.");
    renderTableAndReconcileSelection();
    return;
  }
  if (!state.filters.search) {
    setSearchDiagnostics("error", "Enter a query before running ranked search.");
    els.searchInput.focus();
    return;
  }
  const yearError = validateYearRange();
  if (yearError) {
    setSearchDiagnostics("error", yearError);
    return;
  }

  const requestTab = state.tab;
  const requestMode = state.searchMode;
  const requestSeq = ++state.searchRequestSeq;
  setSearchButtonBusy(true);
  setSearchDiagnostics("loading", `Running ${requestMode} search…`);
  try {
    const payload = await fetchJson(rankedSearchUrl());
    if (state.tab !== requestTab || state.searchMode !== requestMode || state.searchRequestSeq !== requestSeq) return;
    const results = Array.isArray(payload.results) ? payload.results : [];
    const diagnostics = payload.diagnostics || {};
    if (diagnostics.status === "unavailable" && results.length === 0) {
      state.ranked = null;
      state.sortKey = "year";
      state.sortDir = "desc";
    } else {
      state.ranked = {
        byId: new Map(
          results.map((result, index) => [
            result.paper_id,
            {
              rank: Number(result.rank || index + 1),
              score: Number(result.score || 0),
              match: String(result.match || requestMode),
            },
          ]),
        ),
      };
      state.sortKey = "relevance";
      state.sortDir = "asc";
    }
    const message = diagnostics.message || `${results.length} ranked result${results.length === 1 ? "" : "s"}.`;
    setSearchDiagnostics(diagnostics.status || "ok", message, diagnostics.actions || []);
    renderTableAndReconcileSelection();
  } catch (err) {
    if (state.tab !== requestTab || state.searchMode !== requestMode || state.searchRequestSeq !== requestSeq) return;
    setSearchDiagnostics("error", `Search failed: ${String(err)}`);
  } finally {
    if (state.tab === requestTab && state.searchMode === requestMode && state.searchRequestSeq === requestSeq) {
      setSearchButtonBusy(false);
    }
  }
}

function markRankedSearchDirty() {
  state.searchRequestSeq += 1;
  setSearchButtonBusy(false);
  if (state.searchMode === "metadata") {
    state.ranked = null;
    renderTableAndReconcileSelection();
  } else {
    setSearchDiagnostics("info", "Filters changed. Run Search to refresh ranked results.");
  }
  renderActiveFilterCount();
}

function clearAllFilters() {
  state.searchRequestSeq += 1;
  state.searchMode = "metadata";
  state.ranked = null;
  state.searchBusy = false;
  state.sortKey = "year";
  state.sortDir = "desc";
  Object.assign(state.filters, {
    search: "",
    title: "",
    author: "",
    yearFrom: "",
    yearTo: "",
    journal: "",
    doi: "",
    type: "",
    volume: "",
  });
  for (const input of [
    els.searchInput,
    els.titleFilter,
    els.authorFilter,
    els.yearFromFilter,
    els.yearToFilter,
    els.journalFilter,
    els.doiFilter,
    els.typeFilter,
    els.volumeFilter,
  ]) {
    input.value = "";
  }
  updateSearchModeUi();
  renderActiveFilterCount();
  renderTableAndReconcileSelection();
}

function statusPills(row) {
  const pills = [];
  if (row.has_md) pills.push(["MD", "ok"]);
  else pills.push(["No MD", "severe"]);
  if (issueTotal(row) > 0) {
    const counts = row.issue_counts || {};
    if (counts.error) pills.push([`${counts.error} error`, "severe"]);
    if (counts.warning) pills.push([`${counts.warning} warn`, "warn"]);
  } else if (row.has_md) {
    pills.push(["clean", "ok"]);
  }
  if (row.has_l3) pills.push(["L3", ""]);
  if (row.toc_count) pills.push([`TOC ${row.toc_count}`, ""]);
  return pills;
}

function renderTable() {
  const rows = filteredRows();
  els.tableBody.textContent = "";
  els.emptyState.hidden = rows.length > 0;
  els.tableCount.textContent = state.ranked ? `${rows.length} ranked result${rows.length === 1 ? "" : "s"}` : `${rows.length} shown`;
  const payload = activePayload();
  if (payload?.matched !== undefined) {
    els.tableCount.textContent = `${payload.matched ? payload.offset + 1 : 0}–${payload.offset + rows.length} / ${payload.matched}`;
    document.getElementById("page-previous").disabled = payload.offset === 0;
    document.getElementById("page-next").disabled = payload.offset + rows.length >= payload.matched;
  }
  for (const row of rows) {
    const tr = document.createElement("tr");
    tr.className = state.selected[state.tab] === row.paper_id ? "is-selected" : "";
    tr.addEventListener("click", () => selectRow(row.paper_id));

    const titleCell = document.createElement("td");
    const titleWrap = document.createElement("div");
    titleWrap.className = "title-cell";
    const title = document.createElement("div");
    title.className = "paper-title";
    title.textContent = text(row.title);
    titleWrap.appendChild(title);
    const ranking = rankingFor(row.paper_id);
    if (ranking) {
      const relevance = document.createElement("div");
      relevance.className = "relevance-line";
      const score = Number.isFinite(ranking.score) ? ranking.score.toFixed(4) : "--";
      relevance.textContent = `#${ranking.rank} · ${ranking.match} · ${score}`;
      titleWrap.appendChild(relevance);
    }
    titleCell.appendChild(titleWrap);
    tr.appendChild(titleCell);

    for (const value of [row.authors_text, row.year, row.paper_type]) {
      const td = document.createElement("td");
      td.textContent = text(value);
      tr.appendChild(td);
    }

    const status = document.createElement("td");
    const pillRow = document.createElement("div");
    pillRow.className = "pill-row";
    for (const [label, kind] of statusPills(row)) {
      const pill = document.createElement("span");
      pill.className = `pill ${kind}`;
      pill.textContent = label;
      pillRow.appendChild(pill);
    }
    if (row.has_pdf && row.pdf_url) {
      const pdfButton = document.createElement("button");
      pdfButton.className = "pill pdf-pill";
      pdfButton.type = "button";
      pdfButton.textContent = "PDF";
      pdfButton.addEventListener("click", (event) => {
        event.stopPropagation();
        openPdf(row);
      });
      pillRow.appendChild(pdfButton);
    }
    status.appendChild(pillRow);
    tr.appendChild(status);
    els.tableBody.appendChild(tr);
  }
}

function reconcileVisibleSelection() {
  const rows = filteredRows();
  const selected = state.selected[state.tab];
  if (selected && rows.some((row) => row.paper_id === selected)) return;
  const next = rows[0]?.paper_id || "";
  state.detailRequestSeq += 1;
  state.selected[state.tab] = next;
  if (next) {
    renderDetail(null);
    selectRow(next);
  } else {
    renderDetail(null);
  }
}

function renderTableAndReconcileSelection() {
  if (activePayload()?.matched !== undefined) {
    state.pageOffset = 0;
    state.refreshRequestSeq[state.tab] += 1;
    clearTimeout(state.filterTimer);
    state.filterTimer = setTimeout(() => refreshActive({ keepSelection: true }), 180);
    return;
  }
  renderTable();
  reconcileVisibleSelection();
}

function renderMetadata(detail) {
  els.metadataGrid.textContent = "";
  const pairs = [
    ["Directory", detail.dir_name],
    ["Authors", detail.authors_text],
    ["Year", detail.year],
    ["Type", detail.paper_type],
    ["Journal", detail.journal],
    ["DOI", detail.doi],
  ];
  if (state.tab === "proceedings") pairs.splice(2, 0, ["Volume", detail.proceeding_title]);
  for (const [label, value] of pairs) {
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    dd.textContent = text(value);
    els.metadataGrid.append(dt, dd);
  }
}

function renderIssues(detail) {
  els.issueList.textContent = "";
  const issues = detail.issues || [];
  if (!issues.length) {
    const empty = document.createElement("div");
    empty.className = "pill ok";
    empty.textContent = "No audit issues";
    els.issueList.appendChild(empty);
    return;
  }
  for (const issue of issues) {
    const item = document.createElement("div");
    item.className = `issue-item ${issue.severity}`;
    const rule = document.createElement("div");
    rule.className = "issue-rule";
    rule.textContent = `${issue.severity}: ${issue.rule}`;
    const message = document.createElement("div");
    message.className = "issue-message";
    message.textContent = issue.message;
    item.append(rule, message);
    els.issueList.appendChild(item);
  }
}

function renderToc(detail) {
  els.tocList.textContent = "";
  const toc = detail.toc || [];
  if (!toc.length) {
    const empty = document.createElement("div");
    empty.className = "pill";
    empty.textContent = "No TOC";
    els.tocList.appendChild(empty);
    return;
  }
  for (const entry of toc) {
    const item = document.createElement("div");
    item.className = "toc-item";
    const title = document.createElement("span");
    title.textContent = `${"#".repeat(Number(entry.level || 1))} ${entry.title || ""}`;
    const line = document.createElement("span");
    line.textContent = entry.line ? `L${entry.line}` : "";
    item.append(title, line);
    els.tocList.appendChild(item);
  }
}

function renderDetailActions(detail) {
  const hasRecord = Boolean(detail?.paper_id);
  const hasPdf = Boolean(detail?.has_pdf && detail?.pdf_url);
  els.detailActions.hidden = !hasRecord;
  els.copyBibtexButton.disabled = !hasRecord || state.actionBusy.bibtex;
  els.copyBibtexButton.setAttribute?.("aria-busy", state.actionBusy.bibtex ? "true" : "false");
  els.copyBibtexButton.textContent = state.actionBusy.bibtex ? "Copying…" : "Copy BibTeX";
  els.previewPdfButton.disabled = !hasPdf;
  els.previewPdfButton.title = hasPdf ? "Preview this PDF inside ScholarAIO" : "No local PDF is available";
  const delivery = state.capabilities.pdfDelivery || {};
  const deliveryMode = delivery.mode === "native" && state.capabilities.nativePdfOpen ? "native" : "download";
  const deliveryLabel = deliveryMode === "native" ? "Open in default viewer" : "Download PDF";
  els.nativePdfButton.disabled = !hasPdf || state.actionBusy.nativePdf;
  els.nativePdfButton.setAttribute?.("aria-busy", state.actionBusy.nativePdf ? "true" : "false");
  els.nativePdfButton.textContent = state.actionBusy.nativePdf
    ? deliveryMode === "native"
      ? "Opening…"
      : "Downloading…"
    : String(delivery.label || deliveryLabel);
  if (!hasPdf) els.nativePdfButton.title = "No local PDF is available";
  else if (deliveryMode === "download") {
    const reason = String(delivery.reason || state.capabilities.nativePdfReason || "");
    els.nativePdfButton.title = reason
      ? `Download this PDF to your browser. ${reason}`
      : "Download this PDF to your browser";
  } else if (delivery.target === "windows") {
    els.nativePdfButton.title = "Open this PDF with the Windows default viewer";
  } else els.nativePdfButton.title = "Open this PDF with the operating system's default viewer";
}

function renderPdfSyncStatus(status) {
  const stateName = String(status?.state || "not_opened");
  const actionable = ["sync_pending", "sync_failed", "conflict"].includes(stateName);
  document.getElementById("pdf-recovery-button").hidden = stateName !== "conflict";
  els.pdfSyncStatus.hidden = !actionable;
  els.pdfSyncStatus.dataset.state = stateName;
  els.pdfSyncStatus.textContent = actionable
    ? String(status?.message || (stateName === "sync_pending" ? "PDF synchronization is pending." : "PDF synchronization failed."))
    : "";
}

function closePdfRecovery() {
  state.recoveryRequestSeq += 1;
  state.recovery = null;
  document.getElementById("pdf-recovery-panel").hidden = true;
}

async function inspectPdfRecovery() {
  const source = state.tab;
  const id = state.selected[source];
  if (!id) return;
  const requestSeq = ++state.recoveryRequestSeq;
  const panel = document.getElementById("pdf-recovery-panel");
  const message = document.getElementById("pdf-recovery-message");
  try {
    const snapshot = await fetchJson(`/api/${source}/pdf-recovery?id=${encodeURIComponent(id)}`);
    if (state.recoveryRequestSeq !== requestSeq || state.tab !== source || state.selected[source] !== id) return;
    state.recovery = { source, id, snapshot };
    panel.hidden = false;
    document.getElementById("pdf-readers-closed").checked = false;
    message.textContent = "Download the versions you want to keep, or choose one to synchronize both active copies.";
    const list = document.getElementById("pdf-recovery-versions");
    list.textContent = "";
    for (const version of snapshot.versions) {
      const row = document.createElement("div");
      row.className = "pdf-recovery-version";
      const label = document.createElement("p");
      const name = version.id === "canonical" ? "Library copy" : version.id === "mirror" ? "Windows viewer copy" : "Retained save";
      label.textContent = `${name}: ${version.size} bytes · ${new Date(version.mtime_ns / 1e6).toLocaleString()} · ${version.hash.slice(0, 12)}${version.valid ? "" : " (unavailable or invalid)"}`;
      row.appendChild(label);
      if (version.exportable) {
        const params = new URLSearchParams({ id, version: version.id, token: snapshot.token });
        const url = `/api/${source}/pdf-recovery?${params}`;
        const links = [["Download / keep this copy", "&download=1"]];
        if (version.valid) links.unshift(["Preview", ""]);
        for (const [label, suffix] of links) {
          const link = document.createElement("a");
          link.textContent = label;
          link.href = url + suffix;
          link.target = "_blank";
          link.rel = "noopener";
          row.appendChild(link);
          row.appendChild(document.createTextNode(" "));
        }
      }
      if (version.valid) {
        const use = document.createElement("button");
        use.className = "action-button";
        use.textContent = "Use this version for both copies";
        use.addEventListener("click", async () => {
          if (!document.getElementById("pdf-readers-closed").checked) {
            message.textContent = "Close all PDF readers and check the confirmation first.";
            return;
          }
          if (state.recovery?.snapshot !== snapshot) return;
          use.disabled = true;
          try {
            await fetchJson(`/api/${source}/resolve-pdf`, { method: "POST",
              headers: { "Content-Type": "application/json", "X-ScholarAIO-CSRF": state.capabilities.csrfToken },
              body: JSON.stringify({ id, token: snapshot.token, version: version.id, readers_closed: true }) });
            if (state.recovery?.snapshot !== snapshot) return;
            closePdfRecovery();
            showToast("Selected PDF synchronized. Recovery copies retained.");
            await refreshPdfSyncStatus();
          } catch (err) {
            if (state.recovery?.snapshot !== snapshot) return;
            message.textContent = `${String(err)} Reopen Review PDF versions to inspect the latest copies.`;
          } finally { use.disabled = false; }
        });
        row.appendChild(use);
      }
      list.appendChild(row);
    }
  } catch (err) {
    if (state.recoveryRequestSeq === requestSeq) showToast(`Could not inspect PDF versions: ${String(err)}`, "error");
  }
}

function stopPdfSyncPolling() {
  clearInterval(state.pdfSyncTimer);
  state.pdfSyncTimer = null;
  state.pdfSyncKey = "";
  state.pdfSyncRequestSeq += 1;
}

function pdfSyncPollingEligible(detail) {
  return Boolean(
    detail?.paper_id &&
      detail?.has_pdf &&
      state.capabilities.pdfDelivery?.target === "windows" &&
      state.capabilities.pdfDelivery?.sync === "automatic" &&
      document.visibilityState !== "hidden",
  );
}

async function refreshPdfSyncStatus() {
  const detail = state.detail;
  const source = state.tab === "main" ? "main" : "proceedings";
  const paperId = detail?.paper_id;
  if (!pdfSyncPollingEligible(detail) || state.selected[source] !== paperId) return;
  const requestSeq = ++state.pdfSyncRequestSeq;
  try {
    const status = await fetchJson(`/api/${source}/pdf-sync?id=${encodeURIComponent(paperId)}`);
    if (
      requestSeq !== state.pdfSyncRequestSeq ||
      state.tab !== source ||
      state.selected[source] !== paperId ||
      state.detail?.paper_id !== paperId
    ) {
      return;
    }
    state.detail = { ...state.detail, pdf_sync: status };
    renderPdfSyncStatus(status);
  } catch (_err) {
    if (
      requestSeq === state.pdfSyncRequestSeq &&
      state.tab === source &&
      state.selected[source] === paperId &&
      state.detail?.paper_id === paperId
    ) {
      renderPdfSyncStatus({
        state: "sync_failed",
        retryable: true,
        message: "Could not refresh PDF synchronization status.",
      });
    }
  }
}

function schedulePdfSyncPolling(detail) {
  if (!pdfSyncPollingEligible(detail)) {
    stopPdfSyncPolling();
    return;
  }
  const source = state.tab === "main" ? "main" : "proceedings";
  const key = `${source}:${detail.paper_id}`;
  if (state.pdfSyncTimer && state.pdfSyncKey === key) return;
  stopPdfSyncPolling();
  state.pdfSyncKey = key;
  state.pdfSyncTimer = setInterval(refreshPdfSyncStatus, PDF_SYNC_POLL_MS);
}

function renderDetail(detail) {
  if (detail && state.detail) {
    const { pdf_sync: previousSync, audit: previousAudit, ...previousContent } = state.detail;
    const { pdf_sync: nextSync, audit: nextAudit, ...nextContent } = detail;
    if (JSON.stringify(previousContent) === JSON.stringify(nextContent)) {
      state.detail = detail;
      if (JSON.stringify(previousSync) !== JSON.stringify(nextSync)) renderPdfSyncStatus(nextSync);
      return;
    }
  }
  if (!detail) {
    closePdfRecovery();
    state.detail = null;
    els.detailTitle.textContent = "Select a record";
    els.metadataGrid.textContent = "";
    els.issueList.textContent = "";
    els.detailAbstract.textContent = "--";
    els.detailConclusion.textContent = "--";
    els.tocList.textContent = "";
    renderPdfSyncStatus(null);
    stopPdfSyncPolling();
    renderDetailActions(null);
    return;
  }
  state.detail = detail;
  els.detailTitle.textContent = text(detail.title);
  renderMetadata(detail);
  renderIssues(detail);
  renderMarkdown(els.detailAbstract, detail.abstract);
  renderMarkdown(els.detailConclusion, detail.l3_conclusion);
  renderToc(detail);
  renderPdfSyncStatus(detail.pdf_sync);
  schedulePdfSyncPolling(detail);
  renderDetailActions(detail);
}

async function copyText(value) {
  const content = String(value ?? "");
  try {
    if (!navigator.clipboard?.writeText) throw new Error("Clipboard API unavailable");
    await navigator.clipboard.writeText(content);
    return;
  } catch (_clipboardError) {
    const textarea = document.createElement("textarea");
    const previousFocus = document.activeElement;
    textarea.value = content;
    textarea.className = "clipboard-fallback";
    textarea.setAttribute("readonly", "");
    document.body.appendChild(textarea);
    try {
      textarea.focus();
      textarea.select();
      if (!document.execCommand("copy")) throw new Error("Clipboard fallback was rejected");
    } finally {
      textarea.remove();
      if (previousFocus?.focus) previousFocus.focus();
    }
  }
}

let toastTimer = null;
function showToast(message, kind = "success") {
  clearTimeout(toastTimer);
  els.toast.textContent = message;
  els.toast.dataset.kind = kind;
  els.toast.hidden = false;
  toastTimer = setTimeout(() => {
    els.toast.hidden = true;
  }, 3600);
  if (toastTimer?.unref) toastTimer.unref();
}

function setRecordActionBusy(action, busy) {
  state.actionBusy[action] = Boolean(busy);
  renderDetailActions(state.detail);
}

async function copySourceRoot() {
  const root = activePayload()?.root || "";
  if (!root) return;
  try {
    await copyText(root);
    els.sourceCopyButton.textContent = "Copied";
  } catch (_err) {
    els.sourceCopyButton.textContent = "Copy failed";
  }
}

async function copySelectedBibtex() {
  const detail = state.detail;
  if (!detail?.paper_id || state.actionBusy.bibtex) return;
  const source = state.tab === "main" ? "main" : "proceedings";
  setRecordActionBusy("bibtex", true);
  try {
    const payload = await fetchJson(`/api/${source}/bibtex?id=${encodeURIComponent(detail.paper_id)}`);
    await copyText(payload.bibtex || "");
    showToast("BibTeX copied to clipboard.");
  } catch (err) {
    showToast(`Could not copy BibTeX: ${String(err)}`, "error");
  } finally {
    setRecordActionBusy("bibtex", false);
  }
}

function previewSelectedPdf() {
  if (!state.detail?.has_pdf || !state.detail?.pdf_url) return;
  openPdf(state.detail);
}

function pdfDownloadUrl(pdfUrl) {
  const value = String(pdfUrl || "");
  if (!value) return "";
  if (/([?&])download=[^&#]*/.test(value)) {
    return value.replace(/([?&])download=[^&#]*/, "$1download=1");
  }
  const hashIndex = value.indexOf("#");
  const base = hashIndex >= 0 ? value.slice(0, hashIndex) : value;
  const hash = hashIndex >= 0 ? value.slice(hashIndex) : "";
  return `${base}${base.includes("?") ? "&" : "?"}download=1${hash}`;
}

function downloadPdf(detail) {
  const href = pdfDownloadUrl(detail?.pdf_url);
  if (!href) return false;
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = "";
  anchor.hidden = true;
  document.body.appendChild(anchor);
  try {
    anchor.click();
  } finally {
    anchor.remove();
  }
  return true;
}

async function deliverSelectedPdf() {
  const detail = state.detail;
  if (!detail?.paper_id || !detail.has_pdf || !detail.pdf_url || state.actionBusy.nativePdf) {
    return;
  }
  const deliveryMode =
    state.capabilities.pdfDelivery?.mode === "native" && state.capabilities.nativePdfOpen ? "native" : "download";
  if (deliveryMode === "download") {
    setRecordActionBusy("nativePdf", true);
    try {
      if (downloadPdf(detail)) showToast("PDF download started.");
    } finally {
      setRecordActionBusy("nativePdf", false);
    }
    return;
  }
  const source = state.tab === "main" ? "main" : "proceedings";
  setRecordActionBusy("nativePdf", true);
  try {
    showToast("Preparing PDF for the default viewer…");
    await fetchJson(`/api/${source}/open-pdf`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-ScholarAIO-CSRF": state.capabilities.csrfToken,
      },
      body: JSON.stringify({ id: detail.paper_id }),
    });
    showToast("PDF opened in the default viewer.");
    await refreshPdfSyncStatus();
  } catch (err) {
    if (err.code === "pdf_sync_conflict") {
      showToast(String(err), "error");
      await refreshPdfSyncStatus();
    } else if (err.name === "TimeoutError" || err.name === "AbortError") {
      showToast("PDF preparation has not responded yet. Check the default viewer before trying again.", "warning");
    } else if (downloadPdf(detail)) {
      showToast(`The default viewer could not be opened, so the PDF was downloaded instead: ${String(err)}`, "warning");
    } else {
      showToast(`Could not open the default viewer: ${String(err)}`, "error");
    }
  } finally {
    setRecordActionBusy("nativePdf", false);
  }
}

function setPdfFullscreen(enabled) {
  state.pdfFullscreen = Boolean(enabled);
  els.tablePanel.classList.toggle("is-pdf-fullscreen", state.pdfFullscreen);
  els.pdfFullscreenButton.textContent = state.pdfFullscreen ? "Exit fullscreen" : "Fullscreen";
}

function showRecords() {
  setPdfFullscreen(false);
  state.pdf = null;
  els.pdfFrame.removeAttribute("src");
  els.recordsToolbarTitle.hidden = false;
  els.refreshButton.hidden = false;
  els.recordsView.hidden = false;
  els.pdfToolbarTitle.hidden = true;
  els.pdfViewer.hidden = true;
}

function openPdf(row) {
  setPdfFullscreen(false);
  state.pdf = { url: row.pdf_url, title: row.title || row.dir_name || row.paper_id };
  els.pdfTitle.textContent = text(state.pdf.title);
  els.pdfFrame.src = row.pdf_url;
  els.recordsToolbarTitle.hidden = true;
  els.refreshButton.hidden = true;
  els.recordsView.hidden = true;
  els.pdfToolbarTitle.hidden = false;
  els.pdfViewer.hidden = false;
}

function deferBackgroundRefresh() {
  if (state.recovery) return true;
  return document.visibilityState === "hidden" || state.pdf || state.selectingText ||
    Boolean(globalThis.getSelection?.()?.toString());
}

async function selectRow(paperId, { background = false } = {}) {
  if (state.selected[state.tab] !== paperId || (state.recovery && state.recovery.source !== state.tab)) {
    closePdfRecovery();
  }
  const requestTab = state.tab;
  const requestSeq = ++state.detailRequestSeq;
  const selectionChanged = state.selected[requestTab] !== paperId;
  state.selected[requestTab] = paperId;
  if (selectionChanged) renderTable();
  try {
    const endpoint = requestTab === "main" ? "/api/main/detail" : "/api/proceedings/detail";
    const detail = await fetchJson(`${endpoint}?id=${encodeURIComponent(paperId)}`);
    if (state.tab !== requestTab || state.selected[requestTab] !== paperId || state.detailRequestSeq !== requestSeq) {
      return;
    }
    if (background && deferBackgroundRefresh()) return;
    renderDetail(detail);
    setConnection("live", "Live");
  } catch (err) {
    if (state.tab !== requestTab || state.selected[requestTab] !== paperId || state.detailRequestSeq !== requestSeq) {
      return;
    }
    if (background && deferBackgroundRefresh()) return;
    setConnection("error", "Detail failed");
    renderDetail({ title: "Detail unavailable", abstract: String(err) });
  }
}

function chooseDefaultSelection() {
  const selected = state.selected[state.tab];
  const rows = filteredRows();
  if (selected && rows.some((row) => row.paper_id === selected)) return selected;
  return rows[0]?.paper_id || "";
}

async function refreshActive({ keepSelection = true, background = false, force = false } = {}) {
  const requestTab = state.tab;
  if (responseCache.size > 24) responseCache.clear();
  if (background && (deferBackgroundRefresh() || state.refreshInFlight[requestTab])) return;
  const requestSeq = ++state.refreshRequestSeq[requestTab];
  state.refreshInFlight[requestTab] += 1;
  const endpoint = requestTab === "main" ? "/api/main/papers" : "/api/proceedings/papers";
  try {
    const params = new URLSearchParams({ limit: "100", offset: String(state.pageOffset),
      sort: state.sortKey, direction: state.sortDir });
    for (const [key, value] of [["title", state.filters.title], ["author", state.filters.author],
      ["journal", state.filters.journal], ["doi", state.filters.doi], ["paper_type", state.filters.type],
      ["volume", state.filters.volume], ["year_from", state.filters.yearFrom], ["year_to", state.filters.yearTo]]) {
      if (value) params.set(key, value);
    }
    if (state.searchMode === "metadata" && state.filters.search) params.set("q", state.filters.search);
    if (state.ranked) params.set("ids", JSON.stringify([...state.ranked.byId.keys()]));
    if (state.pageOffset && activePayload()?.revision) params.set("revision", activePayload().revision);
    if (force) params.set("refresh", "1");
    const payload = await fetchJson(`${endpoint}?${params}`, { conditional: !force });
    if (state.refreshRequestSeq[requestTab] !== requestSeq) {
      return;
    }
    if (background && deferBackgroundRefresh()) return;
    const rowsChanged = JSON.stringify(state.rows[requestTab]) !== JSON.stringify(payload.papers || []);
    const oldPage = state.payload[requestTab];
    const facetsChanged = JSON.stringify([oldPage?.types, oldPage?.volumes]) !==
      JSON.stringify([payload.types, payload.volumes]);
    const pageChanged = oldPage?.matched !== payload.matched || oldPage?.offset !== payload.offset;
    state.payload[requestTab] = payload;
    state.rows[requestTab] = payload.papers || [];
    if (state.tab !== requestTab) {
      return;
    }
    state.pageOffset = payload.offset || 0;
    if (state.pdf && !state.rows[requestTab].some((row) => row.pdf_url === state.pdf.url)) {
      showRecords();
    }
    if (rowsChanged || facetsChanged || !state.detail) renderFilters();
    renderMetrics();
    if (rowsChanged || pageChanged || !state.detail) renderTable();
    setConnection("live", "Live");
    const nextSelection = keepSelection ? chooseDefaultSelection() : filteredRows()[0]?.paper_id || "";
    if (nextSelection) await selectRow(nextSelection, { background });
    else renderDetail(null);
  } catch (err) {
    if (state.tab !== requestTab || state.refreshRequestSeq[requestTab] !== requestSeq ||
        (background && deferBackgroundRefresh())) {
      return;
    }
    setConnection("error", "Refresh failed");
    els.tableCount.textContent = String(err);
  } finally {
    state.refreshInFlight[requestTab] -= 1;
  }
}

function schedulePoll() {
  clearInterval(state.pollTimer);
  state.pollTimer = setInterval(() => refreshActive({ keepSelection: true, background: true }), POLL_MS);
}

function switchTab(tab) {
  if (state.tab === tab) return;
  closePdfRecovery();
  state.tab = tab;
  state.pageOffset = 0;
  state.searchRequestSeq += 1;
  state.searchMode = "metadata";
  state.ranked = null;
  state.searchBusy = false;
  state.sortKey = "year";
  state.sortDir = "desc";
  document.querySelectorAll(".tab").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.tab === tab);
  });
  state.filters.type = "";
  state.filters.volume = "";
  els.typeFilter.value = "";
  els.volumeFilter.value = "";
  els.searchMode.value = "metadata";
  showRecords();
  state.detailRequestSeq += 1;
  renderDetail(null);
  updateSearchModeUi();
  refreshActive({ keepSelection: true });
}

function bindEvents() {
  document.querySelectorAll(".tab").forEach((button) => {
    button.addEventListener("click", () => switchTab(button.dataset.tab));
  });
  for (const input of [
    els.searchInput,
    els.titleFilter,
    els.authorFilter,
    els.yearFromFilter,
    els.yearToFilter,
    els.journalFilter,
    els.doiFilter,
  ]) {
    input.addEventListener("input", () => {
      syncFiltersFromControls();
      const yearError = validateYearRange();
      if (yearError) setSearchDiagnostics("error", yearError);
      else markRankedSearchDirty();
    });
  }
  els.searchInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && state.searchMode !== "metadata") {
      event.preventDefault();
      runRankedSearch();
    }
  });
  els.searchMode.addEventListener("change", () => {
    state.searchRequestSeq += 1;
    state.searchMode = els.searchMode.value;
    state.ranked = null;
    state.searchBusy = false;
    state.sortKey = "year";
    state.sortDir = "desc";
    updateSearchModeUi();
    if (state.searchMode !== "metadata") {
      setSearchDiagnostics("info", `Enter a query, then run ${state.searchMode} search.`);
    }
    renderTableAndReconcileSelection();
  });
  els.searchButton.addEventListener("click", runRankedSearch);
  els.clearFiltersButton.addEventListener("click", clearAllFilters);
  els.typeFilter.addEventListener("change", () => {
    syncFiltersFromControls();
    markRankedSearchDirty();
  });
  els.volumeFilter.addEventListener("change", () => {
    syncFiltersFromControls();
    markRankedSearchDirty();
  });
  els.sourceCopyButton.addEventListener("click", copySourceRoot);
  document.getElementById("pdf-recovery-button").addEventListener("click", inspectPdfRecovery);
  document.getElementById("pdf-recovery-close").addEventListener("click", closePdfRecovery);
  els.copyBibtexButton.addEventListener("click", copySelectedBibtex);
  els.previewPdfButton.addEventListener("click", previewSelectedPdf);
  els.nativePdfButton.addEventListener("click", deliverSelectedPdf);
  els.refreshButton.addEventListener("click", () => refreshActive({ keepSelection: true, force: true }));
  for (const [id, delta] of [["page-previous", -100], ["page-next", 100]]) {
    document.getElementById(id).addEventListener("click", () => {
      state.pageOffset = Math.max(0, state.pageOffset + delta);
      refreshActive({ keepSelection: false });
    });
  }
  els.pdfBackButton.addEventListener("click", showRecords);
  els.pdfFullscreenButton.addEventListener("click", () => setPdfFullscreen(!state.pdfFullscreen));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && state.pdfFullscreen) setPdfFullscreen(false);
  });
  document.addEventListener("pointerdown", () => { state.selectingText = true; });
  document.addEventListener("pointerup", () => { state.selectingText = false; });
  document.addEventListener("pointercancel", () => { state.selectingText = false; });
  globalThis.addEventListener?.("blur", () => { state.selectingText = false; });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") stopPdfSyncPolling();
    else schedulePdfSyncPolling(state.detail);
  });
  globalThis.addEventListener?.("beforeunload", stopPdfSyncPolling);
  document.querySelectorAll("th[data-sort]").forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
      if (state.sortKey === key) state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
      else {
        state.sortKey = key;
        state.sortDir = key === "year" ? "desc" : "asc";
      }
      renderTableAndReconcileSelection();
    });
  });
}

bindEvents();
loadCapabilities();
refreshActive({ keepSelection: false });
schedulePoll();
