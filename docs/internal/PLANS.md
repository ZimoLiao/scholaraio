# Repository Plans

Status: Current map

Last Updated: 2026-07-21

Plans are repository knowledge, not chat history. Store them here so agents can
resume work without relying on external context.

## Active Plans

There are no active execution plans. Product-scope decisions are grounded in
the repository-root `STRATEGY.md`; release work should create a focused active
plan only when implementation spans multiple resumable stages.

## Completed Plans

- `docs/internal/exec-plans/completed/2026-08-30-remove-external-webtools-plan.md`
  records the next-major removal of qt-web-extractor and the dormant external
  web-search compatibility adapter.
- `docs/internal/exec-plans/completed/scholaraio-upgrade-plan.md` is the current upgrade
  entry point for the 1.4 runtime-layout cleanup record.
- `docs/internal/exec-plans/completed/breaking-compat-cleanup-plan.md` records the
  breaking cleanup generation for legacy import and runtime layout behavior.
- `docs/internal/exec-plans/completed/2026-06-05-001-feat-agent-setup-automation-plan.md`
  records the completed cross-project agent setup automation feature.

## Planning Rules

- Use `active/` for plans that still describe work to execute.
- Use `completed/` for plans whose execution is historical context.
- Keep progress in commits and pull requests; avoid editing old plan bodies only
  to mark status.
- Promote long-lived decisions from plans into `docs/design-docs/` or
  `docs/product-specs/`.
- Keep known follow-up work in `docs/internal/exec-plans/tech-debt-tracker.md` when it is
  too small or too cross-cutting for a full plan.
