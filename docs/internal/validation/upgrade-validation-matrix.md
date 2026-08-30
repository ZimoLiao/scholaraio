# ScholarAIO Upgrade Validation Matrix

Status: Compatibility-window validation authority

Last Updated: 2026-08-30

Scope: release-grade functional validation, migration rehearsal, migration-state detection, and acceptance gates for the current breaking cleanup generation built on top of the completed compatibility-window upgrade.

Execution record:

- `docs/internal/validation/reports/upgrade-validation-report-20260423.md`
  - current end-to-end rehearsal record for the 2026-04-23 validation run
- `docs/internal/validation/reports/upgrade-validation-report-20260424.md`
  - real-data migration, real-root CLI validation, and breaking-cleanup finalization record
- `docs/internal/validation/reports/upgrade-validation-report-20260425-main-v1.3.1.md`
  - main/v1.3.1 command-surface comparison, recent PR cross-check, 67-command real CLI canary record, and legacy one-command migration rehearsal

2026-04-24 implementation note:

- current explicit `migrate run` coverage is `citation_styles`, `toolref`, `explore`, `proceedings`, `spool`, `papers`, and `workspace`
- current migration control-plane surface is `scholaraio migrate status|plan|recover|verify|cleanup|run|finalize|upgrade`
- current release validation must verify the fresh-layout-only runtime plus the hardened post-migration finalization path
- current release signoff must verify both migration rehearsal and `migrate upgrade --confirm`; `migrate finalize --confirm` remains the lower-level post-store cleanup gate

2026-08-30 next-major cleanup note:

- `webextract` and `ingest-link` are no longer release surfaces or provider
  canaries; live web access is host-native and persisted content uses the normal
  document inbox

## 1. Purpose

This document defines what must be tested before the team may claim that the compatibility-window upgrade is correct.

It exists to answer four concrete questions:

1. what feature coverage must be exercised on the upgraded codebase
2. how a legacy runtime root must be detected, classified, and rehearsed through migration
3. what evidence is required before a migration can be called safe
4. what post-migration checks must still pass before the release can be called complete

This is not another directory-vision document. It is the release gate for the current upgrade generation.

## 2. Relationship to Other Upgrade Docs

Use the development documents in this order:

- `docs/internal/exec-plans/completed/scholaraio-upgrade-plan.md`
  - entry point and authority map
- `docs/design-docs/directory-structure-spec.md`
  - target runtime and repository layout
- `docs/design-docs/directory-migration-sequence.md`
  - move order and implementation sequencing
- `docs/design-docs/migration-mechanism-spec.md`
  - control-plane contract, journals, locking, verify, cleanup
- `docs/design-docs/user-data-migration-strategy.md`
  - compatibility and user-data preservation policy
- `docs/internal/references/config-surface-audit.md`
  - path-authority history and remaining config-risk context
- `docs/internal/validation/upgrade-validation-matrix.md`
  - the release-grade validation and migration rehearsal gate

The first six documents define what ScholarAIO should be. This document defines what must be demonstrated before we say it is working.

## 3. Non-Negotiable Release Rule

The upgrade is not complete just because unit tests pass or `migrate run` succeeds once.

The release may be called correct only when all of the following are true:

- deterministic repo checks are green
- representative feature smoke tests pass on a fresh-layout runtime root
- representative feature smoke tests pass on a legacy-layout runtime root before migration
- migration detection and planning are correct on the rehearsal root
- each currently supported migration store is executed and verified in journaled form
- post-migration feature regression passes on the migrated root
- recovery and cleanup paths are exercised
- provider-backed surfaces are either run successfully or explicitly marked unverified in the release record

A `--help` screen does not count as functional validation. Every feature family below requires at least one behavioral command that reads, writes, searches, transforms, migrates, or verifies real artifacts.

## 4. Required Validation Assets

### 4.1 Runtime Copies

Validation must use disposable copies, not the operator's real long-lived runtime root.

Recommended working area:

```text
workspace/release-validation/<stamp>/
├── fixtures/
├── fresh-root/
├── legacy-root/
├── migrated-root/
└── evidence/
```

Recommended rule:

- `fresh-root/` proves the new defaults work cleanly
- `legacy-root/` proves compatibility reading and migration detection
- `migrated-root/` proves the post-migration runtime still behaves correctly
- `evidence/` stores command transcripts, journal snapshots, outputs, and summaries

### 4.1.1 Writable Execution Rule

Rehearsal roots must be writable.

Reason:

- current CLI startup calls `cfg.ensure_dirs()`
- even read-oriented commands may create accessor-backed directories such as workspace output roots or control metadata roots
- validating against a read-only copy of a real runtime root will produce false failures unrelated to the feature under test

Practical rule:

- never point release validation at a read-only bind mount of the real runtime root
- always validate against a writable disposable copy

### 4.1.2 Config Discovery Rule

Each rehearsal root must contain a valid `config.yaml`.

Commands must be executed in one of two ways:

- run from the rehearsal root so config discovery finds its local `config.yaml`
- or set `SCHOLARAIO_CONFIG=<rehearsal-root>/config.yaml`

Do not assume the current shell working directory or a developer's global `~/.scholaraio/config.yaml` will point at the intended rehearsal root.

### 4.2 Local Fixture Sources

If the local machine already has a sibling checkout at `../scholaraio/`, treat it as the preferred seed source for rehearsal data, but never mutate it in place.

Current useful local sources already observed there:

- root config at `../scholaraio/config.yaml`
- optional local-only secrets at `../scholaraio/config.local.yaml`
- legacy runtime roots under `../scholaraio/data/`
  - `data/papers/`
  - `data/explore/`
  - `data/proceedings/`
  - `data/inbox*`
  - `data/pending/`
  - `data/index.db`
- legacy workspaces under `../scholaraio/workspace/*/papers.json`
- at least one paper PDF at `../scholaraio/workspace/annual-review-particle-turbulence/main.pdf`
- inbox Markdown seeds under `../scholaraio/data/inbox/`
- real pending cases under `../scholaraio/data/pending/`, including `paper.md`, `pending.json`, images, and some original PDFs

Recommended operator rule:

- copy from `../scholaraio/` into `workspace/release-validation/<stamp>/...`
- never run migration directly against `../scholaraio/`
- never use the real sibling checkout as the only evidence source for destructive or semi-destructive rehearsal
- copy `config.local.yaml` only when provider-backed canaries are intentionally in scope on the disposable root
- if `config.local.yaml` is not copied, keep provider-backed surfaces in the release record as explicitly unverified rather than failing deterministic local validation

### 4.2.1 Fixture Tiers

Not all copied fixtures are equivalent.

Use these tiers explicitly:

- `structural-only`
  - proves that file trees, metadata files, and compatibility readers are intact
  - may be enough for baseline read-path smoke
  - is not enough for a green `migrate verify` if searchable derived state is missing or stale
- `searchable`
  - includes the corresponding searchable state or has been rebuilt locally so search probes are meaningful
  - required before expecting `keyword_search_accessible`, `explore_search_accessible`, or similar verify checks to pass

Practical examples from real CLI rehearsal:

- copying `data/papers/` without rebuilding `index.db` may leave `keyword_search_accessible` failing even when `search` can still return some results
- copying an `explore` library with only `papers.jsonl` and `meta.json` is structural-only; a green `explore_search_accessible` check requires a searchable fixture such as one with `explore.db` or an equivalent local rebuild
- a proceedings volume tree without searchable proceedings papers and `proceedings.db` is enough for proceedings-volume helper checks, but not for `fsearch --scope proceedings ...`

### 4.3 Minimum Input-Class Coverage

The validation corpus must cover at least these classes before the release may be called fully validated:

- already ingested paper directory with `meta.json` and `paper.md`
- workspace with legacy `papers.json`
- legacy search DB / registry state
- legacy `explore` library
- legacy `proceedings` library
- pending entry with `pending.json`
- regular inbox item
- at least one PDF-backed ingest or attach flow
- at least one export/output flow that writes user-visible artifacts

If thesis / patent / document / proceedings-volume ingest is part of the claimed release scope, each class must also have a real sample in the rehearsal corpus. If those samples are missing locally, release signoff must stop until they are copied in or otherwise prepared.

### 4.4 Durable Content vs Derived State

Default release posture:

- migrate durable user-owned content as whole trees
- rebuild derived search/index state wherever a supported rebuild path exists

Durable content that should be copied or migrated intact includes:

- `data/papers/<paper-dir>/`
- `data/pending/<item>/`
- raw inbox files such as PDF / Markdown / Office inputs
- `workspace/<name>/`
- paper-level `meta.json`, `paper.md`, `notes.md`, translated Markdown, images, layout artifacts, and resume state

Derived state that should normally be rebuilt or re-derived after relocation or downsampling includes:

- main-library keyword/vector search state such as `data/index.db`, `faiss.index`, and `faiss_ids.json`
- BERTopic output under `data/topic_model/` or future `data/state/topics/`
- `data/explore/<name>/explore.db`, explore FAISS, and explore topic artifacts
- `data/proceedings/proceedings.db` or future proceedings search DB state

Current compatibility-window guidance:

- if a supported rebuild surface exists, prefer rebuild over trusting copied index state
- if no rebuild surface exists yet for a store, copy-then-verify is still acceptable, but the copied DB must be treated as derived and non-authoritative
- operator default for this release should be: migrate PDF / Markdown / JSON / images / workspace trees intact, then rebuild index-like state before calling the migrated root release-grade

## 5. Evidence Capture

Every validation run should leave a compact but durable evidence bundle under:

```text
workspace/release-validation/<stamp>/evidence/
├── environment.txt
├── commands.txt
├── repo-checks.txt
├── fresh-smoke.txt
├── legacy-smoke.txt
├── online-canaries.txt
├── migration/
│   ├── status-before.json
│   ├── plan.json
│   ├── verify-before.json
│   ├── run-<store>.txt
│   ├── verify-after-<store>.json
│   ├── cleanup-preview.txt
│   ├── cleanup-confirm.txt
│   ├── finalize.txt
│   └── status-after.json
└── summary.md
```

Minimum evidence expectations:

- exact commands run
- current git commit SHA
- path to the rehearsal root used
- captured migration journal IDs
- captured `migrate finalize --confirm` output when finalization is part of the rehearsal
- captured post-finalize `migrate status` output proving `layout_state=normal`,
  `layout_version=1`, and the activity-selected `latest_journal`
- sample output artifact paths for export / diagram / translation / document checks
- explicit list of surfaces still unverified, if any

## 6. Migration-State Detection Matrix

Before any store move, classify the root correctly.

| State | Signals | What must still work | Required operator action |
| --- | --- | --- | --- |
| `legacy_implicit` | no `instance.json`, or compatibility bootstrap sets `layout_state=legacy_implicit` | `scholaraio migrate status`, normal compatibility reads, baseline feature smoke | run baseline checks, then `migrate plan` |
| `normal` | supported `instance.json`, no active `migration.lock` | normal commands, `migrate status`, `migrate verify` | continue normal validation or post-migration regression |
| `migrating` | `migration.lock` exists and `instance.json.layout_state == migrating` | migration/recovery surface only | stop feature testing; inspect journal; recover or continue migration intentionally |
| `needs_recovery` | `instance.json.layout_state == needs_recovery` | `migrate status`, `migrate recover --clear-lock` | do not continue normal validation until the recovery path is documented and the root is stable again |
| unsupported future layout | `instance.json.layout_version` newer than running code supports | `migrate status` only | upgrade the program before using the root |
| mixed legacy + fresh content | both old and new store roots exist with divergent content | `migrate status`, `migrate plan`, targeted inventory | stop and record the divergence before claiming a green migration path |

### 6.1 Store-Level Migration-Need Detection

For the current compatibility window, a rehearsal root must inventory these store signals:

| Store | Legacy signal to detect | Fresh target after migration |
| --- | --- | --- |
| `citation_styles` | `data/citation_styles/` | `data/libraries/citation_styles/` |
| `toolref` | legacy toolref root discovered by `Config` | `data/libraries/toolref/` |
| `explore` | `data/explore/` | `data/libraries/explore/` |
| `proceedings` | `data/proceedings/` | `data/libraries/proceedings/` |
| `spool` | `data/inbox*` and `data/pending/` | `data/spool/inbox*` and `data/spool/pending/` |
| `papers` | `data/papers/` | `data/libraries/papers/` |

Required commands:

```bash
scholaraio migrate status
scholaraio migrate plan --migration-id <migration-id>
scholaraio migrate verify --migration-id <migration-id>
```

The plan must be reviewed before any `migrate run` is accepted.

Post-migration cleanup rule:

- for user-facing one-command migration, prefer `scholaraio migrate upgrade --migration-id <migration-id> --confirm`
- after all intended `migrate run --store ... --confirm` steps are green, the hardened one-click cleanup path is `scholaraio migrate finalize --migration-id <migration-id> --confirm`
- finalize is not a cosmetic wrapper around `cleanup --confirm`; it is the
  required operator-facing gate that must:
  - migrate workspace root `papers.json` to `refs/papers.json`
  - migrate legacy workspace system-output roots into `workspace/_system/`
  - preserve existing canonical target files on conflict
  - archive the remaining legacy roots into the journal
  - leave the root reporting `layout_state=normal` and `layout_version=1`

### 6.2 Store Presence Classification

Before running store moves, classify each supported store in the rehearsal root as one of:

- `present_searchable`
  - durable content exists and the corresponding searchable or queryable state is ready for verification
- `present_structural_only`
  - durable content exists but searchable state is absent or stale; structural smoke is possible, but a green verify is not yet expected
- `not_present`
  - the rehearsal root genuinely has no legacy content for that store
- `blocked`
  - the store should be present, but fixture corruption, missing dependencies, or operator mistakes prevent safe validation

Execution rule:

- only run `migrate run --store ...` for stores classified `present_searchable` or `present_structural_only`
- stores classified `not_present` must be recorded as `N/A`, not forced through a fake migration
- stores classified `blocked` stop release signoff until the block is resolved or explicitly waived

## 7. Release Gates

The release gate is intentionally sequential.

Execution discipline:

- run migration-control commands serially on one rehearsal root
- do not parallelize `status`, `plan`, `verify`, `run`, `cleanup`, `cleanup --confirm`, `finalize --confirm`, or `upgrade --confirm` against the same root
- each step must finish and persist its journal artifacts before the next control-plane command is evaluated

### Gate G0. Repo And Environment Sanity

Must pass:

- `python -m ruff check scholaraio tests`
- `python -m ruff format --check scholaraio tests`
- `git diff --check`
- `python -m mkdocs build --strict`
- `python -m pytest -q -p no:cacheprovider`

This gate proves the branch is internally consistent. It does not replace runtime validation.

### Gate G1. Fresh-Root Feature Baseline

Goal:

- prove the new default layout works on a clean runtime root without relying on legacy fallbacks

Fresh-root preparation rule:

- seed `fresh-root/` only with new-layout stores such as `data/libraries/...`, `workspace/...`, and the matching rebuilt or copied derived state needed for the chosen smoke set
- do not seed `fresh-root/` with legacy roots such as `data/papers/` or `data/explore/` if the purpose of that root is to prove fresh-layout defaults
- copying `../scholaraio/config.yaml` is acceptable when it still uses the default compatibility aliases such as `data/papers`; the current config resolver maps those defaults to fresh-layout locations when only fresh-layout stores are present

Minimum surface coverage:

| Feature family | Representative commands | Minimum acceptance |
| --- | --- | --- |
| startup and config | `scholaraio --help`, `scholaraio setup check` | CLI boots normally and reports usable config state |
| paper retrieval | `scholaraio search ...`, `show ...`, `search-author ...`, `fsearch ...` | search returns expected hits and `show` can load paper content progressively |
| semantic/index path | `embed`, `vsearch`, `usearch`, `index` | index DB updates and semantic or hybrid search returns expected records |
| citation graph | `refs`, `citing`, `shared-refs`, `top-cited` | graph-derived outputs are readable and non-empty on the seed corpus |
| data quality | `audit`, `repair`, `rename`, `backfill-abstract` | commands run against a disposable target and leave expected metadata changes or reports |
| local writing and citation validation | `citation-check` against a local file or stdin | real citations are recognized, ambiguous matches are reported, and missing citations are surfaced clearly |
| workspace | `ws init`, `ws add`, `ws list`, `ws show`, `ws search`, `ws export` | named workspace remains usable and outputs remain under `workspace/` |
| export and document outputs | `export`, `document inspect` | at least one real export artifact is created and inspected successfully |
| local diagram rendering | `diagram --from-ir ...` with a prepared IR fixture | rendering works and output is written to the expected accessor-backed path; the IR fixture must include `title`, `nodes`, `edges`, and `layout_hint`, and edges must use `from` / `to` keys |
| explore and federated search | `explore list/info/search --name <lib> ...`, `fsearch --scope explore:* ...` | explore stores open correctly and federated search can include them |
| tool documentation | `toolref list/search/show/use` | current-version resolution and doc retrieval work against the local toolref store |
| proceedings search | `fsearch --scope proceedings ...` only when the fixture includes searchable proceedings papers plus `proceedings.db` | proceedings search works against a genuinely searchable proceedings fixture |
| proceedings volume helpers | `proceedings build-clean-candidates ...`, `apply-clean ...`, or `apply-split ...` against a proceedings-volume fixture | proceedings-volume management flows still route even when no searchable proceedings DB exists |
| insights and metrics | `insights`, `metrics --summary` | metrics DB is readable and insights produce stable output |
| citation styles | `style list`, `style show ...` | style store is readable and no path regression is present |
| backup surface | `backup list`, `backup run <target> --dry-run` when a target exists | backup routing still works and a dry-run plan can be produced |
| ingest/import local surfaces | `attach-pdf --dry-run`, `import-endnote --dry-run`, `import-zotero --local ... --dry-run` when a local fixture exists | import plans and attach plans resolve the right targets without mutating the rehearsal root unexpectedly |
| pipeline local surface | `pipeline --list`, plus a fixture-appropriate `pipeline <preset> --dry-run --inspect` or `pipeline --steps ... --dry-run --inspect` | pipeline planning works on the chosen fixture type and reports a realistic execution plan |
| topic-model local surface | `topics --build` and `topics --topic ...` when BERTopic dependencies are available and the fixture size is appropriate | topic model build or readback works on the rehearsal corpus |

Important nuance for `pipeline`:

- `pipeline --dry-run --inspect` by itself is incomplete; current CLI requires either a preset such as `full|ingest|enrich|reindex` or an explicit `--steps`
- for an md-only inbox fixture, prefer an explicit dry-run such as `pipeline --steps extract,dedup,ingest,embed,index --dry-run --inspect`
- for a PDF inbox fixture with a real MinerU path available, `pipeline ingest --dry-run --inspect` is the stronger smoke

Important nuance for LLM-backed surfaces:

- `enrich-toc`, `enrich-l3`, `translate`, and `diagram --from-text` are provider-backed canaries, not deterministic local smokes
- keep them in Gate G7 unless the release is explicitly scoped to an offline/mock backend

### Gate G2. Legacy-Root Compatibility Baseline

Goal:

- prove the upgraded program still reads the pre-migration layout correctly before any physical store move

Must demonstrate:

- old `data/papers/`, `data/explore/`, `data/proceedings/`, `data/inbox*`, and `workspace/<name>/papers.json` remain readable through compatibility accessors
- at least one search, one `show`, one workspace command, and one explore / toolref / proceedings read path succeed on the legacy copy
- no command silently rewrites the large legacy root just by opening it
- the rehearsal root remains writable even for read-oriented commands, because CLI startup may create accessor-backed directories or control metadata

Recommended minimum commands:

```bash
scholaraio migrate status
scholaraio search <query>
scholaraio show <paper-id>
scholaraio ws list
scholaraio explore list
scholaraio toolref list
scholaraio fsearch --scope proceedings <query>
```

### Gate G3. Migration Detection And Planning

Goal:

- prove that ScholarAIO can correctly classify the root and describe the proposed store moves before any copy happens

Required outputs:

- `migrate status` on the rehearsal root
- one frozen `plan.json`
- one pre-run `verify.json`
- written note of blockers or conflicts, if any

Mandatory rule:

- if plan or verify reports unresolved blockers, do not continue to `migrate run`

### Gate G4. Per-Store Migration Rehearsal

Stores must be migrated in the currently approved order:

1. `citation_styles`
2. `toolref`
3. `explore`
4. `proceedings`
5. `spool`
6. `papers`

Only stores classified as present in Section 6.2 should be run. `not_present` stores are recorded as `N/A` for that rehearsal root.

Required command pattern:

```bash
scholaraio migrate run --store <store> --migration-id <migration-id> --confirm
scholaraio migrate verify --migration-id <migration-id>
```

Compatibility-window note:

- a per-store `migrate run` may record `verify.json.status = passed_with_warnings` when the only remaining failed checks are explicitly non-authoritative derived-state checks waiting on a documented rebuild
- this does not replace the final post-rebuild green gate; the migrated root is only release-grade after the rebuild step and a fully green follow-up `migrate verify`

After each store move, run the targeted smoke family most affected by that store:

| Store | Required targeted smoke after `migrate run` |
| --- | --- |
| `citation_styles` | `style list`, `style show ...` |
| `toolref` | `toolref list`, `toolref search ...`, `toolref show ...` |
| `explore` | `explore list`, `explore info ...`, `explore search ...`, `fsearch --scope explore:* ...` |
| `proceedings` | `fsearch --scope proceedings ...` only for a searchable proceedings fixture; otherwise at least one proceedings helper command plus a clear `present_structural_only` record |
| `spool` | `pipeline --list`, then a fixture-appropriate `pipeline <preset> --dry-run --inspect` or `pipeline --steps ... --dry-run --inspect`, plus queue-root inventory in `verify.json` |
| `papers` | `search`, `show`, `embed`, `vsearch`, `usearch`, `ws show`, `export` |

Derived-state rebuild expectation after durable store moves:

- after `papers`, prefer `index --rebuild` and `embed --rebuild` before final migrated-root regression
- after `explore`, rebuild what is currently rebuildable from CLI, such as `explore embed --name <lib> --rebuild`, then verify copied search state
- after `proceedings`, when searchable proceedings behavior is in scope, rebuild or refresh `proceedings.db` through the available proceedings-volume flows before claiming a green searchable result
- if a store has no complete rebuild surface yet, record that limitation explicitly and treat copied DB artifacts as derived compatibility baggage rather than authoritative migrated state

### Gate G5. Recovery And Cleanup Rehearsal

Goal:

- prove the operator can recover safely and that cleanup does not silently destroy data

Must exercise:

- `scholaraio migrate recover --clear-lock`
- `scholaraio migrate cleanup --migration-id <migration-id>`
- `scholaraio migrate cleanup --migration-id <migration-id> --confirm`

Acceptance criteria:

- stale or injected lock handling is explicit and documented
- cleanup refuses to run without a passed verification record
- cleanup archives legacy content into the migration journal rather than deleting it directly

### Gate G6. Post-Migration Regression On The Migrated Root

Goal:

- prove the migrated runtime root behaves like a normal upgraded installation

Must rerun the high-signal feature families on the migrated root:

- startup and `setup check`
- search / show / search-author / fsearch
- embed / vsearch / usearch / index
- refs / citing / shared-refs / top-cited
- audit / repair / rename
- workspace search and export
- one export artifact
- one diagram artifact
- one translation artifact when the translation path is part of the claimed release surface
- explore / toolref / proceedings reads
- insights / metrics / style

Post-migration acceptance requires all of the following:

- `instance.json.layout_state == normal`
- the journal records a passed verification
- the root opens normally without `migration.lock`
- migrated stores read from their fresh targets successfully
- the rehearsal evidence includes the migrated artifact paths

### Gate G7. Provider And Network Canaries

Offline validation is not enough for provider-backed surfaces.

The release record must classify each provider-backed surface as one of:

- passed in a real canary run
- intentionally out of scope for this release
- blocked and therefore release-critical

Recommended canaries:

| Surface | Minimum canary |
| --- | --- |
| `arxiv` | real search or fetch against arXiv |
| `explore fetch` | real OpenAlex pull on a tiny query |
| `refetch` / `backfill-abstract` | at least one real metadata lookup |
| `patent-search` / `patent-fetch` | one real USPTO search and one fetch when a reachable sample exists |
| `translate` | one real LLM-backed translation |
| `enrich-toc` / `enrich-l3` | one real LLM-backed enrichment |
| `diagram --from-text` or paper-driven IR extraction | one real LLM-backed diagram generation run |
| `backup run` | one real dry-run against a configured target; one real transfer if backup behavior is part of the release promise |
| MinerU cloud or local daemon paths | at least one real parse when PDF ingest behavior is claimed |

For `translate`, a canary is only fully green when all of the following are true:

- `paper_{lang}.md` is written successfully
- `--portable` also writes the portable bundle when requested
- the resumable `.translate_<lang>/` workdir is removed after successful completion
- observed progress continues to advance even when successes arrive behind a prefix gap, so operators can distinguish slow recovery from a true stall

All provider-backed surfaces must be marked explicitly as unverified rather than silently assumed green when credentials, daemons, or network are unavailable.

## 8. Feature Coverage Notes By Capability Family

### 8.1 Ingest And Import Surfaces

The upgrade is not fully validated if only read paths are tested.

At minimum, the validation record should exercise:

- one regular inbox ingest path
- one PDF-backed attach path through `attach-pdf`
- one fixture-appropriate `pipeline <preset> --dry-run --inspect` or `pipeline --steps ... --dry-run --inspect` run on a prepared inbox
- one import path from either Endnote or Zotero when fixtures are available

If the release claims thesis, patent, document, or proceedings-volume ingest remains correct, each class must be exercised with a real sample from the rehearsal corpus.

### 8.2 Workspace And Output Surfaces

Because this upgrade changed workspace path authority and output accessors, the validation record should always include:

- one workspace created fresh on the new root
- one legacy workspace copied from `../scholaraio/workspace/`
- one DOCX export written through the configured output accessor
- one diagram output written through the configured figures accessor
- one translation output written through `translation_bundle_root` when translation export is in scope

### 8.4 Command-Surface Coverage Inventory

Every top-level CLI surface must be explicitly classified in the release record, even if it is waived.

| Surface | Validation class | Minimum expectation |
| --- | --- | --- |
| `index`, `search`, `search-author`, `show`, `embed`, `vsearch`, `usearch`, `refs`, `citing`, `shared-refs`, `top-cited` | deterministic local | must be covered in fresh-root and migrated-root regression |
| `topics` | deterministic local with dependency caveat | run when BERTopic stack is available and corpus size is appropriate; otherwise mark blocked |
| `backfill-abstract`, `refetch` | provider-backed or hybrid | run real canaries when release scope claims metadata fetch correctness |
| `rename`, `audit`, `repair`, `citation-check` | deterministic local | must be exercised against disposable content or local fixture files |
| `pipeline` | fixture-dependent local | always run `pipeline --list`; then run a valid preset or explicit `--steps` dry-run matched to the fixture type |
| `export`, `document` | deterministic local | create and inspect at least one real output artifact |
| `ws` | deterministic local | cover list/show/search/export plus one fresh workspace operation |
| `import-endnote`, `attach-pdf` | deterministic local or dry-run | exercise at least one local-file fixture path |
| `import-zotero` | local or provider/integration | use `--local ... --dry-run` when a SQLite fixture exists; otherwise classify under canary/integration |
| `migrate` | deterministic local | status, plan, verify, relevant run, cleanup, and recovery must be exercised on rehearsal roots |
| `setup`, `backup`, `metrics`, `insights`, `style` | deterministic local | must be exercised when their configured prerequisites exist |
| `explore list/info/search` | deterministic local if searchable fixture exists | run against a searchable explore fixture; if only structural fixture exists, mark search blocked |
| `explore fetch` | provider-backed canary | run only with network/API availability |
| `proceedings` | local helper or searchable local | distinguish helper-path validation from searchable proceedings validation |
| `toolref list/show/search/use` | deterministic local | must resolve current version and return real docs from a local toolref store |
| `toolref fetch` | provider-backed or repo/integration canary | run when tool-doc fetching behavior is part of the claimed release surface and the required source/network access is available |
| `arxiv`, `patent-search`, `patent-fetch` | provider-backed canary | run when network and required services are available |
| `translate`, `enrich-toc`, `enrich-l3` | provider-backed canary | run when LLM backend is available |
| `diagram --from-ir` | deterministic local | should render from a prepared IR fixture |
| `diagram --from-text` or paper-driven generation | provider-backed canary | run when LLM backend is available |

### 8.3 Migration And Compatibility Surfaces

Because compatibility readers remain deliberately active in this generation, validation must prove both sides:

- legacy roots are still readable before migration
- fresh targets are preferred and usable after migration
- cleanup does not remove the compatibility archive without operator intent

## 9. Suggested Command Skeleton

Local-clone validation may use `python -m scholaraio.cli ...` instead of `scholaraio ...` if the editable install is not active.

Example rehearsal skeleton:

```bash
# 1. build disposable rehearsal roots
cp ../scholaraio/config.yaml workspace/release-validation/<stamp>/legacy-root/config.yaml
# optional only when provider-backed canaries are intentionally in scope
# cp ../scholaraio/config.local.yaml workspace/release-validation/<stamp>/legacy-root/config.local.yaml
cp -R ../scholaraio/data workspace/release-validation/<stamp>/legacy-root/data
cp -R ../scholaraio/workspace workspace/release-validation/<stamp>/legacy-root/workspace

# 1b. seed a fresh-layout root for Gate G1
cp ../scholaraio/config.yaml workspace/release-validation/<stamp>/fresh-root/config.yaml
mkdir -p workspace/release-validation/<stamp>/fresh-root/data/libraries
cp -R workspace/release-validation/<stamp>/migrated-root/data/libraries/papers \
  workspace/release-validation/<stamp>/fresh-root/data/libraries/papers
cp -R workspace/release-validation/<stamp>/migrated-root/data/libraries/explore \
  workspace/release-validation/<stamp>/fresh-root/data/libraries/explore
cp -R workspace/release-validation/<stamp>/migrated-root/data/libraries/toolref \
  workspace/release-validation/<stamp>/fresh-root/data/libraries/toolref
cp workspace/release-validation/<stamp>/migrated-root/data/index.db \
  workspace/release-validation/<stamp>/fresh-root/data/index.db

# 2. baseline
export SCHOLARAIO_CONFIG=/path/to/legacy-root/config.yaml
python -m scholaraio.cli migrate status
python -m scholaraio.cli migrate plan --migration-id mig-<stamp>
python -m scholaraio.cli migrate verify --migration-id mig-<stamp>

# 3. migrate store by store
python -m scholaraio.cli migrate upgrade --migration-id mig-<stamp> --confirm

# 3b. lower-level equivalent for debugging store-by-store behavior
python -m scholaraio.cli migrate run --store citation_styles --migration-id mig-<stamp> --confirm
python -m scholaraio.cli migrate verify --migration-id mig-<stamp>
python -m scholaraio.cli migrate run --store toolref --migration-id mig-<stamp> --confirm
python -m scholaraio.cli migrate verify --migration-id mig-<stamp>
python -m scholaraio.cli migrate run --store explore --migration-id mig-<stamp> --confirm
python -m scholaraio.cli migrate verify --migration-id mig-<stamp>
python -m scholaraio.cli migrate run --store proceedings --migration-id mig-<stamp> --confirm
python -m scholaraio.cli migrate verify --migration-id mig-<stamp>
python -m scholaraio.cli migrate run --store spool --migration-id mig-<stamp> --confirm
python -m scholaraio.cli migrate verify --migration-id mig-<stamp>
python -m scholaraio.cli migrate run --store papers --migration-id mig-<stamp> --confirm
python -m scholaraio.cli index --rebuild
python -m scholaraio.cli embed --rebuild
python -m scholaraio.cli migrate verify --migration-id mig-<stamp>

# 4. cleanup rehearsal
python -m scholaraio.cli migrate cleanup --migration-id mig-<stamp>
python -m scholaraio.cli migrate cleanup --migration-id mig-<stamp> --confirm
```

This is only the migration skeleton. The feature smokes and evidence capture listed above are still required around it.

## 10. Stop Conditions

Stop the release process immediately if any of the following occurs:

- a compatibility read path works only because a test monkeypatch hid a real path regression
- a migration plan reports unresolved blockers or unexpected mixed-root divergence
- `migrate verify` fails after any store move
- cleanup attempts to remove data outside the migration journal
- a feature family is skipped without being explicitly marked unverified
- the upgraded code can open the migrated root only through legacy fallback behavior instead of the fresh target

## 11. Definition Of Done For This Upgrade Generation

The current breaking cleanup generation is release-ready only when:

- repo checks are green
- full test suite is green
- the validation evidence bundle exists
- migration rehearsal has been run through journaled plan / verify / run / finalize
- the migrated root passes the post-migration feature regression
- provider-backed surfaces are either green or explicitly called out as unverified

Until then, "the refactor is mostly done" is not an acceptable release claim.
