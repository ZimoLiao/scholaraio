---
title: "refactor: Remove External Webtools"
type: refactor
status: completed
date: 2026-08-30
---

# refactor: Remove External Webtools

## Summary

Remove ScholarAIO's qt-web-extractor and dormant GUILessBingSearch integration
surfaces. Live web discovery and URL reading belong to the active agent;
reviewable content can still enter ScholarAIO through supported inbox files and
the normal ingest pipeline.

## Decision

The upstream qt-web-extractor added useful multimodal PDF/image handling,
lazy-loaded image recovery, SVG text extraction, and stronger regression tests.
It still requires a separately operated PySide6/Qt WebEngine service and has no
tagged release or stable published package. That narrow rendered-page value did
not justify permanent MCP, skill, CLI, config, setup, provider, documentation,
and validation ownership inside ScholarAIO.

This removal follows `STRATEGY.md` and the third-party integration gate. It is a
breaking cleanup for the next major generation: the documented `webextract` and
`ingest-link` surfaces must not be removed in a 2.x release without the
deprecation window required by `docs/design-docs/2.x-public-contract.md`.

## Scope

- Remove the project MCP registration and both web-extraction skills.
- Remove `webextract` / `ingest-link` CLI parsing, handlers, compatibility
  aliases, provider code, setup diagnostics, and config fields.
- Remove the ingest-link-only image localization service and now-orphaned
  sanitizer fixtures.
- Remove the dormant GUILessBingSearch compatibility implementation bundled in
  the same provider.
- Update current setup, CLI, integration-audit, config-audit, and release
  validation documentation.
- Preserve historical changelog and validation reports, plus compatibility for
  persisted metadata values such as `extraction_method: qt-web-extractor`.

## Validation

- Full pytest suite: 1,568 passed.
- Ruff lint and format checks passed.
- MkDocs strict build passed.
- Package, typecheck, semantic smoke, and Python 3.10/3.11/3.12 CI checks passed
  on the reviewed implementation commit.
- Repo-local CLI help and `setup check` no longer expose or diagnose external
  webtools.

## Rollout Constraint

Do not merge this work into the 2.x line as a patch or minor change. Land it only
as part of a next-major release path.
