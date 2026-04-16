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
scholaraio enrich-toc
scholaraio enrich-l3
scholaraio backfill-abstract
scholaraio refetch
scholaraio translate
scholaraio attach-pdf
```

- `pipeline` is the main composable ingest entrypoint.
- `ingest-link` pulls one or more rendered web URLs or online PDFs through an external `qt-web-extractor` service and routes them into the existing document ingest flow.
- `websearch` performs live web search through an external `GUILessBingSearch` service.
- `webextract` extracts rendered web content through `qt-web-extractor`; by default it prints a preview, and `--full` expands to the full body.
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

## Import, Export, And Workspaces

```text
scholaraio import-endnote
scholaraio import-zotero
scholaraio export
scholaraio ws
```

- `import-endnote` and `import-zotero` bring existing libraries into ScholarAIO.
- `export` handles BibTeX, RIS, Markdown, and DOCX export.
- `ws` manages paper subsets for focused projects and writing workflows.

## Scientific Runtime And Documents

```text
scholaraio toolref
scholaraio arxiv
scholaraio document
scholaraio style
scholaraio backup
```

- `toolref` provides versioned scientific tool documentation lookup.
- Current `toolref` subcommands are `fetch`, `show`, `search`, `list`, and `use`.
- `arxiv` supports arXiv search and PDF fetch.
- `document` provides Office-document utilities such as inspection.
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
