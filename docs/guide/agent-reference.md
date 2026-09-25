# Agent Reference

This document is the deeper reference for agents and maintainers. The root entry docs such as `AGENTS.md`, `CLAUDE.md`, and `.qwen/QWEN.md` are intentionally kept lighter and should stay focused on durable project facts, hard constraints, and navigation. For the full repository knowledge map, start at `docs/DESIGN.md`.

## Instruction Layering

Use the instruction stack in this order:

1. Root wrapper for your host tool
   - `CLAUDE.md`
   - `AGENTS.md`
   - `.qwen/QWEN.md`
   - `.cursor/rules/scholaraio.mdc`
   - `.clinerules`
   - `.windsurfrules`
   - `.github/copilot-instructions.md`
2. Matching project skill under `.claude/skills/<name>/SKILL.md`
3. Focused reference docs such as CLI, setup, writing, or migration specs
4. Source code and tests

Practical rule:

- if the content is a durable fact or invariant, keep it in the entry doc
- if the content is a reusable multi-step workflow, make it a skill
- if the content is long-form reference, keep it in docs or skill supporting files

## Repository Knowledge System

ScholarAIO treats repository-local Markdown as the system of record for agent
context. `AGENTS.md` is the map injected early in agent sessions; it should not
become the encyclopedia.

Key indexes:

- `docs/DESIGN.md`: repository knowledge map and directory roles
- `docs/design-docs/index.md`: architecture and runtime design authorities
- `docs/generated/index.md`: generated reference rules
- `docs/product-specs/index.md`: product behavior spec rules

Internal plans, validation records, and audits are intentionally excluded from
the published documentation site.

## How Skills Are Organized

The canonical project skill source is:

- `.claude/skills/<skill-name>/SKILL.md`

Cross-agent discovery wrappers expose the same skill set through:

- `.agents/skills/`
- `.qwen/skills/`
- `skills/`

For reuse from another project, prefer the automated registration command:

```bash
scholaraio setup agent
scholaraio setup agent --apply
scholaraio setup agent check
```

It previews and applies shell runtime wiring, Codex/OpenClaw global skill discovery, project-local wrappers for supported hosts, and Claude Code plugin instructions where automation is not possible.

Project-local wrappers are local machine integration blocks. They may contain absolute paths to the active ScholarAIO checkout and config, so review them before committing target-project files.

Project guidance for maintaining skills:

- keep `SKILL.md` focused on entry instructions and decision rules
- move large examples, templates, or helper scripts into sibling files inside the same skill directory
- if a skill grows into long reference material, split the detail into supporting files and link them from `SKILL.md`
- if a repo-wide instruction file starts turning into a checklist or operating procedure, move that procedure into a skill instead

### Capability-Based Routing

Shared skills route by the task's required capability and output contract, not
by the host or Agent brand:

| Route | Use it when |
|---|---|
| Current-session native capability | The capability is actually exposed in this session and can complete the one-off reading, reasoning, writing, browsing, or visual task |
| ScholarAIO core CLI | The task needs library access, provenance, persistent notes, reproducible IR, deterministic Office files, or another tested project contract |
| Optional sidecar or external extension | The user explicitly requests it, or the native/core route cannot meet a specialized rendering or benchmark contract |

Never infer tool availability from an Agent name. Check the capabilities that
are actually available, select the smallest route that satisfies the output,
and state any verification boundary. This keeps the canonical skills portable
while still allowing host-specific setup commands in dedicated integration
documentation.

Representative skills:

- Core research: `search`, `show`, `ingest`, `workspace`, `audit`, `translate`
- Writing: `academic-writing`, `nature-workflow`, `literature-review`, `paper-guided-reading`, `paper-writing`, `citation-check`, `writing-polish`, `review-response`, `research-gap`, `poster`, `technical-report`
- Outputs and tooling: `draw`, `document`, `publish`, `scientific-runtime`, `scientific-tool-onboarding`

## Repo And Module Map

ScholarAIO’s canonical implementation namespaces are:

- `scholaraio/core/`
- `scholaraio/providers/`
- `scholaraio/stores/`
- `scholaraio/projects/`
- `scholaraio/services/`
- `scholaraio/interfaces/cli/`

High-signal mental model:

- `core/`: config, logging, runtime foundations
- `providers/`: external APIs, parsing backends, transport adapters
- `stores/`: persistent storage helpers and durable library roots
- `projects/`: workspace and project-level structures
- `services/`: business logic and orchestration
- `interfaces/cli/`: parser, startup, and user-facing command handlers

The breaking cleanup generation removed legacy public facades such as
`scholaraio.index`, `scholaraio.workspace`, `scholaraio.translate`, and
`scholaraio.ingest.pipeline`.

Current import rules:

- implementation code must import canonical namespaces directly
- `scholaraio.cli` is only the published entrypoint
- internal CLI patch/wiring surfaces live in `scholaraio.interfaces.cli.compat`

## Current Runtime Layout

Fresh-layout runtime:

- durable libraries under `data/libraries/`
- inbox and pending queues under `data/spool/`
- stateful indexes and rebuildable state under `data/state/`
- user project outputs under `workspace/`
- final audited deliverable archives under git-ignored `published/`

Breaking cleanup behavior:

- legacy roots such as `data/papers/`, `data/explore/`, `data/proceedings/`, and `data/inbox*` are no longer opened implicitly
- root/public facade imports are no longer supported
- supported old-layout roots should be upgraded with `scholaraio migrate upgrade --migration-id <id> --confirm`

Workspace rules:

- `workspace/<name>/` is a free-form user project tree, not a rigid scaffold
- paper references live in `refs/papers.json`
- `workspace.yaml` is additive metadata only
- system-owned outputs should converge under `workspace/_system/`

Migration rules:

- runtime-layout migration control lives under `.scholaraio-control/`
- use `scholaraio migrate upgrade --migration-id <id> --confirm` for the normal one-command upgrade path
- use `scholaraio migrate plan|verify|run|cleanup|finalize` only when inspecting or repairing individual migration steps
- current covered move stores are `citation_styles`, `toolref`, `explore`, `proceedings`, `spool`, and `papers`
- `migrate finalize --confirm` is the hardened one-click post-migration cleanup flow for real user roots

## Agent Operating Model

ScholarAIO is meant to be used through an agent, not only through direct shell scripting.

Agents should:

- prefer real CLI execution over only explaining intended steps
- load information progressively from lightweight metadata toward heavier full text
- treat paper conclusions as claims and compare evidence across sources
- keep user-facing outputs inside `workspace/`
- avoid direct edits to runtime data when tested helpers or CLI flows already exist

## Notes And Cross-Session Analysis

When analysis should persist across sessions, use paper-level `notes.md`.

Conventions:

- location: `<papers_dir>/<Author-Year-Title>/notes.md`
- append sections in the form `## YYYY-MM-DD | <source> | <analysis type>`
- keep long-lived findings, cross-paper links, and notable limitations there
- `scholaraio show "<paper-id>" --append-notes "..."` is the user-facing append path

Useful mental model:

- T1: final answer for the current conversation
- T2: durable notes worth keeping in `notes.md`
- T3: ephemeral search or reasoning details that should not be persisted

## Deep Links

Use the smallest doc that answers the question:

- Product overview: [`docs/index.md`](../index.md)
- Repository knowledge map: [`docs/DESIGN.md`](../DESIGN.md)
- Agent setup: [`docs/getting-started/agent-setup.md`](../getting-started/agent-setup.md)
- Installation: [`docs/getting-started/installation.md`](../getting-started/installation.md)
- Configuration: [`docs/getting-started/configuration.md`](../getting-started/configuration.md)
- CLI reference: [`docs/guide/cli-reference.md`](cli-reference.md)
- Writing workflows: [`docs/guide/writing.md`](writing.md)
- Runtime layout authority: [`docs/design-docs/directory-structure-spec.md`](../design-docs/directory-structure-spec.md)
- Migration execution order: [`docs/design-docs/directory-migration-sequence.md`](../design-docs/directory-migration-sequence.md)
- Migration control-plane contract: [`docs/design-docs/migration-mechanism-spec.md`](../design-docs/migration-mechanism-spec.md)

The maintenance rule for this repo is simple:

- keep entry docs slim
- keep procedures in skills
- keep heavy reference material in dedicated docs

## Concurrent record updates

Use `scholaraio.stores.papers.update_meta` for field changes, or `modify_meta` for short in-memory edits such as updating a nested translation entry. These helpers lock a persistent sidecar for the complete read–modify–write and atomically replace the JSON through a unique temporary file. Do network calls and extraction before entering the transaction. `write_meta` is a whole-record replacement, not a merge of a previously read snapshot. Workspace reference create/add/remove operations follow the same locking contract. Hidden `.scholaraio-<hash>.lock` files live beside each record’s containing directory (the paper-library root for metadata, or the workspace root for references). Keeping the handle outside the directory allows Windows to rename that directory while holding the lock. These are persistent coordination files; do not delete them while writers are active.

Library rename/refetch/repair callers pass `cfg.index_db` explicitly so fresh and custom runtime layouts update registered directory names and search paths together. An index update failure rolls the directory name back and surfaces the error. Standalone file tools may omit the database, but must not guess an old runtime path from a file's parent.
