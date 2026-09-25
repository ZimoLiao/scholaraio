# Library projections and query consistency

`meta.json` and the paper files are authoritative. SQLite keyword, citation and
WebUI catalog data are disposable projections. Semantic vectors and evidence
chunks are separate, explicitly built projections; rebuilding keyword metadata
does not silently launch embedding models or pay for remote embeddings.

## Mutation and failure contract

| Change | Metadata / detail | Keyword / citation index | WebUI catalog |
|---|---|---|---|
| Application metadata update | Atomic file replacement under the library metadata lock | Refresh before the next ordinary query | Collection stamp invalidates the snapshot |
| Import or directory rename | Filesystem and stable paper ID remain authoritative | Refresh paths and indexed fields | Reconcile added/changed paths |
| Record removal | Missing record | Remove stale search rows and outgoing citations; re-resolve incoming targets | Remove missing record |
| External file edit | Detail reads current files | File identity scan detects it, cached for up to five seconds | Background scans start about five seconds apart |
| Failed index refresh | Never roll back good metadata to satisfy an index | Fail the query; retain the previous committed projection; retry/rebuild | Report failure and keep the previous published snapshot |
| Invalid JSON | Expose a metadata quality problem | Retain last good indexed record until repair or deletion | Show an error row |

Scans take time; a large or slow filesystem can extend the five-second detection
interval. Refresh forces a synchronous scan. Application writes invalidate the
in-process manifest cache and generation, and attempt to touch the owning collection
directory so other processes can detect them. A failed timestamp notification is
logged without failing an already committed metadata write; other processes still
observe the change on their next periodic scan. Proceedings child writes are also detected by the
background scan. No claim of a cross-filesystem/SQLite atomic transaction is
made. An edit concurrent with an index build leaves a different source manifest,
so a subsequent query detects the need to rebuild again.

A keyword build records its source root and manifest in `index_source`, commits
schema and data changes in a single SQLite transaction, and rejects duplicate
paper IDs and conflicting DOIs; constraint failures roll back every projection. Existing indexes remain usable; run `scholaraio index` once to enroll
an older database in automatic refresh. After moving a library or restoring it
at another root, rebuild with the new configuration before querying it.

Registry lookups used for identity repair deliberately retain their last known
mapping: refreshing before repair could destroy the only recoverable UUID.
Ordinary search refreshes; identity recovery is a separate operation.

Semantic/unified search reports whether the filtered records have missing or
outdated title/abstract embeddings. `scholaraio embed` updates them explicitly.
This freshness indicator concerns source text, not the relevance of results or
an assurance that every embedding provider configuration is interchangeable.

## WebUI query contract

The UI requests `/api/{main|proceedings}/papers?limit=100`. The optional paged
contract accepts `offset`, `limit` (1–200), `sort`, `direction`, metadata filters,
and an optional `revision`. The legacy unpaged endpoint remains available.

Filtering and sorting happen over a process-local SQLite catalog. Only changed
metadata files are reparsed; unchanged page requests neither reread all JSON
files nor serialize every record. Results contain `total`, `matched`, `offset`,
`limit`, `revision`, global type/volume facets, and the requested `papers` page.
Stable paper ID and path break sort ties. A changed revision resets an old page
request to page zero instead of pretending offsets address the same snapshot.
The revision advances only when projected row contents or membership change;
saving annotations to an existing PDF and repeating an identical audit do not
reset pagination. Invalid scalar metadata fields are surfaced as row warnings.

Ranked search returns at most 200 IDs; the catalog hydrates and pages those IDs
in rank order. Detail, BibTeX and PDF content remain separate requests. Browsing
pages does not select/export every record in the library. Text selection and
PDF reading suspend automatic UI refresh, including while reviewing a conflict.
The background scan can continue without replacing selected DOM nodes.

The catalog is rebuilt on server restart. It adds no new authoritative runtime
layout. The server owns and closes its catalog connections and scanner threads.

## Repeatable performance checks

Run `python scripts/benchmarks/library_catalog.py --sizes 2000 10000 50000 --samples 20 --check`.
Fixtures are temporary, synthetic and isolated from the configured library.
Cold means a fresh catalog, not a flushed OS cache. Results report cold build,
warm and filtered page p50/p95, forced scan, first detail, response bytes and
SQLite projection size (not total process memory). Browser rendering, desktop
viewer startup and network transport are separate measurements.

On the September 2026 WSL baseline, 50,000 records took about seven seconds to
build; warm page p95 was 10 ms and filtered page p95 24 ms. Each 100-row response
was about 44 KB; forced scanning took about 1.7 seconds. These are observations,
not promises for a different disk, machine, metadata payload or library.

Acceptance budgets for this fixture on a comparable machine: warm and filtered
page p95 below 250 ms, cold catalog below 30 seconds at 50k records, at most 100
rendered table rows, and page payload below 256 KiB. CI asserts bounded records,
unchanged-record reuse, stable pagination and selection. Wall-clock budgets are
checked with the benchmark rather than a flaky shared-runner unit threshold.

## CLI dependencies and typing

Command modules call logging, clocks, executors and helper-owning modules
directly. `compat` is an internal assembly surface for parser/runtime imports;
commands must not import it to access helpers. Tests patch the actual dependency
boundary. Config, record writes, PDF recovery, catalog and HTTP handlers opt into
checking untyped function bodies; optional scientific modules are tightened
incrementally when changed.
