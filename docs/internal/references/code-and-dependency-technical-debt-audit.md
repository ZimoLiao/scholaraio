# ScholarAIO Code and Dependency Technical-Debt Audit

Status: Historical baseline with tracked resolutions

Audited: 2026-07-21

Repository revision: `387de9bf7a49fa2aee3b201a58f374268e114314`

Update note (2026-07-29): PR #130 resolved TD-07 by removing the shipped
Toolref legacy snapshot and replacing its differential-oracle coverage with
explicit contract tests. The baseline counts and remaining evidence below stay
pinned to the audited repository revision unless a finding is marked resolved.

Update note (2026-08-30): the next-major external-webtools cleanup resolves the
qt-web-extractor and GUILessBingSearch portion of TD-10 by removing their MCP,
skill, CLI, config, setup, provider, and validation surfaces. The earlier
keep-optional recommendation below is superseded; historical validation reports
remain pinned to the versions they evaluated.

## 1. Executive Summary

ScholarAIO is in a workable beta state, with a substantial automated test suite
and a mostly sensible separation between core dependencies and optional research
tooling. The repository is not facing a broad rewrite problem. The main risk is
that several recently established contracts are not consistently enforced at
their boundaries.

This audit found:

- **2 P1 findings** that can silently bypass intended protection: the macOS
  semantic-search smoke workflow does not trigger for the canonical modules it
  is meant to protect, and part of the public Explore API can still write to a
  removed legacy runtime root.
- **8 P2 findings** concentrated in configuration propagation, architectural
  boundaries, CLI test seams, complex orchestration functions, shipped legacy
  code, dependency packaging, and integration evidence.
- **No P0 finding** and no evidence that a repository-wide rewrite is warranted.

The dependency conclusion is equally important:

1. Codex-native capabilities should be the default for one-shot web discovery,
   source-backed reading, visual interpretation, and agent-authored prose,
   diagrams, or presentation drafts.
2. Third-party runtime dependencies remain justified when ScholarAIO must offer
   deterministic batch execution, offline/local operation, persistent indexes,
   structured metadata, exact file formats, provenance, or repeatable CLI
   behavior outside a Codex session.
3. `mineru-open-api` should not remain a mandatory base dependency. The current
   runtime shells out to its executable, so it belongs in a dedicated optional
   extra.
4. `mermaid-py` and `cli-anything-inkscape` do not currently have a runtime import
   path and should not be in the published `draw`/`full` dependency surface
   without a measured workflow that needs them.
5. Paper2Any should remain a quarantined, separately installed extension until a
   native-vs-external quality bakeoff proves unique value. It should not be a
   default prerequisite or an always-on integration surface.

## 2. Scope and Method

The review covered the current Python package, tests, CI workflows, packaging
metadata, agent skills, runtime/configuration documentation, and existing
third-party integration records. It included:

- static inspection of `scholaraio/core`, `providers`, `stores`, `projects`,
  `services`, and `interfaces/cli`;
- an AST-level import-direction inventory;
- an additional Ruff complexity pass using `C901`, `PLR0911`, `PLR0912`,
  `PLR0913`, and `PLR0915`, which are not part of the normal lint selection;
- review of base and optional dependencies against actual runtime imports and
  command execution;
- review of official Codex capability documentation and the official upstream
  pages for selected external components;
- local unit, lint, and type-check baselines.

This was a code and dependency review, not a live acceptance test of every
external service. OpenAlex, MinerU, Paper2Any, Zotero, USPTO, hosted LLMs, and
other remote providers were not exercised against production endpoints in this
pass. The existing integration evidence matrix remains the source of truth for
which live workflows have been verified.

## 3. Baseline Evidence

| Signal | Result | Interpretation |
|---|---:|---|
| Runtime Python code | 47,128 lines | A medium-sized package; boundary discipline now matters more than adding new facades. |
| Test Python code | 34,795 lines | Strong investment in regression coverage, though several large test modules mirror current coupling. |
| Pytest | 1,623 passed in 220.62 s | Current unit/integration-fixture baseline is green. |
| Normal Ruff check | Passed | Enabled style and correctness rules are green. |
| Mypy | Passed for 148 source files | A weak signal because untyped bodies are unchecked by default and several high-risk modules use `ignore_errors = true`. |
| Additional Ruff complexity audit | 117 `C901`, 79 excessive-branch, 61 excessive-statement findings | Complexity is concentrated in orchestration and CLI dispatch paths. |
| Direct `requests.<verb>` spot check | 11 call sites; all specify a timeout | The inspected direct calls avoid an obvious indefinite-wait failure mode. |
| Shell execution spot check | No `shell=True` or `os.system` match | The inspected subprocess surface avoids the most direct shell-injection pattern. |
| Local `pip check` | Failed on two ambient conflicts | Not attributable to ScholarAIO from this environment alone; it demonstrates why extras need clean-environment resolution checks in CI. |

The largest implementation files include
`stores/toolref/_legacy_snapshot.py` (2,433 lines),
`services/migration_control.py` (2,374), `providers/mineru.py` (1,524),
`services/setup.py` (1,291), `core/config.py` (1,272), and
`services/vectors.py` (1,257). File size is not itself a defect, but these files
deserve stricter change gates because they combine many decisions and failure
modes.

## 4. Findings

### TD-01 — P1 — macOS semantic smoke does not watch canonical implementation paths

**Evidence**

`.github/workflows/macos-semantic-smoke.yml:10-13` and `:22-25` watch:

- `scholaraio/cli.py`
- `scholaraio/explore.py`
- `scholaraio/index.py`
- `scholaraio/vectors.py`

The breaking cleanup moved the implementations to:

- `scholaraio/interfaces/cli/**`
- `scholaraio/stores/explore.py`
- `scholaraio/services/index.py`
- `scholaraio/services/vectors.py`

`tests/test_ci_workflows.py` verifies the smoke script's command text but does not
verify the workflow path filters.

**Impact**

A pull request can change the real semantic-search implementation without
starting the macOS smoke job. This is a silent green/absent control, which is
more dangerous than an explicitly failing job.

**Recommended action**

Replace the removed paths with the canonical modules and add a workflow-contract
test that asserts canonical paths are present and removed facade paths are not.
Include `pyproject.toml` and relevant test paths as today.

### TD-02 — P1 — the fresh-layout-only contract is still bypassed by Explore

**Evidence**

`scholaraio/stores/explore.py:44-53` defines
`_DEFAULT_EXPLORE_DIR = Path("data/explore")` and returns it whenever `cfg` is
omitted. The module-level usage example calls `fetch_explore(...)` without a
configuration object. `fetch_explore` then creates that directory at
`stores/explore.py:323-325`.

This conflicts with the repository's fresh-layout-only contract, whose canonical
Explore root is `data/libraries/explore`. It also conflicts with the function
documentation for `explore_db_path`, which says configuration is resolved from
the environment when omitted even though `_explore_root` does not do so.

Several current-facing comments still describe automatic legacy fallback that
the `Config` accessors do not implement:

- `config.yaml:4`, `:8`, `:117`, and `:123`;
- `scholaraio/services/setup.py:1208`;
- `scholaraio/services/metrics.py:6`;
- `docs/guide/insights.md:3-5`.

By contrast, `core/config.py:481-504` resolves fresh state paths directly, and
`tests/test_config.py:418-433` asserts those fresh defaults.

**Impact**

Direct Python users can create a new legacy library that the normal configured
runtime does not see. Separately, users can believe old index, metrics, or topic
state is still discovered automatically when it is not, making migrated data
appear missing.

**Recommended action**

- Remove `_DEFAULT_EXPLORE_DIR`; either require `cfg` or call `load_config()` when
  it is omitted.
- Make all public Explore entry points follow the same path-resolution contract.
- Add a regression test proving no no-config call can create `data/explore`.
- Remove or explicitly mark historical all automatic-fallback claims in active
  config templates, module documentation, and user guides.

### TD-03 — P2 — an explicitly supplied OpenAlex API key is ignored

**Evidence**

`fetch_explore(..., cfg=cfg)` uses `cfg` for output paths, but `_fetch_page` calls
`_oa_api_key()` at `stores/explore.py:219`. `_oa_api_key()` independently calls
the global `load_config()` at `:182-188`; the `cfg.openalex.api_key` supplied to
`fetch_explore` is never passed through.

**Impact**

Library callers, tests, and isolated workspaces can supply a valid `Config` and
still authenticate with a different global key or no key. This makes rate-limit
and credential behavior environment-dependent.

**Recommended action**

Pass an OpenAlex client or explicit API key down to `_fetch_page`. Add a test that
constructs a non-global `Config` and asserts the request contains its key. Avoid
adding an OpenAlex SDK for this fix; the current HTTP surface is small enough for
a typed local provider adapter.

### TD-04 — P2 — `interfaces/cli/compat.py` is a circular service locator

**Evidence**

`scholaraio/interfaces/cli/compat.py` eagerly imports nearly every command module
and re-exports both public commands and private helpers. At the same time, 48 CLI
modules contain 139 imports of `compat as cli_mod`.

This is a command-module -> compat hub -> command-module cycle. It exists largely
to preserve monkeypatch points such as `TIME`, `FUTURES`, UI functions, helper
functions, and command handlers. `interfaces/cli/parser.py` is 979 lines, and its
single `_build_parser` function contains 527 statements under the additional
Ruff audit.

**Impact**

Adding a command expands a global import graph and a global patch surface. Tests
can pass through compatibility aliases while the direct implementation contract
drifts. Import order, startup behavior, and command ownership are harder to
reason about.

**Recommended action**

Introduce a small explicit `CliContext` for UI, logging, clock/executor, config,
and service dependencies. Let each command module expose a parser-registration
function and its handler. Migrate tests to patch the owning module or inject a
fake context, then delete compatibility aliases incrementally. This deserves a
separate execution plan rather than a one-shot rewrite.

### TD-05 — P2 — package layers are names, not enforced boundaries

**Evidence**

The import inventory found the following upward dependencies:

- `providers/endnote.py` and `providers/zotero.py` import the private
  `_extract_lastname` helper and `PaperMetadata` model from
  `services.ingest_metadata`;
- `projects/workspace.py` imports `services.index.lookup_paper` at four call sites;
- `stores/explore.py` imports metrics, vector, and topic services at six call
  sites.

`stores/explore.py` consequently owns OpenAlex I/O, files, SQLite, FTS5, FAISS,
topic modeling, and metrics. `services/metrics.py` similarly owns both SQLite
observability and handwritten OpenAI-compatible, Anthropic, and Google LLM
transport code; nine other service paths import `call_llm` from that metrics
module.

**Impact**

Lower-level packages know higher-level orchestration details, private helpers
become accidental public contracts, and unrelated changes share test and import
blast radius.

**Recommended action**

- Move `PaperMetadata` and shared normalization helpers to a neutral domain
  module below providers and services.
- Split Explore into an OpenAlex provider, an Explore repository/store, and a
  service that orchestrates indexing/topics/metrics.
- Split LLM transport from metrics. Keep a small provider protocol and wrap calls
  with metrics rather than making metrics own every provider.
- Add an import-boundary test or linter rule so `providers`, `stores`, and
  `projects` cannot import `services` without an explicit exception.

Do not add OpenAI, Anthropic, Google, or a multi-provider SDK merely to perform
this split. The present `requests` adapters keep the base install smaller; add an
SDK only if a measured protocol feature or maintenance burden justifies it.

### TD-06 — P2 — complexity and type-check blind spots overlap critical workflows

**Evidence**

The additional Ruff pass found 117 functions over the default `C901` threshold.
The highest-complexity functions were:

| Function | Complexity |
|---|---:|
| `services/ingest_metadata/_api.py:485 enrich_metadata` | 76 |
| `services/migration_control.py:628 run_migration_verification` | 75 |
| `services/ingest/inbox_orchestration.py:45 process_inbox` | 57 |
| `interfaces/cli/explore.py:51 cmd_explore` | 55 |
| `interfaces/cli/workspace.py:115 cmd_ws` | 41 |
| `interfaces/cli/patent.py:31 cmd_patent_search` | 39 |
| `interfaces/cli/attach_pdf.py:35 cmd_attach_pdf` | 37 |
| `services/ingest/pipeline_runner.py:43 run_pipeline` | 35 |

The default Ruff selection does not include complexity rules. The Mypy baseline
uses `check_untyped_defs = false` and `ignore_missing_imports = true`, and ignores
all errors in `stores.explore`, vector/topic services, CLI entry code, and the
ingest/metadata packages. These are many of the same high-complexity areas.

Coverage is collected in CI, but `pyproject.toml` defines no `fail_under`
threshold or changed-line policy.

**Impact**

The green quality gates provide less protection in the exact functions that
coordinate migrations, ingestion, external requests, and large CLI branches.

**Recommended action**

- Establish a baseline ratchet instead of enabling a repository-wide complexity
  failure immediately: prohibit new functions over an agreed threshold and
  reduce the listed hotspots when touched.
- Split each hotspot by state transition or failure domain, not by arbitrary
  line count.
- Turn on `check_untyped_defs` module by module and shrink the `ignore_errors`
  list, starting with Explore configuration and ingest metadata boundaries.
- Add a modest coverage floor or changed-line coverage check only after recording
  the current clean-CI baseline.

### TD-07 — Resolved 2026-07-29 — shipped legacy Toolref test oracle

PR #130 removed `scholaraio/stores/toolref/_legacy_snapshot.py` from the
installed package. Explicit score goldens and tie-break contract tests now
cover the behavior that depended on the differential oracle.

**Evidence**

`scholaraio/stores/toolref/_legacy_snapshot.py` duplicates the pre-split Toolref
implementation and still documents the removed `data/toolref` layout. Runtime
code does not import it; only `tests/test_toolref.py` imports it for differential
comparison. Because it lives under `scholaraio`, setuptools includes it in the
published package.

The modular `stores/toolref/__init__.py` also changes its module class at runtime
to preserve historical monkeypatch behavior, extending the compatibility cost.

**Impact**

The distribution ships dead production code, stale path documentation, and a
second implementation that can be mistaken for a supported surface. The test
oracle itself may drift.

**Recommended action**

Move the snapshot to a test fixture outside the installed package or replace the
differential test with explicit contract fixtures. Set an expiry condition for
the compatibility module-class shim and migrate tests to direct module seams.

### TD-08 — P2 — published dependency groups do not match runtime ownership

**Evidence**

`pyproject.toml` makes `mineru-open-api>=0.5.9` a mandatory dependency. The
ScholarAIO runtime does not import it as a library; `providers/mineru.py` discovers
and launches the `mineru-open-api` executable. This is a feature-specific cloud
parser path, not a prerequisite for search, local libraries, metadata, or the
base CLI.

The `draw` extra declares `mermaid-py` and `cli-anything-inkscape`, but neither is
imported by runtime Python code. `cli-anything-inkscape` appears in the draw skill,
and an Inkscape rendering path in `services/diagram.py` is commented out.

**Impact**

Every base user receives a parser-specific executable package, and every `full`
user receives draw dependencies without a runtime owner. This increases resolver,
upgrade, and supply-chain surface without guaranteed product value.

**Recommended action**

- Move `mineru-open-api` to a dedicated `mineru-cloud` or `parse-cloud` extra and
  keep setup diagnostics/install hints capability-based.
- Remove `mermaid-py` from published extras while ScholarAIO only emits Mermaid
  source text.
- Remove `cli-anything-inkscape` from `full`; keep it as an on-demand skill tool
  only if a quality benchmark shows value over direct SVG/DOT generation.
- Add a packaging contract test mapping every dependency group to at least one
  runtime import, executable probe, or explicitly documented skill-only owner.

### TD-09 — P2 — optional dependency resolution is not a release gate

**Evidence**

Linux CI installs `.[dev,office]`; the macOS smoke installs `.[dev,embed]`; the
release workflow also installs `.[dev,office]`. No workflow builds a clean wheel,
installs `.[full]` or each supported extra into a clean environment, runs
`pip check`, and performs import/CLI smokes.

The local review environment's `pip check` reported Starlette and Protobuf
conflicts. Those packages may have been introduced by unrelated tools, so this is
not evidence that ScholarAIO's metadata is currently unsatisfiable. It is evidence
that the existing developer environment cannot answer that question reliably.

**Impact**

An extra can become uninstallable or import-incompatible without blocking a
release. Heavy packages such as embedding/topic stacks amplify this risk.

**Recommended action**

Add clean-environment jobs for the base wheel and supported extras. At minimum,
gate `base`, `office`, `embed`, and `full` with `pip check` plus one representative
import/CLI smoke. Split provider-specific conveniences such as `modelscope` and
`curl-cffi` from an unbounded `full` group if clean resolution cannot be sustained.

### TD-10 — P2 — external integrations lack a native-first admission gate and synchronized evidence

**Resolution (2026-08-30)**

Resolved for the external webtools surface in the next-major cleanup. Routine
web access belongs to the active agent, while reviewable content can enter the
normal document inbox. Paper2Any remains separately isolated and evidence-gated.

**Evidence**

`docs/internal/references/third-party-integration-audit.md` still marks most
providers `not-yet-reviewed`. `.mcp.json` nevertheless advertises both the web
extractor and Paper2Any sidecar by default, and `setup check` always includes a
Paper2Any status surface.

The official [Paper2Any repository](https://github.com/OpenDCAI/Paper2Any)
advertises figures, editable DrawIO/PPT, posters, rebuttals, technical reports,
citations, knowledge-base search, and video workflows. Much of that overlaps
ScholarAIO skills plus Codex. Its potentially differentiating capabilities are
layout-preserving/editable conversions, specialized DrawIO workflows, and
repeatable multimodal batch pipelines; those have not been compared against the
native path in this repository's evidence matrix.

Codex can accept documents, PDFs, and images; use source-backed
[web search](https://learn.chatgpt.com/docs/web-search); and connect to external
tools through [MCP](https://learn.chatgpt.com/docs/extend/mcp). These features are
host- and session-configurable: web search can be cached, live, or disabled, and
an MCP service may be absent. They are therefore strong interactive defaults but
not universal replacements for deterministic ScholarAIO runtime contracts.

**Impact**

The project can accumulate setup checks, configuration, skills, tests, MCP
servers, and maintenance burden before unique user value is demonstrated. At the
same time, treating Codex as always available could break non-agent, offline, or
batch use cases.

**Recommended action**

Adopt the admission gate in section 6. In particular:

- keep routine web discovery on Codex/host-native search; do not restore
  GUILessBingSearch as a default surface;
- remove `qt-web-extractor` from ScholarAIO after it failed to demonstrate enough
  recurring academic value to justify its MCP, skill, CLI, config, setup, and
  provider maintenance surface;
- keep Paper2Any isolated from the Python base/full extras and remove any
  implication that it is required; run a fixed-corpus bakeoff before promoting
  individual capabilities;
- synchronize the integration audit whenever an MCP entry, setup diagnostic,
  skill, or provider is added or materially changed.

## 5. Dependency Decisions

The table below distinguishes whether a capability is valuable from whether it
belongs in the default package.

| Dependency or integration | Decision | Rationale and boundary |
|---|---|---|
| `requests`, `PyYAML`, `defusedxml`, `beautifulsoup4` | **Keep in base** | Small, broadly used foundations for HTTP, config, safe XML, and HTML metadata parsing. |
| `mineru-open-api` | **Keep capability; move out of base** | Useful for repeatable cloud parsing, but runtime-owned as an external executable and irrelevant to many users. |
| MinerU local/remote parsers | **Keep optional** | Codex can read an attached PDF interactively, but does not replace batch ingestion, structured Markdown/assets, resumability, and indexing. The official [MinerU project](https://github.com/opendatalab/MinerU) targets document-to-Markdown/JSON workflows. |
| Sentence Transformers, NumPy, FAISS | **Keep optional** | Provide deterministic offline/local embeddings and persistent search indexes; Codex session reasoning is not a substitute. |
| BERTopic and Pandas | **Keep optional, usage-gated** | Worthwhile for repeatable corpus clustering; avoid installing for ordinary search-only users. |
| PyMuPDF | **Keep optional with license gate** | A useful lightweight PDF fallback and editor. Official documentation states AGPL/commercial dual licensing; distribution and deployment use must be reviewed against the project's intended use. See [PyMuPDF licensing](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright). This is an engineering flag, not legal advice. |
| `endnote-utils`, `pyzotero` | **Keep optional** | Exact import/API interoperability and stable identifiers are not replaceable by model inference. Move shared metadata models below providers. |
| MarkItDown, `python-docx`, `python-pptx`, `openpyxl` | **Keep optional** | Deterministic Office ingest/export is a real runtime contract. Codex artifact creation is a preferred interactive path, not a headless CLI replacement. |
| `mermaid-py` | **Remove from extras for now** | Runtime emits source without importing the library. Codex can author Mermaid/DOT directly. Re-add only with an owned render path and acceptance tests. |
| `cli-anything-inkscape` | **Skill-only or remove** | No active runtime path. Direct SVG/DOT generation covers most current use; require an editable-vector quality win before publishing it as a dependency. |
| `modelscope` | **Keep narrow optional** | Valuable where ModelScope is the selected embedding-model source. It should not silently broaden the base install. |
| `curl-cffi` | **Keep narrow optional fallback** | It supports a specific DOI/Cloudflare recovery path. Treat it as a provider fallback, not a general HTTP replacement. |
| `qt-web-extractor` | **Remove in next major** | Its rendered/batch path is useful in isolation, but did not justify a permanent ScholarAIO surface over host-native reading plus the normal document inbox. Keep it available only as a user-managed external tool. |
| GUILessBingSearch adapter | **Deprecate/remove; do not reintroduce** | Host-native source-backed web search offers the better agent workflow. Retain only a time-bounded compatibility path if known Python callers still exist. |
| Paper2Any | **Quarantine and benchmark** | Do not vendor or add to base/full. Promote only capabilities that beat native ScholarAIO + Codex on fixed acceptance criteria, especially editable/layout-preserving output. |
| OpenAlex, Crossref, Semantic Scholar, arXiv, USPTO, Zotero APIs | **Keep provider adapters** | They provide structured, attributable identifiers and metadata. Native web search may help discovery but should not replace authoritative data contracts. |
| OpenAI/Anthropic/Google SDKs or a multi-provider SDK | **Do not add yet** | Current HTTP adapters cover the narrow batch LLM contract. First split transport from metrics and measure missing protocol features or maintenance cost. |
| Scientific CLIs such as GROMACS/LAMMPS/OpenFOAM | **Keep external and skill-mediated** | Codex can orchestrate and explain them but cannot substitute for the numerical executables or their validated results. Do not put them in Python extras. |

## 6. Third-Party Admission Gate

A new third-party dependency or integration should enter ScholarAIO only when all
applicable questions have satisfactory evidence.

1. **Unique value:** What user-visible result cannot Codex plus current
   ScholarAIO skills produce as well or better?
2. **Runtime necessity:** Does the capability require deterministic batch,
   offline/local, persistent, exact-format, or provenance-bearing behavior?
3. **Owned entry point:** Which CLI command, service, or skill owns it? A package
   with no import, executable probe, or explicit skill owner does not qualify.
4. **Isolation:** Can it be an optional extra, external CLI, MCP service, or
   isolated sidecar rather than part of the base environment?
5. **Acceptance evidence:** Is there a fixed corpus and a measurable success
   criterion for quality, latency, cost, and failure behavior?
6. **Degradation:** What happens when credentials, network, GPU, executable, or
   service are unavailable? Optional integrations must fail closed with a useful
   native or lightweight fallback.
7. **Operational fitness:** Are maintenance activity, release compatibility,
   security posture, transitive dependencies, and platform support acceptable?
8. **License and data handling:** Are redistribution, hosted-service terms,
   telemetry, uploaded-paper privacy, and generated-artifact ownership compatible
   with ScholarAIO's intended use?
9. **Exit path:** Can the integration be removed without corrupting user data or
   making stored projects unreadable?

The default decision should be:

- **Codex/skill only** for one-shot reasoning, drafting, browsing, and visual
  creation;
- **optional runtime dependency** for repeatable local or headless workflows;
- **isolated MCP/sidecar** for large external systems;
- **base dependency** only for small, broadly exercised foundations required by
  ordinary ScholarAIO commands.

## 7. Recommended Sequence

### Immediate correctness and control fixes

1. Fix the macOS smoke path filters and add a workflow-contract test.
2. Eliminate the no-config `data/explore` path and align active fallback
   documentation with the fresh-layout-only runtime.
3. Propagate the supplied OpenAlex config/API key through the provider call.

### Packaging and release containment

4. Move `mineru-open-api` to a dedicated optional extra.
5. Remove unowned draw packages from `draw`/`full`.
6. Add clean-wheel, extras, `pip check`, and representative import/CLI jobs.
7. Add a license/data-handling review record for PDF and remote parsing paths.

### Architectural reduction

8. Write an execution plan for replacing the CLI compatibility hub with explicit
   parser registration and dependency injection.
9. Split Explore provider/store/orchestration responsibilities and split LLM
   transport from metrics.
10. Ratchet complexity and typing on the listed hotspots; do not attempt a
    repository-wide rewrite.
11. Retire the Toolref legacy snapshot and module monkeypatch shim after explicit
    contract fixtures replace them.

### Integration governance

12. Run a fixed-corpus Paper2Any comparison covering at least editable diagram,
    layout-preserving PDF-to-PPT, poster, and rebuttal paths. Compare artifact
    editability, factual grounding, latency, setup burden, and failure behavior.
13. Update the third-party evidence matrix at the same time as MCP/config/skill
    changes, and require a live canary before labeling an integration `good`.

## 8. Definition of Done for This Debt Set

This audit should be considered substantially addressed when:

- canonical implementation changes reliably trigger their platform smoke jobs;
- no normal public API writes to removed runtime roots;
- explicit configuration objects are honored end to end;
- base and supported extras install cleanly from a built wheel in CI;
- every published dependency has an owned, tested runtime or skill path;
- CLI modules no longer depend on a circular global compatibility hub;
- providers/stores/projects do not import services without a reviewed boundary;
- complexity/type-check exceptions have a shrinking baseline;
- optional integrations have current evidence, graceful absence behavior, and a
  recorded license/data-handling decision.
