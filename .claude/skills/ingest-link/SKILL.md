---
name: ingest-link
description: Use when the user wants to ingest one or more web URLs into ScholarAIO, convert rendered web content into Markdown through qt-web-extractor, or turn an online page/PDF into a normal document-ingest workflow.
---

# Ingest Web Links

Use this skill when the user already has one or more URLs and wants them pulled into the ScholarAIO library as document-style records.

## When to Use

Use this skill when the user wants to:

- ingest a webpage directly into the local knowledge base
- ingest an online PDF or report from a URL
- capture technical documentation, standards, manuals, or web articles as `document` items
- route rendered web content through the normal ScholarAIO ingest/index flow

Do not use this skill when:

- the task is only to search the local library; use `search`
- the task is mainly about arXiv preprints; use `arxiv`
- the user only wants broad web discovery without ingesting; use external web search first, then come back if ingestion is desired

## Core Workflow

### 1. Confirm the source shape

- If the user already provides URL(s), go straight to `scholaraio ingest-link`
- If the user only has a topic but no URL, discover URLs first through external web search, then ingest selected results

### 2. Use the CLI entrypoint

Basic ingestion:

```bash
scholaraio ingest-link https://example.com/page
scholaraio ingest-link https://example.com/page https://example.com/report.pdf
```

Preview only:

```bash
scholaraio ingest-link https://example.com/page --dry-run
```

Ingest without rebuilding indexes immediately:

```bash
scholaraio ingest-link https://example.com/page --no-index
```

Force PDF extraction mode when the backend needs a hint:

```bash
scholaraio ingest-link https://example.com/report.pdf --pdf
```

### 3. Keep the backend model clear

- ScholarAIO does not render webpages itself in this flow
- It depends on an external `qt-web-extractor` service
- The value of that service is rendered-content extraction, not just raw HTML download
- Default endpoint: `http://127.0.0.1:8766`
- Override with `config.yaml -> webextract.base_url` / `webextract.api_key`
- Environment variables `WEBEXTRACT_URL` / `WEBEXTRACT_API_KEY` still work as fallback

### 4. Understand what gets stored

- The extracted page is written into a temporary document inbox
- ScholarAIO reuses the existing document ingest flow
- Final records stay in the current `document` family, not a separate `webdocument` type
- Provenance fields such as `source_url`, `source_type`, and `extraction_method` are preserved in `meta.json`

## Practical Heuristics

- Prefer `--no-index` when ingesting many links and you plan to rebuild once at the end
- Let the backend auto-detect normal web pages and PDF URLs first; prefer `--pdf` only when detection seems unreliable
- If the backend is unavailable, report that clearly instead of pretending ScholarAIO can fetch/render the page alone

## Output Style

- Make it clear that the content came from a URL rather than a local file
- Mention the source URL in summaries when it matters
- If ingestion fails, surface the backend/service reason directly
