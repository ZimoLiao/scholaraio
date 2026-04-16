# Webtools Integration (Optional)

ScholarAIO is agent-first: users talk to an agent, and the agent orchestrates local ScholarAIO skills.  
If you also want live web search/extraction, ScholarAIO can integrate the same backend daemons used by [AnterCreeper/claude-webtools](https://github.com/AnterCreeper/claude-webtools) as an external capability layer.

## When to use this

- You need **internet discovery** (news, latest announcements, online docs) in addition to the local paper KB.
- You want the agent to combine:
  - ScholarAIO local retrieval (`/scholaraio:search`, `/scholaraio:show`, etc.)
  - external web lookup from `GUILessBingSearch` / `qt-web-extractor`.

## Native ScholarAIO entrypoint

ScholarAIO now provides a native URL-ingest command:

```bash
scholaraio ingest-link https://example.com/page
```

This command:

1. Calls a running `qt-web-extractor` service.
2. Pulls rendered page content instead of only raw HTML source.
3. Writes extracted Markdown into a temporary document inbox.
4. Reuses the existing ScholarAIO document ingest pipeline.

In practice, this means `scholaraio ingest-link` can ingest:

- JavaScript-rendered pages that a plain HTTP fetch would miss
- online PDFs and report URLs
- technical docs, manuals, standards, and web articles as normal `document` records

The current command resolves `qt-web-extractor` in this order:

- `config.yaml -> webextract.base_url` / `webextract.api_key`
- `WEBEXTRACT_URL` / `WEBEXTRACT_API_KEY`
- otherwise `http://127.0.0.1:8766`

## Recommended setup

1. Install and configure the backend services:
   - `qt-web-extractor` for rendered URL/PDF extraction
   - optional `GUILessBingSearch` for search-first workflows
2. Keep ScholarAIO as the authoritative local knowledge pipeline (ingest/index/enrich).
3. In agent workflows:
   - use ScholarAIO first for reproducible local evidence;
   - use webtools only when freshness or external coverage is required.

`qt-web-extractor` is an external daemon, not a built-in ScholarAIO fetcher. ScholarAIO delegates browser rendering to that service and then continues with its own ingest pipeline.

## Operational guidelines

- Prefer local KB evidence for stable academic claims.
- For time-sensitive facts, cross-check via webtools and record access date.
- When webtools is unavailable, agent should degrade gracefully to local-only ScholarAIO workflows.
- Prefer the default automatic URL handling first; use `scholaraio ingest-link --pdf <url>` only when a PDF URL needs an explicit hint.
