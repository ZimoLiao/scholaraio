# ScholarAIO Directory Migration Execution Sequence (Draft)

Status: Draft

Last Updated: 2026-04-17

Scope: execution order for directory and path migration, based on audited current code and tests.

## 1. Purpose

This document defines the recommended execution order for migrating ScholarAIO toward the target directory structure described in `docs/development/directory-structure-spec.md`.

This is an implementation-order document, not a vision document. Its job is to answer:

- what MUST be frozen first
- what MUST be abstracted before any physical move
- when migration control-plane work MUST land before real user-data moves
- which migrations are low-risk leaf moves
- which migrations are high-risk and MUST be deferred
- how to keep multi-agent skill discovery and current CLI behavior working during the transition

This document should be read together with:

- `docs/development/migration-mechanism-spec.md`

That companion document defines the control-plane contract (`instance.json`, `migration.lock`, journal, verification, cleanup gating). This document defines when that machinery must appear in the execution order.

## 2. Audited Baseline

The sequence below is based on direct inspection of the current codebase and on path-related regression tests run on 2026-04-16.

### 2.1 Code Areas Audited

- `scholaraio/config.py`
- `scholaraio/cli.py`
- `scholaraio/workspace.py`
- `scholaraio/insights.py`
- `scholaraio/setup.py`
- `scholaraio/explore.py`
- `scholaraio/toolref/paths.py`
- `scholaraio/citation_styles.py`
- `scholaraio/translate.py`
- `scholaraio/ingest/pipeline.py`
- `.qwen/QWEN.md`
- `clawhub.yaml`
- `.cursor/rules/scholaraio.mdc`

Key audited facts:

- `scholaraio/config.py:352-405` exposes only partial path accessors and still hardcodes multiple runtime directories in `ensure_dirs()`
- `scholaraio/config.py:515-570` locks current root-level `config.yaml` discovery behavior
- `scholaraio/workspace.py:1-198` defines the current workspace contract around `workspace/<name>/papers.json`
- `scholaraio/cli.py:163-176`, `1953-1974`, `2508-2514`, and `2778-2780` directly construct workspace and inbox paths
- `scholaraio/setup.py:531-537` checks current runtime directories by fixed layout
- `scholaraio/explore.py:43-78` anchors explore libraries under `data/explore/`
- `scholaraio/toolref/paths.py:9-18` anchors toolref under `data/toolref/`
- `scholaraio/citation_styles.py:253-255` derives citation-style storage from `cfg.papers_dir.parent`
- `scholaraio/translate.py:578-595` locks portable translation bundles under `workspace/translation-ws/`
- `scholaraio/ingest/pipeline.py:1314-1418` directly wires all inbox and pending paths into the pipeline entry flow
- `.qwen/QWEN.md:9-13` and `clawhub.yaml:16-127` confirm that skill discovery is rooted in `.claude/skills/`
- `tests/test_cursor_rules.py:8-27`, `tests/test_academic_writing_skills.py:80-87`, `tests/test_workspace.py:20-31`, `tests/test_explore.py:42-43`, and `tests/test_translate.py:230-290` lock the current discovery and path contracts

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
  tests/test_ingest_link_cli.py \
  tests/test_proceedings.py \
  tests/test_cli_messages.py
```

Observed result:

- `252` tests passed
- no failures

## 3. Non-Negotiable Invariants

These constraints are already enforced by current code, wrappers, and tests. The migration sequence MUST treat them as frozen until their replacements are intentionally designed and tested.

### 3.1 Config Discovery Invariant

Current behavior in `scholaraio/config.py`:

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

### 4.1 `Config` Has Only Partial Path Accessors

`scholaraio/config.py` currently exposes:

- `papers_dir`
- `index_db`
- `log_file`
- `metrics_db_path`
- `topics_model_dir`
- `workspace_dir`

But `ensure_dirs()` still hardcodes:

- `data/inbox`
- `data/inbox-proceedings`
- `data/inbox-thesis`
- `data/inbox-patent`
- `data/inbox-doc`
- `data/pending`
- `data/proceedings`

Implication:

- migration cannot start with physical path moves
- `Config` must first become the complete path authority

### 4.2 Workspace Contract Is Hardcoded in Both Code and Tests

Current behavior:

- `scholaraio/workspace.py` defines a workspace as `workspace/<name>/papers.json`
- `scholaraio/cli.py` constructs workspace paths directly under `cfg._root / "workspace"`
- `scholaraio/insights.py` enumerates workspaces through that layout
- `tests/test_workspace.py` locks the `papers.json` contract
- `tests/test_translate.py` locks portable bundle output under `workspace/translation-ws/`

Implication:

- workspace is not ready for a direct schema or root-layout move
- a compatibility phase is required before any workspace physical restructuring

### 4.3 Ingest and Queue Paths Are Concentrated in `pipeline.py`

Current behavior:

- `scholaraio/ingest/pipeline.py` directly references `data/inbox`, `data/inbox-doc`, `data/inbox-thesis`, `data/inbox-patent`, `data/inbox-proceedings`, `data/pending`, and `data/proceedings`
- `scholaraio/cli.py` also directly writes arXiv downloads to `data/inbox`
- `scholaraio/setup.py` checks `data/inbox`, `data/pending`, and `workspace`

Implication:

- queue/spool migration is a late, high-risk phase
- it MUST wait until path accessors exist and shallow consumers have already moved

### 4.4 Leaf Stores Already Form Natural Low-Risk Migration Units

Current audited path helpers:

- `scholaraio/explore.py` anchors to `data/explore/<name>/`
- `scholaraio/toolref/paths.py` anchors to `data/toolref/`
- `scholaraio/citation_styles.py` derives `data/citation_styles/` from `cfg.papers_dir.parent`
- `scholaraio/translate.py` anchors portable output to `workspace/translation-ws/`

Implication:

- these modules should be converted to config-backed accessors before larger pipeline moves
- `explore`, `toolref`, and `citation_styles` are safer physical-move candidates than `papers`

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

Primary audit reference:

- `docs/development/config-surface-audit.md`

Required additions in or around `scholaraio/config.py`:

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
- `scholaraio/setup.py` directory checks must switch to the new accessors

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

- `scholaraio/explore.py`
- `scholaraio/toolref/paths.py`
- `scholaraio/citation_styles.py`
- `scholaraio/translate.py`

Required changes:

- replace `cfg._root / "data" / ...` constructions with `Config` accessors
- stop deriving `citation_styles` from `cfg.papers_dir.parent`
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
- `scholaraio/insights.py`

Required changes:

- use `cfg.workspace_dir` everywhere instead of re-constructing workspace root
- use new path accessors for explore and translation defaults
- keep CLI surface behavior unchanged

Why this phase is separate from A2:

- the CLI touches more commands and user-facing defaults
- but it is still lower risk than workspace schema change or ingest queue migration

Exit criteria:

- `cmd_ws`, `_resolve_ws_paper_ids`, arXiv inbox download, and insights workspace listing no longer hardcode raw runtime paths where an accessor exists
- CLI output and user-facing defaults remain backward compatible

### Phase A4. Introduce Workspace Compatibility Layer Before Workspace Migration

Objective:

- make workspace independently evolvable without breaking the current `workspace/<name>/papers.json` contract

Current constraint:

- current code and tests treat `papers.json` at workspace root as the canonical paper-ref index

Required changes:

- extend `scholaraio/workspace.py` to become the single authority for workspace layout
- add compatibility helpers so the module can read:
  - legacy root `papers.json`
  - future `refs/papers.json`
- if a future `workspace.yaml` manifest is introduced, treat it as additive first, not replacing legacy files immediately

Do not do yet:

- do not move workspaces out of the top-level `workspace/`
- do not remove support for root `papers.json`
- do not relocate `translation-ws` until the broader workspace model is settled

Rationale:

- workspace is evolving from paper subset into project boundary
- that evolution needs a compatibility bridge, not a direct cut

Exit criteria:

- `workspace.py` owns the layout contract
- `tests/test_workspace.py` still pass
- new tests cover legacy and future-compatible readers

### Phase A5. Abstract Queue and Proceedings Paths in `pipeline.py`

Objective:

- cut over the highest-risk runtime path knot only after accessor and workspace groundwork are in place

Modules in scope:

- `scholaraio/ingest/pipeline.py`
- queue-related parts of `scholaraio/cli.py`
- `scholaraio/setup.py`

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

- align this phase with `docs/development/migration-mechanism-spec.md`

Why this phase exists here:

- once A7 starts, ScholarAIO is no longer just refactoring paths; it is performing real user-data migration work
- physical moves without the control plane would make rollback, verification, and operator support much weaker

Exit criteria:

- the codebase has a stable root-level control directory contract
- migration can mark runtime roots as legacy / normal / migrating / recovery-needed
- command gating exists while migration is active
- no physical move depends on implicit or startup-time relocation

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

### Phase A11. Remove Compatibility Shims and Update Public Docs

Objective:

- finish the migration by deleting transitional assumptions only after the new layout is proven

Actions:

- remove legacy fallback readers once all producers and consumers have switched
- update `AGENTS.md`, `CLAUDE.md`, README, setup docs, and relevant skills to the final runtime layout
- keep skill discovery surfaces unchanged unless a separate wrapper-versioning plan exists

Exit criteria:

- old and new layouts are no longer both required
- docs reflect only the supported runtime layout

## 7. Track B: Source-Repository Package Migration

Track B is intentionally later and slower than Track A.

### Phase B0. Reserve `gui/` Immediately

Low-risk action:

- create or keep top-level `gui/` as a reserved source directory at any time

Constraint:

- `gui/` MUST remain presentation-only
- it MUST NOT read raw runtime directories as if they were stable internal APIs

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

- current imports are still broadly flat
- moving source files before runtime-path stabilization would mix two refactors into one risk envelope

### Phase B2. Move Low-Coupling Modules Before Central Orchestrators

Recommended order:

1. store-like or provider-like leaves
   - `toolref/*`
   - `explore.py`
   - `citation_styles.py`
2. project boundary module
   - `workspace.py`
3. service modules
   - `translate.py`
   - `insights.py`
   - ingest metadata helpers

Late movers:

- `cli.py`
- `ingest/pipeline.py`

Reason:

- these two remain the largest cross-cutting surfaces in the current architecture

### Phase B3. Split `cli.py` and `pipeline.py` Last

Recommended target:

- `interfaces/cli/` for command registration and per-domain handlers
- `services/ingest/` for pipeline orchestration and ingest subflows

Precondition:

- Track A runtime path abstraction must already be complete enough that these files are not also carrying directory migration risk

## 8. Items Explicitly Deferred

The following decisions should remain deferred until the earlier phases above are complete:

- whether `workspace/translation-ws/` remains a special export root or becomes a more general project-export area
- the final manifest schema for workspaces
- whether `explore` remains only a shared store or also supports workspace-local mounts
- any attempt to relocate canonical skill files away from `.claude/skills/`

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
