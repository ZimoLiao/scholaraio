# ScholarAIO Config Surface Audit

Status: Historical audit, updated for the current compatibility window

Last Updated: 2026-08-30

Scope: repo-wide audit of hardcoded runtime paths, operational knobs, and external-service defaults that are candidates for formal configuration.

2026-07-15 compatibility note:

- external web discovery now uses the host agent's native search capability
- the former search skill, CLI command, default MCP registration, setup check, and generated config block have been removed
- `Config.websearch` and the low-level provider adapter remain compatibility-only; older recommendations below to expose them through the CLI or skill layer are superseded

2026-08-30 next-major cleanup note:

- the remaining `Config.websearch` / `Config.webextract` fields, provider code,
  CLI commands, skills, setup diagnostics, and environment-variable adapters
  have been removed
- active agents now own live web discovery and URL reading; reviewable content
  enters ScholarAIO through supported inbox files and the normal ingest pipeline
- the webtools details retained later in this historical audit describe the
  pre-removal surface and are superseded by this note

2026-04-23 status note:

- much of the path-authority work originally captured below has now landed in code
- `workspace_dir`, queue/inbox roots, `explore_root`, `toolref_root`, `citation_styles_dir`, and `translation_bundle_root` now all have real config-backed accessors
- logical state roots are also now active for fresh installs: search, metrics, and topics default under `data/state/...` while preserving legacy auto-detection for existing stores
- after the Track B namespace split, the implementation lives in `scholaraio/core/config.py`; older `scholaraio/config.py` references in this historical audit refer to the compatibility import path unless explicitly noted
- migration-run support now covers `citation_styles`, `toolref`, `explore`, `proceedings`, `spool`, and `papers`; cleanup archives legacy data under migration journals instead of deleting it directly
- sections below are still useful as migration-history context, but resolved items should be read together with these updates

## 1. Purpose

This document records which currently hardcoded values in the ScholarAIO codebase are worth moving into formal configuration, and which should stay as code-level constants.

The goal is not to make every number configurable. The goal is to identify the hardcoded surfaces that will matter during the upcoming upgrade work, especially:

- runtime directory layout and path authority
- external service endpoints and request policy
- user- or deployment-dependent retry / timeout behavior
- places where configuration already exists in spirit but is still bypassed in implementation

## 2. Audit Method

This audit is based on:

- direct inspection of `scholaraio/config.py`
- repo-wide text search for:
  - `cfg._root / ...`
  - `Path("data/...")`
  - `Path("workspace/...")`
  - `config.yaml`, `config.local.yaml`, `~/.scholaraio`
  - `os.environ.get(...)`
  - URL, timeout, retry, worker, and threshold constants
- targeted review of the modules that still anchor important runtime paths or network behavior

The audit intentionally separates:

- items that SHOULD become config
- items that MAY become config later
- items that SHOULD stay in code

## 3. Current State Summary

`scholaraio/config.py` already exposes a meaningful config surface for:

- main library path (`paths.papers_dir`)
- logical state/cache/runtime roots
- main search DB (`cfg.index_db`, now backed by logical-state defaults plus legacy auto-detection)
- logging and metrics DB (`cfg.metrics_db_path`, same compatibility pattern)
- LLM backend and timeouts
- embedding provider, model, cache, API settings
- ingest parser and many MinerU knobs
- search top-k
- topics model directory (`cfg.topics_model_dir`, now backed by logical-state defaults plus legacy auto-detection)
- translation chunk size and concurrency
- patent ODP API key
- backup target settings
- OpenAlex API key

At this point, the high-priority `Config` path surface is mostly in place for the compatibility window. The remaining risks are narrower:

1. compatibility bridges still exist where logical-state defaults must coexist with legacy runtime layouts.
2. a few no-config helper paths intentionally preserve legacy package-level defaults for import/API compatibility.
3. some non-path operational defaults may later deserve config treatment, but they should not block the runtime-layout upgrade.

The most important conclusion from this audit is:

**for this upgrade generation, `Config` is the runtime-layout authority; remaining work should shrink compatibility fallbacks deliberately rather than add broad new knobs.**

## 4. Priority Levels

### P0 — Must Become Config Soon

These are high-priority because they directly affect layout migration, runtime-root decoupling, or cross-environment correctness.

### P1 — Good Config Candidates After Path Authority

These are meaningful user- or deployment-dependent knobs, but they are less urgent than path authority.

### P2 — Optional / Low-Priority Config Candidates

These may be useful later, but they should not delay the main upgrade path.

### Keep in Code

These are better treated as internal constants, protocol facts, or curated product defaults rather than user-facing config.

## 5. P0 Findings: Runtime Paths That Should Move Into Config

### 5.1 Runtime Path Authority Is Mostly Landed, but Logical-State Compatibility Still Needs Care

Current status:

- `PathsConfig` now covers the main runtime roots, including `workspace_dir`, `workspace_figures_dir`, `workspace_docx_output_path`, inbox/pending/proceedings roots, `explore_root`, `toolref_root`, `citation_styles_dir`, `translation_bundle_root`, and `state_root/cache_root/runtime_root`
- `cfg.index_db`, `cfg.metrics_db_path`, and `cfg.topics_model_dir` now derive fresh-install defaults from logical state roots
- those three accessors still preserve legacy auto-detection for existing `data/index.db`, `data/metrics.db`, and `data/topic_model/`

Implication:

- the biggest remaining risk is no longer missing accessors
- it is letting downstream modules bypass these accessors and reintroduce special-case path logic

### 5.2 `workspace_dir` Is Config-Backed

Current status:

- `PathsConfig.workspace_dir` defaults to `workspace`
- `Config.workspace_dir` resolves that value relative to the runtime root
- explicit `paths.workspace_dir` overrides are covered by tests
- `workspace_figures_dir` and `workspace_docx_output_path` now derive their defaults from `cfg.workspace_dir` unless explicitly configured
- `translation_bundle_root` defaults under `cfg.workspace_dir / "_system" / "translation-bundles"` unless explicitly configured

Source:

- `scholaraio/core/config.py`
- `tests/test_config.py`

Downstream consumers:

- workspace command handling now lives in `scholaraio/interfaces/cli/workspace.py`
- shared CLI workspace path helpers live in `scholaraio/interfaces/cli/paths.py`
- `scholaraio/projects/workspace.py` remains the project/workspace layout authority

Recommendation:

- keep `Config.workspace_dir` as the accessor
- treat future workspace-output conventions as a separate design decision, not as a missing config accessor

### 5.3 Inbox and Queue Paths Have Config-Backed Spool Defaults

Current status:

- `Config` already exposes `inbox_dir`, `doc_inbox_dir`, `thesis_inbox_dir`, `patent_inbox_dir`, `proceedings_inbox_dir`, and `pending_dir`
- fresh instances default those queue roots to `data/spool/inbox*` and `data/spool/pending`
- existing legacy `data/inbox*` and `data/pending` directories are auto-detected when the corresponding spool target does not yet exist
- `scholaraio/ingest/pipeline.py` now resolves default queue paths through local helper accessors backed by `Config`
- `scholaraio/services/patent_fetch.py` now prefers `cfg.patent_inbox_dir`, uses `data/spool/inbox-patent` as the no-config default, and keeps legacy fallback through `Config`
- `scholaraio/cli.py` now routes arXiv downloads through `cfg.inbox_dir`

Key sources:

- `scholaraio/config.py`
- `scholaraio/ingest/pipeline.py`
- `scholaraio/services/patent_fetch.py:download_patent_pdf`
- `scholaraio/cli.py:cmd_arxiv_fetch`
- `scholaraio/services/setup.py`

Recommendation:

- keep the existing accessor surface as the only default authority
- continue shrinking compatibility fallbacks so future queue writers do not reintroduce raw path literals

These are the most important path additions for migration readiness.

### 5.4 Proceedings Root and DB Path Have a Config-Backed Durable-Library Default

Current behavior:

- `Config` exposes `proceedings_dir`; fresh instances default to `data/libraries/proceedings/`
- existing legacy `data/proceedings/` is auto-detected when the durable-library target does not exist
- `pipeline` now resolves proceedings writes through a helper backed by `cfg.proceedings_dir`
- low-level proceedings iteration helpers still accept an explicit proceedings-root path argument

Sources:

- `scholaraio/stores/proceedings.py:proceedings_db_path`
- `scholaraio/stores/proceedings.py:iter_proceedings_dirs`
- `scholaraio/ingest/pipeline.py:_proceedings_dir`

Recommendation:

- preserve `paths.proceedings_dir` as the single source of truth for pipeline entry points
- continue preserving explicit `paths.proceedings_dir` overrides and legacy fallback behavior until migration cleanup is complete

### 5.5 Explore Root Has a Config-Backed Durable-Library Default

Current behavior:

- explore helper functions use `cfg.explore_root` when a config is provided
- fresh instances default to `data/libraries/explore/`
- existing legacy `data/explore/` is auto-detected when the durable-library target does not exist
- no-config helper calls still preserve `_DEFAULT_EXPLORE_DIR = Path("data/explore")` for package-level compatibility

Sources:

- `scholaraio/stores/explore.py:_DEFAULT_EXPLORE_DIR`
- `scholaraio/stores/explore.py:_explore_root`
- `scholaraio/interfaces/cli/explore.py:cmd_explore`

Recommendation:

- continue preserving explicit `paths.explore_root` overrides and legacy fallback behavior until migration cleanup is complete

### 5.6 Toolref Root Has a Config-Backed Durable-Library Default

Current behavior:

- toolref helper functions use `cfg.toolref_root` when a config is provided
- fresh instances default to `data/libraries/toolref/`
- existing legacy `data/toolref/` is auto-detected when the durable-library target does not exist
- `scholaraio/toolref/_legacy_snapshot.py` still carries a parallel root-resolution implementation for compatibility tests

Source:

- `scholaraio/toolref/paths.py:9-18`
- `scholaraio/toolref/_legacy_snapshot.py:45-130`

Recommendation:

- continue preserving explicit `paths.toolref_root` overrides and legacy fallback behavior until migration cleanup is complete

### 5.7 Citation Styles Path Has a Config-Backed Durable-Library Default

Current behavior:

- `styles_dir(cfg)` follows `cfg.citation_styles_dir`
- fresh instances default to `data/libraries/citation_styles/`
- existing legacy `data/citation_styles/` directories are still auto-detected when the new target does not exist

Source:

- `scholaraio/stores/citation_styles.py:styles_dir`
- `scholaraio/core/config.py:citation_styles_dir`

Historical hidden coupling:

- citation styles are not actually conceptually subordinate to the papers directory
- they previously only happened to live next to the paper library

Recommendation:

- continue preserving explicit `paths.citation_styles_dir` and legacy fallback behavior until migration cleanup is complete

### 5.8 Portable Translation Bundle Root Is Config-Backed

Current behavior:

- `Config.translation_bundle_root` is now the primary default authority for portable translation bundles
- the fresh-layout default is `workspace/_system/translation-bundles/<paper>/`
- the helper still keeps a final fallback to `paper_dir.parent.parent / "workspace"` only for non-`Config` callers that do not expose `translation_bundle_root`

Source:

- `scholaraio/core/config.py:translation_bundle_root`
- `scholaraio/services/translate.py:_portable_bundle_dir`
- `tests/test_config.py`
- `tests/test_translate.py`

Related CLI/doc default:

- `scholaraio/interfaces/cli/parser.py`

Assessment:

- future portable bundle root moves can now happen by changing one accessor instead of rewriting translation entry points
- the remaining helper fallback is a compatibility backstop, not the primary design authority

### 5.9 Setup and Bootstrap Logic Still Assume Root-Level Config Filenames

Current behavior:

- setup generates `config.yaml` and `config.local.yaml` directly at runtime root
- config discovery searches for those exact names

Sources:

- `scholaraio/config.py:515-571`
- `scholaraio/services/setup.py:457-459`
- `scholaraio/services/setup.py:831`
- `scholaraio/services/setup.py:903`

Recommendation:

- do **not** make these filenames user-configurable now
- but explicitly recognize them as bootstrap contracts, not incidental strings

This belongs in the config/bootstrap design, not as a free-form user knob.

## 6. P1 Findings: Operational Knobs Worth Config After Path Authority

### 6.1 Webtools Configuration (Resolved By Removal)

Resolution (2026-08-30): the next-major cleanup removes this configuration and
its owning runtime surfaces. The inventory below is retained only as a record of
the pre-removal compatibility window.

Historical behavior:

- the code supported:
  - `websearch.base_url`
  - `websearch.api_key`
  - `websearch.transport`
  - `websearch.mcp_url`
  - `websearch.mcp_tool`
  - `webextract.base_url`
  - `webextract.api_key`
  - `webextract.transport`
  - `webextract.mcp_url`
  - `webextract.mcp_tool`
- environment variables existed as fallback / override:
  - `WEBSEARCH_URL`
  - `WEBEXTRACT_URL`
  - `WEBSEARCH_API_KEY`
  - `WEBEXTRACT_API_KEY`
  - `WEBSEARCH_TRANSPORT`
  - `WEBSEARCH_MCP_URL`
  - `GUILESS_BING_SEARCH_MCP_URL`
  - `GUILESS_BING_SEARCH_API_KEY`
  - `WEBEXTRACT_TRANSPORT`
  - `WEBEXTRACT_MCP_URL`
  - `QT_WEB_EXTRACTOR_MCP_URL`
  - `QT_WEB_EXTRACTOR_API_KEY`
- localhost defaults and several timeout values still live in code
- `websearch` supported an explicit `transport: mcp` provider path for GUILessBingSearch remote `search_bing`
- `webextract` supported an explicit `transport: mcp` provider path for qt-web-extractor remote `fetch_url`
- common MCP Streamable HTTP client behavior lives in `scholaraio/providers/mcp.py`

Source:

- `scholaraio/core/config.py`
- `scholaraio/providers/mcp.py`
- `scholaraio/providers/webtools.py:19-20`
- `scholaraio/providers/webtools.py`
- `scholaraio/interfaces/cli/web.py`

Recommendation:

- do not restore these fields unless a future integration independently passes
  the current third-party admission gate

Assessment:

- the old "env-only" diagnosis is no longer correct
- the PR #74 MCP follow-up is now represented in code for both webtools capabilities
- remaining design work is mostly operational: documenting recommended MCP setup and adding live canaries when remote services are available

### 6.2 MinerU Still Has Several Timeout Constants Outside Config

Current behavior:

- `API_TIMEOUT = 600`
- `DEFAULT_UPLOAD_TIMEOUT = 120`
- `DEFAULT_DOWNLOAD_TIMEOUT = 120`

Sources:

- `scholaraio/providers/mineru.py:121-123` (`scholaraio/ingest/mineru.py` compatibility alias)

Already-configured nearby knobs:

- `mineru_batch_size`
- `mineru_upload_workers`
- `mineru_upload_retries`
- `mineru_download_retries`
- `mineru_poll_timeout`

Source:

- `scholaraio/config.py:205-237`

Recommendation:

- add explicit config support for:
  - local MinerU request timeout
  - cloud upload timeout
  - cloud download timeout

These belong with the existing `ingest.mineru_*` family.

### 6.3 Metadata API Timeout and Retry Policy Are Hardcoded

Current behavior:

- academic metadata APIs use:
  - fixed bases for Crossref / Semantic Scholar / OpenAlex
  - `TIMEOUT = 10`
  - request retry policy with `total=3`, `backoff_factor=1`
  - title-match thresholds `0.85` and `0.65`

Sources:

- `scholaraio/ingest/metadata/_models.py:146-191`
- `scholaraio/ingest/metadata/_api.py:58-119`

Recommendation:

- do **not** rush to config-ize the API base URLs
- but it is reasonable to move timeout/retry policy into config

Suggested fields:

- `metadata.request_timeout`
- `metadata.retry_total`
- `metadata.retry_backoff_factor`

Title-match thresholds are lower priority and should stay in code for now unless there is a real quality-tuning workflow that needs them.

### 6.4 Explore Fetch Timeout and Retry Policy Are Hardcoded

Current behavior:

- OpenAlex fetch uses:
  - `timeout=30`
  - exponential backoff via `2**attempt`
  - three total attempts

Source:

- `scholaraio/stores/explore.py:_fetch_page`

Recommendation:

- add an `explore.fetch` config subsection if explore is expected to be used in diverse network environments

Suggested fields:

- `request_timeout`
- `max_retries`
- `retry_backoff_base`

Keep `_PER_PAGE = 200` in code. That is closer to an upstream API contract than to a user preference.

### 6.5 Toolref Discovery Policy Is Hardcoded

Current behavior:

- request timeout tuples for manifest fetch and discovery are hardcoded
- OpenFOAM discovery page cap is hardcoded to `800`

Sources:

- `scholaraio/toolref/constants.py:3-7`
- `scholaraio/toolref/manifest.py:373-387`
- `scholaraio/toolref/fetch.py:70`

Recommendation:

- add a `toolref` config section for network/discovery policy

Suggested fields:

- `manifest_request_timeout`
- `openfoam_discovery_timeout`
- `openfoam_max_discovery_pages`
- `bio_discovery_timeout`
- `git_clone_timeout`

This is worth config because toolref is now a first-class subsystem and these values affect runtime cost and reliability.

### 6.6 Translation Retry Policy Is Hardcoded

Current behavior:

- translation retry attempts default to `5`
- retry backoff base is a code constant

Sources:

- `scholaraio/services/translate.py:DEFAULT_TRANSLATE_MAX_ATTEMPTS`
- `scholaraio/services/translate.py:DEFAULT_TRANSLATE_BACKOFF_BASE`
- `scholaraio/services/translate.py:_translate_chunk_with_retry`

Recommendation:

- add to `translate` config:
  - `max_attempts`
  - `retry_backoff_base`

These are user-visible reliability knobs for long-running LLM operations and fit naturally beside `chunk_size` and `concurrency`.

### 6.7 Global GPU Profile Cache Path Bypasses Runtime Config

Current behavior:

- GPU adaptive batching profiles are written to a fixed global path:
  - `~/.cache/scholaraio/gpu_profile.json`

Source:

- `scholaraio/vectors.py:314`
- `scholaraio/vectors.py:423-447`

Why this matters:

- it is a real persistent runtime artifact
- it lives outside the runtime root
- it is not currently represented in `Config`
- it will matter when the project formalizes `data/state` vs `data/cache` boundaries

Recommendation:

- add an explicit cache path accessor or embed-profile path setting
- at minimum, stop treating this as an invisible module-global path

This does not have to be user-facing immediately, but it should become part of the formal path authority.

### 6.8 Fallback Parser Timeout Is Hardcoded

Current behavior:

- the Docling CLI fallback path uses a hardcoded subprocess timeout of `300` seconds

Source:

- `scholaraio/providers/pdf_fallback.py:131-136` (`scholaraio.ingest.pdf_fallback` compatibility alias)

Recommendation:

- consider adding an ingest-level parser timeout knob, or at least a dedicated fallback-parser timeout constant owned by config/bootstrap rather than buried in the fallback module

This is lower priority than path authority, but it is a real operational knob for slow environments and large PDFs.

## 7. P2 Findings: Optional Config Candidates

These are real hardcoded values, but they are not urgent enough to justify config surface expansion right now.

### 7.1 arXiv Request Timeouts and Retry Policy

Current behavior:

- hardcoded timeouts for API, recent page, abs page, and PDF download
- retry adapter uses fixed policy

Sources:

- `scholaraio/sources/arxiv.py:38-47`
- `scholaraio/sources/arxiv.py:130`
- `scholaraio/sources/arxiv.py:175`
- `scholaraio/sources/arxiv.py:228`
- `scholaraio/sources/arxiv.py:326`

Assessment:

- nice to tune in poor-network environments
- not as urgent as webtools, MinerU, or metadata APIs

### 7.2 Document Metadata LLM Input Cap

Current behavior:

- `_MAX_TEXT_FOR_LLM = 60_000`

Source:

- `scholaraio/ingest/metadata/_doc_extract.py:25-26`

Assessment:

- this is a prompt-safety / cost-control constant
- it should stay in code unless there is a demonstrated need for operator tuning

### 7.3 Insights Defaults

Current behavior:

- several CLI-facing defaults are hardcoded:
  - keyword top-k
  - recent-day window
  - recommendation counts

Sources:

- `scholaraio/interfaces/cli/insights.py:cmd_insights`
- `scholaraio/services/insights.py:extract_hot_keywords`
- `scholaraio/services/insights.py:aggregate_most_read_titles`
- `scholaraio/services/insights.py:recommend_unread_neighbors`

Assessment:

- if these need tuning, CLI flags are probably a better first step than global config

### 7.4 Default DOCX Output Path

Current behavior:

- document export defaults to `<workspace>/_system/output/output.docx`
- CLI now resolves that default through `Config.workspace_docx_output_path` (via shared CLI helpers) instead of a raw literal

Source:

- `scholaraio/interfaces/cli/paths.py:_default_docx_output_path`
- `scholaraio/interfaces/cli/export.py:_cmd_export_docx`

Assessment:

- the fresh-layout default now lives under `<workspace>/_system/output/`
- future output-root moves can happen by changing one accessor instead of patching each CLI entry point

### 7.5 Default Diagram Output Root

Current behavior:

- diagram generation defaults to `<workspace>/_system/figures/`
- the default is now centralized behind `Config.workspace_figures_dir` plus shared helpers instead of duplicated raw literals across every entry point

Sources:

- `scholaraio/services/diagram.py:_default_out_dir`
- `scholaraio/interfaces/cli/paths.py:_workspace_figures_dir`
- `scholaraio/services/diagram.py:generate_diagram_with_critic`
- `scholaraio/services/diagram.py:generate_diagram`
- `scholaraio/services/diagram.py:generate_diagram_from_text`

Assessment:

- `Config.workspace_figures_dir` is now the primary default authority for diagram outputs
- the fresh-layout default remains `<workspace>/_system/figures/` unless the accessor is explicitly overridden
- future figure-root moves can happen by changing one accessor while keeping CLI and service callers stable

## 8. Items That Should Stay in Code

The following are intentionally **not** recommended as config at this stage.

### 8.1 Root Agent Wrappers and Skill Discovery Surfaces

These are compatibility and host-discovery contracts, not runtime-user preferences.

Examples:

- root agent wrapper filenames
- canonical skill root placement

These should stay as repository-structure invariants, not config.

### 8.2 Fixed Upstream Scholarly API Bases

Examples:

- Crossref base URL
- Semantic Scholar base URL
- OpenAlex base URL
- official arXiv endpoints

Reason:

- these are protocol endpoints for public upstream services
- making them user-configurable adds complexity without a strong current deployment need

If self-hosting or mirroring ever becomes a real supported mode, this can be revisited.

### 8.3 Backend-Enforced Safety Limits

Examples:

- MinerU cloud max pages / max bytes
- cloud-safe filename limits

Sources:

- `scholaraio/providers/mineru.py:129-132` (`scholaraio/ingest/mineru.py` compatibility alias)
- `scholaraio/providers/mineru.py:870-875` (`scholaraio/ingest/mineru.py` compatibility alias)

Reason:

- these represent backend constraints or safety rules
- turning them into config would encourage unsupported combinations

### 8.4 Internal NLP / Matching Heuristics

Examples:

- stopword sets in `insights.py`
- title-match thresholds in metadata enrichment
- document-extraction truncation cap

These are implementation heuristics. They should only become config if there is a concrete operator workflow that depends on tuning them.

### 8.5 Curated Tool Registry Content

Examples:

- built-in tool Git repos
- manifest seed pages
- curated default versions

Sources:

- `scholaraio/toolref/constants.py:15-56`

Reason:

- this is product-curated knowledge, not a normal runtime preference

## 9. Config-Surface Synchronization Gaps

A separate but important finding:

some values are already in `Config`, but the setup/template surface does not expose them clearly.

Example gaps:

- `llm.concurrency`
- `ingest.contact_email`
- `ingest.s2_api_key`
- `ingest.chunk_page_limit`
- `ingest.mineru_batch_size`
- `ingest.mineru_upload_workers`
- `ingest.mineru_upload_retries`
- `ingest.mineru_download_retries`
- `ingest.mineru_poll_timeout`
- `ingest.pdf_fallback_order`
- `ingest.pdf_fallback_auto_detect`
- `patent.uspto_odp_api_key`
- backup configuration surface

Relevant sources:

- `scholaraio/config.py:172-342`
- `scholaraio/config.py:859-929`
- `scholaraio/services/setup.py:1033-1105`

This is not a hardcoding bug in the same sense as direct path construction, but it **is** a product/configuration gap:

- the code supports these fields
- the generated config template does not surface many of them

That means future config work should update:

- `config.py`
- setup template / setup wizard
- configuration docs

in the same change set whenever new config is added.

### 9.1 Duplicated Defaults Outside `Config`

Some defaults already conceptually belong to `Config`, but implementation modules still repeat them when `cfg` is omitted.

This is not exactly the same as "missing config", but it is still a configuration problem because it creates multiple sources of truth.

#### MinerU duplicates

Current duplicated defaults include:

- `DEFAULT_API_URL = "http://localhost:8000"`
- `CLOUD_API_URL = "https://mineru.net/api/v4"`
- `DEFAULT_POLL_TIMEOUT = 900`
- `_DEFAULT_CLOUD_BATCH_SIZE = 20`

Sources:

- `scholaraio/providers/mineru.py:106` (`scholaraio/ingest/mineru.py` compatibility alias)
- `scholaraio/providers/mineru.py:127` (`scholaraio/ingest/mineru.py` compatibility alias)
- `scholaraio/providers/mineru.py:541` (`scholaraio/ingest/mineru.py` compatibility alias)
- `scholaraio/providers/mineru.py:740` (`scholaraio/ingest/mineru.py` compatibility alias)

These overlap with existing config-backed values such as:

- `ingest.mineru_endpoint`
- `ingest.mineru_cloud_url`
- `ingest.mineru_poll_timeout`
- `ingest.mineru_batch_size`

#### Embedding duplicates

Current duplicated defaults include:

- local embedding model defaults such as `Qwen/Qwen3-Embedding-0.6B`
- OpenAI-compatible embedding model fallback `text-embedding-3-small`
- default local cache dir `~/.cache/modelscope/hub/models`
- default API base `https://api.openai.com/v1`
- default API timeout / batch size / max retries inside `vectors.py`

Sources:

- `scholaraio/vectors.py:71-88`
- `scholaraio/vectors.py:162-178`
- `scholaraio/vectors.py:358-420`
- `scholaraio/vectors.py:629-637`

Recommendation:

- after the main path-authority wave, centralize these fallbacks so `Config` remains the primary default authority
- avoid introducing new module-level defaults for values that already have a home in `Config`

#### Workspace-output duplicates

Current duplicated defaults include:

- the fresh `<workspace>/_system/figures/` convention, now centralized behind `Config.workspace_figures_dir`
- the fresh `<workspace>/_system/output/output.docx` convention, now centralized behind `Config.workspace_docx_output_path`

Sources:

- `scholaraio/services/diagram.py:_default_out_dir`
- `scholaraio/interfaces/cli/paths.py:_workspace_figures_dir`
- `scholaraio/interfaces/cli/paths.py:_default_docx_output_path`
- `scholaraio/interfaces/cli/diagram.py:_build_diagram_out_path`
- `scholaraio/interfaces/cli/export.py:_cmd_export_docx`

Assessment:

- these do not necessarily belong in global config
- but they are still secondary sources of truth and therefore part of migration risk
- future workspace/output work should corral them behind one explicit convention instead of leaving them as repeated string literals

This is especially important for maintainability: otherwise config refactors can appear complete while behavior still depends on stale in-module fallback values.

## 10. Recommended Next Steps

### 10.1 First Wave

The first wave should focus only on path authority:

- expand `PathsConfig`
- add accessors for all runtime roots and queue roots
- migrate callers off `cfg._root / ...`

This gives the highest leverage for the directory upgrade work.

### 10.2 Second Wave

After path authority is in place:

- expose already-existing patent config through setup templates and configuration docs
- add missing MinerU timeout knobs
- add toolref network/discovery config
- add translation retry config
- consider metadata API timeout/retry config

### 10.3 Third Wave

Only after the first two waves:

- decide whether low-priority operational constants actually need user-facing config
- avoid widening config surface without a real support or deployment use case

## 11. Bottom Line

The main config problem in ScholarAIO today is **not** that there are too many hardcoded numbers.

The main config problem is:

**runtime layout authority is still split between `Config` and scattered path construction.**

If that is fixed first, the later upgrade and migration work becomes much cleaner. The remaining timeout/retry knobs can then be added in a controlled way instead of turning config into a grab bag.
