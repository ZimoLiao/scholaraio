# Tech Debt Tracker

Status: Current tracker

Last Updated: 2026-07-21

This file is for small, durable follow-up items discovered during agent work.
Use a full execution plan when the work needs design context, sequencing, or
multiple implementation units.

## Open

- **P1:** Fix `.github/workflows/macos-semantic-smoke.yml` path filters so the
  canonical Explore/index/vector/CLI modules trigger the job, and cover the
  filters in `tests/test_ci_workflows.py`.
- **P1:** Remove the residual no-config `data/explore` runtime path and align all
  active config/setup/guide text with the fresh-layout-only contract.
- **P2:** Pass caller-supplied OpenAlex configuration through the complete
  provider request path.
- **P2:** Create an execution plan to replace the circular CLI compatibility hub
  with modular parser registration and an explicit CLI context.
- **P2:** Restore architectural direction by separating Explore provider/store
  orchestration, moving shared metadata models below providers/services, and
  splitting LLM transport from metrics.
- **P2:** Establish complexity and typing ratchets for ingestion, migration,
  Explore, and CLI hotspots; retire the Toolref legacy snapshot from the shipped
  package.
- **P2:** Move `mineru-open-api` out of base and validate supported extras from
  clean wheels with `pip check` and smoke tests.
- See `docs/internal/references/code-and-dependency-technical-debt-audit.md` for
  evidence, dependency decisions, and the recommended sequence.
- Add generated CLI or schema references under `docs/generated/` once the
  refresh command and freshness check are agreed.
- Add automated stale-link or freshness checks for repository knowledge indexes.

## Closed

- 2026-08-30: Removed the Paper2Any CLI, MCP sidecar, config, setup, provider,
  skill, docs, and test surface after it failed to establish unique value over
  agent-native workflows; the local isolated runtime was recoverably removed.
- 2026-07-21: Removed the runtime-unowned `mermaid-py` and
  `cli-anything-inkscape` requirements while preserving the empty `draw` extra
  as an installation-compatibility marker.
