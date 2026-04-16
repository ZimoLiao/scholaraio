# ScholarAIO User Data Migration Strategy (Draft)

Status: Draft

Last Updated: 2026-04-17

Scope: user-facing data migration strategy for future runtime-layout upgrades.

## 1. Purpose

This document defines how ScholarAIO should migrate existing user data when the runtime layout evolves.

The goal is not to optimize for the cleanest directory tree on day one. The goal is:

- zero or near-zero surprise for existing users
- no silent data loss
- no hidden corruption of resumable work
- explicit verification and rollback
- compatibility-first upgrades before physical data moves

This document intentionally focuses on migration strategy, not implementation sequencing. The lower-level execution order is covered separately in `docs/development/directory-migration-sequence.md`.

## 2. Design Position

ScholarAIO already has real users and real accumulated state. Therefore, future layout upgrades MUST treat migration as a product feature, not as a one-time refactor.

The recommended migration model is:

1. **compatibility release first**
2. **plan/check before move**
3. **physical migration only as an explicit operation**
4. **path-bearing indexes rebuilt after move**
5. **rollback preserved until verification succeeds**

For the first migration-capable generation, the following product assumptions are now also treated as settled:

- migration is **offline only** for real runtime-layout moves
- compatibility is **one-way only**
  - new versions should learn to read old layouts
  - old versions should not continue opening fully migrated layouts as if nothing changed
- multi-root discovery and merge are **out of scope for V1**
  - V1 may assume a single canonical runtime root selected by the existing config-resolution flow

This is the same general direction used by mature systems:

- VS Code moved MCP configuration into a dedicated `mcp.json` file but added automatic detection, migration, notifications, and cross-environment support rather than expecting manual edits
  - Source: https://code.visualstudio.com/updates/v1_102
- PostgreSQL `pg_upgrade` provides `--check`, mode-specific preflight, and explicit rollback expectations before destructive operations
  - Source: https://www.postgresql.org/docs/current/pgupgrade.html
- Firefox treats the profile directory as the authoritative user state and recommends copying the whole profile, not reassembling selected files by guesswork
  - Source: https://support.mozilla.org/en-US/kb/back-and-restore-information-firefox-profiles
- Microsoft USMT explicitly distinguishes what migrates, what does not, and what needs manifest-driven rules
  - Source: https://learn.microsoft.com/en-us/windows/deployment/usmt/usmt-what-does-usmt-migrate
- Kubernetes storage-version migration rewrites stored objects to the new storage form instead of assuming old storage can stay in place forever
  - Source: https://kubernetes.io/docs/tasks/manage-kubernetes-objects/storage-version-migration/

## 3. Core Principles

### 3.1 Compatibility Before Relocation

New ScholarAIO versions SHOULD first learn how to read the old layout before asking users to move anything.

Implication:

- the first release of a new layout SHOULD be a compatibility release
- users SHOULD be able to upgrade and keep working even if no physical migration has happened yet

### 3.2 Whole-Tree Preservation Over File-Pattern Guessing

If a subtree contains user-authored or user-managed content, migration MUST preserve the entire subtree unless there is a strong reason not to.

Implication:

- `workspace/<name>/` MUST be treated as an opaque project tree
- paper directories MUST be migrated as whole directories
- proceedings directories MUST be migrated as whole directories

### 3.3 Derived State Must Not Be Trusted Blindly After Path Changes

Any database or index that stores absolute or physical file paths MUST be rebuilt or rewritten after physical relocation.

Implication:

- moving data without rebuilding affected indexes is unsafe even if files appear intact

### 3.4 Unknown Files Must Survive

Migration MUST preserve files that ScholarAIO does not currently understand, as long as they are inside user-owned subtrees.

Implication:

- no whitelist-only migration for `workspace/`
- no whitelist-only migration for paper directories

### 3.5 Rollback Must Be Practical

Rollback MUST mean more than “restore from memory”.

Implication:

- migration needs a manifest/journal
- destructive cleanup happens only after verification
- rollback must not depend on the current `backup` command alone

## 4. Audited Current Data Surfaces

The following persistence surfaces were checked against the current codebase.

### 4.1 Config and Entry State

- `config.yaml`
- `config.local.yaml`

Current behavior:

- `scholaraio/config.py` resolves all relative paths from the directory containing `config.yaml`
- `_find_config_file()` still expects `config.yaml` at runtime root or `~/.scholaraio/config.yaml`

Migration consequence:

- config files are authoritative entry-state and MUST migrate first or remain readable in place

### 4.2 Main Library: `data/papers/`

Each paper directory currently may contain more than the obvious baseline files.

Confirmed persistent or semi-persistent contents:

- `meta.json`
- `paper.md`
- `notes.md`
- `paper_{lang}.md`
- `images/`
- `layout.json` and/or `*_layout.json`
- `*_content_list.json`
- `.scrubbed`
- `.translate_<lang>/`

Relevant code:

- `scholaraio/papers.py`
- `scholaraio/loader.py`
- `scholaraio/translate.py`
- `scholaraio/ingest/pipeline.py`

Migration consequence:

- a paper directory MUST be migrated as a whole directory
- migration MUST NOT reconstruct a paper directory from a known-file whitelist

### 4.3 Pending Queue: `data/pending/`

Each pending item may contain:

- `paper.md`
- original uploaded PDF or source file
- `pending.json`
- extracted assets such as `images/`, `layout.json`, `*_content_list.json`

Relevant code:

- `_move_to_pending()` in `scholaraio/ingest/pipeline.py`

Migration consequence:

- pending items are resumable review state and MUST be migrated intact

### 4.4 Proceedings Library: `data/proceedings/`

Proceedings state is richer than a flat paper store.

Confirmed contents include:

- per-volume `meta.json`
- `proceeding.md`
- `split_candidates.json`
- `split_plan.json`
- `clean_candidates.json`
- `clean_plan.json`
- child-paper directories under `papers/`
- `proceedings.db`

Relevant code:

- `scholaraio/proceedings.py`
- `scholaraio/ingest/proceedings.py`
- `scholaraio/index.py`

Migration consequence:

- each proceedings volume MUST be migrated intact
- `proceedings.db` is derived and MUST be rebuilt or rewritten after physical relocation

### 4.5 Explore Silos: `data/explore/<name>/`

Confirmed contents include:

- `papers.jsonl`
- `meta.json`
- `explore.db`
- `faiss.index`
- `faiss_ids.json`
- `topic_model/`
  - `bertopic_model.pkl`
  - `scholaraio_meta.pkl`
  - `info.json`
  - `viz/`

Relevant code:

- `scholaraio/explore.py`
- `scholaraio/topics.py`
- `scholaraio/vectors.py`

Migration consequence:

- the silo directory itself MUST be preserved
- `explore.db`, FAISS, and topic artifacts SHOULD be treated as rebuildable derived state if migration verification fails

### 4.6 Tool Reference Store: `data/toolref/`

Confirmed contents include:

- tool/version directories
- fetched docs
- `meta.json`
- tool-level `toolref.db`
- `current` symlink

Relevant code:

- `scholaraio/toolref/paths.py`
- `scholaraio/toolref/storage.py`
- `scholaraio/toolref/fetch.py`

Migration consequence:

- the full toolref tree MUST survive
- migration must preserve or recreate the `current` selection explicitly

### 4.7 Citation Style Cache: `data/citation_styles/`

Confirmed contents include:

- custom Python formatter files loaded dynamically

Relevant code:

- `scholaraio/citation_styles.py`

Migration consequence:

- user-installed style files are durable user data and MUST not be regenerated or discarded

### 4.8 Workspace Trees: `workspace/<name>/`

Current code only manages part of the tree, but the module contract already allows broader user content.

Confirmed or explicitly permitted contents:

- `papers.json`
- future `refs/` or `workspace.yaml`
- user notes
- drafts
- scripts
- exports
- reports
- optional `.git/`
- arbitrary user-created files

Relevant code:

- `scholaraio/workspace.py`
- `scholaraio/cli.py`
- `scholaraio/insights.py`

Migration consequence:

- every workspace MUST be treated as an opaque project tree
- migration MUST preserve unknown files and subdirectories

### 4.9 Translation Export Roots

Current export root:

- `workspace/translation-ws/`

Relevant code:

- `scholaraio/translate.py`
- `tests/test_translate.py`

Migration consequence:

- translation export bundles are user-visible outputs and SHOULD be preserved by default

### 4.10 Indexes, Search DBs, and Metrics

Confirmed derived state includes:

- `data/index.db`
- `data/proceedings/proceedings.db`
- `data/metrics.db`
- main-library `faiss.index` / `faiss_ids.json` adjacent to `index.db`
- `data/topic_model/`

Relevant code:

- `scholaraio/index.py`
- `scholaraio/vectors.py`
- `scholaraio/topics.py`
- `scholaraio/metrics.py`

Important nuance:

- `index.py` stores `md_path`
- proceedings search rows also store `md_path`
- FAISS and BERTopic are rebuildable from authoritative stores, but the rebuild may be expensive

Migration consequence:

- path-bearing indexes MUST be rebuilt or rewritten after relocation
- metrics may be preserved, but loss of metrics must never block a successful migration

### 4.11 Logs

Confirmed runtime log location:

- `data/scholaraio.log`

Relevant code:

- `scholaraio/log.py`

Migration consequence:

- logs are lowest-priority retained state
- they MAY be preserved, but should not block migration success

### 4.12 External Caches Not Owned by the Runtime Root

Confirmed external caches include:

- embedding model caches under user cache directories
- GPU profile cache at `~/.cache/scholaraio/gpu_profile.json`

Relevant code:

- `scholaraio/vectors.py`

Migration consequence:

- these MUST NOT be part of the required in-instance data migration
- they can be reused if present, but migration must not depend on them

## 5. Data Classes and Required Treatment

The migration system SHOULD classify data into four categories.

### 5.1 Category A: Authoritative User Data

These are the source of truth and MUST be preserved exactly.

Includes:

- config files
- `data/papers/`
- `data/pending/`
- `data/proceedings/` volume trees
- `data/explore/` silo trees
- `data/toolref/`
- `data/citation_styles/`
- `workspace/`
- `workspace/translation-ws/`

Default migration action:

- whole-tree copy/move
- preserve unknown files
- preserve timestamps if feasible

### 5.2 Category B: Resumable Working State

These are not always user-authored, but losing them would interrupt work.

Includes:

- `.translate_<lang>/`
- proceedings review plans and candidates
- pending review trees
- toolref current-version selection

Default migration action:

- preserve by default
- verify after move
- never discard silently

### 5.3 Category C: Derived but Valuable State

These can be rebuilt, but rebuilding may be expensive.

Includes:

- `index.db`
- `proceedings.db`
- FAISS indexes
- BERTopic models

Default migration action:

- migrate if safe
- mark for rebuild if path validation fails
- do not trust blindly after relocation

### 5.4 Category D: Disposable Runtime State

These are safe to regenerate.

Includes:

- logs
- external caches outside the instance root
- transient temporary files

Default migration action:

- best-effort preservation only
- not required for migration success

## 6. Recommended Product Strategy

### 6.1 Release 1: Compatibility Release

The first release that introduces a new runtime layout SHOULD NOT require physical migration.

It SHOULD:

- read old layout and new layout
- write or maintain the root-level `instance.json` metadata contract
- surface deprecation notices only when needed
- keep the user productive immediately after upgrade

User expectation:

- “upgrade succeeded, nothing broke”

### 6.2 Release 2: Optional Physical Migration

Physical reorganization SHOULD be an explicit command, not an implicit surprise on startup.

Recommended command family:

- `scholaraio migrate plan`
- `scholaraio migrate run`
- `scholaraio migrate verify`
- `scholaraio migrate rollback`

User expectation:

- “I can preview what will happen before anything moves”

## 7. Recommended User-Facing Migration Flow

### Step 1. Inventory

The tool scans the runtime root and produces a migration manifest.

The manifest SHOULD include:

- discovered config files
- discovered library roots
- workspace list
- per-category data sizes
- path-bearing indexes found
- unknown files under authoritative trees

### Step 2. Preflight Checks

The tool validates:

- enough free space
- same-filesystem requirements if using move/link/clone optimizations
- no active ScholarAIO process holding files open
- current layout version is supported
- target layout is writable

The tool SHOULD fail before moving anything if preflight fails.

### Step 3. Migration Snapshot / Journal

Before any destructive or path-changing operation, the tool creates a migration journal.

This journal SHOULD record:

- source root
- target root
- version transition
- every tree to be moved
- every tree to be copied
- every index to rebuild
- rollback actions

Important:

- this journal is required even if the user already uses `scholaraio backup`
- current backup defaults to syncing `data/` only and is not a full migration safety net for `workspace/` plus config

### Step 4. Whole-Tree Move/Copy for Category A and B

Migration then relocates authoritative and resumable state.

Rules:

- move/copy whole trees, not selected files
- never flatten paper directories
- never flatten workspace trees
- preserve proceedings review artifacts
- preserve toolref version directories and current selection

### Step 5. Rebuild or Rewrite Path-Bearing Derived State

After physical relocation, the tool MUST handle path-sensitive derived data.

At minimum:

- rebuild `index.db`
- rebuild `proceedings.db`
- invalidate or rebuild FAISS caches
- rebuild BERTopic artifacts if path validation fails or if the model references stale files

Metrics handling:

- `metrics.db` MAY be copied forward
- migration success MUST NOT depend on metrics recovery

### Step 6. Verification

Verification MUST be explicit.

Minimum checks:

- can load config
- can enumerate papers
- can enumerate workspaces
- can resolve paper UUID lookups
- can run keyword search
- can run proceedings search if proceedings exist
- can load one explore silo if present
- can read toolref current version if present
- can detect translation resume state if present

### Step 7. Deferred Cleanup

Old layout cleanup SHOULD happen only after verification succeeds.

Recommended default:

- keep old trees until the user confirms cleanup
- keep the migration journal until cleanup

## 8. What “No-Pain Migration” Means for ScholarAIO

For ScholarAIO, “no-pain” should mean:

- upgrading does not immediately require manual filesystem work
- if migration is needed, the user gets a preview first
- user-authored content survives even if ScholarAIO does not recognize every file
- resumable work survives
- indexes are repaired automatically when needed
- rollback remains available until verification passes

It SHOULD NOT mean:

- silently moving everything on first startup
- silently deleting old trees after copy
- assuming `data/` is the only important state
- assuming `workspace/` contains only `papers.json`

## 9. Explicit Recommendations

### 9.1 Do

- ship a compatibility release before shipping a physical move
- treat `workspace/` as opaque user project state
- treat every paper directory as opaque document state
- rebuild path-bearing indexes after relocation
- preserve unknown files inside user-owned trees
- require explicit verification before cleanup

### 9.2 Do Not

- rely on whitelist-only file migration
- trust old search/index databases after path relocation
- use current `backup run` as the only rollback mechanism
- auto-delete legacy trees immediately after migration
- move `.claude/skills/` or root agent wrappers as part of user-data migration

## 10. Companion Implementation Spec

The implementation-facing companion document now lives at:

- `docs/development/migration-mechanism-spec.md`

That document defines:

- the root-level migration control directory
- the `instance.json` layout-version and state contract
- the migration-lock contract
- the migration journal contract
- the verification and cleanup gating rules
- the minimum command-surface behavior for `migrate plan/run/verify/cleanup`

This strategy document remains the higher-level user-data policy document. The mechanism spec is where future implementation work should look for the minimum migration control plane.

The execution-order companion document remains:

- `docs/development/directory-migration-sequence.md`

That document defines when `Config` path authority, workspace compatibility work, migration control-plane work, and physical directory moves should happen relative to each other.
