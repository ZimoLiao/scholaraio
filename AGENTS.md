# ScholarAIO - Agent Entry

This is the repository entry document for coding agents. It is intentionally short:

- keep durable project facts and hard constraints here
- move multi-step procedures into skills
- move deep reference material into `docs/guide/agent-reference.md`

## What ScholarAIO Is

ScholarAIO is an AI-native research terminal. Users work through a coding agent in natural language to search literature, read papers, analyze claims, inspect figures and formulas, write notes or reports, and run scientific-computing support workflows.

The Python package is `scholaraio`. Real work should usually happen through the ScholarAIO CLI and project skills, not by bypassing runtime helpers with ad hoc file edits.

## How To Work In This Repo

- Prefer a matching project skill in `.claude/skills/` when the user request clearly maps to one.
- Use the `scholaraio` CLI to do real work instead of only describing what should be done.
- Load information progressively. Prefer metadata or abstracts first, then conclusions or full text only when needed.
- Treat paper conclusions as claims, not facts. Compare evidence, point out limitations, and distinguish supported results from author interpretation.
- Keep user-facing drafts, reports, exports, and research outputs under `workspace/`, not the repository root or `scholaraio/`.
- Do not casually rewrite or delete runtime data. When touching runtime layout, use `Config`, migration helpers, and tested accessors.
- When changing runtime layout, compatibility behavior, agent entry docs, or skill discovery, update tests and aligned docs in the same change.
- After code or doc changes, run the relevant checks and at least one real smoke path when feasible.

## Start Here

Read these in roughly this order:

1. [`README.md`](README.md) for the product overview and top-level structure.
2. [`docs/getting-started/agent-setup.md`](docs/getting-started/agent-setup.md) for repo-open vs plugin or cross-project setup.
3. [`docs/guide/cli-reference.md`](docs/guide/cli-reference.md) for the current user-facing CLI surface.
4. [`docs/guide/agent-reference.md`](docs/guide/agent-reference.md) for deeper agent, runtime, and skill organization details.
5. [`docs/development/scholaraio-upgrade-plan.md`](docs/development/scholaraio-upgrade-plan.md) before changing runtime layout, migration, or compatibility behavior.

## Skill-First Workflow

The canonical project skill source is `.claude/skills/`. Cross-agent discovery paths are wrappers around that same source:

- `.agents/skills/`
- `.qwen/skills/`
- `skills/`

Representative skills to check first:

- Core research: `search`, `show`, `ingest`, `workspace`, `audit`, `translate`
- Writing: `academic-writing`, `literature-review`, `paper-guided-reading`, `paper-writing`, `citation-check`, `writing-polish`, `review-response`, `research-gap`, `poster`, `technical-report`
- Outputs and tooling: `draw`, `document`, `paper2any`, `publish`, `websearch`, `webextract`, `scientific-runtime`, `scientific-tool-onboarding`

If a workflow has grown into a reusable playbook, move it into a skill instead of expanding this file.

## Repo Map

- `scholaraio/core/`: config, logging, and shared runtime foundations
- `scholaraio/providers/`: external service clients and parsing backends
- `scholaraio/stores/`: persistent library roots and storage helpers
- `scholaraio/projects/`: user project and workspace behavior
- `scholaraio/services/`: domain logic and orchestration
- `scholaraio/interfaces/cli/`: CLI parser, startup, and command handlers

The breaking cleanup generation removed legacy root-level public facades such as
`scholaraio.index`, `scholaraio.workspace`, and `scholaraio.translate`. New code
should import canonical namespaces directly.

High-signal canonical implementation pointers:

- `scholaraio/stores/explore.py`
- `scholaraio/projects/workspace.py`
- `scholaraio/services/insights.py`
- `scholaraio/services/translate.py`
- `scholaraio/interfaces/cli/`
- `scholaraio/interfaces/cli/compat.py` for internal CLI wiring
- `scholaraio/cli.py` as the published entrypoint only

## Current Runtime Model

- Runtime is fresh-layout-only under `data/libraries/`, `data/spool/`, and `data/state/`.
- Legacy roots such as `data/papers/`, `data/explore/`, `data/proceedings/`, and `data/inbox*` are no longer normal runtime inputs. Use `scholaraio migrate upgrade --migration-id <migration-id> --confirm` for the one-command supported migration, or `scholaraio migrate ...` to inventory, verify, and run individual stores.
- `workspace/<name>/` stays a free-form user project tree.
- Workspace paper references live in `workspace/<name>/refs/papers.json`.
- `workspace.yaml` is additive metadata only; it does not replace `refs/papers.json`.
- System-owned workspace outputs live under `workspace/_system/`, especially:
  - `workspace/_system/translation-bundles/`
  - `workspace/_system/figures/`
  - `workspace/_system/output/`
- Runtime-layout migration control lives under `.scholaraio-control/`. The standardized one-command upgrade gate is `scholaraio migrate upgrade --migration-id <migration-id> --confirm`; `finalize` remains the post-store cleanup/final verification step.

## Commands To Know

- `scholaraio --help`
- For repo-local validation, prefer `python -m scholaraio.cli ...` so you are exercising the current checkout instead of an older installed console script.
- `scholaraio setup check`
- `scholaraio search --help`
- `scholaraio show --help`
- `scholaraio pipeline --help`
- `scholaraio ws --help`
- `scholaraio paper2any --help`
- `scholaraio migrate --help`
- `scholaraio migrate upgrade --help`
- `scholaraio migrate finalize --help`

Common verification commands in this repo:

- `python -m pytest -q -p no:cacheprovider`
- `python -m ruff check scholaraio tests`
- `python -m ruff format --check scholaraio tests`
- `python -m mkdocs build --strict`

## Multi-Agent Entry Points

- Claude Code: `CLAUDE.md` + `.claude/skills/`
- Codex / OpenClaw: `AGENTS.md` + `.agents/skills/`
- Qwen: `.qwen/QWEN.md` + `.qwen/skills/`
- Cursor: `.cursor/rules/scholaraio.mdc`, then `AGENTS.md`
- Cline: `.clinerules`, then `AGENTS.md`
- Windsurf: `.windsurfrules`, then `AGENTS.md`
- GitHub Copilot: `.github/copilot-instructions.md`, then `AGENTS.md`

Keep these wrappers lightweight. Do not turn every wrapper into a second full manual.

Optional webtools MCP servers are listed in `.mcp.json` for hosts that support
project MCP JSON. Codex uses its own MCP registry; see
`docs/guide/webtools-integration.md` for `codex mcp add ...` commands.

## Deep Reference

Use the smallest doc that answers the question:

- Agent and skill organization: [`docs/guide/agent-reference.md`](docs/guide/agent-reference.md)
- Setup and installation: [`docs/getting-started/agent-setup.md`](docs/getting-started/agent-setup.md), [`docs/getting-started/installation.md`](docs/getting-started/installation.md), [`docs/getting-started/configuration.md`](docs/getting-started/configuration.md)
- CLI behavior: [`docs/guide/cli-reference.md`](docs/guide/cli-reference.md)
- Writing workflows: [`docs/guide/writing.md`](docs/guide/writing.md)
- Runtime layout and migration: [`docs/development/scholaraio-upgrade-plan.md`](docs/development/scholaraio-upgrade-plan.md), [`docs/development/directory-structure-spec.md`](docs/development/directory-structure-spec.md), [`docs/development/directory-migration-sequence.md`](docs/development/directory-migration-sequence.md), [`docs/development/migration-mechanism-spec.md`](docs/development/migration-mechanism-spec.md)

When in doubt, keep this file short, keep skills procedural, and keep deep detail in dedicated reference docs.
