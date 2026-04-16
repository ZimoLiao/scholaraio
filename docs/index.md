# ScholarAIO

**Scholar All-In-One** — A research infrastructure for AI agents.

ScholarAIO is a research infrastructure for AI agents. You interact with your literature knowledge base through natural language — searching, reading, analyzing, and writing — all from the command line.

## Features

- **PDF Ingestion**: Convert PDFs to structured Markdown via MinerU (cloud or local)
- **Hybrid Search**: FTS5 keyword search + FAISS semantic search + RRF fusion
- **Topic Modeling**: BERTopic clustering with interactive HTML visualizations
- **Citation Graph**: View references, citing papers, and shared references
- **BibTeX Export**: Filtered export with standard citation formats
- **Paper Translation**: Translate papers with concurrent chunked LLM calls and optional portable bundles
- **Literature Exploration**: Multi-dimensional OpenAlex queries with isolated data
- **Workspace Management**: Organize papers into subsets for focused work
- **Federated Discovery**: Search your library, explore silos, and arXiv in one flow
- **Research Insights**: Inspect search/read behavior trends and semantic neighbor recommendations
- **Scientific Tool Docs**: Query indexed official docs for scientific computing tools with `toolref`
- **Extensible Tool Onboarding**: Keep adding the next scientific tool users need through a documented onboarding workflow
- **Office Document Inspection**: Verify DOCX / PPTX / XLSX structure with `document inspect`
- **Agent Skills**: Reusable workflows for search, writing, scientific runtime, and more
- **Writing Router**: Start with `academic-writing` to route reviews, guided deep reading, paper sections, rebuttals, posters, and technical reports to the right workflow

## Quick Start

```bash
pip install "scholaraio[full]"
scholaraio setup
```

See [Installation](getting-started/installation.md) for detailed instructions.
If you are working from a local clone or contributing to ScholarAIO itself, use the editable install path shown there instead.
See [Agent Setup](getting-started/agent-setup.md) for repo-open vs plugin setup paths.
See [Translation Guide](guide/translate.md) for translation, resume, and portable export behavior.
See [Insights Guide](guide/insights.md) for reading/search behavior analytics.
See [API Reference](api/index.md) for Python module documentation.

## Two Usage Modes

| Mode | Interface | Best for |
|------|-----------|----------|
| **Agent** | Claude Code CLI | Full research workflow via natural language |
| **CLI** | Terminal | Scripting and automation |
