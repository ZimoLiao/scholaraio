# ScholarAIO Directory Migration Execution Sequence

Status: Historical compatibility-window record

Last Updated: 2026-04-24

Scope: historical execution order for directory and path migration. This file preserves
the compatibility-window migration record; it is no longer the source of truth for
the active breaking-cleanup runtime.

2026-04-24 breaking cleanup note:

- this document remains the historical execution record for the compatibility-window generation
- current runtime behavior is no longer compatibility-window behavior: legacy public import facades are removed and legacy runtime roots are no longer auto-opened
- the active breaking-generation execution authority is kept in internal release-gate records
- the hardened post-migration user cleanup flow is now `scholaraio migrate finalize --confirm`

## 1. Purpose

This document defines the recommended execution order for migrating ScholarAIO toward the target directory structure described in `docs/design-docs/directory-structure-spec.md`.

This is an implementation-order document, not a vision document. Its job is to answer:

- what MUST be frozen first
- what MUST be abstracted before any physical move
- when migration control-plane work MUST land before real user-data moves
- which migrations are low-risk leaf moves
- which migrations are high-risk and MUST be deferred
- how to keep multi-agent skill discovery and current CLI behavior working during the transition

This document should be read together with:

- `docs/design-docs/migration-mechanism-spec.md`

That companion document defines the control-plane contract (`instance.json`, `migration.lock`, journal, verification, cleanup gating). This document defines when that machinery must appear in the execution order.

## 2. Audited Baseline

The sequence below is based on direct inspection of the current codebase and on path-related regression tests revalidated on 2026-04-19 after the earlier 2026-04-16, 2026-04-17, and 2026-04-18 audits.

### 2.1 Code Areas Audited

The entries in this subsection describe the compatibility-window state that was
audited before the 2026-04-24 breaking cleanup. Parenthetical legacy import paths
below are historical targets from that window; they are not active public facades
in the current release generation.

- `scholaraio/core/config.py` (`scholaraio.config` compatibility alias)
- `scholaraio/cli.py`
- `scholaraio/projects/workspace.py` (`scholaraio.workspace` compatibility alias)
- `scholaraio/services/insights.py` (`scholaraio.insights` compatibility alias)
- `scholaraio/services/setup.py` (`scholaraio.setup` compatibility alias)
- `scholaraio/services/index.py` (`scholaraio.index` compatibility alias)
- `scholaraio/services/loader.py` (`scholaraio.loader` compatibility alias)
- `scholaraio/services/topics.py` (`scholaraio.topics` compatibility alias)
- `scholaraio/services/vectors.py` (`scholaraio.vectors` compatibility alias)
- `scholaraio/stores/explore.py` (`scholaraio.explore` compatibility alias)
- `scholaraio/services/diagram.py` (`scholaraio.diagram` compatibility alias)
- `scholaraio/stores/proceedings.py` (`scholaraio.proceedings` compatibility alias)
- `scholaraio/services/patent_fetch.py` (`scholaraio.patent_fetch` compatibility alias)
- `scholaraio/providers/arxiv.py` (`scholaraio.sources.arxiv` compatibility alias)
- `scholaraio/providers/endnote.py` (`scholaraio.sources.endnote` compatibility alias)
- `scholaraio/providers/zotero.py` (`scholaraio.sources.zotero` compatibility alias)
- `scholaraio/providers/mineru.py` (`scholaraio.ingest.mineru` compatibility alias)
- `scholaraio/providers/pdf_fallback.py` (`scholaraio.ingest.pdf_fallback` compatibility alias)
- `scholaraio/services/ingest_metadata/extractor.py` (`scholaraio.ingest.extractor` compatibility alias)
- `scholaraio/services/ingest/parser_matrix_benchmark.py` (`scholaraio.ingest.parser_matrix_benchmark` compatibility alias)
- `scholaraio/services/ingest/proceedings_volume.py` (`scholaraio.ingest.proceedings` compatibility alias)
- `scholaraio/providers/uspto_odp.py` (`scholaraio.uspto_odp` compatibility alias)
- `scholaraio/providers/uspto_ppubs.py` (`scholaraio.uspto_ppubs` compatibility alias)
- `scholaraio/services/backup.py` (`scholaraio.backup` compatibility alias)
- `scholaraio/sources/webtools.py`
- `scholaraio/toolref/paths.py`
- `scholaraio/toolref/_legacy_snapshot.py`
- `scholaraio/stores/citation_styles.py` (`scholaraio.citation_styles` compatibility alias)
- `scholaraio/services/translate.py` (`scholaraio.translate` compatibility alias)
- `scholaraio/services/ingest/pipeline.py` (`scholaraio.ingest.pipeline` compatibility alias)
- `.qwen/QWEN.md`
- `clawhub.yaml`
- `.cursor/rules/scholaraio.mdc`

Historical audited facts from the compatibility-window generation:

The following bullets intentionally preserve the pre-cleanup compatibility
language used during migration planning. In the active release generation, legacy
public import facades have been removed; see the internal breaking-cleanup
release gate and `docs/guide/agent-reference.md` for the current contract.

- `scholaraio/core/config.py` now exposes a much broader runtime-path accessor surface and routes `ensure_dirs()` through those accessors, which lowers path-migration risk but does not yet remove direct path construction in downstream modules
- `scholaraio/core/config.py` now resolves `index_db`, `metrics_db_path`, and `topics_model_dir` through logical `state_root` subdirectories for fresh installs, while still auto-detecting existing legacy `data/index.db`, `data/metrics.db`, and `data/topic_model/` stores
- `scholaraio/core/config.py` locks current root-level `config.yaml` discovery behavior; `scholaraio.config` remains the legacy import path for compatibility
- `scholaraio/projects/workspace.py` now owns the workspace paper-index layout contract and supports both legacy root `papers.json` and future-compatible `refs/papers.json`; `scholaraio.workspace` remains the compatibility alias
- `scholaraio/cli.py` now routes workspace-root defaults through `_workspace_root()` and defers workspace index existence checks to `scholaraio.workspace`
- `scholaraio/services/setup.py:531-537` now checks current runtime directories via `Config` accessors instead of fixed string literals
- `scholaraio/services/index.py` now owns keyword search, proceedings search, registry lookup, citation graph helpers, and unified search orchestration; `scholaraio.index` remains a module alias so CLI and tests can keep using the public legacy import path
- `scholaraio/services/loader.py` now owns L1-L4 layered paper loading, agent notes, TOC enrichment, and L3 extraction; `scholaraio.loader` remains a module alias so CLI and tests can keep using the public legacy import path
- `scholaraio/services/topics.py` now owns BERTopic fitting, topic browsing, reduction/merge helpers, model persistence, and visualizations; `scholaraio.topics` remains a module alias so CLI, explore, workspace, and tests can keep using the public legacy import path
- `scholaraio/services/vectors.py` now owns embedding backend selection, vector index maintenance, FAISS helpers, and semantic search; `scholaraio.vectors` remains a module alias so CLI, topics, explore, and tests can keep using the public legacy import path
- `scholaraio/stores/explore.py` now follows `cfg.explore_root`; `scholaraio.explore` remains the compatibility alias, fresh instances default to `data/libraries/explore/`, while existing legacy `data/explore/` remains auto-detected
- `scholaraio/services/diagram.py` now routes default output through `cfg.workspace_figures_dir`; fresh instances default to `workspace/_system/figures/`
- `scholaraio/stores/proceedings.py` now owns proceedings storage iteration and proceedings DB path helpers; `scholaraio.proceedings` remains a module alias so existing imports and monkeypatches still target the same implementation
- `scholaraio/services/patent_fetch.py:download_patent_pdf` now prefers `cfg.patent_inbox_dir`; fresh no-config defaults use `data/spool/inbox-patent`, while legacy `data/inbox-patent` remains auto-detected through `Config`
- `scholaraio/providers/arxiv.py` now owns arXiv search, metadata fetch, and PDF download helpers; `scholaraio.sources.arxiv` remains a module alias so existing imports and monkeypatches still target the same implementation
- `scholaraio/providers/endnote.py` now owns EndNote XML/RIS parsing and PDF attachment discovery; `scholaraio.sources.endnote` remains a module alias so existing imports and monkeypatches still target the same implementation
- `scholaraio/providers/zotero.py` now owns Zotero Web API and local SQLite parsing; `scholaraio.sources.zotero` remains a module alias so existing imports and monkeypatches still target the same implementation
- `scholaraio/providers/mineru.py` now owns MinerU local/cloud PDF parsing helpers and its module CLI; `scholaraio.ingest.mineru` remains a module alias/import-compatible CLI delegator so existing imports, monkeypatches, and `python -m scholaraio.ingest.mineru` still target the same implementation
- `scholaraio/providers/pdf_fallback.py` now owns Docling/PyMuPDF fallback parsing; `scholaraio.ingest.pdf_fallback` remains a module alias so existing imports and monkeypatches still target the same implementation
- `scholaraio/services/ingest_metadata/extractor.py` now owns Stage-1 metadata extraction modes; `scholaraio.ingest.extractor` remains a module alias so existing imports and monkeypatches still target the same implementation
- `scholaraio/services/ingest/parser_matrix_benchmark.py` now owns parser matrix benchmarking helpers; `scholaraio.ingest.parser_matrix_benchmark` remains a module alias so existing imports and monkeypatches still target the same implementation
- `scholaraio/services/ingest/proceedings_volume.py` now owns proceedings volume preparation, split-plan application, and clean-plan application; `scholaraio.ingest.proceedings` remains a module alias so existing imports and monkeypatches still target the same implementation
- `scholaraio/providers/uspto_odp.py` now owns the USPTO ODP API client; `scholaraio.uspto_odp` remains a module alias so existing imports and monkeypatches still target the same implementation
- `scholaraio/providers/uspto_ppubs.py` now owns the USPTO PPUBS session/search/PDF-export client; `scholaraio.uspto_ppubs` remains a module alias so existing imports and monkeypatches still target the same implementation
- `scholaraio/services/ingest/pipeline.py` now exposes the ingest pipeline compatibility facade, and routes inbox/pending/proceedings defaults through small accessor helpers (`_inbox_dir`, `_pending_dir`, `_proceedings_dir`, etc.), with fresh queue defaults under `data/spool/`
- `scholaraio/services/backup.py` plus `scholaraio/core/config.py` confirm backup still defaults to syncing `data/`, not the full runtime root
- At the time of this migration, `scholaraio/providers/webtools.py` formed the external-adapter seam for rendered extraction and legacy search compatibility. That adapter was removed after the migration when live web access moved fully to host-native agent capabilities.
- `scholaraio/toolref/paths.py:9-20` now follows `cfg.toolref_root`; fresh instances default to `data/libraries/toolref/`, while existing legacy `data/toolref/` remains auto-detected
- `scholaraio/toolref/_legacy_snapshot.py:111-130` preserves the same `cfg.toolref_root` behavior in a parallel legacy implementation
- `scholaraio/stores/citation_styles.py:253-255` now follows `cfg.citation_styles_dir`; fresh instances default to `data/libraries/citation_styles/`, while existing legacy `data/citation_styles/` remains auto-detected
- `scholaraio/services/translate.py` now resolves portable translation bundles through `cfg.translation_bundle_root`; fresh instances default to `workspace/_system/translation-bundles/`
- `scholaraio/services/ingest/pipeline.py` still concentrates the compatibility surface for queue/proceedings orchestration, but its default directory resolution now flows through explicit helper functions instead of raw literals
- `.qwen/QWEN.md:9-13` and `clawhub.yaml:16-127` confirm that skill discovery is rooted in `.claude/skills/`
- `tests/test_cursor_rules.py:8-27`, `tests/test_academic_writing_skills.py:80-87`, `tests/test_workspace.py`, `tests/test_explore.py:42-43`, and `tests/test_translate.py:230-320` lock the current discovery and path contracts, including workspace legacy/future compatibility plus configured translation-bundle overrides

### 2.2 Tests Run

The following test batches were executed successfully as migration-baseline verification:

```bash
python -m pytest -q \
  tests/test_cursor_rules.py \
  tests/test_writing_docs_alignment.py \
  tests/test_academic_writing_skills.py \
  tests/test_skill_routing_smoke.py \
  tests/test_workspace.py \
  tests/test_config.py

python -m pytest -q \
  tests/test_explore.py \
  tests/test_translate.py \
  tests/test_webtools_source.py \
  tests/test_ingest_link_cli.py \
  tests/test_proceedings.py \
  tests/test_cli_messages.py

# 2026-04-17 revalidation after additional develop-branch merges
python -m pytest -q \
  tests/test_config.py \
  tests/test_explore.py \
  tests/test_translate.py \
  tests/test_proceedings.py \
  tests/test_metrics.py

python -m pytest -q \
  tests/test_patent_tools.py \
  tests/test_backup.py \
  tests/test_diagram.py \
  tests/test_document.py
```

Observed result:

- the combined baseline batch list above currently re-runs as `283` passing tests on 2026-04-18
- the 2026-04-17 revalidation batches also passed with `165` passing tests plus `100` passing tests and `3` skips
- no failures

## 3. Non-Negotiable Invariants

These constraints are already enforced by current code, wrappers, and tests. The migration sequence MUST treat them as frozen until their replacements are intentionally designed and tested.

### 3.1 Config Discovery Invariant

Compatibility-window behavior in `scholaraio/core/config.py` (before removal of
the legacy `scholaraio.config` import path):

- `load_config()` resolves paths relative to the directory containing `config.yaml`
- `_find_config_file()` searches upward for `config.yaml`
- fallback global config is `~/.scholaraio/config.yaml`

Implication:

- `config.yaml` and `config.local.yaml` MUST remain valid at runtime-instance root during early and middle migration phases
- moving config into `config/` MUST NOT happen before config discovery is redesigned

### 3.2 Root Agent Integration Invariant

Current wrappers and tests assume fixed root-level entry points:

- `AGENTS.md`
- `CLAUDE.md`
- `AGENTS_CN.md`
- `.qwen/QWEN.md`
- `.cursor/rules/`
- `.clinerules`
- `.windsurfrules`
- `.github/copilot-instructions.md`
- `.claude-plugin/`
- `clawhub.yaml`

Implication:

- these files and directories MUST NOT be moved as part of directory migration

### 3.3 Canonical Skill Root Invariant

Current audited behavior:

- `.claude/skills/` is the canonical skill source
- `.agents/skills`, `.qwen/skills`, and `skills` are compatibility aliases
- `clawhub.yaml` registers skill paths as `.claude/skills/<name>`
- `.qwen/QWEN.md` explicitly instructs Qwen to use `.qwen/skills/`
- tests assert `.cursor/rules/scholaraio.mdc` references `.claude/skills/*/SKILL.md`

Implication:

- no migration phase may move `SKILL.md` files into `scholaraio/`
- no migration phase may remove the repository-root discovery surfaces for skills

### 3.4 Runtime Top-Level Compatibility Invariant

Current code assumes both of the following runtime top-level directories exist:

- `data/`
- `workspace/`

Implication:

- early migration phases MUST keep those top-level anchors intact
- physical re-rooting under `data/libraries`, `data/spool`, `data/state`, and related subtrees can only happen after accessor cutover

### 3.5 Method Invariant

Migration MUST follow this order:

1. freeze invariants and tests
2. add path accessors
3. switch consumers to accessors
4. add compatibility readers/writers if formats change
5. perform physical moves last

Direct physical directory moves before consumer cutover are explicitly out of order.

## 4. Current Coupling Summary

The execution order below follows the actual current coupling, not the desired architecture.

### 4.1 `Config` Is Now the Runtime Path Authority for First Migration Roots

`scholaraio/core/config.py` currently exposes accessors for the major runtime roots:

- paper/workspace roots
- queue and pending roots
- proceedings/explore/toolref/citation-style durable-library roots
- state/cache/runtime roots
- control-plane roots

`ensure_dirs()` now routes through these accessors rather than recreating fixed legacy strings.

Implication:

- physical moves must continue to happen through explicit migration tooling, not by reintroducing raw path construction in consumers
- remaining migration phases should preserve explicit config overrides and legacy fallback behavior until cleanup has archived the old trees

### 4.2 Workspace Contract Is Hardcoded in Both Code and Tests

Current behavior:

- `scholaraio/projects/workspace.py` now owns the paper-index layout contract and can read both `<workspace-root>/<name>/papers.json` and `<workspace-root>/<name>/refs/papers.json`
- `scholaraio/projects/workspace.py` still creates new workspaces with root `papers.json` by default, but preserves existing future-compatible `refs/papers.json` layouts for reads and writes
- `scholaraio/cli.py` now routes workspace paths through `_workspace_root()` / `cfg.workspace_dir` and uses `scholaraio.workspace` helpers for workspace index detection
- `scholaraio/services/insights.py` now counts workspaces through `scholaraio.workspace.paper_count()`
- `scholaraio/services/diagram.py` defaults generated diagrams through `cfg.workspace_figures_dir`, which resolves to `<workspace>/_system/figures/` for fresh instances
- `scholaraio/interfaces/cli/export.py` defaults DOCX export through `cfg.workspace_docx_output_path`, which resolves to `<workspace>/_system/output/output.docx` for fresh instances
- `tests/test_workspace.py` now locks both legacy and future-compatible workspace paper-index contracts
- `tests/test_translate.py` locks both the fresh portable bundle default under `workspace/_system/translation-bundles/` and explicit `translation_bundle_root` overrides

Implication:

- workspace is still not ready for a direct physical move, but the compatibility bridge now exists inside `projects/workspace.py`
- later migration steps must build on that module boundary instead of bypassing it with direct `papers.json` path checks
- migration still must account for both named workspaces and legacy workspace-root output conventions

### 4.3 Ingest and Queue Paths Are Concentrated in `pipeline.py`

Current behavior:

- `scholaraio/services/ingest/pipeline.py` still owns the compatibility surface for queue/proceedings orchestration, but default directory resolution now uses helper accessors wired to `Config`
- `scholaraio/cli.py` now routes arXiv downloads through `cfg.inbox_dir` / `_default_inbox_dir()`
- `scholaraio/services/patent_fetch.py` now routes patent downloads through `cfg.patent_inbox_dir` when available, with legacy fallback preserved for compatibility
- `scholaraio/services/setup.py` checks configured queue roots, pending spool, and workspace through `Config`

Implication:

- queue/spool migration is a late, high-risk phase
- it MUST wait until path accessors exist and shallow consumers have already moved

### 4.4 Leaf Stores Already Form Natural Low-Risk Migration Units

Current audited path helpers:

- `scholaraio/stores/explore.py` now follows `cfg.explore_root` with a durable-library fresh default and legacy fallback
- `scholaraio/toolref/paths.py` now follows `cfg.toolref_root` with a durable-library fresh default and legacy fallback
- `scholaraio/toolref/_legacy_snapshot.py` still mirrors the same config-backed root behavior
- `scholaraio/stores/citation_styles.py` now follows `cfg.citation_styles_dir` with a durable-library fresh default and legacy fallback
- `scholaraio/services/translate.py` now resolves portable translation bundles through `translation_bundle_root`

Implication:

- these modules now already sit behind config-backed accessors before larger pipeline moves
- `explore`, `toolref`, `citation_styles`, and portable translation outputs are safer physical-move candidates than `papers`

### 4.5 Backup Scope Is Not a Migration Contract

Current behavior:

- `services/backup.py` keeps `scope: data` as the compatibility default and syncs `cfg.backup_source_dir`
- opt-in `scope: instance` targets cover config, data, workspace, published archives, and migration-control metadata with a restore manifest

Implication:

- backup remains a useful operator tool
- but migration design MUST NOT treat it as the primary rollback or relocation contract for runtime-layout upgrades

## 5. Execution Order

The migration is split into two tracks:

- **Track A**: runtime-instance directory migration
- **Track B**: source-repository package migration

Track A is the critical path and MUST happen first. Track B SHOULD begin only after Track A has established stable accessors and compatibility layers.

## 6. Track A: Runtime-Instance Migration

### Phase A0. Freeze Invariants and Expand Regression Coverage

Objective:

- lock down the currently relied-on root integration surfaces and path contracts

Actions:

- keep root agent wrappers and `.claude/skills/` unchanged
- keep top-level `data/` and `workspace/` unchanged
- treat the current test batches in Section 2.2 as the minimum migration baseline
- add any missing tests only for newly introduced accessors and compatibility behavior

Do not do yet:

- no directory renames
- no symlink migration tricks
- no moving `config.yaml`

Exit criteria:

- path-related baseline tests remain green
- migration work starts from a known compatibility floor

### Phase A1. Make `Config` the Complete Path Authority

Objective:

- eliminate hardcoded runtime paths from leaf modules and orchestration code by first exposing them through `Config`

Primary audit reference: internal config-surface audit records.

Required additions in or around `scholaraio/core/config.py`:

- inbox path accessors
  - `inbox_dir`
  - `doc_inbox_dir`
  - `thesis_inbox_dir`
  - `patent_inbox_dir`
  - `proceedings_inbox_dir`
- durable/runtime accessors
  - `pending_dir`
  - `proceedings_dir`
  - `explore_root`
  - `toolref_root`
  - `citation_styles_dir`
  - `translation_bundle_root`
- future-state accessors
  - `state_root`
  - `cache_root`
  - `runtime_root`

Immediate consumer updates in this phase:

- `Config.ensure_dirs()` must switch to the new accessors
- `scholaraio/services/setup.py` directory checks must switch to the new accessors

Rationale:

- these are the lowest-level central choke points
- if this phase is skipped, later moves will produce duplicated path logic

Exit criteria:

- no module still needs to invent raw runtime paths for the directories above
- defaults still resolve to the current physical layout
- existing behavior remains unchanged

### Phase A2. Cut Over Leaf Store Consumers First

Objective:

- convert low-blast-radius modules to accessor-based path resolution while keeping the physical layout unchanged

Modules in scope:

- `scholaraio/stores/explore.py` (`scholaraio.explore` compatibility alias)
- `scholaraio/toolref/paths.py`
- `scholaraio/toolref/_legacy_snapshot.py`
- `scholaraio/stores/citation_styles.py` (`scholaraio.citation_styles` compatibility alias)
- `scholaraio/services/translate.py` (`scholaraio.translate` compatibility alias)

Required changes:

- replace `cfg._root / "data" / ...` constructions with `Config` accessors
- preserve the new `citation_styles_dir` accessor behavior: fresh durable-library default plus legacy fallback until cleanup is complete
- stop hardcoding `workspace/translation-ws/` in helper implementations; route through `translation_bundle_root`

Why this phase comes early:

- these modules already have narrow, local path boundaries
- they are easier to validate than `pipeline.py`

Exit criteria:

- `tests/test_explore.py` and `tests/test_translate.py` still pass
- equivalent path-override tests exist for the new accessors
- no physical directory move has happened yet

### Phase A3. Cut Over Shallow CLI and Analytics Consumers

Objective:

- remove direct `cfg._root / "workspace"` and similar constructions from non-orchestration interface code

Modules in scope:

- `scholaraio/cli.py`
- `scholaraio/services/insights.py` (`scholaraio.insights` compatibility alias)

Required changes:

- use `cfg.workspace_dir` everywhere instead of re-constructing workspace root
- use new path accessors for explore, translation, and patent-fetch defaults
- isolate legacy workspace-root output conventions such as `workspace/figures/` and `workspace/output.docx` behind explicit helpers or compatibility rules instead of raw literals
- keep CLI surface behavior unchanged

Why this phase is separate from A2:

- the CLI touches more commands and user-facing defaults
- but it is still lower risk than workspace schema change or ingest queue migration

Exit criteria:

- `cmd_ws`, `_resolve_ws_paper_ids`, arXiv inbox download, patent fetch defaults, and insights workspace listing no longer hardcode raw runtime paths where an accessor exists
- CLI output and user-facing defaults remain backward compatible

### Phase A4. Introduce Workspace Compatibility Layer Before Workspace Migration

Objective:

- make workspace independently evolvable without breaking the current `workspace/<name>/papers.json` contract

Current constraint:

- current code and tests treat `papers.json` at workspace root as the canonical paper-ref index

Required changes:

- extend `scholaraio/projects/workspace.py` to become the single authority for workspace layout
- add compatibility helpers so the module can read:
  - legacy root `papers.json`
  - future `refs/papers.json`
- if a future `workspace.yaml` manifest is introduced, treat it as additive first, not replacing legacy files immediately
- keep named workspaces as opaque/free-form project roots instead of turning them into rigid templates

Do not do yet:

- do not move workspaces out of the top-level `workspace/`
- do not remove support for root `papers.json`
- do not remove legacy workspace-root outputs until explicit compatibility helpers or migration rules own them

Rationale:

- workspace is evolving from paper subset into project boundary
- that evolution needs a compatibility bridge, not a direct cut

### Phase A4 Outcome: Workspace Topology Decision

For the compatibility window and the next migration design pass, the workspace-topology direction is now fixed:

- named workspaces remain opaque/free-form project roots
- `workspace/translation-ws/` -> `workspace/_system/translation-bundles/`
- `workspace/figures/` -> `workspace/_system/figures/`
- `workspace/output.*` -> `workspace/_system/output/`
- the minimal additive `workspace.yaml` envelope is `schema_version`, optional `name` / `description` / `tags`, optional explicit `mounts`, and optional `outputs`; it MUST NOT replace root `papers.json` or future-compatible `refs/papers.json`
- the validation/normalization policy for that minimal envelope is also fixed: absent manifests stay valid, unknown keys are preserved, `outputs.default_dir` stays workspace-relative, and shared-store mounts are logical IDs rather than physical paths
- `explore` remains a shared store for the compatibility window; if workspace-local mounts are added later, they MUST be explicit manifest-declared opt-ins and SHOULD start read-only
- `.claude/skills/` remains the canonical skill source and is not a migration target
- only outputs that are explicitly scoped to a named workspace should later use `workspace/<name>/outputs/`

Exit criteria:

- `workspace.py` owns the layout contract
- `tests/test_workspace.py` still pass
- new tests cover legacy and future-compatible readers

Implementation status (2026-04-20):

- completed in code: `workspace.py`, `cli.py`, and `insights.py` now consume the compatibility layer instead of assuming only root `papers.json`
- completed in code: `projects/workspace.py:read_manifest()` now parses `workspace.yaml` when present, normalizes supported schema-v1 metadata, preserves unknown top-level keys, rejects path-like shared-store mounts, and treats newer schema versions as opaque metadata instead of rewriting them blindly
- completed in code: `interfaces/cli/workspace.py` now surfaces additive `workspace.yaml` metadata in `ws list` / `ws show`, while keeping manifest-declared mounts informational only and not turning them into active runtime routing
- verified with targeted tests plus real CLI smoke on a future-compatible `refs/papers.json` workspace

### Phase A5. Abstract Queue and Proceedings Paths in `pipeline.py`

Objective:

- cut over the highest-risk runtime path knot only after accessor and workspace groundwork are in place

Modules in scope:

- `scholaraio/services/ingest/pipeline.py` (`scholaraio.ingest.pipeline` compatibility alias)
- queue-related parts of `scholaraio/cli.py`
- `scholaraio/services/setup.py` (`scholaraio.setup` compatibility alias)

Required changes:

- replace all hardcoded queue and pending paths in `run_pipeline()`
- replace queue and proceedings path construction in helper functions such as:
  - `import_external()`
  - `_move_to_pending()`
  - proceedings ingest context helpers
- route arXiv and ingest-link related temporary and default paths through accessors where appropriate

Why this is late:

- `pipeline.py` is the densest operational hub for runtime directories
- changing it before A1-A4 would mix accessor introduction, queue semantics, and physical moves in one step

Exit criteria:

- pipeline logic can operate entirely from accessor-provided queue/store paths
- `tests/test_ingest_link_cli.py` and `tests/test_proceedings.py` still pass
- the physical layout is still backward compatible

### Phase A6. Split State/Cache/Runtime Logically Before Moving Libraries

Objective:

- make internal state directories explicit while leaving user-facing libraries stable

Current central state locations:

- `index.db`
- `metrics.db`
- `topic_model/`

Required changes:

- back them with explicit logical roots such as:
  - `data/state/search/`
  - `data/state/metrics/`
  - `data/state/topics/`
- treat cache-like directories separately from durable stores
- keep existing defaults until all consumers are accessorized

Why this phase precedes major library moves:

- state and cache boundaries are easier to isolate than `papers`
- they reduce later ambiguity over what is safe to rebuild

Exit criteria:

- search, metrics, and topic-model paths are no longer special cases hidden in unrelated config fields
- migration can now distinguish durable stores from rebuildable internals

Implementation status (2026-04-19):

- completed in code: `Config` now exposes logical `search_state_dir`, `metrics_state_dir`, and `topics_state_dir`
- completed in code: fresh configs default to `data/state/search/index.db`, `data/state/metrics/metrics.db`, and `data/state/topics/`
- compatibility retained: existing `data/index.db`, `data/metrics.db`, and `data/topic_model/` are still discovered automatically when present
- remaining work: physical migration tooling and broader state/cache policy are still deferred to later phases

### Phase A6.5. Introduce Migration Control Plane Before Physical Moves

Objective:

- land the minimum migration control plane before any real user-data directory relocation happens

Required changes:

- reserve the root-level `.scholaraio-control/` directory
- introduce `instance.json`
- introduce `migration.lock`
- introduce per-run migration journals
- introduce explicit verification state
- ensure startup still does compatibility reading without silently performing large moves

Required reference:

- align this phase with `docs/design-docs/migration-mechanism-spec.md`

Why this phase exists here:

- once A7 starts, ScholarAIO is no longer just refactoring paths; it is performing real user-data migration work
- physical moves without the control plane would make rollback, verification, and operator support much weaker

Exit criteria:

- the codebase has a stable root-level control directory contract
- migration can mark runtime roots as legacy / normal / migrating / recovery-needed
- command gating exists while migration is active
- no physical move depends on implicit or startup-time relocation

Historical implementation status during the compatibility window (2026-04-23,
superseded by the 2026-04-24 breaking cleanup):

The bullets below are retained as an execution log. Statements that a legacy
module path "remains" an alias refer to the compatibility-window implementation,
not to the active release generation.

- completed in code for the compatibility window: `Config` exposes `.scholaraio-control/`, `instance.json`, `migration.lock`, and journal-root accessors
- completed in code for the compatibility window: normal CLI startup bootstraps a minimal `instance.json` with `legacy_implicit` state when metadata is absent
- completed in code for the compatibility window: normal CLI commands fail fast while `migration.lock` exists, and `scholaraio migrate status|recover --clear-lock` provides the recovery surface
- completed in code for the compatibility window: normal CLI commands also fail fast when `instance.json.layout_version` is newer than the running program supports, while `migrate status` remains available for diagnosis
- completed in code for the compatibility window: migration journals can be scaffolded under `.scholaraio-control/migrations/<migration-id>/`, and `migrate status` reports the current journal inventory
- completed in code for the compatibility window: `scholaraio migrate plan` creates a non-executing journal-backed inventory record (`plan.json`) with store-level target metadata and planned legacy-move records
- completed in code for the compatibility window: `scholaraio migrate verify` refreshes `verify.json` and records component-aware checks covering papers/workspaces/index-registry/keyword-search/citation-style loadability/explore openability/toolref current-version resolution/proceedings search/translation-resume inventory
- completed in code for the compatibility window: `scholaraio migrate run --store citation_styles --confirm`, `toolref`, `explore`, `proceedings`, `spool`, and `papers` copy legacy stores into their current targets and record cleanup candidates
- completed in code for the compatibility window: `scholaraio migrate cleanup` enforces a passed-verify gate, records preview/confirm journal steps, and archives explicit cleanup candidates under the migration journal instead of deleting them directly
- policy is fixed: compatibility fallback readers stay in place through a full deprecation window and may be removed only in a later breaking-layout generation with an approved rollout plan

### Phase A7. Physically Move Isolated Libraries First

Objective:

- perform the first real physical directory moves on lower-risk durable stores

Recommended move order:

1. `citation_styles`
2. `toolref`
3. `explore`

Target subtree:

- `data/libraries/`

Recommended approach:

- switch defaults to the new target paths only after A1-A6.5 are complete
- use explicit migration tooling as the primary mechanism
- only use temporary compatibility symlinks if they are covered by the same migration and verification flow

Why these three come first:

- they already have relatively self-contained path logic
- they are less central than `papers`
- current tests already isolate `explore` and writing/skill discovery separately

Exit criteria:

- each store can be relocated without editing unrelated modules
- path consumers read only from accessors
- compatibility behavior is documented and tested

### Phase A8. Move `proceedings` as a Durable Library

Objective:

- move `data/proceedings` into the durable-library subtree only after pipeline consumers no longer depend on fixed raw paths

Target:

- `data/libraries/proceedings/`

Why this is not grouped with A7:

- `proceedings` is more tightly coupled to ingest orchestration than `toolref`, `explore`, or `citation_styles`
- it should move only after A5 has finished queue/proceedings path abstraction

Why this still happens before `papers`:

- it is materially less central than the main paper library
- moving it earlier helps validate the durable-library migration pattern before the highest-risk store move

Exit criteria:

- proceedings ingest helpers, CLI flows, and tests no longer assume the legacy physical location directly
- durable proceedings storage is clearly separated from proceedings inbox/spool semantics

Implementation status (2026-04-20):

- completed in code for the compatibility window: fresh `Config.proceedings_dir` resolves to `data/libraries/proceedings/`, existing `data/proceedings/` remains readable as a legacy fallback, `migrate run --store proceedings --confirm` copies the full tree, and `migrate cleanup --confirm` archives the legacy tree into the migration journal

### Phase A9. Physically Move Queue/Spool Subtree

Objective:

- move queue-like content under `data/spool/` only after pipeline consumers have been fully abstracted

Recommended target:

- `data/spool/inbox`
- `data/spool/inbox-thesis`
- `data/spool/inbox-patent`
- `data/spool/inbox-doc`
- `data/spool/inbox-proceedings`
- `data/spool/pending`

Notes:

- queue migration MUST include user-facing documentation changes because users directly interact with inbox directories

Exit criteria:

- ingest commands, setup checks, and docs all agree on spool semantics
- no pipeline code still assumes legacy queue paths directly

Implementation status (2026-04-20):

- completed in code for the compatibility window: fresh `Config` queue roots resolve to `data/spool/inbox*` and `data/spool/pending`, existing legacy `data/inbox*` and `data/pending` queues remain readable as legacy fallbacks, `migrate run --store spool --confirm` copies all queue roots into `data/spool/`, and `migrate cleanup --confirm` archives the legacy queue roots into the migration journal

### Phase A10. Move `papers` Last

Objective:

- migrate the main paper library only after all less-central stores and queue/state layers are already stable

Target:

- `data/libraries/papers/`

Why this is last:

- `papers` is used by the largest number of modules
- `papers` affects search, vectors, topics, workspace references, notes, export, enrich, audit, translate, and many CLI flows
- current tests, docs, and code all assume it is the center of the system

Required preconditions:

- A1 through A9 complete
- no remaining direct consumer builds `data/papers` by string/path convention
- registry and UUID-based lookups remain stable across the move

Exit criteria:

- `papers` physical location is no longer special-cased anywhere outside configuration and explicit migration tooling

Implementation status (2026-04-20):

- completed in code for the compatibility window: fresh `Config.papers_dir` resolves to `data/libraries/papers/`, legacy-default aliases such as `data/papers` continue to auto-detect existing legacy libraries, `migrate run --store papers --confirm` copies the full paper tree, and `migrate cleanup --confirm` archives the legacy paper tree into the migration journal

### Phase A11. Freeze Compatibility Window and Update Public Docs

Objective:

- finish Track A for this upgrade generation without breaking existing runtime roots

Actions:

- keep legacy fallback readers during the migration-capable compatibility window
- update `AGENTS.md`, `CLAUDE.md`, README, setup docs, and relevant skills to describe the final runtime layout plus explicit legacy auto-detection
- keep skill discovery surfaces unchanged unless a separate wrapper-versioning plan exists

Exit criteria:

- current public docs point users at the new layout while still explaining how existing legacy layouts are handled
- compatibility-removal work is not attempted until a later breaking-layout generation has an approved rollout plan

Do not do yet:

- do not remove `Config` legacy fallback readers in this branch
- do not remove workspace `papers.json` compatibility
- do not delete legacy import paths while Track B only has namespace skeletons

Implementation status (2026-04-20):

- completed for the non-breaking upgrade window: public docs, agent instructions, setup guidance, and relevant skills now point to `data/libraries/`, `data/spool/`, and `data/state/` defaults while documenting legacy auto-detection and explicit migration tooling

## 7. Track B: Source-Repository Package Migration

Track B is intentionally later and slower than Track A.

### Phase B0. Reserve `gui/` Immediately

Low-risk action:

- create or keep top-level `gui/` as a reserved source directory at any time

Constraint:

- `gui/` MUST remain presentation-only
- it MUST NOT read raw runtime directories as if they were stable internal APIs

Implementation status (2026-04-20):

- completed as a boundary reservation: `gui/README.md` exists and documents that GUI code must remain presentation-oriented and must not become the source of truth for runtime layout or business behavior

### Phase B1. Introduce New Package Namespaces Without Moving Behavior Yet

Recommended target namespaces:

- `scholaraio/core/`
- `scholaraio/providers/`
- `scholaraio/stores/`
- `scholaraio/projects/`
- `scholaraio/services/`
- `scholaraio/interfaces/`
- `scholaraio/compat/`

Method:

- introduce new packages first
- use re-export shims from old module locations during migration

Why not earlier:

- at the time of the initial plan, imports were still broadly flat
- moving source files before runtime-path stabilization would have mixed two refactors into one risk envelope

Historical implementation status during the compatibility window (2026-04-23;
superseded by the 2026-04-24 breaking cleanup):

- completed for the then-active compatibility window: the target packages were importable, behavior had moved into canonical `core` / `providers` / `stores` / `projects` / `services` namespaces, and legacy public module paths were still compatibility aliases at that time
- completed in code for canonical implementation roots: internal imports now target canonical namespaces directly instead of depending on legacy facade modules

### Phase B2. Move Low-Coupling Modules Before Central Orchestrators

Recommended order:

1. store-like or provider-like leaves
   - `toolref/*`
   - `explore.py`
   - `citation_styles.py`
   - `proceedings.py`
   - `sources/webtools.py`
   - `uspto_odp.py`
   - `uspto_ppubs.py`
2. project boundary module
   - `workspace.py`
3. service modules
   - `diagram.py`
   - `translate.py`
   - `insights.py`
   - ingest metadata helpers

Additional constraint for `webtools`:

- preserve current user-facing capability names such as `webextract` and `ingest-link`
- but move the backend contract toward a provider boundary so the same logical capability can later be backed either by the current HTTP services or by an MCP-style transport without rewriting the CLI/skill surface first
- do not treat the current skill packaging or localhost HTTP defaults as the long-term architectural contract

Late movers:

- `cli.py`
- `services/ingest/pipeline.py` (`ingest/pipeline.py` compatibility alias)

Reason:

- these two remain the largest cross-cutting surfaces in the current architecture

Historical implementation status during the compatibility window (2026-04-23;
superseded by the 2026-04-24 breaking cleanup):

The bullets below are retained as historical execution notes. Statements that a
legacy module path "remains" an alias do not describe the active breaking-cleanup
release generation.

- started with non-disruptive namespace adapters only: `scholaraio.core.config`, `scholaraio.core.log`, `scholaraio.stores.citation_styles`, `scholaraio.stores.toolref`, `scholaraio.stores.explore`, `scholaraio.stores.proceedings`, `scholaraio.providers.arxiv`, `scholaraio.providers.endnote`, `scholaraio.providers.zotero`, `scholaraio.providers.mineru`, `scholaraio.providers.pdf_fallback`, `scholaraio.providers.webtools`, `scholaraio.providers.uspto_odp`, `scholaraio.providers.uspto_ppubs`, `scholaraio.projects.workspace`, `scholaraio.services.audit`, `scholaraio.services.backup`, `scholaraio.services.citation_check`, `scholaraio.services.diagram`, `scholaraio.services.document`, `scholaraio.services.export`, `scholaraio.services.index`, `scholaraio.services.loader`, `scholaraio.services.migration_control`, `scholaraio.services.patent_fetch`, `scholaraio.services.setup`, `scholaraio.services.topics`, `scholaraio.services.translate`, `scholaraio.services.vectors`, `scholaraio.services.insights`, `scholaraio.services.ingest_metadata` (including `extractor`), `scholaraio.services.ingest.parser_matrix_benchmark`, and `scholaraio.services.ingest.proceedings_volume` now re-export the existing implementations
- `config` implementation has moved to `scholaraio.core.config`; `scholaraio.config` remains a module alias so legacy monkeypatch/import paths still target the real implementation
- `log` implementation has moved to `scholaraio.core.log`; `scholaraio.log` remains a module alias so legacy monkeypatch/import paths still target the real implementation
- `audit` implementation has moved to `scholaraio.services.audit`; `scholaraio.audit` remains a module alias so legacy monkeypatch/import paths still target the real implementation
- `citation_styles` implementation has moved to `scholaraio.stores.citation_styles`; `scholaraio.citation_styles` remains a module alias so legacy monkeypatch/import paths still target the real implementation
- `papers` implementation has moved to `scholaraio.stores.papers`; `scholaraio.papers` remains a module alias so legacy monkeypatch/import paths still target the real implementation
- `proceedings` implementation has moved to `scholaraio.stores.proceedings`; `scholaraio.proceedings` remains a module alias so legacy monkeypatch/import paths still target the real implementation
- `webtools` implementation has moved to `scholaraio.providers.webtools`; `scholaraio.sources.webtools` remains a module alias so legacy monkeypatch/import paths still target the real implementation
- `arxiv` implementation has moved to `scholaraio.providers.arxiv`; `scholaraio.sources.arxiv` remains a module alias so legacy monkeypatch/import paths still target the real implementation
- `endnote` implementation has moved to `scholaraio.providers.endnote`; `scholaraio.sources.endnote` remains a module alias so legacy monkeypatch/import paths still target the real implementation
- `zotero` implementation has moved to `scholaraio.providers.zotero`; `scholaraio.sources.zotero` remains a module alias so legacy monkeypatch/import paths still target the real implementation
- `mineru` implementation has moved to `scholaraio.providers.mineru`; `scholaraio.ingest.mineru` remains a module alias and module-CLI delegator so legacy monkeypatch/import and `python -m` paths still target the real implementation
- `pdf_fallback` implementation has moved to `scholaraio.providers.pdf_fallback`; `scholaraio.ingest.pdf_fallback` remains a module alias so legacy monkeypatch/import paths still target the real implementation
- `ingest.extractor` implementation has moved to `scholaraio.services.ingest_metadata.extractor`; `scholaraio.ingest.extractor` remains a module alias so legacy monkeypatch/import paths still target the real implementation
- `parser_matrix_benchmark` implementation has moved to `scholaraio.services.ingest.parser_matrix_benchmark`; `scholaraio.ingest.parser_matrix_benchmark` remains a module alias so legacy monkeypatch/import paths still target the real implementation
- `ingest.proceedings` volume implementation has moved to `scholaraio.services.ingest.proceedings_volume`; `scholaraio.ingest.proceedings` remains a module alias so legacy monkeypatch/import paths still target the real implementation
- `uspto_odp` implementation has moved to `scholaraio.providers.uspto_odp`; `scholaraio.uspto_odp` remains a module alias so legacy monkeypatch/import paths still target the real implementation
- `uspto_ppubs` implementation has moved to `scholaraio.providers.uspto_ppubs`; `scholaraio.uspto_ppubs` remains a module alias so legacy monkeypatch/import paths still target the real implementation
- `explore` implementation has moved to `scholaraio.stores.explore`; `scholaraio.explore` remains a module alias so legacy monkeypatch/import paths still target the real implementation
- `workspace` implementation has moved to `scholaraio.projects.workspace`; `scholaraio.workspace` remains a module alias so legacy monkeypatch/import paths still target the real implementation
- `translate` implementation has moved to `scholaraio.services.translate`; `scholaraio.translate` remains a module alias so legacy monkeypatch/import paths still target the real implementation
- `insights` implementation has moved to `scholaraio.services.insights`; `scholaraio.insights` remains a module alias so legacy monkeypatch/import paths still target the real implementation
- `metrics` implementation has moved to `scholaraio.services.metrics`; `scholaraio.metrics` remains a module alias so legacy monkeypatch/import paths still target the real implementation
- `backup` implementation has moved to `scholaraio.services.backup`; `scholaraio.backup` remains a module alias so legacy monkeypatch/import paths still target the real implementation
- `citation_check` implementation has moved to `scholaraio.services.citation_check`; `scholaraio.citation_check` remains a module alias so legacy monkeypatch/import paths still target the real implementation
- `diagram` implementation has moved to `scholaraio.services.diagram`; `scholaraio.diagram` remains a module alias so legacy monkeypatch/import paths still target the real implementation
- `document` implementation has moved to `scholaraio.services.document`; `scholaraio.document` remains a module alias so legacy monkeypatch/import paths still target the real implementation
- `export` implementation has moved to `scholaraio.services.export`; `scholaraio.export` remains a module alias so legacy monkeypatch/import paths still target the real implementation
- `index` implementation has moved to `scholaraio.services.index`; `scholaraio.index` remains a module alias so legacy monkeypatch/import paths still target the real implementation
- `loader` implementation has moved to `scholaraio.services.loader`; `scholaraio.loader` remains a module alias so legacy monkeypatch/import paths still target the real implementation
- `topics` implementation has moved to `scholaraio.services.topics`; `scholaraio.topics` remains a module alias so legacy monkeypatch/import paths still target the real implementation
- `vectors` implementation has moved to `scholaraio.services.vectors`; `scholaraio.vectors` remains a module alias so legacy monkeypatch/import paths still target the real implementation
- `migration_control` implementation has moved to `scholaraio.services.migration_control`; `scholaraio.migration_control` remains a module alias so legacy monkeypatch/import paths still target the real implementation
- `patent_fetch` implementation has moved to `scholaraio.services.patent_fetch`; `scholaraio.patent_fetch` remains a module alias so legacy monkeypatch/import paths still target the real implementation
- `setup` implementation has moved to `scholaraio.services.setup`; `scholaraio.setup` remains a module alias so legacy monkeypatch/import paths still target the real implementation
- `toolref` implementation has moved to `scholaraio.stores.toolref`; `scholaraio.toolref` remains a package alias, including legacy submodule aliases such as `scholaraio.toolref.storage`
- `ingest.metadata` implementation has moved to `scholaraio.services.ingest_metadata`; `scholaraio.ingest.metadata` remains a package alias, including legacy submodule aliases such as `scholaraio.ingest.metadata._api`
- late movers (`cli.py` and `ingest/pipeline.py`) are now covered by Phase B3 facade splits; the ingest pipeline compatibility facade now lives at `scholaraio.services.ingest.pipeline`, while `scholaraio.ingest.pipeline` remains a module alias

### Phase B3. Split `cli.py` and `pipeline.py` Last

Recommended target:

- `interfaces/cli/` for command registration and per-domain handlers
- `services/ingest/` for pipeline orchestration and ingest subflows

Precondition:

- Track A runtime path abstraction must already be complete enough that these files are not also carrying directory migration risk

Implementation status (2026-04-20):

- `insights` command handling has moved to `scholaraio.interfaces.cli.insights`; `scholaraio.cli.cmd_insights` remains the parser-facing callable
- `metrics` command handling has moved to `scholaraio.interfaces.cli.metrics`; `scholaraio.cli.cmd_metrics` remains the parser-facing callable
- `translate` command handling has moved to `scholaraio.interfaces.cli.translate`; `scholaraio.cli.cmd_translate` remains the parser-facing callable
- `backup` command handling has moved to `scholaraio.interfaces.cli.backup`; `scholaraio.cli.cmd_backup` remains the parser-facing callable
- `style` command handling has moved to `scholaraio.interfaces.cli.style`; `scholaraio.cli.cmd_style` remains the parser-facing callable
- `document` command handling has moved to `scholaraio.interfaces.cli.document`; `scholaraio.cli.cmd_document` remains the parser-facing callable
- `export` command handling has moved to `scholaraio.interfaces.cli.export`; `scholaraio.cli.cmd_export` and existing `_cmd_export_*` helper aliases remain available
- `diagram` command handling has moved to `scholaraio.interfaces.cli.diagram`; `scholaraio.cli.cmd_diagram` and existing diagram helper aliases remain available
- `setup` command handling has moved to `scholaraio.interfaces.cli.setup`; `scholaraio.cli.cmd_setup` remains the parser-facing callable
- `index` command handling has moved to `scholaraio.interfaces.cli.index`; `scholaraio.cli.cmd_index` remains the parser-facing callable
- `search` and `search-author` command handling has moved to `scholaraio.interfaces.cli.search`; `scholaraio.cli.cmd_search` and `scholaraio.cli.cmd_search_author` remain parser-facing callables
- `top-cited` command handling has moved to `scholaraio.interfaces.cli.citations`; `scholaraio.cli.cmd_top_cited` remains the parser-facing callable
- `rename` command handling has moved to `scholaraio.interfaces.cli.rename`; `scholaraio.cli.cmd_rename` remains the parser-facing callable
- `audit` command handling has moved to `scholaraio.interfaces.cli.audit`; `scholaraio.cli.cmd_audit` remains the parser-facing callable
- citation-graph command handling (`refs`, `citing`, `shared-refs`) has moved to `scholaraio.interfaces.cli.graph`; the corresponding `scholaraio.cli.cmd_*` callables remain parser-facing aliases
- `toolref` command handling has moved to `scholaraio.interfaces.cli.toolref`; `scholaraio.cli.cmd_toolref` remains the parser-facing callable
- `show` command handling has moved to `scholaraio.interfaces.cli.show`; `scholaraio.cli.cmd_show` remains the parser-facing callable
- `citation-check` command handling has moved to `scholaraio.interfaces.cli.citation_check`; `scholaraio.cli.cmd_citation_check` remains the parser-facing callable
- `migrate` command handling has moved to `scholaraio.interfaces.cli.migrate`; `scholaraio.cli.cmd_migrate` remains the parser-facing callable
- `proceedings` command handling has moved to `scholaraio.interfaces.cli.proceedings`; `scholaraio.cli.cmd_proceedings` remains the parser-facing callable
- `import-endnote` command handling has moved to `scholaraio.interfaces.cli.import_endnote`; `scholaraio.cli.cmd_import_endnote` remains the parser-facing callable
- `import-zotero` command handling has moved to `scholaraio.interfaces.cli.import_zotero`; `scholaraio.cli.cmd_import_zotero` and the existing `_import_zotero_collections_as_workspaces` helper alias remain available
- `fsearch` command handling has moved to `scholaraio.interfaces.cli.fsearch`; `scholaraio.cli.cmd_fsearch` and existing arXiv lookup helper aliases remain available
- `ws` command handling has moved to `scholaraio.interfaces.cli.workspace`; `scholaraio.cli.cmd_ws` remains the parser-facing callable
- retrieval command handling (`embed`, `vsearch`, `usearch`) has moved to `scholaraio.interfaces.cli.retrieval`; the corresponding `scholaraio.cli.cmd_*` callables remain parser-facing aliases
- `repair` command handling has moved to `scholaraio.interfaces.cli.repair`; `scholaraio.cli.cmd_repair` remains the parser-facing callable
- `pipeline` command handling has moved to `scholaraio.interfaces.cli.pipeline`; `scholaraio.cli.cmd_pipeline` remains the parser-facing callable
- `backfill-abstract` command handling has moved to `scholaraio.interfaces.cli.backfill_abstract`; `scholaraio.cli.cmd_backfill_abstract` remains the parser-facing callable
- `topics` command handling has moved to `scholaraio.interfaces.cli.topics`; `scholaraio.cli.cmd_topics` and the existing `_write_all_viz` helper alias remain available
- `refetch` command handling has moved to `scholaraio.interfaces.cli.refetch`; `scholaraio.cli.cmd_refetch` remains the parser-facing callable
- enrichment command handling (`enrich-toc`, `enrich-l3`) has moved to `scholaraio.interfaces.cli.enrich`; `scholaraio.cli.cmd_enrich_*` and existing enrichment helper aliases remain available
- arXiv command handling (`arxiv search`, `arxiv fetch`) has moved to `scholaraio.interfaces.cli.arxiv`; the corresponding `scholaraio.cli.cmd_arxiv_*` callables remain parser-facing aliases
- rendered web command handling (`webextract`) has moved to `scholaraio.interfaces.cli.web`; the `_terminal_preview` helper alias remains available
- `explore` command handling has moved to `scholaraio.interfaces.cli.explore`; `scholaraio.cli.cmd_explore` and the existing `_explore_root` helper alias remain available
- `ingest-link` command handling has moved to `scholaraio.interfaces.cli.ingest_link`; `scholaraio.cli.cmd_ingest_link` and existing ingest-link helper aliases remain available
- patent command handling (`patent-fetch`, `patent-search`) has moved to `scholaraio.interfaces.cli.patent`; the corresponding `scholaraio.cli.cmd_patent_*` callables remain parser-facing aliases
- `attach-pdf` command handling has moved to `scholaraio.interfaces.cli.attach_pdf`; `scholaraio.cli.cmd_attach_pdf` and the existing `_batch_convert_pdfs` helper alias remain available
- shared CLI argument helpers have moved to `scholaraio.interfaces.cli.arguments`; legacy `scholaraio.cli._add_result_limit_arg`, `_resolve_result_limit`, `_resolve_top`, and `_add_filter_args` remain aliases
- shared CLI output/search formatting helpers have moved to `scholaraio.interfaces.cli.output`; legacy `scholaraio.cli._print_search_result`, `_print_search_next_steps`, `_format_match_tag`, and `_format_citations` remain aliases
- shared CLI optional-dependency diagnostics have moved to `scholaraio.interfaces.cli.dependencies`; legacy `scholaraio.cli._INSTALL_HINTS` and `_check_import_error` remain aliases and keep the old logging monkeypatch point
- shared CLI workspace/inbox path helpers have moved to `scholaraio.interfaces.cli.paths`; legacy `scholaraio.cli._resolve_ws_paper_ids`, `_workspace_root`, and `_default_inbox_dir` remain aliases and keep old UI/helper monkeypatch points
- shared CLI paper resolution/display helpers have moved to `scholaraio.interfaces.cli.paper`; legacy `scholaraio.cli._lookup_registry_by_candidates`, `_resolve_paper`, `_print_header`, and `_enrich_show_header` remain aliases and keep old UI/logging/helper monkeypatch points
- shared CLI search metrics recording has moved to `scholaraio.interfaces.cli.search_metrics`; legacy `scholaraio.cli._record_search_metrics` remains an alias and keeps the old logging monkeypatch point
- CLI runtime startup/gating has moved to `scholaraio.interfaces.cli.runtime`; legacy `scholaraio.cli.main` remains the script entrypoint alias and keeps old config/UI/parser monkeypatch points
- CLI parser construction has moved to `scholaraio.interfaces.cli.parser`; legacy `scholaraio.cli._build_parser` remains an alias and dynamically binds parser defaults from current `scholaraio.cli` command/helper aliases
- ingest pipeline orchestration facade has moved to `scholaraio.services.ingest.pipeline`; current CLI-interface consumers import that target namespace, while `scholaraio.ingest.pipeline` remains the same module object for legacy imports and monkeypatch paths
- ingest queue/proceedings path helpers have moved to `scholaraio.services.ingest.paths`; legacy private helpers such as `scholaraio.ingest.pipeline._inbox_dir` remain aliases during the compatibility window
- ingest pipeline type definitions (`StepResult`, `StepDef`, `InboxCtx`) have moved to `scholaraio.services.ingest.types`; `scholaraio.ingest.pipeline` keeps the same public names as compatibility aliases
- ingest MinerU asset discovery and move/cleanup helpers have moved to `scholaraio.services.ingest.assets`; legacy private helper names in `scholaraio.ingest.pipeline` remain aliases
- ingest duplicate-detection identifier helpers have moved to `scholaraio.services.ingest.identifiers`; legacy `scholaraio.ingest.pipeline._collect_existing_*` and `_normalize_arxiv_id` remain aliases
- ingest document-detection JSON parsing and patent/thesis/book classifier helpers have moved to `scholaraio.services.ingest.detection`; legacy pipeline private helper names remain aliases
- ingest document sidecar metadata loading and post-ingest abstract repair have moved to `scholaraio.services.ingest.documents`; legacy pipeline private helper names remain aliases
- ingest search-registry update helpers have moved to `scholaraio.services.ingest.registry`; legacy `_ensure_registry_schema`, `_update_registry`, and `_registry_migrated` remain aliases
- ingest inbox cleanup has moved to `scholaraio.services.ingest.cleanup`; legacy `scholaraio.ingest.pipeline._cleanup_inbox` remains an alias
- ingest pending-spool file movement has moved to `scholaraio.services.ingest.pending`; legacy `scholaraio.ingest.pipeline._move_to_pending` remains an alias
- ingest proceedings routing has moved to `scholaraio.services.ingest.proceedings`; proceedings volume preparation has moved to `scholaraio.services.ingest.proceedings_volume`; legacy `scholaraio.ingest.pipeline._ingest_proceedings_ctx` and `scholaraio.ingest.proceedings` remain aliases
- ingest paper/global pipeline steps (`toc`, `l3`, `translate`, `refetch`, `embed`, `index`) have moved to `scholaraio.services.ingest.steps`; legacy public `scholaraio.ingest.pipeline.step_*` names remain aliases
- ingest batch-conversion asset helpers have moved to `scholaraio.services.ingest.batch_assets`; legacy `_move_batch_images` and `_flatten_cloud_batch_output` remain aliases
- ingest single-file batch conversion postprocessing has moved to `scholaraio.services.ingest.batch_postprocess`; legacy `_postprocess_convert` remains an alias
- ingest batch conversion postprocessing has moved to `scholaraio.services.ingest.batch_postprocess`; legacy `_batch_postprocess` remains an alias and still honors pipeline-level step/UI monkeypatches
- ingest batch PDF conversion orchestration has moved to `scholaraio.services.ingest.batch_convert`; legacy `batch_convert_pdfs` remains an alias and still honors pipeline-level helper/UI monkeypatches
- ingest external reference-manager import orchestration has moved to `scholaraio.services.ingest.external_import`; legacy `import_external` remains an alias and still honors pipeline-level helper/step/UI monkeypatches
- ingest pipeline step registry and presets have moved to `scholaraio.services.ingest.step_registry`; legacy `STEPS`, `PRESETS`, `_DOC_INBOX_STEPS`, and `_OFFICE_EXTENSIONS` remain aliases
- ingest per-inbox orchestration has moved to `scholaraio.services.ingest.inbox_orchestration`; legacy `_process_inbox` remains an alias and still honors pipeline-level step/helper/UI/logging monkeypatches
- ingest top-level pipeline runner has moved to `scholaraio.services.ingest.pipeline_runner`; legacy `run_pipeline` remains an alias and still honors pipeline-level step/helper/UI/logging monkeypatches
- ingest Office inbox conversion step has moved to `scholaraio.services.ingest.inbox_steps`; legacy `step_office_convert` remains an alias and still honors pipeline-level logging monkeypatches
- ingest MinerU/PDF conversion step has moved to `scholaraio.services.ingest.inbox_steps`; legacy `step_mineru` remains an alias and still honors pipeline-level UI/logging monkeypatches
- ingest metadata extraction inbox steps have moved to `scholaraio.services.ingest.inbox_steps`; legacy `step_extract_doc` and `step_extract` remain aliases and still honor pipeline-level helper/UI/logging monkeypatches
- ingest dedup/API-completion step has moved to `scholaraio.services.ingest.inbox_steps`; legacy `step_dedup` remains an alias and still honors pipeline-level helper/UI/logging monkeypatches
- ingest write-to-library step has moved to `scholaraio.services.ingest.inbox_steps`; legacy `step_ingest` remains an alias and still honors pipeline-level helper/UI/logging monkeypatches

## 8. Items Explicitly Deferred

The following implementation details should remain deferred until the earlier phases above are complete:

- the concrete `workspace.yaml` field schema beyond the minimal additive metadata/mount envelope above
- any actual implementation of manifest-declared workspace-local `explore` mounts after the shared-store compatibility window

## 9. Practical Summary

The safe execution order is:

1. freeze root integration and config invariants
2. make `Config` the complete path authority
3. convert leaf modules and shallow CLI consumers to accessors
4. introduce a workspace compatibility layer
5. abstract queue/proceedings paths in `pipeline.py`
6. separate state/cache/runtime logically
7. move isolated libraries first
8. move `proceedings` as a durable library
9. move queue/spool paths
10. move `papers` last
11. clean up compatibility layers

Anything that starts by directly renaming `data/`, `workspace/`, or `.claude/skills/` is not aligned with the audited current codebase.
