# ScholarAIO Directory Structure Specification

Status: Current layout specification

Last Updated: 2026-04-24

Scope: repository layout, runtime instance layout, agent-surface placement, and migration constraints for future refactors.

2026-04-24 status note:

- the canonical implementation namespaces are now the only supported Python import surface
- root-level public import aliases have been removed in the breaking cleanup generation
- fresh runtime defaults use `data/libraries/`, `data/spool/`, and `data/state/`
- migrated user roots should be finalized with `scholaraio migrate finalize --confirm`

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
- `providers/`: external adapters such as LLM providers, scholarly APIs, parsing backends, import adapters, and transport-specific clients for web/runtime integrations (for example HTTP services or MCP-backed adapters)
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

- `docs/design-docs/migration-mechanism-spec.md`

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
├── pdf-edit-mirror/
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
- WSL PDF edit-mirror mappings and one bounded non-canonical recovery copy per opened PDF

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
- figures
- exported documents
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

This reference shape is not a rigid scaffold. Named workspaces remain user-owned project roots and MAY contain additional files or subdirectories beyond the examples above.

Requirements:

- `workspace/<name>/` MUST be safe to use as an independent project root
- `workspace/<name>/` MUST remain a free-form user project tree
- workspace metadata SHOULD move toward explicit manifests instead of only implicit conventions
- ScholarAIO-managed metadata inside named workspaces SHOULD stay narrow and additive, centered on stable reference files such as `papers.json`, `refs/papers.json`, and any future additive `workspace.yaml`
- any future `workspace.yaml` MUST stay additive and MUST NOT replace `papers.json` / `refs/papers.json` as the paper-reference compatibility chain
- future manifest-driven mounts or output preferences MUST be explicit opt-ins rather than implicit directory ownership
- user-authored outputs SHOULD default to the active workspace, not to repository root or package directories

### 7.2.1 Minimal `workspace.yaml` Envelope

For the next design pass, the minimal additive `workspace.yaml` envelope SHOULD be:

```yaml
schema_version: 1
name: turbulence-review
description: Drafting workspace for a turbulence review article
tags:
  - review
  - turbulence
mounts:
  explore: []
  toolref: []
outputs:
  default_dir: outputs/
```

Interpretation rules:

- `schema_version` identifies the manifest format and is required once `workspace.yaml` exists
- `name`, `description`, and `tags` are optional metadata only
- `mounts` is optional and expresses explicit opt-in external attachments; if `explore` mounts are ever implemented, they SHOULD start as read-only shared-store references
- `outputs` is optional and only expresses workspace-local preferences such as a default output directory
- paper references MUST remain authoritative in `papers.json` / `refs/papers.json`, not be duplicated or replaced inside `workspace.yaml`
- any later schema growth SHOULD extend this envelope instead of redefining the workspace around a rigid scaffold

### 7.2.2 Manifest Validation and Normalization Rules

The minimal `workspace.yaml` envelope above SHOULD follow these validation and normalization rules:

- the absence of `workspace.yaml` MUST remain a normal, fully supported state
- current readers recognize `schema_version: 1`; if a newer schema version is encountered, implementations SHOULD treat the file as opaque metadata and MUST NOT rewrite it blindly
- `name` and `description`, when present, SHOULD be strings trimmed of surrounding whitespace; empty strings SHOULD normalize to absence
- `name` is descriptive metadata only and MUST NOT be treated as the canonical workspace directory name
- `tags`, when present, SHOULD be a list of strings; normalization SHOULD trim whitespace, drop empty items, and de-duplicate exact repeats while preserving order
- `mounts.explore` and `mounts.toolref`, when present, SHOULD be lists of logical shared-store identifiers rather than filesystem paths
- mount entries MUST NOT be absolute paths, MUST NOT contain `..` traversal, and MUST NOT imply ownership of `data/libraries/` or `workspace/_system/`
- unknown mount buckets and unknown top-level keys SHOULD be preserved and ignored by implementations that do not understand them, rather than being silently deleted
- `outputs.default_dir`, when present, MUST resolve to a workspace-relative path; it MUST NOT be absolute and MUST NOT escape the workspace root
- normalization SHOULD be idempotent: re-reading and re-writing an unchanged manifest SHOULD NOT keep changing its shape
- `workspace.yaml` MUST NOT duplicate paper-reference payloads, search indexes, or other heavyweight derived state that already belongs elsewhere

### 7.3 Reserved Workspace Namespace

System-generated workspaces or workspace-like output trees SHOULD use a reserved namespace under `workspace/`.

Recommended form:

```text
workspace/_system/
```

Examples:

- portable translation bundles
- generated figure bundles
- autogenerated report packs
- future GUI-exported viewing bundles

Legacy compatibility outputs such as `workspace/translation-ws/`, `workspace/figures/`, or root-level files like `workspace/output.docx` MAY remain temporarily, but system-owned or cross-workspace outputs SHOULD converge under `workspace/_system/`. Only outputs that are explicitly scoped to one named workspace SHOULD prefer `workspace/<name>/outputs/`.

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
- skill names and CLI verbs MAY stay stable even when a backend transport changes; optional external integrations MUST NOT be locked to a single skill-packaging or HTTP-only implementation shape
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
| `workspace/figures/` | `workspace/_system/figures/` |
| `workspace/output.*` | `workspace/_system/output/` |

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
