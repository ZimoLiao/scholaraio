# ScholarAIO Directory Structure Specification (Draft)

Status: Draft

Last Updated: 2026-04-17

Scope: repository layout, runtime instance layout, agent-surface placement, and migration constraints for future refactors.

## 1. Purpose

This document defines the target directory structure for ScholarAIO and the compatibility constraints that MUST be preserved while migrating from the current layout.

This is a refactoring specification, not a release note. It exists to:

- separate source-repository structure from runtime-instance structure
- keep user data, internal state, caches, and runtime files decoupled
- preserve multi-agent skill discovery and host-specific wrapper behavior
- provide a stable layout contract for future `cli.py`, `pipeline.py`, and workspace refactors

## 2. Normative Language

The key words `MUST`, `MUST NOT`, `SHOULD`, `SHOULD NOT`, and `MAY` are to be interpreted as requirement levels for future refactors.

## 3. Design Principles

### 3.1 Source vs Runtime

ScholarAIO MUST distinguish between:

- the **source repository**: code, tests, docs, wrappers, and skill definitions
- the **runtime instance**: config, libraries, workspaces, state, cache, and runtime artifacts

The repository root and the runtime-instance root MAY be the same directory in local-clone mode. In plugin mode, the runtime-instance root MAY instead be `~/.scholaraio/`.

### 3.2 Lifecycle Separation

Directories MUST be partitioned by lifecycle and ownership, not only by feature name. At minimum, the design MUST distinguish:

- durable user-owned content
- durable internal application state
- rebuildable cache data
- temporary runtime artifacts
- queued work awaiting later processing

### 3.3 Stable Agent Entry Points

Agent host discovery relies on fixed file locations. Therefore:

- host-specific wrapper files MUST remain at repository root
- the canonical skill source MUST remain discoverable at repository root
- future refactors MUST NOT hide the skill system inside the Python package tree

## 4. Repository Root Specification

The repository root is the top-level project tree used by contributors and agent hosts.

### 4.1 Required Root-Level Integration Surface

The following files or directories MUST remain at repository root:

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

Rationale:

- current host discovery and wrapper tests assume these fixed root-level entry points
- moving them would break repository-open mode for multiple agent hosts

### 4.2 Canonical Skill Placement

The canonical skill source MUST be:

- `.claude/skills/`

The following compatibility entry points MUST continue to resolve to the same skill set:

- `.agents/skills`
- `.qwen/skills`
- `skills`

These MAY remain symlinks or MAY become equivalent wrapper directories, but they MUST continue to expose the same skill inventory.

`scholaraio/` MUST NOT become the canonical physical home of `SKILL.md` files.

### 4.3 Target Repository Layout

The target repository layout is:

```text
repo-root/
├── AGENTS.md
├── CLAUDE.md
├── AGENTS_CN.md
├── .claude/skills/
├── .agents/skills -> ../.claude/skills
├── .qwen/QWEN.md
├── .qwen/skills -> ../.claude/skills
├── .cursor/rules/
├── .clinerules
├── .windsurfrules
├── .github/copilot-instructions.md
├── .claude-plugin/
├── clawhub.yaml
├── scholaraio/
├── gui/
├── docs/
├── tests/
└── scripts/
```

### 4.4 `scholaraio/` Package Layout

The Python package SHOULD evolve toward the following second-level structure:

```text
scholaraio/
├── core/
├── providers/
├── stores/
├── projects/
├── services/
├── interfaces/
└── compat/
```

The intended responsibilities are:

- `core/`: config, logging, observability, shared primitives, error types
- `providers/`: external adapters such as LLM providers, scholarly APIs, parsing backends, and import adapters
- `stores/`: persistence-facing contracts for papers, proceedings, explore, toolref, citation styles, and similar durable stores
- `projects/`: workspace and other project-level boundaries built on top of shared stores
- `services/`: ingest, retrieval, authoring, scientific runtime, and operational orchestration
- `interfaces/`: CLI-facing and agent-facing entry adapters
- `compat/`: temporary compatibility shims during migration

### 4.5 `gui/`

`gui/` MUST be reserved as a top-level source directory for the future presentation shell.

`gui/`:

- MAY be empty initially
- MUST NOT become the source of truth for business rules
- MUST NOT directly depend on repository-local data layout as if the filesystem were a stable internal API
- SHOULD consume stable service outputs or explicit view-model adapters

## 5. Runtime Instance Root Specification

The runtime-instance root is the directory relative to which ScholarAIO resolves config and user data.

### 5.1 Current Compatibility Constraint

Until config discovery is redesigned, the following files MUST remain valid at the runtime-instance root:

- `config.yaml`
- `config.local.yaml`

Rationale:

- current `load_config()` searches `config.yaml` upward from the current working directory and falls back to `~/.scholaraio/config.yaml`
- moving config into `config/` would break current discovery behavior

### 5.2 Current Compatibility Top Level

For compatibility with the current codebase, the runtime-instance root MUST continue to support:

- `data/`
- `workspace/`

This applies both in repository-local mode and in plugin mode.

In addition, future migration-capable versions SHOULD reserve a root-level control directory:

- `.scholaraio-control/`

### 5.3 Target Runtime Layout

Within those top-level compatibility anchors, the target runtime layout is:

```text
instance-root/
├── config.yaml
├── config.local.yaml
├── data/
│   ├── libraries/
│   ├── spool/
│   ├── state/
│   ├── cache/
│   └── runtime/
├── .scholaraio-control/
└── workspace/
```

The purpose of each subtree is defined below.

### 5.4 Root-Level Control Metadata

`.scholaraio-control/` is the reserved root-level control directory for migration and instance metadata.

It SHOULD contain control-plane artifacts such as:

- `instance.json`
- `migration.lock`
- migration journals

It MUST NOT be treated as part of:

- `data/libraries/`
- `data/state/`
- `workspace/`

Rationale:

- `data/` and `workspace/` are themselves migration targets
- control metadata must remain outside those trees so migration can reason about them safely

The detailed contract for this directory is defined in:

- `docs/development/migration-mechanism-spec.md`

## 6. `data/` Subtree Specification

### 6.1 `data/libraries/`

`data/libraries/` contains durable, user-meaningful knowledge stores.

Target second-level layout:

```text
data/libraries/
├── papers/
├── proceedings/
├── explore/
├── toolref/
└── citation_styles/
```

Requirements:

- content here MUST be durable
- content here MUST NOT be treated as disposable cache
- content here MAY be referenced by workspaces
- content here SHOULD expose stable identifiers rather than only path conventions

### 6.2 `data/spool/`

`data/spool/` contains queued work items awaiting later processing or manual review.

Target second-level layout:

```text
data/spool/
├── inbox/
├── inbox-thesis/
├── inbox-patent/
├── inbox-doc/
├── inbox-proceedings/
└── pending/
```

Requirements:

- this subtree MUST be treated as work-to-be-processed, not as a durable library
- files MAY be deleted or moved after successful processing
- user-facing docs SHOULD describe these directories as queue semantics, not permanent storage

### 6.3 `data/state/`

`data/state/` contains persistent internal state that is important to the application but is not itself a user-facing library.

Target second-level layout:

```text
data/state/
├── search/
├── metrics/
├── topics/
└── sessions/
```

Examples:

- SQLite indexes
- metrics database
- topic-model metadata
- persistent session or history records

Requirements:

- state data MUST persist across restarts
- state data SHOULD be reconstructible only when explicitly intended; otherwise it is authoritative operational state
- state data MUST be kept distinct from user-authored content

### 6.4 `data/cache/`

`data/cache/` contains rebuildable derived data.

Target second-level layout:

```text
data/cache/
├── parser/
├── previews/
├── vectors/
└── topics/
```

Requirements:

- anything stored here SHOULD be safe to rebuild
- code MUST NOT rely on cache paths as canonical IDs
- user documentation SHOULD treat loss of cache data as recoverable

### 6.5 `data/runtime/`

`data/runtime/` contains temporary runtime artifacts.

Target second-level layout:

```text
data/runtime/
├── tmp/
├── locks/
└── sockets/
```

Requirements:

- runtime artifacts MUST NOT be treated as durable user data
- code SHOULD tolerate their removal between runs

## 7. `workspace/` Subtree Specification

### 7.1 Workspace as Independent Project Boundary

`workspace/` MUST be treated as a first-class project root, not merely as a paper-subset helper.

Each workspace MAY contain:

- paper references
- explore references
- toolref references
- drafts
- notes
- scripts
- generated reports
- run records
- its own `.git/`

Therefore, `workspace/` MUST NOT be modeled only as a view over `data/libraries/papers/`.

### 7.2 Target Workspace Layout

The target layout for a user workspace is:

```text
workspace/<name>/
├── workspace.yaml
├── refs/
│   ├── papers.json
│   ├── explore.json
│   └── toolref.json
├── notes/
├── drafts/
├── outputs/
├── runs/
└── .git/
```

Requirements:

- `workspace/<name>/` MUST be safe to use as an independent project root
- workspace metadata SHOULD move toward explicit manifests instead of only implicit conventions
- user-authored outputs SHOULD default to the active workspace, not to repository root or package directories

### 7.3 Reserved Workspace Namespace

System-generated workspaces or workspace-like output trees SHOULD use a reserved namespace under `workspace/`.

Recommended form:

```text
workspace/_system/
```

Examples:

- portable translation bundles
- autogenerated report packs
- future GUI-exported viewing bundles

Legacy compatibility directories such as `workspace/translation-ws/` MAY remain temporarily, but future features SHOULD prefer the reserved system namespace instead of creating new ad hoc root-level workspace siblings.

## 8. Decoupling Rules

### 8.1 Between Top-Level Runtime Trees

- `workspace/` MUST reference libraries through stable IDs or manifests, not by taking ownership of library files
- `data/libraries/` MUST NOT depend on workspace layout
- `data/state/`, `data/cache/`, and `data/runtime/` MUST NOT store user-authored canonical content

### 8.2 Inside the Python Package

- `providers/` MUST NOT depend on `interfaces/`
- `stores/` MUST NOT depend on `interfaces/`
- `projects/` MAY depend on `stores/` and `services/`, but MUST NOT define external provider clients
- `services/` MAY compose `providers/`, `stores/`, and `projects/`
- `interfaces/` SHOULD remain thin and MUST NOT become the only place where business rules exist

### 8.3 Skills and Agent Surfaces

- skills MUST remain an interface-layer concern
- skills MUST NOT become the canonical source of runtime layout truth
- host wrappers MUST remain lightweight and SHOULD defer to `AGENTS.md` plus the skill system

## 9. Multi-Agent Discovery and Registration Constraints

The following constraints are mandatory:

### 9.1 Canonical Skill Source

- `.claude/skills/` MUST remain the canonical skill source

### 9.2 Host-Specific Discovery Paths

The following discovery surfaces MUST continue to work:

- Claude Code via `CLAUDE.md` and `.claude/skills/`
- Codex and OpenClaw via `AGENTS.md` and `.agents/skills/`
- Qwen via `.qwen/QWEN.md` and `.qwen/skills/`
- Cursor via `.cursor/rules/scholaraio.mdc`, then `AGENTS.md`, then `.claude/skills/*/SKILL.md`
- Cline via `.clinerules` and `.claude/skills/`
- Windsurf via `.windsurfrules`
- GitHub Copilot via `.github/copilot-instructions.md`
- Claude plugin and marketplace registration via `.claude-plugin/` and `clawhub.yaml`

### 9.3 Migration Rule

Any refactor that changes the physical location or wrapper path of skills MUST update:

- repository wrappers
- plugin and marketplace manifests
- host-setup docs
- alignment tests

No directory-structure migration is complete until those discovery surfaces still work.

## 10. Compatibility Mapping for Refactor Planning

The current codebase still uses legacy paths. During migration, the following logical mapping SHOULD be adopted:

| Current path | Target logical location |
|---|---|
| `data/papers/` | `data/libraries/papers/` |
| `data/proceedings/` | `data/libraries/proceedings/` |
| `data/explore/` | `data/libraries/explore/` |
| `data/toolref/` | `data/libraries/toolref/` |
| `data/citation_styles/` | `data/libraries/citation_styles/` |
| `data/inbox*` | `data/spool/*` |
| `data/pending/` | `data/spool/pending/` |
| `data/index.db` | `data/state/search/index.db` |
| `data/metrics.db` | `data/state/metrics/metrics.db` |
| `data/topic_model/` | `data/state/topics/` or `data/cache/topics/`, depending on rebuild policy |
| `workspace/translation-ws/` | `workspace/_system/translation-bundles/` |

This mapping is a migration target, not a requirement for an all-at-once rename.

## 11. Migration Constraints

The migration MUST be incremental.

Before any large directory move, ScholarAIO SHOULD first:

1. centralize all runtime directory access through config accessors
2. stop constructing sibling runtime paths with raw `cfg._root / "data" / ...` expressions in feature modules
3. introduce compatibility shims or alias paths where needed
4. update tests, agent wrappers, and host setup docs in the same change set

The current codebase is not yet ready for an atomic layout flip. Therefore:

- direct physical renames of `data/` or `workspace/` SHOULD NOT happen first
- `config.yaml` discovery behavior SHOULD remain stable until an explicit config-discovery redesign is approved
- workspace refactors SHOULD preserve the ability to `git init` inside a workspace without affecting the main repository

## 12. Non-Goals

This specification does not define:

- final public documentation navigation
- GUI implementation details
- concrete API types for future service-layer view models
- exact migration order for every module

Those belong in companion architecture and execution documents.

## 13. Immediate Governance Outcome

Until superseded by a later approved version, future refactors SHOULD treat this document as the governing directory-structure target for:

- `cli.py` decomposition
- `ingest/pipeline.py` decomposition
- workspace redesign
- skill-system preservation
- plugin and wrapper compatibility
