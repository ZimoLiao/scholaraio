# Paper Ingestion

## Quick Ingest

Place PDFs in `data/inbox/` and run the pipeline:

```bash
scholaraio pipeline ingest
```

This will:

1. Convert PDFs to Markdown (MinerU first, then Docling / PyMuPDF fallback when needed)
2. Extract metadata (regex + LLM)
3. Query APIs for completeness (Crossref, Semantic Scholar, OpenAlex)
4. Deduplicate by DOI
5. Move to `data/papers/` and update indexes

If `translate.auto_translate: true` is enabled in config, the pipeline will also auto-inject the `translate` step for newly ingested papers before `embed/index`. It does not retroactively translate the whole library.

## Five Inboxes

| Inbox | Path | Behavior |
|-------|------|----------|
| Papers | `data/inbox/` | Standard pipeline with DOI dedup |
| Proceedings | `data/inbox-proceedings/` | Two-stage proceedings pipeline; first ingest creates `data/proceedings/<Volume>/` with `proceeding.md` + `split_candidates.json` and marks `split_status=pending_review` |
| Theses | `data/inbox-thesis/` | Skips DOI check, marks as thesis |
| Patents | `data/inbox-patent/` | Extracts publication number and deduplicates as patent |
| Documents | `data/inbox-doc/` | Skips DOI check, LLM-generated title/abstract |

Proceedings are only routed from the dedicated `data/inbox-proceedings/` path. Regular `data/inbox/` items always stay on the normal paper/document flow unless you move them into the proceedings inbox explicitly. Child papers are written under `data/proceedings/<Volume>/papers/` only after you review the split and run `scholaraio proceedings apply-split`.

## Proceedings Search

Proceedings child papers are not included in default main-library search. Use federated search when you want them:

```bash
scholaraio fsearch granular damping --scope proceedings
```

ScholarAIO prefers MinerU when available, but the live ingest path does not depend on MinerU alone. If MinerU is unavailable or fails, the fallback parser chain is `Docling -> PyMuPDF`.

## Skip PDF Parsing

Already have Markdown? Place `.md` files directly in the inbox — PDF parsing is skipped entirely.

## Pending Papers

Papers without DOI (that aren't theses) go to `data/pending/` for manual review. Add a DOI and re-run the pipeline to complete ingestion.

## External Import

```bash
# From Endnote
scholaraio import-endnote library.xml

# From Zotero
scholaraio import-zotero --api-key KEY --library-id ID
```

## Metadata Maintenance

After papers are already in `data/papers/`, the metadata subpackage also powers two maintenance flows:

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
