# ScholarAIO Migration Mechanism Specification (Draft)

Status: Draft

Last Updated: 2026-04-17

Scope: implementation-facing migration control-plane specification for future runtime-layout upgrades.

## 1. Purpose

This document defines the minimum migration mechanisms ScholarAIO SHOULD implement before performing a real runtime-layout move for existing users.

This is not the directory-vision document and not the user-facing migration story document. Its job is narrower:

- define the minimum control metadata required for safe upgrades
- define when migration is allowed to run
- define how migration state is recorded
- define what "verification complete" means
- define which behaviors are automatic and which MUST remain explicit

This document exists so that future implementation work does not jump directly from "new directory idea" to "move user files".

## 2. Relationship to Other Migration Docs

This document is a companion to the existing migration documents:

- `docs/development/directory-structure-spec.md`
  - defines the target repository and runtime layout
- `docs/development/directory-migration-sequence.md`
  - defines execution order for path abstraction and physical moves
- `docs/development/user-data-migration-strategy.md`
  - defines the user-data preservation and product strategy

This document fills the missing middle layer:

- the migration control plane
- the minimum persistent metadata
- the rules for offline execution, journaling, validation, and cleanup

## 3. Agreed Product Decisions

The following product decisions are treated as settled assumptions for the first migration-capable implementation.

### 3.1 Offline Migration Only

The first real runtime-layout migration MUST be an offline migration.

Meaning:

- the user is not allowed to keep using ScholarAIO normally while migration is running
- migration MUST acquire an exclusive lock before mutating state
- mutating commands MUST refuse to run while a migration is active

Rationale:

- current ScholarAIO uses multiple SQLite databases in WAL mode
- current code also includes resumable and partially persisted work state such as translation workdirs, pending queues, and index rebuilds
- trying to support hot migration would add high risk with limited short-term benefit

### 3.2 One-Way Compatibility

Compatibility for the first migration generation MUST be one-way only.

Meaning:

- a new ScholarAIO version SHOULD be able to read the pre-migration layout
- after a runtime root is fully migrated to the new layout, older ScholarAIO versions MUST NOT continue opening it as if nothing changed

Rationale:

- two-way compatibility would force long-lived dual-write and dual-layout behavior
- the cost and risk are too high for the first migration generation

### 3.3 No Large Automatic Move on Startup

Large runtime-layout migration MUST remain an explicit user operation.

Meaning:

- startup MAY warn
- startup MAY create or refresh lightweight metadata
- startup MUST NOT silently move `data/`, `workspace/`, or other large user-owned trees

Small additive metadata upgrades MAY happen automatically if they are local, reversible, and do not relocate user content.

### 3.4 Multi-Root Merge Is Out of Scope for V1

The first migration generation MAY assume a single canonical runtime root chosen by the user or by the existing config-resolution path.

Meaning:

- V1 migration does not need to solve cross-root merge
- V1 migration does not need to auto-discover and unify multiple historical ScholarAIO roots

This is an intentional simplification, not a claim that multiple roots never exist.

## 4. Control Metadata Root

ScholarAIO SHOULD reserve a hidden control directory at runtime-instance root:

```text
instance-root/
├── config.yaml
├── config.local.yaml
├── data/
├── workspace/
└── .scholaraio-control/
```

Recommended contents:

```text
.scholaraio-control/
├── instance.json
├── migration.lock
└── migrations/
    └── <migration-id>/
        ├── plan.json
        ├── steps.jsonl
        ├── verify.json
        ├── rollback.json
        └── summary.md
```

### 4.1 Why a Dedicated Hidden Control Directory

The control metadata SHOULD NOT be mixed into `data/` or `workspace/` because those trees are themselves migration targets.

It SHOULD NOT use a generic filename such as `layout.json` at instance root because `layout.json` already has an established meaning inside paper directories for MinerU-derived layout artifacts.

The control metadata SHOULD live at a stable root-level location that works in both:

- local-clone mode
- plugin/global mode under `~/.scholaraio/`

## 5. Instance Metadata: `instance.json`

`instance.json` is the minimum durable record that tells ScholarAIO what kind of runtime root it is opening.

### 5.1 Required Responsibilities

`instance.json` SHOULD answer four questions:

- what layout generation this runtime root uses
- whether migration is currently in progress or incomplete
- which ScholarAIO version last wrote the metadata
- whether the runtime root can be opened normally

### 5.2 Recommended Minimal Fields

The exact schema MAY evolve, but the first version SHOULD include fields equivalent to:

- `instance_meta_version`
- `layout_version`
- `layout_state`
- `writer_version`
- `instance_id`
- `updated_at`
- `last_successful_migration_id`

Recommended meanings:

- `instance_meta_version`
  - schema version of `instance.json` itself
- `layout_version`
  - semantic version or integer generation of the runtime layout
- `layout_state`
  - one of `legacy_implicit`, `normal`, `migrating`, `needs_recovery`
- `writer_version`
  - ScholarAIO version that last updated the metadata
- `instance_id`
  - stable identifier for the runtime root
- `updated_at`
  - last metadata update timestamp
- `last_successful_migration_id`
  - the journal ID of the last completed migration

### 5.3 Startup Behavior

The startup rules SHOULD be:

- if `instance.json` does not exist:
  - treat the runtime root as legacy implicit layout
  - continue in compatibility mode
- if `instance.json` exists and `layout_state == migrating`:
  - refuse normal writes
  - require migration recovery, retry, or explicit rollback handling
- if `instance.json` exists and `layout_version` is newer than the running program supports:
  - refuse to open normally
  - show an upgrade-required message
- if `instance.json` exists and is supported:
  - continue normally

### 5.4 File-Naming Constraint

The root-level layout marker MUST NOT be a plain `layout.json`.

Reason:

- `layout.json` is already a meaningful per-paper artifact name in the current ingest and parsing flow
- reusing the same generic name at runtime root would make logs, support requests, and migration tooling more error-prone

## 6. Migration Lock: `migration.lock`

`migration.lock` is the mechanism that turns "offline migration only" into an enforceable runtime rule.

### 6.1 Required Responsibilities

The lock MUST:

- guarantee at most one active migration per runtime root
- block normal mutating commands while migration is in progress
- preserve enough metadata to explain who owns the lock and when it started

### 6.2 Recommended Minimal Fields

The lock file SHOULD record:

- `migration_id`
- `pid`
- `hostname`
- `started_at`
- `writer_version`
- `mode`

`mode` MAY distinguish states such as `plan`, `run`, or `rollback` if needed later. For V1, `run` is sufficient.

### 6.3 Command Gating Rule

While `migration.lock` exists, normal ScholarAIO commands SHOULD fail fast unless they belong to the migration/recovery surface.

For V1, the simplest rule is:

- allow only migration-status and migration-recovery commands
- refuse all other commands, including normal read commands

This is intentionally conservative. The goal is not to maximize availability during migration. The goal is to minimize accidental mixed-state access.

### 6.4 Stale Lock Handling

The first implementation SHOULD treat stale locks cautiously.

Minimum behavior:

- detect that the owning process no longer exists when possible
- require explicit user confirmation or explicit recovery command before ignoring a stale lock

The system MUST NOT silently delete a lock just because a timestamp looks old.

## 7. Migration Journal

Each migration run SHOULD create a dedicated journal directory under:

```text
.scholaraio-control/migrations/<migration-id>/
```

The journal is the durable record of what the migration attempted and what actually happened.

### 7.1 Required Responsibilities

The journal MUST make it possible to answer:

- what the plan was
- what actually ran
- which step failed or succeeded
- what still needs verification
- what data the user should keep or clean up

### 7.2 Recommended Files

#### `plan.json`

The frozen migration plan for this run.

It SHOULD record at least:

- source layout version or legacy status
- target layout version
- selected runtime root
- discovered stores and project roots
- expected moves or rewrites
- estimated rebuild tasks

#### `steps.jsonl`

An append-only execution log.

Each entry SHOULD include:

- step name
- timestamp
- status
- message
- optional details

JSONL is preferred because it is easy to append safely and easy to inspect incrementally.

#### `verify.json`

The structured verification result.

It SHOULD record:

- which verification checks ran
- pass or fail status for each check
- summary counts
- follow-up action if verification is incomplete

#### `rollback.json`

The rollback recipe or rollback-relevant state.

This file does not require a perfect reverse operation graph in V1. It MUST at least preserve enough information to support deterministic recovery decisions.

#### `summary.md`

A human-readable report.

It SHOULD explain in plain language:

- what changed
- what was preserved in place
- what was rebuilt
- whether cleanup is safe
- where the old data still lives, if it still exists

### 7.3 Journal Lifetime

The migration journal MUST survive until cleanup completes.

The journal MUST NOT be deleted immediately after a successful `run`.

## 8. Verification Contract

Verification is the final safety gate between "data moved" and "migration accepted".

### 8.1 Minimum Verification Scope

The first implementation SHOULD verify at least:

- config still loads
- papers can be enumerated
- workspace directories can be enumerated
- paper UUID lookup still works
- keyword search still works
- proceedings search works if proceedings exist
- one explore silo can be opened if any exist
- toolref current-version resolution still works if toolref exists
- translation resume state can still be detected if any translation workdir exists

### 8.2 Verification Philosophy

Verification SHOULD focus on user-visible system health, not just filesystem existence.

That means the verification target is not:

- "did the directory appear"

It is:

- "can ScholarAIO still operate on the migrated data in the ways users depend on"

### 8.3 Success Rule

A migration MUST NOT be marked fully accepted until verification succeeds.

Implication:

- `instance.json` MUST NOT be finalized as fully migrated before verification passes
- cleanup MUST remain blocked until verification passes

## 9. Product Flow Requirements

### 9.1 Startup Flow

The desired startup behavior is:

1. detect legacy-compatible layout
2. continue working normally
3. inform the user that migration is available
4. do not perform the large move automatically

This matches the compatibility-first strategy already defined in the migration strategy document.

### 9.2 `migrate plan`

`migrate plan` SHOULD:

- inspect the current runtime root
- classify the current layout
- inventory major data surfaces
- estimate required rebuilds
- report blockers
- produce a dry-run journal or equivalent plan record

`migrate plan` MUST NOT mutate user data.

### 9.3 `migrate run`

`migrate run` SHOULD:

- acquire the migration lock
- initialize the journal
- mark `instance.json` as `migrating`
- perform the physical and logical migration work
- run verification
- update instance metadata on success
- preserve rollback-relevant state on failure

If migration fails mid-run, the runtime root MUST remain recoverable and MUST NOT be silently treated as fully migrated.

### 9.4 `migrate verify`

`migrate verify` SHOULD:

- rerun the verification contract
- refresh `verify.json`
- refresh the user-facing summary if needed

This command is especially useful when the user wants extra confidence before cleanup.

### 9.5 `migrate cleanup`

`migrate cleanup` SHOULD:

- require a successful verification record
- remove or archive legacy trees only after explicit confirmation
- preserve enough metadata to explain what was removed

Cleanup MUST be a separate step from migration execution.

### 9.6 Rollback Surface

Whether rollback is fully automatic or partly operator-driven MAY vary in V1.

However, the implementation MUST support one of the following:

- automatic rollback during failed `migrate run`
- a deterministic manual recovery path driven by the migration journal

The system MUST NOT leave operators with only an unstructured partial filesystem and no durable record of what happened.

## 10. Safety Constraints for Planning and Inventory

### 10.1 Planning Must Be Non-Executing

`migrate plan` and inventory logic MUST NOT execute arbitrary user-provided code as part of discovery.

Implication:

- planning custom citation styles MUST treat them as files, not as importable Python modules
- planning unknown workspace contents MUST not interpret them

### 10.2 Unknown Files Are Reported, Not Dropped

If planning encounters files that do not match a known schema, it SHOULD:

- preserve them
- report them in the plan if useful

It MUST NOT:

- silently discard them
- silently rewrite them

### 10.3 Current Backup Command Is Not Sufficient as the Only Safety Net

Migration protection MUST NOT rely only on the current `backup` feature, because current backup defaults still focus on `data/` rather than the full runtime root.

Migration needs its own lock, journal, and verification path even if backup integration is added later.

## 11. Non-Goals for the First Implementation

The first implementation does not need to solve all future migration concerns.

It MAY explicitly defer:

- online or hot migration
- automatic multi-root discovery and merge
- cross-machine coordinated migration
- background asynchronous migration workers
- moving root-level agent wrappers or skill discovery surfaces
- perfect reversible rollback for every partial step

The V1 goal is narrower:

- safe
- explicit
- inspectable
- supportable

## 12. Minimum Deliverables Before Real Physical Migration

Before ScholarAIO performs a real runtime-layout move for existing users, the codebase SHOULD have all of the following:

- a stable root-level control directory
- `instance.json` support
- migration lock support
- migration journal support
- explicit verification support
- startup gating for unsupported future layouts
- command gating while migration is active

Without these pieces, ScholarAIO would still be doing a refactor, not a user-safe upgrade.
