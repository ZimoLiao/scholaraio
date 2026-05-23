# Paper Ingestion

## Quick Ingest

Place PDFs in the configured paper inbox (fresh default: `data/spool/inbox/`) and run the pipeline:

```bash
scholaraio pipeline ingest
```

This will:

1. Convert PDFs to Markdown (MinerU first, then Docling / PyMuPDF fallback when needed)
2. Extract metadata (regex + LLM)
3. Query APIs for completeness (Crossref, Semantic Scholar, OpenAlex)
4. Deduplicate by DOI
5. Move to the configured papers library (fresh default: `data/libraries/papers/`) and update indexes

If `translate.auto_translate: true` is enabled in config, the pipeline will also auto-inject the `translate` step for newly ingested papers before `embed/index`. It does not retroactively translate the whole library.

Older roots such as `data/inbox/` and `data/papers/` are migration inputs, not normal runtime inputs. Upgrade them with `scholaraio migrate upgrade --migration-id <id> --confirm` before relying on the current ingest flow.

## Publisher PDF Fetch

When your current network has legitimate access to a publisher PDF, use `fetch-pdf` instead of manually downloading the file:

```bash
# Download a DOI, publisher landing page, direct PDF URL, or title to the configured paper inbox
scholaraio fetch-pdf 10.xxxx/example --direct

# Download and immediately run the normal ingest pipeline; the PDF is staged temporarily
scholaraio fetch-pdf 10.xxxx/example --direct --ingest

# Save the fetched PDF to a chosen directory; with --ingest, only that fetched file is ingested
scholaraio fetch-pdf 10.xxxx/example --direct --out-dir workspace/pdfs --ingest

# Refresh canonical PDFs for already ingested records
scholaraio fetch-pdf --paper <paper-id> --direct --force
scholaraio fetch-pdf --paper <paper-id-1> <paper-id-2> --direct --force
scholaraio fetch-pdf --all --direct --force
```

`fetch-pdf` is a native ScholarAIO acquisition helper, not a Paper Fetch Skill or MCP dependency. It does not bypass paywalls or access controls; it only uses the user's current legal network and publisher session behavior. `--direct` ignores proxy environment variables, which is useful when a campus network has access but a local proxy would route traffic elsewhere.

New downloads can enter the regular PDF-to-Markdown pipeline with `--ingest`. Without `--out-dir`, ScholarAIO stages the fetched PDF temporarily for ingest and does not leave a separate copy in the configured inbox. Use `--out-dir` when you want to keep the fetched PDF; ScholarAIO still ingests only that fetched file by copying it through a temporary single-file inbox, so unrelated PDFs already present in `--out-dir` are not processed. Refetching PDFs for existing records only replaces the canonical PDF; it intentionally does not regenerate `paper.md`, so use `attach-pdf` or a conversion workflow when Markdown must be rebuilt.

## Five Inboxes

| Inbox | Path | Behavior |
|-------|------|----------|
| Papers | `data/spool/inbox/` | Standard pipeline with DOI dedup |
| Proceedings | `data/spool/inbox-proceedings/` | Two-stage proceedings pipeline; first ingest creates `data/libraries/proceedings/<Volume>/` with `proceeding.md` + `split_candidates.json` and marks `split_status=pending_review` |
| Theses | `data/spool/inbox-thesis/` | Skips DOI check, marks as thesis |
| Patents | `data/spool/inbox-patent/` | Extracts publication number and deduplicates as patent |
| Documents | `data/spool/inbox-doc/` | Skips DOI check, LLM-generated title/abstract |

Proceedings are only routed from the dedicated `data/spool/inbox-proceedings/` path. Regular `data/spool/inbox/` items always stay on the normal paper/document flow unless you move them into the proceedings inbox explicitly. Child papers are written under the configured proceedings library (fresh default: `data/libraries/proceedings/<Volume>/papers/`) only after you review the split and run `scholaraio proceedings apply-split`.

## Proceedings Search

Proceedings child papers are not included in default main-library search. Use federated search when you want them:

```bash
scholaraio fsearch granular damping --scope proceedings
```

ScholarAIO prefers MinerU when available, but the live ingest path does not depend on MinerU alone. If MinerU is unavailable or fails, the fallback parser chain is `Docling -> PyMuPDF`.

## Skip PDF Parsing

Already have Markdown? Place `.md` files directly in the inbox — PDF parsing is skipped entirely.

## Pending Papers

Papers without DOI (that aren't theses) go to the configured pending spool (fresh default: `data/spool/pending/`) for manual review. Add a DOI and re-run the pipeline to complete ingestion.

## External Import

```bash
# From Endnote
scholaraio import-endnote library.xml

# From Zotero
scholaraio import-zotero --api-key KEY --library-id ID
```

## Metadata Maintenance

After papers are already in the configured papers library, the metadata subpackage also powers two maintenance flows:

```bash
# Backfill missing abstracts from paper.md, with optional DOI-page fetch
scholaraio backfill-abstract
scholaraio backfill-abstract --doi-fetch

# Re-fetch citation counts and bibliographic details from APIs
scholaraio refetch --all
scholaraio refetch "<paper-id>"

# Only backfill missing references for DOI-bearing papers
scholaraio refetch --all --references-only
scholaraio refetch "<paper-id>" --references-only
```

- `backfill-abstract` fills missing abstracts from local Markdown, and can prefer official publisher abstracts when `--doi-fetch` is enabled.
- `refetch` re-runs Crossref / Semantic Scholar / OpenAlex enrichment for already ingested papers, including structured `references` backfill.
- `refetch --references-only` / `--refs-only` is the low-risk maintenance path when you only want to fill empty `references`; batch mode skips papers that already have references, and single-paper mode leaves citation-count refresh alone.
