# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **Guided single-paper reading workflow**: Added the `paper-guided-reading` skill plus the companion `docs/writing-guide/paper-reading-framework.md` so agents can start from fuzzy intent, confirm one target paper, perform structured deep reading, and persist reusable findings into `notes.md`
- **Incremental metadata scrub workflow**: Added the `scrub` skill for post-enrich metadata cleanup of low-quality paper records, plus reusable `.scrubbed` marker helpers in `papers.py` and conservative scrub-suspect detection helpers in `audit.py`
- **Rsync backup workflow** ([#54](https://github.com/ZimoLiao/scholaraio/issues/54)): Added typed `backup` configuration, the `scholaraio.backup` module, `scholaraio backup list/run`, and the `backup` skill so ScholarAIO data can be synced to named remote targets through rsync instead of hand-written shell commands
- **macOS semantic-search smoke workflow**: Added a dedicated GitHub Actions job on `macos-14` to exercise the `sentence-transformers` -> `faiss-cpu` semantic-search stack and run targeted regression tests for vector-search paths
- **Academic writing router** ([#55](https://github.com/ZimoLiao/scholaraio/issues/55)): Added the `academic-writing` skill as a stable top-level entry point that routes users by deliverable and writing stage instead of forcing them to guess among multiple writing skills
- **Deliverable-first writing workflows** ([#55](https://github.com/ZimoLiao/scholaraio/issues/55)): Added lightweight `poster` and `technical-report` skills so conference posters, poster-style summaries, topic reports, and research briefings are first-class workflows rather than implicit combinations of lower-level skills
- **Writing workflow regression coverage**: Added tests for skill frontmatter validity, router references, approximate host-style skill selection, and 11 rounds of documentation-alignment checks across docs, agent instructions, and marketplace metadata
- **Rendered web URL ingestion** ([#52](https://github.com/ZimoLiao/scholaraio/issues/52)): Added the native `scholaraio ingest-link` CLI, `ingest-link` skill, and `sources.webtools` connector flow so webpages and online PDFs can be ingested through an external `qt-web-extractor` daemon while preserving provenance fields such as `source_url`, `source_type`, `extracted_at`, and `extraction_method`
- **References-only metadata refresh**: `scholaraio refetch` can now backfill structured `references` for DOI-bearing papers, with `--references-only` / `--refs-only` to target only papers whose references are still empty and a Semantic Scholar -> Crossref fallback chain when one source has no usable references

### Fixed

- **Writing-skill discovery alignment**: Synchronized `academic-writing`, `docs/guide/writing.md`, `README.md`, `README_CN.md`, `docs/index.md`, `AGENTS.md`, `AGENTS_CN.md`, `CLAUDE.md`, and `clawhub.yaml` so `paper-guided-reading` is discoverable consistently across router, docs, agent instructions, and marketplace metadata
- **Audit title matching and type-aware skips**: `audit` now compares metadata titles against title-like candidates from the first 80 lines of `paper.md`, honors `title_translated`, keeps `missing_doi` / `missing_journal` warnings active when `paper_type` is blank, and skips front-matter-driven `title_mismatch` false positives for dissertation and document-like records
- **Backup runtime robustness**: `scholaraio backup run` now reports missing `rsync` executables as controlled CLI errors, shell-quotes the displayed rsync command preview, defaults full-data backups to the safer `default` rsync mode instead of append-only behavior, forces SSH batch mode so runs fail fast instead of hanging on interactive authentication or host-key prompts, supports a `config.local.yaml` password fallback for password-only hosts, and prints concrete setup guidance when authentication or host trust is not ready yet
- **macOS semantic/unified search crash** ([#65](https://github.com/ZimoLiao/scholaraio/issues/65)): main-library and explore semantic search now embed and normalize the query before loading or searching FAISS indexes, avoiding a known `faiss` / `sentence-transformers` import-order segfault pattern on macOS while preserving existing ranking behavior
- **Academic writing docs alignment** ([#55](https://github.com/ZimoLiao/scholaraio/issues/55)): Synchronized `docs/guide/writing.md`, `README.md`, `README_CN.md`, `docs/index.md`, `AGENTS.md`, `AGENTS_CN.md`, `CLAUDE.md`, and `clawhub.yaml` around a router-first writing model so poster/report workflows and the academic-writing entry point are discoverable consistently across user and agent surfaces
- **`ingest-link` reliability and isolation** ([#52](https://github.com/ZimoLiao/scholaraio/issues/52)): URL ingest now preserves extractor PDF autodetect unless `--pdf` is explicitly requested, isolates both temporary inboxes from the real library, skips only failed URLs in multi-link batches, keeps warning-bearing extractions with usable text, retries transient extraction failures with exponential backoff, and avoids overlong fallback filenames for title-less URLs
- **Scrub workflow edge cases** ([#51](https://github.com/ZimoLiao/scholaraio/issues/51)): `show` now surfaces the stable UUID for partially corrupted records, direct-directory `repair` generates a UUID when recovering markdown-only papers, collision-suffixed directory names no longer get renumbered again by `rename`, and the scrub skill docs now distinguish `invalid_metadata` records from normal `show`-first review paths

## [1.3.1] — 2026-04-14

### Added

- **Qwen agent support**: Added `.qwen/skills` symlink to `.claude/skills/` so Qwen-based agents can discover ScholarAIO skills out of the box
- **Qwen project context**: Added `.qwen/QWEN.md` so Qwen Code has a repository-native project context file instead of relying on `AGENTS.md` / `CLAUDE.md`
- **Cursor native project rules**: Added `.cursor/rules/scholaraio.mdc` as the primary Cursor integration path, with `AGENTS.md` as the shared multi-agent instruction source and `.cursorrules` kept only as a legacy fallback
- **OpenAI-compatible embedding backend support**: Added `embed.provider` config with `local` / `openai-compat` / `none` options; cloud API supports configurable `api_base`, `api_key`, `api_timeout`, `batch_size`, and `max_retries`; `provider=none` disables embeddings gracefully and falls back to keyword-only search

### Fixed

- **Cursor compatibility CI coverage**: Added regression coverage to keep the Cursor rule wrapper lightweight and explicitly MCP-free
- **Proceedings routing test stability**: Tests no longer assume the first `data/proceedings` entry is a proceedings volume directory, avoiding CI-only failures when `proceedings.db` sorts before real volume folders
- **Unified search transparency**: `usearch` and `fsearch` now print an explicit message when semantic retrieval is unavailable and the command degrades to keyword-only search
- **Zhipu GLM OpenAI-compatible chat routing** ([#60](https://github.com/ZimoLiao/scholaraio/issues/60)): `call_llm()` now maps `open.bigmodel.cn/api/paas` to the correct `/v4/chat/completions` endpoint instead of incorrectly forcing `/v1/chat/completions`

## [1.3.0] — 2026-04-06

### Added

- **AI-for-Science foundation**: ScholarAIO v1.3.0 pushes the project beyond a paper-centric research terminal toward an AI-for-Science runtime. Added five lightweight scientific-computing domains for agents: Quantum ESPRESSO, LAMMPS, GROMACS, OpenFOAM, and bioinformatics
- **Versioned scientific tool docs via `toolref`**: Added `scholaraio toolref fetch/list/show/search/use` plus the top-level `scholaraio.toolref` facade so agents can query exact official interfaces at runtime instead of guessing parameters from memory. Current indexed coverage includes Quantum ESPRESSO, LAMMPS, GROMACS, OpenFOAM, and curated bioinformatics tools
- **Extensible onboarding for new scientific software**: Added a dedicated scientific-tool onboarding workflow so ScholarAIO can keep incorporating user-requested tools through official-doc ingestion, `toolref` integration, lightweight skill design, and end-to-end CLI verification, rather than being limited to the five tools already onboarded
- **Toolref-first scientific runtime design**: Aligned tool-specific scientific skills around a clear separation of concerns: papers and notes hold scientific context, skills hold workflow and judgment, and `toolref` holds exact interface details. This keeps skills lightweight while letting agents stay grounded in both literature and tool docs
- **Semantic Scholar API key support**: Configure `ingest.s2_api_key` (or env var `S2_API_KEY`) to authenticate Semantic Scholar requests, increasing rate limits from 100 req/5min (public) to 1 req/s (authenticated); polite delay automatically reduced from 3s to 1s when key is present
- **PDF parser benchmark harness**: Added `scholaraio/ingest/parser_matrix_benchmark.py` plus tests for comparing Docling / MinerU / PyMuPDF parser runs and configuration matrices
- **Parser-aware setup guidance**: `scholaraio setup` and the setup skill now explain MinerU vs Docling selection, provide official deployment links, note that MinerU tokens for `mineru-open-api` are free to apply for, and warn agent users about sandbox/network mis-detection
- **Insights analytics module coverage**: `scholaraio.insights` now owns reusable behavior-analysis helpers, with dedicated tests plus CLI smoke coverage for `scholaraio insights`

### Fixed

- **PDF parser fallback flow**: Batch conversion and `attach-pdf` now follow the same MinerU → fallback behavior as the main ingest path; fallback assets are preserved; unsupported parser options from the previous broader design were removed so the active chain matches the current MinerU / Docling / PyMuPDF strategy
- **MinerU cloud backend + chunking limits**: All MinerU cloud ingest entrypoints now use the `mineru-open-api` / ModelScope-backed path instead of the old raw API flow, and cloud chunk planning now respects both the 600-page and 200MB single-file limits with size-aware chunk estimation
- **Proceedings ingest routing**: Regular `data/inbox/` items no longer auto-route into `data/proceedings/`; proceedings now enter that workflow only through the dedicated `data/inbox-proceedings/` inbox, and misclassified real-library proceedings shells were cleaned back into normal paper ingest
- **Setup robustness for agents**: `setup` / `setup check` no longer fail hard when `metrics.db` is locked, parser recommendations honor an already-configured MinerU token before network probing, and interactive prompts treat EOF as empty input so agent-driven stdin does not crash the wizard
- **Docs consistency**: README, README_CN, AGENTS, and CLAUDE now describe the current parser stack and setup behavior consistently
- **arXiv ingest edge cases**: `scholaraio.sources.arxiv` no longer makes `bs4` a transitive hard dependency for normal metadata flows, and old-style arXiv IDs like `hep-th/9901001` now create parent directories correctly during PDF download
- **Scientific runtime docs compatibility**: toolref runtime behavior, scientific skills, and published setup/docs metadata now match the refactored `toolref` facade and current public CLI/package surface
- **Optional dependency guidance**: missing-dependency messages and `setup check` now consistently point users to `scholaraio[import]`, `scholaraio[pdf]`, `scholaraio[office]`, and `scholaraio[draw]` instead of raw leaf packages
- **Translate / enrich CLI feedback and recovery**: `translate` now reports chunk-level progress, persists per-chunk state in `.translate_{lang}/`, resumes unfinished work safely, and avoids writing fake success output when every chunk fails; `enrich-toc` now reports start/success/failure with extracted TOC counts for single-paper runs
- **Workspace removal and refetch status accuracy**: `ws remove` now falls back to exact workspace `dir_name` matching when registry lookup misses, and `refetch` no longer reports spurious updates when API enrichment returns no authoritative data

### Removed

- **MCP server**: Removed `scholaraio/mcp_server.py` (1585 lines, 32 tools) and the `scholaraio-mcp` entry point. All agent interactions now go through CLI + skills, which are agent-agnostic and supported across Claude Code, Codex, Cursor, Windsurf, Cline, and GitHub Copilot. The `[mcp]` optional dependency group has also been removed.

## [1.2.0] — 2026-03-26

### Added

- **Agent analysis notes (T2)**: Per-paper `notes.md` for persistent cross-session analysis notes; `show` now auto-displays existing notes, `show --append-notes` appends new notes, and `loader.load_notes()` / `loader.append_notes()` expose the workflow in Python
- **Context management guidance**: Workspace skill and 4 academic writing skills updated with `notes.md` read/write workflow and large-content delegation guidance for subagent-heavy analysis

### Fixed

- **Zotero LaTeX filename too long** ([#32](https://github.com/ZimoLiao/scholaraio/issues/32)): Titles containing LaTeX math (e.g. `$\mathrm{La}{\mathrm{BH}}_8$`) or HTML/MathML entities now get properly cleaned before directory naming; added 255-byte filename length limit as safety net

## [1.1.0] — 2026-03-24

### Added

- **Patent literature management**: New `data/inbox-patent/` inbox for patent documents; automatic publication number extraction (CN/US/EP/WO/JP/KR/DE/FR/GB/TW/IN/AU + more formats); deduplication by publication number; `paper_type: patent` auto-tagging; `publication_number` field in `PaperMetadata` and `papers_registry`
- **Paper translation** (`translate` CLI + skill): LLM-based markdown translation preserving LaTeX formulas, code blocks, and images; language detection heuristic; configurable defaults (`config.yaml` `translate` section) with per-call `--lang`/`--force` override; single paper and batch modes; `show --lang` to view translated versions; `pipeline --steps translate` for batch processing
- **Federated search** (`fsearch` CLI + `federated_search` MCP tool): search across main library, explore silos (`explore:NAME` / `explore:*`), and arXiv in a single command; arXiv results annotated with "已入库" when DOI matches the main library
- **arXiv source module** (`sources/arxiv.py`): shared Atom API client using `defusedxml` for safe XML parsing
- **Insights analytics** (`scholaraio insights`): behavior dashboard showing top search keywords, most-read papers, weekly reading trend, semantic neighbor recommendations, and active workspaces with paper counts
- **Metrics recording for search/read**: `search`, `usearch`, `vsearch`, and `show` commands now record events to `metrics.db` for behavior analysis
- **`MetricsStore.query_distinct_names()`**: efficient distinct-name query with supporting `(category, name)` index, used by insights recommendations
- **Skill YAML front matter**: all 26 skills now carry standardized `version`/`author`/`license`/`tags` metadata; new `insights` and `document` skills added
- **clawhub.yaml**: marketplace manifest listing all available skills for discovery
- **`explore fetch --limit`**: cap the number of papers fetched from OpenAlex (useful for quick sampling)
- **`attach-pdf --dry-run`**: preview what `attach-pdf` will do without actually running MinerU conversion
- **`document inspect`** (`scholaraio document inspect <file>`): inspect Office documents (DOCX/PPTX/XLSX) showing structure, layout, content preview, and overflow warnings; new `document.py` module with `inspect_pptx`/`inspect_docx`/`inspect_xlsx` functions
- **Office format ingest**: `inbox-doc/` now accepts `.docx`, `.xlsx`, `.pptx` files; new `step_office_convert` pipeline step converts them to Markdown via MarkItDown before ingestion
- **RIS export**: `export ris` outputs RIS format compatible with Zotero, Endnote, and Mendeley (zero dependencies)
- **Markdown reference list export**: `export markdown` generates formatted reference lists with configurable citation styles (APA, Vancouver, Chicago, MLA); supports ordered/unordered lists
- **DOCX export**: `export docx` converts any Markdown content to a Word `.docx` file, supporting headings, paragraphs, tables, lists, code blocks, and bold/italic text
- **Citation styles module** (`citation_styles.py`): manages built-in (APA/Vancouver/Chicago/MLA) and custom citation formats; custom styles loaded from `data/citation_styles/*.py` with path-traversal protection
- **draw skill** (`.claude/skills/draw/`): generate diagrams (Mermaid flowcharts, sequence diagrams, ER diagrams, Gantt charts, mind maps) and vector graphics (cli-anything-inkscape); outputs to `workspace/figures/`
- **`[office]` optional dependency group**: `markitdown[docx,pptx,xlsx]` + `python-docx`

### Fixed

- **Chicago citation format**: empty authors list no longer causes `IndexError`; condition reordered to check `not authors` first (consistent with APA/Vancouver)
- **Federated search DOI annotation**: `WHERE doi IN (...)` replaced with `WHERE LOWER(doi) IN (...)` in `cli.py`, preventing false negatives when stored DOIs have different casing
- **`insights --days` validation**: replaced `args.days or 30` with explicit `days <= 0` check; `--days 0` or negative values now produce a clear error instead of silently defaulting to 30

- CLI error messages and output text unified to Chinese
- `citation_styles`: `show_style()`, `list_styles()`, `get_formatter()` error messages Chinese-ified; Google-style docstrings added
- **Translation same-language skip**: language detection now recognizes common German/French/Spanish inputs, avoiding unnecessary same-language translation calls for supported targets

## [1.0.0] — 2026-03-14

### Added

- **Workspace batch add**: `ws add` now supports `--search "<query>"`, `--topic <id>`, and `--all` flags for bulk paper addition, with `--limit`/`--year`/`--journal`/`--type` filter support (`--top` remains a compatibility alias)
- **PDF optional dependency**: `pymupdf` declared in `pyproject.toml` as `[pdf]` extra (included in `[full]`), fixing undeclared dependency for long PDF splitting
- **Subagent information tiers**: T1/T2/T3 architecture documented in CLAUDE.md and AGENTS.md for structured context management

### Fixed

- **MCP `build_topics`**: `nr_topics=0` now correctly maps to `"auto"` (automatic topic merging/reduction) instead of `None` (no reduction); added `-1` as explicit "no reduction" value

## [0.1.0] — 2026-03-13

### Knowledge Base

- PDF ingestion via MinerU (local API / `mineru-open-api` cloud CLI), with auto-splitting for long PDFs (>100 pages)
- Three inboxes: regular papers (`inbox/`), theses (`inbox-thesis/`), general documents (`inbox-doc/`)
- DOI-based deduplication; unresolved papers held in `pending/` for manual review
- Metadata extraction with 4 modes: regex, auto (regex + LLM fallback), robust (regex + LLM cross-check), llm
- API-based metadata enrichment (Crossref, Semantic Scholar, OpenAlex)
- L1–L4 layered content loading (metadata → abstract → conclusion → full text)
- FTS5 full-text search index
- FAISS semantic search with Qwen3-Embedding-0.6B, GPU-adaptive batch profiling
- Unified search with Reciprocal Rank Fusion (RRF) combining keyword + semantic results
- Author search and top-cited paper ranking
- BibTeX export with year/journal filtering
- Data quality audit with structured issue reports and LLM-assisted repair
- BERTopic topic modeling with 6 HTML visualizations (hierarchy, 2D map, barchart, heatmap, term rank, topics over time)
- Citation graph queries (references, citing papers, shared references)
- Citation count fetching from Semantic Scholar / OpenAlex APIs
- Workspace management for organizing paper subsets (search, export within workspace)

### Content Enrichment

- Table of contents (TOC) extraction via LLM
- Conclusion (L3) extraction via LLM, with skip logic for non-article types (thesis, book, document, etc.)
- Abstract backfill via LLM for papers missing abstracts
- Concurrent LLM calls for batch enrichment (configurable worker count)

### Literature Exploration

- Multi-dimensional OpenAlex exploration (ISSN, concept, topic, author, institution, source type, year range, min citations)
- Isolated explore datasets (`data/explore/<name>/`) with independent FTS5 + FAISS + BERTopic
- Explore-specific unified/semantic/keyword search

### Import & Export

- Endnote import (XML and RIS formats)
- Zotero import (Web API and local SQLite)
- PDF attachment to existing papers
- BibTeX export with filtering by year, journal, or paper IDs

### LLM & Embedding

- Multi-LLM backend support: OpenAI-compatible (DeepSeek/OpenAI/vLLM/Ollama), Anthropic (Claude), Google (Gemini)
- API key resolution: config → environment variable → vendor-specific env vars
- LLM token usage and API call timing via MetricsStore
- GPU-adaptive batch embedding with automatic profiling and OOM fallback

### AI Agent Integration

- 22 Claude Code skills following AgentSkills.io open standard
- MCP server with 31 tools
- CLI with 29 subcommands (`scholaraio --help`)
- Multi-agent compatibility: AGENTS.md, .cursorrules, .windsurfrules, .clinerules, .github/copilot-instructions.md
- Claude Code plugin packaging (`.claude-plugin/plugin.json`, `marketplace.json`)
- SessionStart hook for auto-installing dependencies in plugin mode
- Global config fallback (`~/.scholaraio/`) for plugin usage outside the project repo

### Project Infrastructure

- Bilingual setup wizard (EN/ZH) with environment diagnostics
- Code quality toolchain: ruff linter/formatter, mypy type checking, pre-commit hooks
- CI workflow: lint, typecheck, test matrix (Python 3.10–3.12)
- Contract-level test suite (36 tests across 6 modules)
- Community governance: CONTRIBUTING.md, CODE_OF_CONDUCT.md, SECURITY.md
- GitHub issue/PR templates (bug report, feature request)
- CITATION.cff for academic citation
- MkDocs documentation site with API reference (mkdocstrings)
- Release workflow for PyPI publishing (trusted OIDC)
