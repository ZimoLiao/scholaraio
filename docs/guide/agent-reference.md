# Agent Reference

This document is the deeper reference for agents and maintainers. The root entry docs such as `AGENTS.md`, `CLAUDE.md`, and `.qwen/QWEN.md` are intentionally kept lighter and should stay focused on durable project facts, hard constraints, and navigation.

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

## How Skills Are Organized

The canonical project skill source is:

- `.claude/skills/<skill-name>/SKILL.md`

Cross-agent discovery wrappers expose the same skill set through:

- `.agents/skills/`
- `.qwen/skills/`
- `skills/`

Project guidance for maintaining skills:

- keep `SKILL.md` focused on entry instructions and decision rules
- move large examples, templates, or helper scripts into sibling files inside the same skill directory
- if a skill grows into long reference material, split the detail into supporting files and link them from `SKILL.md`
- if a repo-wide instruction file starts turning into a checklist or operating procedure, move that procedure into a skill instead

Representative skills:

- Core research: `search`, `show`, `ingest`, `workspace`, `audit`, `translate`
- Writing: `academic-writing`, `literature-review`, `paper-guided-reading`, `paper-writing`, `citation-check`, `writing-polish`, `review-response`, `research-gap`, `poster`, `technical-report`
- Outputs and tooling: `draw`, `document`, `paper2any`, `publish`, `scientific-runtime`, `scientific-tool-onboarding`

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
- Agent setup: [`docs/getting-started/agent-setup.md`](../getting-started/agent-setup.md)
- Installation: [`docs/getting-started/installation.md`](../getting-started/installation.md)
- Configuration: [`docs/getting-started/configuration.md`](../getting-started/configuration.md)
- CLI reference: [`docs/guide/cli-reference.md`](cli-reference.md)
- Writing workflows: [`docs/guide/writing.md`](writing.md)
- Runtime layout authority: [`docs/development/directory-structure-spec.md`](../development/directory-structure-spec.md)
- Migration execution order: [`docs/development/directory-migration-sequence.md`](../development/directory-migration-sequence.md)
- Migration control-plane contract: [`docs/development/migration-mechanism-spec.md`](../development/migration-mechanism-spec.md)
- Upgrade validation matrix: [`docs/development/upgrade-validation-matrix.md`](../development/upgrade-validation-matrix.md)
- Upgrade entry point: [`docs/development/scholaraio-upgrade-plan.md`](../development/scholaraio-upgrade-plan.md)

The maintenance rule for this repo is simple:

- keep entry docs slim
- keep procedures in skills
- keep heavy reference material in dedicated docs
