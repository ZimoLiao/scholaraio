---
title: "refactor: Remove Paper2Any"
type: refactor
status: completed
date: 2026-08-30
---

# refactor: Remove Paper2Any

## Summary

Remove ScholarAIO's Paper2Any CLI, MCP sidecar, configuration, setup diagnostics,
provider code, skill, documentation, tests, and isolated local runtime. Artifact
creation remains available through the active agent and ScholarAIO's native
document, draw, poster, writing, and review workflows.

## Decision

Paper2Any never produced the fixed-corpus evidence required by ScholarAIO's
third-party admission gate. Its advertised workflows substantially overlap the
active agent, while ScholarAIO carried a broad integration surface and the local
checkout plus environment consumed about 3.1 GB. The local sidecar was not
running, and the retained outputs were benchmark artifacts rather than durable
ScholarAIO library state.

This is a breaking cleanup for the next major generation. The documented 2.x
CLI, configuration, and skill contracts prohibit shipping the removal in a 2.x
patch or minor release without the required deprecation window.

## Scope

- Remove the `paper2any` skill and CLI command family.
- Remove MCP client/server, checkout setup, and backend-launch providers.
- Remove configuration fields, environment-facing setup checks, templates, and
  current user documentation.
- Remove integration-specific tests and add negative contract coverage proving
  the surface stays absent.
- Preserve historical changelog and completed-plan records.
- Move the exact local runtime directory to the system trash so old benchmark
  outputs remain recoverable until the trash is emptied.

## Validation

- Repo-local CLI help and setup checks do not mention Paper2Any.
- Current source, skill, config, and published docs do not expose Paper2Any.
- Full pytest passed: 1,547 tests.
- Ruff lint and format checks passed.
- MkDocs strict build passed.
- The 3.1 GB local runtime was moved to
  `~/.local/share/Trash/files/paper2any` and is recoverable until trash is
  emptied.

## Rollout Constraint

Do not merge this work into the 2.x line as a patch or minor change. Land it only
as part of a next-major release path.
