# CLI Reference

ScholarAIO is designed to work best through an AI coding agent, but the CLI remains useful for scripting, inspection, and quick queries.

The authoritative source is always:

```bash
scholaraio --help
scholaraio <command> --help
```

The command groups below are aligned with the current codebase.

## Core Commands

```text
scholaraio index
scholaraio search
scholaraio search-author
scholaraio show
scholaraio embed
scholaraio vsearch
scholaraio usearch
scholaraio fsearch
scholaraio top-cited
```

- `search` performs keyword search.
- `vsearch` performs semantic vector search.
- `usearch` performs fused keyword + semantic retrieval.
- `fsearch` searches across the main library, proceedings, explore databases, and arXiv.
- `show` supports layered reading from metadata to full text.

## Ingest And Enrich

```text
scholaraio pipeline [preset]
scholaraio ingest-link <url> [<url> ...]
scholaraio websearch <query> [--count N]
scholaraio webextract <url> [--pdf] [--full] [--max-chars N]
scholaraio paper2any setup [--install-runtime]
scholaraio paper2any mcp-serve
scholaraio paper2any backend-serve
scholaraio paper2any status|tools|call
scholaraio patent-search <query> [--count N]
scholaraio patent-fetch <publication-number-or-url>
scholaraio enrich-toc
scholaraio enrich-l3
scholaraio backfill-abstract
scholaraio refetch
scholaraio translate
scholaraio attach-pdf
```

- `pipeline` is the main composable ingest entrypoint.
- `ingest-link` pulls one or more rendered web URLs or online PDFs through an external `qt-web-extractor` service and routes them into the existing document ingest flow.
- `websearch` performs live web search through an external `GUILessBingSearch` service; prefer `websearch.transport: mcp` with the `search_bing` tool when available, while the legacy HTTP `/search` transport remains supported.
- `webextract` extracts rendered web content through `qt-web-extractor`; prefer `webextract.transport: mcp` with the `fetch_url` tool for agent workflows, while the legacy HTTP `/extract` transport remains supported. By default it prints a preview, and `--full` expands to the full body.
- `paper2any` starts and calls the lightweight MCP sidecar for an external OpenDCAI/Paper2Any checkout. Use it for real Paper2Any paper-to-figure, PPT, poster, video, citation, rebuttal, DrawIO, mindmap, PDF-to-PPT, image-to-PPT, and KB workflows without vendoring Paper2Any into ScholarAIO.
- `patent-search` discovers patent candidates through USPTO PPUBS by default, with optional ODP API support.
- `patent-fetch` downloads a patent PDF into the configured patent inbox for the normal patent ingest flow.
- `refetch` refreshes citation counts, bibliographic metadata, and structured `references` for already ingested papers.
- `refetch --references-only` / `--refs-only` limits the run to DOI papers whose `references` field is still empty; in single-paper mode it only updates `references`.
- Current preset values are `full`, `ingest`, `enrich`, and `reindex`.
- Run `scholaraio pipeline --help` for pipeline options such as `--steps`, `--dry-run`, `--no-api`, and `--rebuild`.

## Graph, Topics, And Explore

```text
scholaraio refs
scholaraio citing
scholaraio shared-refs
scholaraio topics
scholaraio explore
```

- Use `refs`, `citing`, and `shared-refs` for citation-graph analysis.
- Use `topics` for BERTopic-based topic modeling and exploration.
- Use `explore` for OpenAlex-backed literature exploration outside the main library.

## Import, Export, Publish, And Workspaces

```text
scholaraio import-endnote
scholaraio import-zotero
scholaraio export
scholaraio publish-site
scholaraio ws
```

## Migration

```text
scholaraio migrate status
scholaraio migrate upgrade --migration-id <id> --confirm
scholaraio migrate verify --migration-id <id>
scholaraio migrate finalize --migration-id <id> --confirm
```

- `migrate upgrade` is the one-command path from supported legacy layout roots to the current fresh layout. It runs needed store moves, verification, cleanup archival, and final verification in one journal.
- Supported legacy signals are the layout-version-0 / implicit pre-cleanup roots: `data/papers/`, `data/citation_styles/`, `data/toolref/`, `data/explore/`, `data/proceedings/`, `data/inbox*`, `data/pending/`, `workspace/<name>/papers.json`, and legacy workspace outputs.
- Empty legacy roots are cleanup candidates too, so finalized upgrades do not leave historical empty directories behind.
- `migrate finalize` remains available when a user or operator has already run store-level migration steps manually and only needs final cleanup and verification.

- `import-endnote` and `import-zotero` bring existing libraries into ScholarAIO.
- `export` handles BibTeX, RIS, Markdown, and DOCX export.
- `publish-site` generates a static site from audited `published/*/metadata.json` archives, copying PDF/source assets by default and supporting `--symlink` for local preview.
- `ws` manages paper subsets for focused projects and writing workflows.

## Scientific Runtime And Documents

```text
scholaraio toolref
scholaraio arxiv
scholaraio document
scholaraio diagram
scholaraio style
scholaraio backup
```

- `toolref` provides versioned scientific tool documentation lookup.
- Current `toolref` subcommands are `fetch`, `show`, `search`, `list`, and `use`.
- `arxiv` supports arXiv search and PDF fetch.
- `document` provides Office-document utilities such as inspection.
- `diagram` generates editable scientific diagrams from paper content or structured text.
- `style` manages citation styles.
- `backup` lists configured rsync targets and runs a named backup plan.
- `backup run` is intentionally non-interactive: SSH is launched with `BatchMode=yes`, so key-based auth and host trust must already be prepared.
- If a target stores `password` in `config.local.yaml`, ScholarAIO switches to an internal non-interactive askpass path instead of waiting for a terminal prompt.
- A good first-run sequence is `ssh-keyscan ... >> ~/.ssh/known_hosts`, then `ssh -i <key> -p <port> <user>@<host> true`, then `scholaraio backup run <target> --dry-run`.

## Audit, Setup, And Runtime Inspection

```text
scholaraio audit
scholaraio repair
scholaraio rename
scholaraio setup
scholaraio insights
scholaraio metrics
scholaraio proceedings
scholaraio citation-check
```

- `audit` checks missing metadata, duplicate DOIs, filename issues, and title/content mismatches.
- `audit` uses paper-type-aware skips so documents, patents, dissertations, and similar front matter do not create spurious `title_mismatch` warnings.
- `setup` is the environment check and setup wizard entrypoint.
- `insights` analyzes research behavior such as hot keywords and reading trends.
- `metrics` shows LLM token and runtime usage.
- `proceedings` provides dedicated proceedings helpers.
- `citation-check` verifies whether citations in text are backed by the local library.

## Recommended Pattern

Use the agent for the full workflow, and fall back to CLI commands when you want:

- fast scripted access
- a precise diagnostic check
- direct inspection of intermediate results
- reproducible command-line automation
