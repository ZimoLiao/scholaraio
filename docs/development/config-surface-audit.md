# ScholarAIO Config Surface Audit (Draft)

Status: Draft

Last Updated: 2026-04-17

Scope: repo-wide audit of hardcoded runtime paths, operational knobs, and external-service defaults that are candidates for formal configuration.

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
- main search DB (`paths.index_db`)
- logging and metrics DB
- LLM backend and timeouts
- embedding provider, model, cache, API settings
- ingest parser and many MinerU knobs
- search top-k
- topics model directory
- translation chunk size and concurrency
- backup target settings

However, the current `Config` surface is still incomplete in two important ways:

1. `PathsConfig` is much narrower than the actual runtime layout used by the codebase.
2. Several modules still bypass `Config` and construct runtime paths or operational defaults directly.

There is also a third, smaller but still important issue:

3. a few modules duplicate defaults that already conceptually belong to `Config`, creating secondary sources of truth when `cfg` is omitted.

The most important conclusion from this audit is:

**the highest-value config work is not adding more network knobs first; it is making `Config` the complete path authority for runtime layout.**

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

### 5.1 `PathsConfig` Is Too Narrow

Current `PathsConfig` only covers:

- `papers_dir`
- `index_db`

Source:

- `scholaraio/config.py:53-63`

But the runtime actually depends on many more path roots:

- `workspace/`
- `data/inbox/`
- `data/inbox-doc/`
- `data/inbox-thesis/`
- `data/inbox-patent/`
- `data/inbox-proceedings/`
- `data/pending/`
- `data/proceedings/`
- `data/explore/`
- `data/toolref/`
- `data/citation_styles/`
- `workspace/translation-ws/`

This mismatch is the main remaining layout-coupling problem.

### 5.2 `workspace_dir` Exists Only as a Hardcoded Property

Current behavior:

- `Config.workspace_dir` is hardcoded to `self._root / "workspace"`

Source:

- `scholaraio/config.py:377-380`

Downstream direct consumers:

- `scholaraio/cli.py:172`
- `scholaraio/cli.py:1956`
- `scholaraio/cli.py:2778`
- `scholaraio/cli.py:3130`
- `scholaraio/setup.py:536`

Recommendation:

- add `paths.workspace_dir`
- keep `Config.workspace_dir` as the accessor
- migrate callers to the accessor instead of `cfg._root / "workspace"`

### 5.3 Inbox and Queue Paths Are Still Built Ad Hoc

Current hardcoded runtime paths:

- `cfg._root / "data/inbox"`
- `cfg._root / "data" / "inbox-doc"`
- `cfg._root / "data" / "inbox-thesis"`
- `cfg._root / "data" / "inbox-patent"`
- `cfg._root / "data" / "inbox-proceedings"`
- `cfg._root / "data" / "pending"`

Key sources:

- `scholaraio/config.py:390-405`
- `scholaraio/ingest/pipeline.py:1314-1418`
- `scholaraio/ingest/pipeline.py:1554`
- `scholaraio/ingest/pipeline.py:2432`
- `scholaraio/cli.py:2508`
- `scholaraio/setup.py:531-538`

Recommendation:

- add explicit accessors for:
  - `inbox_dir`
  - `doc_inbox_dir`
  - `thesis_inbox_dir`
  - `patent_inbox_dir`
  - `proceedings_inbox_dir`
  - `pending_dir`

These are the most important path additions for migration readiness.

### 5.4 Proceedings Root and DB Path Are Still Root-Relative Helpers

Current behavior:

- `proceedings_db_path(root)` returns `root / "data" / "proceedings" / "proceedings.db"`
- pipeline still builds proceedings root with `ctx.cfg._root / "data" / "proceedings"`

Sources:

- `scholaraio/proceedings.py:14-15`
- `scholaraio/ingest/pipeline.py:2237`

Recommendation:

- add `paths.proceedings_dir`
- derive `proceedings_db` from `proceedings_dir`
- stop passing bare runtime root into proceedings path helpers

### 5.5 Explore Root Is Hardcoded Outside `Config`

Current behavior:

- explore storage uses `_DEFAULT_EXPLORE_DIR = Path("data/explore")`
- when cfg is provided, `_explore_dir()` returns `cfg._root / "data" / "explore" / name`
- CLI also walks `cfg._root / "data" / "explore"` directly

Sources:

- `scholaraio/explore.py:43-49`
- `scholaraio/explore.py:904-906`
- `scholaraio/cli.py:1641`
- `scholaraio/cli.py:1670`
- `scholaraio/cli.py:1696`

Recommendation:

- add `paths.explore_root`
- add `Config.explore_root` accessor
- update explore helper functions and CLI list/info commands to use that accessor

### 5.6 Toolref Root Is Hardcoded Outside `Config`

Current behavior:

- toolref uses `_DEFAULT_TOOLREF_DIR = Path("data/toolref")`
- `_toolref_root(cfg)` returns `cfg._root / "data" / "toolref"`

Source:

- `scholaraio/toolref/paths.py:9-18`

Recommendation:

- add `paths.toolref_root`
- move toolref path resolution fully behind `Config`

### 5.7 Citation Styles Path Is Derived Indirectly from `papers_dir`

Current behavior:

- `styles_dir(cfg)` returns `cfg.papers_dir.parent / "citation_styles"`

Source:

- `scholaraio/citation_styles.py:253-255`

This is a hidden coupling:

- citation styles are not actually conceptually subordinate to the papers directory
- they only happen to live next to it in the current layout

Recommendation:

- add `paths.citation_styles_dir`
- stop deriving citation styles location from the parent of `papers_dir`

### 5.8 Portable Translation Bundle Root Is Hardcoded

Current behavior:

- translation bundles are written to `workspace/translation-ws/<paper>/`
- the helper falls back to `paper_dir.parent.parent / "workspace"` if `config.workspace_dir` is not available

Source:

- `scholaraio/translate.py:578-595`

Related CLI/doc default:

- `scholaraio/cli.py:4096`

Recommendation:

- add an explicit config accessor such as `translation_bundle_root`
- keep it derived from workspace by default, but stop hardcoding the suffix and fallback path logic in helper code

This is especially important because future workspace restructuring has already been identified as part of the upgrade path.

### 5.9 Setup and Bootstrap Logic Still Assume Root-Level Config Filenames

Current behavior:

- setup generates `config.yaml` and `config.local.yaml` directly at runtime root
- config discovery searches for those exact names

Sources:

- `scholaraio/config.py:515-571`
- `scholaraio/setup.py:457-459`
- `scholaraio/setup.py:831`
- `scholaraio/setup.py:903`

Recommendation:

- do **not** make these filenames user-configurable now
- but explicitly recognize them as bootstrap contracts, not incidental strings

This belongs in the config/bootstrap design, not as a free-form user knob.

## 6. P1 Findings: Operational Knobs Worth Config After Path Authority

### 6.1 Webtools Endpoints and Timeouts Are Env-Only Today

Current behavior:

- web search / extraction services use:
  - `WEBSEARCH_URL`
  - `WEBEXTRACT_URL`
  - `WEBSEARCH_API_KEY`
  - `WEBEXTRACT_API_KEY`
- defaults are hardcoded to local ports
- health/search/extract/batch timeouts are hardcoded

Source:

- `scholaraio/sources/webtools.py:10-101`

Recommendation:

- add a dedicated `webtools` config section
- move these into config with env vars as override/fallback

Suggested fields:

- `websearch_url`
- `webextract_url`
- `websearch_api_key`
- `webextract_api_key`
- `health_timeout`
- `search_timeout`
- `extract_timeout`
- `batch_extract_timeout`

Why this is worth config:

- these services are deployment-specific by nature
- env-only configuration makes reproducibility and support harder

### 6.2 MinerU Still Has Several Timeout Constants Outside Config

Current behavior:

- `API_TIMEOUT = 600`
- `DEFAULT_UPLOAD_TIMEOUT = 120`
- `DEFAULT_DOWNLOAD_TIMEOUT = 120`

Sources:

- `scholaraio/ingest/mineru.py:121-123`

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

- `scholaraio/explore.py:114-115`
- `scholaraio/explore.py:206-219`

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

- `scholaraio/translate.py:338`
- `scholaraio/translate.py:556-575`

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

- `scholaraio/ingest/pdf_fallback.py:131-136`

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

- `scholaraio/insights.py:46`
- `scholaraio/insights.py:124`
- `scholaraio/insights.py:138-145`

Assessment:

- if these need tuning, CLI flags are probably a better first step than global config

### 7.4 Default DOCX Output Path

Current behavior:

- document export defaults to `workspace/output.docx`

Source:

- `scholaraio/cli.py:1911`

Assessment:

- this is better handled by a future workspace/output convention than by global config

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

- `scholaraio/ingest/mineru.py:129-132`
- `scholaraio/ingest/mineru.py:870-875`

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
- backup configuration surface

Relevant sources:

- `scholaraio/config.py:172-240`
- `scholaraio/config.py:304-318`
- `scholaraio/setup.py:1033-1105`

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

- `scholaraio/ingest/mineru.py:106`
- `scholaraio/ingest/mineru.py:127`
- `scholaraio/ingest/mineru.py:541`
- `scholaraio/ingest/mineru.py:740`

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

- add `webtools` config
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
